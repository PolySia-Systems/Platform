from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polysia.application.services.candidate_intelligence import (
    PIPELINE_LEASE_RESOURCE,
    CandidateIntelligenceService,
)
from polysia.application.services.copyability_selection import CopyabilitySelectionService
from polysia.deployment.wallet_intelligence_backup import (
    backup_wallet_intelligence_database,
    rehearse_wallet_intelligence_restore,
)
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository


def test_backup_is_actually_restored_and_wallet_schema_is_validated(tmp_path: Path) -> None:
    database = tmp_path / "data" / "wallet-intelligence.sqlite3"
    repository = WalletIntelligenceRepository(database)
    repository.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    address = "0x" + "1" * 40
    digest = hashlib.sha256(address.encode()).hexdigest()
    dataset = CandidateWalletDataset(
        source_id="polycop",
        schema_version="test-v1",
        fetched_at=now,
        source_total_pages=1,
        records=(
            CandidateWalletRecord(
                external_wallet_id=address,
                source_rank=1,
                source_page=1,
                metrics={"score": "90"},
                row_digest=digest,
            ),
        ),
        dataset_digest=hashlib.sha256(digest.encode()).hexdigest(),
    )
    run = repository.start_run("polycop", scheduled_for=now.date(), started_at=now)
    stored = repository.complete_run(run, dataset, accepted_at=now)
    intelligence = CandidateIntelligenceRepository(database)
    intelligence.initialize()
    calculated_at = now + timedelta(minutes=1)
    lease = intelligence.acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="backup-test",
        acquired_at=calculated_at,
        lease_duration=timedelta(minutes=30),
    )
    outcome = CandidateIntelligenceService(
        intelligence,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: calculated_at,
    ).process_snapshot("polycop", stored.snapshot_id, lease=lease)
    selection = CopyabilitySelectionRepository(database)
    selection.initialize()
    CopyabilitySelectionService(
        selection,
        clock=lambda: calculated_at + timedelta(minutes=1),
    ).process_stage2_run("polycop", outcome.pool.run_id, lease=lease)
    intelligence.release_lease(lease)

    backup = backup_wallet_intelligence_database(
        database,
        tmp_path / "backups",
        now=now,
    )
    restored = rehearse_wallet_intelligence_restore(backup.backup_path)

    assert backup.backup_path.name.startswith("wallet-intelligence-")
    assert restored.sha256 == backup.sha256
    assert restored.validation.source_count == 1
    assert restored.validation.snapshot_count == 1
    assert restored.validation.row_count == 1
    assert restored.validation.candidate_intelligence_schema_version == 1
    assert restored.validation.candidate_run_count == 1
    assert restored.validation.candidate_pool_count == 1
    assert restored.validation.copyability_selection_schema_version == 1
    assert restored.validation.copyability_run_count == 1
    assert restored.validation.copyability_membership_count >= 1
