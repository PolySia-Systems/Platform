from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysia.application.ports.candidate_intelligence import CandidatePipelineBusyError
from polysia.application.services.candidate_intelligence import (
    PIPELINE_LEASE_RESOURCE,
    CandidateIntelligenceService,
)
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository


def _snapshot(
    repository: WalletIntelligenceRepository,
    address: str,
    *,
    at: datetime,
) -> str:
    record = CandidateWalletRecord(
        external_wallet_id=address,
        source_rank=1,
        source_page=1,
        metrics={"score": "90", "roi": "2"},
        row_digest=hashlib.sha256(address.encode()).hexdigest(),
    )
    dataset = CandidateWalletDataset(
        source_id="polycop",
        schema_version="test-v1",
        fetched_at=at,
        source_total_pages=1,
        records=(record,),
        dataset_digest=hashlib.sha256(record.row_digest.encode()).hexdigest(),
    )
    run = repository.start_run("polycop", scheduled_for=at.date(), started_at=at)
    return repository.complete_run(run, dataset, accepted_at=at).snapshot_id


def test_additive_migration_preserves_stage1_and_has_independent_version(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    stage1 = WalletIntelligenceRepository(database)
    stage1.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    _snapshot(stage1, "0x" + "1" * 40, at=now)

    stage2 = CandidateIntelligenceRepository(database)
    stage2.initialize()

    validation = stage1.validate_integrity()
    assert validation.schema_version == 1
    assert validation.candidate_intelligence_schema_version == 1
    assert validation.snapshot_count == 1
    assert validation.row_count == 1
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT schema_version FROM wallet_intelligence_metadata"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT schema_version FROM candidate_intelligence_metadata"
        ).fetchone() == (1,)
    finally:
        connection.close()


def test_stage1_retention_can_prune_old_source_data_without_breaking_stage2_lkg(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    stage1 = WalletIntelligenceRepository(database)
    stage1.initialize()
    old = datetime(2025, 1, 1, tzinfo=UTC)
    old_snapshot = _snapshot(stage1, "0x" + "1" * 40, at=old)
    stage2 = CandidateIntelligenceRepository(database)
    stage2.initialize()
    calculated_at = old + timedelta(minutes=1)
    lease = stage2.acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="retention-owner",
        acquired_at=calculated_at,
        lease_duration=timedelta(minutes=30),
    )
    CandidateIntelligenceService(
        stage2,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: calculated_at,
    ).process_snapshot("polycop", old_snapshot, lease=lease)
    stage2.release_lease(lease)
    newer = datetime(2026, 8, 22, tzinfo=UTC)
    _snapshot(stage1, "0x" + "2" * 40, at=newer)

    stage1.prune_history(
        snapshot_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        quarantine_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert stage1.validate_integrity().snapshot_count == 1
    assert len(stage2.current_pool("polycop")) == 1
    stage2.validate_integrity()


def test_separate_connections_compete_for_one_database_lease(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    first = CandidateIntelligenceRepository(database)
    second = CandidateIntelligenceRepository(database)
    first.initialize()
    second.initialize()
    at = datetime(2026, 8, 22, tzinfo=UTC)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcome_lock = threading.Lock()

    def acquire(repository: CandidateIntelligenceRepository, owner: str) -> None:
        barrier.wait()
        try:
            repository.acquire_lease(
                PIPELINE_LEASE_RESOURCE,
                owner_id=owner,
                acquired_at=at,
                lease_duration=timedelta(minutes=30),
            )
        except CandidatePipelineBusyError:
            result = "busy"
        else:
            result = "acquired"
        with outcome_lock:
            outcomes.append(result)

    threads = (
        threading.Thread(target=acquire, args=(first, "startup-owner")),
        threading.Thread(target=acquire, args=(second, "timer-owner")),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["acquired", "busy"]


def test_source_worklist_is_current_only_and_wallet_history_is_bounded_by_key(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    stage1 = WalletIntelligenceRepository(database)
    stage1.initialize()
    address = "0x" + "1" * 40
    first = datetime(2026, 8, 20, tzinfo=UTC)
    _snapshot(stage1, address, at=first)
    _snapshot(stage1, address, at=first + timedelta(days=1))
    current_snapshot = _snapshot(stage1, address, at=first + timedelta(days=2))
    stage2 = CandidateIntelligenceRepository(database)
    stage2.initialize()

    source_history = stage2.load_source_history("polycop", current_snapshot)
    wallet_key = source_history.current_observations[0].wallet_key
    wallet_histories = stage2.load_wallet_histories(
        "polycop",
        current_snapshot,
        (wallet_key,),
    )

    assert len(source_history.snapshots) == 3
    assert len(source_history.current_observations) == 1
    assert len(wallet_histories[wallet_key]) == 3
    assert wallet_histories[wallet_key][-1].snapshot_id == current_snapshot

    with pytest.raises(ValueError, match="must be unique"):
        stage2.load_wallet_histories(
            "polycop",
            current_snapshot,
            (wallet_key, wallet_key),
        )
    with pytest.raises(ValueError, match="1 to 64"):
        stage2.load_wallet_histories(
            "polycop",
            current_snapshot,
            tuple(f"wallet-{index}" for index in range(65)),
        )
