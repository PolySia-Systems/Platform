from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from polysia.deployment.continuous_shadow_migration import (
    migrate_continuous_shadow_database,
)
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.storage.continuous_shadow import (
    ContinuousShadowRepository,
    ContinuousShadowStoreError,
)
from polysia.storage.dynamic_shadow import DynamicShadowRepository

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RETIREMENT_SQL = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "migrations"
    / "retire_legacy_continuous_shadow_v1.sql"
)
V3_SCHEMA = FIXTURES / "continuous_shadow_schema_v3.sql"
V4_SCHEMA = FIXTURES / "continuous_shadow_schema_v4.sql"
STAMP = "2026-08-25T00:00:00+00:00"


def test_stage4b_schema_is_standalone_and_idempotent(tmp_path: Path) -> None:
    intelligence = tmp_path / "wallet-intelligence.sqlite3"
    shadow = tmp_path / "continuous-shadow.sqlite3"
    DynamicShadowRepository(intelligence).initialize()

    ContinuousShadowRepository(shadow).initialize()
    ContinuousShadowRepository(shadow).initialize()

    with sqlite3.connect(intelligence) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'continuous_shadow_metadata'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT schema_version FROM dynamic_shadow_metadata"
        ).fetchone()[0] == 1
    with sqlite3.connect(shadow) as connection:
        assert connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0] == 5
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'dynamic_shadow_metadata'"
        ).fetchone() is None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_legacy_schema_requires_offline_split_migration(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(legacy) as connection:
        connection.executescript(V3_SCHEMA.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO continuous_shadow_metadata (schema_version, initialized_at) "
            "VALUES (3, ?)",
            (STAMP,),
        )

    with pytest.raises(ContinuousShadowStoreError, match="offline split-store"):
        ContinuousShadowRepository(legacy).initialize()

    with sqlite3.connect(legacy) as connection:
        assert connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0] == 3


def test_schema_v4_state_is_atomically_extracted_without_copying_lease(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "wallet-intelligence-v4.sqlite3"
    destination = tmp_path / "continuous-shadow.sqlite3"
    _legacy_v4_database(legacy)

    result = migrate_continuous_shadow_database(legacy, destination)

    assert result.schema_version == 5
    assert result.experiment_id == "exp-1"
    assert result.ledger_balanced is True
    assert result.table_counts["continuous_shadow_experiments"] == 1
    assert destination.is_file()
    with sqlite3.connect(legacy) as source:
        assert source.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0] == 4
        assert source.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'continuous_shadow_leases'"
        ).fetchone() is None
    with sqlite3.connect(destination) as target:
        assert target.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0] == 5
        assert target.execute(
            "SELECT COUNT(*) FROM continuous_shadow_leases"
        ).fetchone()[0] == 0
        snapshot = target.execute(
            "SELECT source_snapshot_id, candidate_count, length(digest) "
            "FROM continuous_shadow_selection_snapshots"
        ).fetchone()
        assert snapshot == ("source-snapshot-1", 1, 64)
        assert target.execute(
            "SELECT normalized_address FROM continuous_shadow_wallets"
        ).fetchone()[0] == "0x" + "1" * 40
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_refuses_unfinished_poll_and_leaves_no_destination(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "wallet-intelligence-v4.sqlite3"
    destination = tmp_path / "continuous-shadow.sqlite3"
    _legacy_v4_database(legacy)
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            "INSERT INTO continuous_shadow_poll_runs ("
            "poll_run_id, experiment_id, selection_run_id, window_start, window_end, "
            "status, started_at, candidate_count) VALUES ("
            "'poll-running', 'exp-1', 'sel-1', ?, ?, 'running', ?, 1)",
            (STAMP, "2026-08-25T00:01:00+00:00", STAMP),
        )

    with pytest.raises(ContinuousShadowStoreError, match="unfinished poll"):
        migrate_continuous_shadow_database(legacy, destination)

    assert not destination.exists()


def test_retirement_removes_only_frozen_stage4b_schema(tmp_path: Path) -> None:
    legacy = tmp_path / "wallet-intelligence-v4.sqlite3"
    _legacy_v4_database(legacy)

    with sqlite3.connect(legacy) as connection:
        connection.executescript(RETIREMENT_SQL.read_text(encoding="utf-8"))
        stage4b_objects = connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'continuous_shadow_%'"
        ).fetchall()
        assert stage4b_objects == []
        assert connection.execute(
            "SELECT schema_version FROM dynamic_shadow_metadata"
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_retirement_refuses_unfinished_legacy_poll(tmp_path: Path) -> None:
    legacy = tmp_path / "wallet-intelligence-v4.sqlite3"
    _legacy_v4_database(legacy)
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            "INSERT INTO continuous_shadow_poll_runs ("
            "poll_run_id, experiment_id, selection_run_id, window_start, window_end, "
            "status, started_at, candidate_count) VALUES ("
            "'poll-running', 'exp-1', 'sel-1', ?, ?, 'running', ?, 1)",
            (STAMP, "2026-08-25T00:01:00+00:00", STAMP),
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.executescript(RETIREMENT_SQL.read_text(encoding="utf-8"))

        assert connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0] == 4


