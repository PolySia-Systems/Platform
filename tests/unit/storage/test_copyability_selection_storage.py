from __future__ import annotations

import sqlite3
from pathlib import Path

from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository


def test_stage3_schema_is_additive_and_preserves_stage1_rows(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source = WalletIntelligenceRepository(database)
    source.initialize()
    connection = sqlite3.connect(database)
    try:
        before_tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        before_source = int(
            connection.execute("SELECT COUNT(*) FROM candidate_current_snapshots").fetchone()[0]
        )
    finally:
        connection.close()

    CopyabilitySelectionRepository(database).initialize()
    validation = source.validate_integrity()
    assert validation.copyability_selection_schema_version == 1
    assert validation.schema_version == 1
    connection = sqlite3.connect(database)
    try:
        after_tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        after_source = int(
            connection.execute("SELECT COUNT(*) FROM candidate_current_snapshots").fetchone()[0]
        )
    finally:
        connection.close()
    assert before_tables <= after_tables
    assert after_source == before_source
    assert "copyability_selection_runs" in after_tables
    assert "copyability_wallet_scores" in after_tables
    assert "copyability_pools_current" in {
        str(row[0])
        for row in sqlite3.connect(database).execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'"
        )
    }
