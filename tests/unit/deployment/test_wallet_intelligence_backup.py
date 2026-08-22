from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from polysia.deployment.wallet_intelligence_backup import (
    backup_wallet_intelligence_database,
    rehearse_wallet_intelligence_restore,
)
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
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
    repository.complete_run(run, dataset, accepted_at=now)

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
