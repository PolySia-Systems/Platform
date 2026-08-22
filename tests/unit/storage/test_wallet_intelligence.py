from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.storage.wallet_intelligence import (
    CandidateRunInProgressError,
    WalletIntelligenceRepository,
)


def _dataset(
    *addresses: str,
    fetched_at: datetime,
    total_pages: int = 1,
    source_id: str = "polycop",
) -> CandidateWalletDataset:
    records = tuple(
        CandidateWalletRecord(
            external_wallet_id=address,
            source_rank=index,
            source_page=min(index, total_pages),
            metrics={"score": str(100 - index)},
            row_digest=hashlib.sha256(address.encode()).hexdigest(),
        )
        for index, address in enumerate(addresses, start=1)
    )
    digest = hashlib.sha256("\n".join(row.row_digest for row in records).encode()).hexdigest()
    return CandidateWalletDataset(
        source_id=source_id,
        schema_version="test-v1",
        fetched_at=fetched_at,
        source_total_pages=total_pages,
        records=records,
        dataset_digest=digest,
    )


def test_snapshot_promotion_is_idempotent_and_keeps_protected_identity_separate(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    repository = WalletIntelligenceRepository(database)
    repository.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    address = "0x" + "1" * 40
    started = repository.start_run("polycop", scheduled_for=now.date(), started_at=now)
    stored = repository.complete_run(started, _dataset(address, fetched_at=now), accepted_at=now)

    replay = repository.start_run(
        "polycop",
        scheduled_for=now.date(),
        started_at=now + timedelta(minutes=1),
    )

    assert replay.already_succeeded is True
    assert replay.run_id == stored.run_id
    state = repository.source_state("polycop")
    assert state.current_snapshot_id == stored.snapshot_id
    assert state.current_record_count == 1
    connection = sqlite3.connect(database)
    try:
        metrics = connection.execute(
            "SELECT metrics_json FROM candidate_wallet_snapshot_rows"
        ).fetchone()[0]
        protected = connection.execute(
            "SELECT external_wallet_id FROM candidate_wallet_identities"
        ).fetchone()[0]
    finally:
        connection.close()
    assert address not in metrics
    assert protected == address


def test_read_only_validation_uses_literal_database_path(tmp_path: Path) -> None:
    repository = WalletIntelligenceRepository(
        tmp_path / "data#source" / "wallet-intelligence.sqlite3"
    )
    repository.initialize()

    validation = repository.validate_integrity()

    assert validation.schema_version == 1


def test_failed_rerun_preserves_last_known_good_snapshot(tmp_path: Path) -> None:
    repository = WalletIntelligenceRepository(tmp_path / "wallet-intelligence.sqlite3")
    repository.initialize()
    first_time = datetime(2026, 8, 22, tzinfo=UTC)
    first = repository.start_run(
        "polycop", scheduled_for=first_time.date(), started_at=first_time
    )
    accepted = repository.complete_run(
        first,
        _dataset("0x" + "1" * 40, fetched_at=first_time),
        accepted_at=first_time,
    )
    second_time = first_time + timedelta(days=1)
    second = repository.start_run(
        "polycop", scheduled_for=second_time.date(), started_at=second_time
    )
    repository.fail_run(
        second.run_id,
        error_code="source_read_failed",
        error_message="safe failure",
        completed_at=second_time,
    )

    state = repository.source_state("polycop")

    assert state.current_snapshot_id == accepted.snapshot_id
    assert state.last_run_status == "failed"
    assert state.last_error_code == "source_read_failed"


def test_force_new_allows_corrected_same_day_snapshot_and_retains_history(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    repository = WalletIntelligenceRepository(database)
    repository.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    first = repository.start_run("polycop", scheduled_for=now.date(), started_at=now)
    repository.complete_run(
        first,
        _dataset("0x" + "1" * 40, fetched_at=now, total_pages=5),
        accepted_at=now,
    )
    second = repository.start_run(
        "polycop",
        scheduled_for=now.date(),
        started_at=now + timedelta(hours=1),
        force_new=True,
    )
    corrected = repository.complete_run(
        second,
        _dataset("0x" + "2" * 40, fetched_at=now, total_pages=50),
        accepted_at=now + timedelta(hours=1),
    )

    assert repository.source_state("polycop").current_snapshot_id == corrected.snapshot_id
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM candidate_wallet_snapshots").fetchone() == (
            2,
        )
    finally:
        connection.close()


def test_history_pruning_never_deletes_current_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    repository = WalletIntelligenceRepository(database)
    repository.initialize()
    old = datetime(2025, 1, 1, tzinfo=UTC)
    run = repository.start_run("polycop", scheduled_for=old.date(), started_at=old)
    stored = repository.complete_run(
        run,
        _dataset("0x" + "1" * 40, fetched_at=old),
        accepted_at=old,
    )

    repository.prune_history(
        snapshot_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        quarantine_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert repository.source_state("polycop").current_snapshot_id == stored.snapshot_id
    assert repository.validate_integrity().snapshot_count == 1


def test_record_count_baseline_warns_but_accepts_complete_dynamic_growth(tmp_path: Path) -> None:
    repository = WalletIntelligenceRepository(tmp_path / "wallet-intelligence.sqlite3")
    repository.initialize()
    start_time = datetime(2026, 8, 1, tzinfo=UTC)
    baseline_addresses = ("0x" + "1" * 40, "0x" + "2" * 40)
    for day_offset in range(7):
        now = start_time + timedelta(days=day_offset)
        run = repository.start_run("polycop", scheduled_for=now.date(), started_at=now)
        repository.complete_run(
            run,
            _dataset(*baseline_addresses, fetched_at=now, total_pages=5),
            accepted_at=now,
        )
    growth_time = start_time + timedelta(days=7)
    growth_addresses = tuple(f"0x{number:040x}" for number in range(10, 15))
    growth_run = repository.start_run(
        "polycop", scheduled_for=growth_time.date(), started_at=growth_time
    )

    stored = repository.complete_run(
        growth_run,
        _dataset(*growth_addresses, fetched_at=growth_time, total_pages=50),
        accepted_at=growth_time,
    )

    assert stored.warning_code == "record_count_above_baseline"
    assert repository.source_state("polycop").current_page_count == 50


def test_non_overlapping_source_run_reclaims_only_abandoned_owner(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    repository = WalletIntelligenceRepository(database)
    repository.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    first = repository.start_run("polycop", scheduled_for=now.date(), started_at=now)

    with pytest.raises(CandidateRunInProgressError):
        repository.start_run(
            "polycop",
            scheduled_for=(now + timedelta(minutes=1)).date(),
            started_at=now + timedelta(minutes=1),
        )

    replacement = repository.start_run(
        "polycop",
        scheduled_for=(now + timedelta(hours=3)).date(),
        started_at=now + timedelta(hours=3),
    )
    connection = sqlite3.connect(database)
    try:
        first_status = connection.execute(
            "SELECT status FROM candidate_source_runs WHERE run_id = ?", (first.run_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert first_status == "failed"
    assert replacement.already_succeeded is False


def test_one_database_partitions_multiple_explicit_sources(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    repository = WalletIntelligenceRepository(database)
    repository.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    address = "0x" + "1" * 40
    polycop_run = repository.start_run("polycop", scheduled_for=now.date(), started_at=now)
    repository.complete_run(
        polycop_run,
        _dataset(address, fetched_at=now, source_id="polycop"),
        accepted_at=now,
    )
    second_run = repository.start_run(
        "second-source", scheduled_for=now.date(), started_at=now
    )
    repository.complete_run(
        second_run,
        _dataset(address, fetched_at=now, source_id="second-source"),
        accepted_at=now,
    )

    validation = repository.validate_integrity()
    assert validation.source_count == 2
    assert repository.source_state("polycop").current_snapshot_id != repository.source_state(
        "second-source"
    ).current_snapshot_id
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM candidate_wallet_identities"
        ).fetchone()[0] == 2
    finally:
        connection.close()