def _legacy_v4_database(path: Path) -> None:
    DynamicShadowRepository(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO canonical_wallets "
            "(wallet_id, chain, normalized_address, created_at, updated_at) "
            "VALUES ('wallet-1', 'polygon', ?, ?, ?)",
            ("0x" + "1" * 40, STAMP, STAMP),
        )
        connection.execute(
            "INSERT INTO candidate_intelligence_runs ("
            "run_id, source_id, source_snapshot_id, feature_set_version, policy_id, "
            "policy_version, ranking_version, status, started_at, calculated_at, "
            "published_at) VALUES ('stage2-1', 'polycop', 'source-snapshot-1', "
            "'features-v1', 'candidate-policy', 'candidate-policy-v1', "
            "'candidate-ranking-v1', 'succeeded', ?, ?, ?)",
            (STAMP, STAMP, STAMP),
        )
        connection.execute(
            "INSERT INTO copyability_selection_runs ("
            "run_id, source_id, source_snapshot_id, stage2_run_id, feature_set_version, "
            "policy_id, policy_version, ranking_version, status, started_at, "
            "calculated_at, published_at) VALUES ('sel-1', 'polycop', "
            "'source-snapshot-1', 'stage2-1', 'features-v1', 'copy-policy', "
            "'copy-policy-v1', 'copy-ranking-v1', 'succeeded', ?, ?, ?)",
            (STAMP, STAMP, STAMP),
        )
        connection.execute(
            "INSERT INTO copyability_wallet_scores ("
            "run_id, wallet_id, status, reasons_json, effective_at, observed_at, "
            "ingested_at, calculated_at) VALUES ("
            "'sel-1', 'wallet-1', 'SELECTED', '[]', ?, ?, ?, ?)",
            (STAMP, STAMP, STAMP, STAMP),
        )
        connection.execute(
            "INSERT INTO copyability_pool_memberships "
            "(run_id, pool_id, wallet_id, pool_rank, reasons_json) "
            "VALUES ('sel-1', 'SHADOW_ALPHA', 'wallet-1', 1, '[]')"
        )
        connection.execute(
            "INSERT INTO copyability_selection_current (source_id, run_id, published_at) "
            "VALUES ('polycop', 'sel-1', ?)",
            (STAMP,),
        )
        connection.executescript(V4_SCHEMA.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO continuous_shadow_metadata (schema_version, initialized_at) "
            "VALUES (4, ?)",
            (STAMP,),
        )
        connection.execute(
            "INSERT INTO continuous_shadow_experiments ("
            "experiment_id, source_id, selection_run_id, policy_version, "
            "cost_model_version, bankroll_version, config_json, lifecycle, started_at) "
            "VALUES ('exp-1', 'polycop', 'sel-1', 'continuous-shadow-policy-v0.2', "
            "'polymarket-fee-depth-delay-v0.2', 'synthetic-bankroll-v0.2', ?, "
            "'RUNNING', ?)",
            (json.dumps(ContinuousShadowConfig().to_dict(), sort_keys=True), STAMP),
        )
        connection.execute(
            "INSERT INTO continuous_shadow_candidates ("
            "experiment_id, wallet_id, pools_json, alpha_rank, stress_rank, "
            "selection_run_id, active, first_selected_at, last_selected_at) VALUES ("
            "'exp-1', 'wallet-1', '[\"SHADOW_ALPHA\"]', 1, NULL, 'sel-1', 1, ?, ?)",
            (STAMP, STAMP),
        )
        for portfolio_id, kind, wallet_id, bankroll in (
            ("wallet:wallet-1", "WALLET", "wallet-1", "100"),
            ("follower", "FOLLOWER", None, "1000"),
        ):
            connection.execute(
                "INSERT INTO continuous_shadow_portfolios ("
                "experiment_id, portfolio_id, kind, wallet_id, initial_cash, cash, "
                "realized_pnl, unrealized_pnl, fees, nav, high_water_nav, drawdown, "
                "exposure, updated_at) VALUES ("
                "'exp-1', ?, ?, ?, ?, ?, '0', '0', '0', ?, ?, '0', '0', ?)",
                (portfolio_id, kind, wallet_id, bankroll, bankroll, bankroll, bankroll, STAMP),
            )
        connection.commit()
