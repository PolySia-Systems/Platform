from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from polysia.storage.dynamic_shadow import DynamicShadowRepository

FIXTURES = Path(__file__).resolve().parent / "fixtures"
V2_SCHEMA = FIXTURES / "continuous_shadow_schema_v2.sql"
V3_SCHEMA = FIXTURES / "continuous_shadow_schema_v3.sql"


def _legacy_config_json() -> str:
    payload = ContinuousShadowConfig().to_dict()
    del payload["price_drift_max_ratio"]
    del payload["negative_cache_ttl_seconds"]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_stage4b_schema_is_additive_and_keeps_stage4a_schema_v1(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()

    ContinuousShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()

    connection = sqlite3.connect(database)
    try:
        dynamic_version = connection.execute(
            "SELECT schema_version FROM dynamic_shadow_metadata"
        ).fetchone()[0]
        continuous_version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
        dynamic_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'dynamic_shadow_evaluations'"
        ).fetchone()[0]
        kinds_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'continuous_shadow_portfolios'"
        ).fetchone()[0]
        cache = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'continuous_shadow_terminal_book_cache'"
        ).fetchone()
    finally:
        connection.close()

    assert dynamic_version == 1
    assert continuous_version == 4
    assert "evaluation_status" in dynamic_sql
    assert "FOLLOWER_ALPHA" in kinds_sql
    assert cache is not None


def test_stage4b_v2_migrates_atomically_and_idempotently_to_v4(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()
    with sqlite3.connect(database) as connection:
        connection.executescript(V2_SCHEMA.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO continuous_shadow_metadata (schema_version, initialized_at) "
            "VALUES (2, '2026-08-25T00:00:00+00:00')"
        )

    repository = ContinuousShadowRepository(database)
    repository.initialize()
    repository.initialize()

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
        journal_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_event_journal)"
            ).fetchall()
        }
        poll_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_poll_runs)"
            ).fetchall()
        }
        ledger_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_ledger)"
            ).fetchall()
        }
        attribution_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_follower_attribution)"
            ).fetchall()
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert version == 4
    assert "processing_status" in journal_columns
    assert "settlement_backlog_count" in poll_columns
    assert "wallet_id" in ledger_columns
    assert "pool_class" in ledger_columns
    assert "portfolio_id" in attribution_columns
    assert integrity == "ok"


def test_stage4b_v3_migrates_to_v4_and_adds_specialized_followers(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()
    with sqlite3.connect(database) as connection:
        connection.executescript(V3_SCHEMA.read_text(encoding="utf-8"))
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO continuous_shadow_metadata (schema_version, initialized_at) "
            "VALUES (3, '2026-08-25T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO continuous_shadow_experiments ("
            "experiment_id, source_id, selection_run_id, policy_version, "
            "cost_model_version, bankroll_version, config_json, lifecycle, started_at) "
            "VALUES ('exp-1', 'polycop', 'sel-1', 'continuous-shadow-policy-v0.2', "
            "'polymarket-fee-depth-delay-v0.2', 'synthetic-bankroll-v0.2', ?, "
            "'RUNNING', '2026-08-25T00:00:00+00:00')",
            (_legacy_config_json(),),
        )
        connection.execute(
            "INSERT INTO continuous_shadow_portfolios ("
            "experiment_id, portfolio_id, kind, wallet_id, initial_cash, cash, "
            "realized_pnl, unrealized_pnl, fees, nav, high_water_nav, drawdown, "
            "exposure, updated_at) VALUES ("
            "'exp-1', 'follower', 'FOLLOWER', NULL, '1000', '1000', '0', '0', '0', "
            "'1000', '1000', '0', '0', '2026-08-25T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO continuous_shadow_candidates ("
            "experiment_id, wallet_id, pools_json, alpha_rank, stress_rank, "
            "selection_run_id, active, first_selected_at, last_selected_at) VALUES ("
            "'exp-1', 'wallet-1', '[\"ALPHA\"]', 1, NULL, 'sel-1', 1, "
            "'2026-08-25T00:00:00+00:00', '2026-08-25T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO continuous_shadow_follower_attribution ("
            "experiment_id, wallet_id, market_reference, outcome_reference, "
            "quantity, cost_basis) VALUES ("
            "'exp-1', 'wallet-1', 'market-1', 'yes', '5', '2')"
        )
        connection.execute(
            "INSERT INTO continuous_shadow_evaluations ("
            "experiment_id, poll_run_id, event_id, portfolio_id, wallet_id, "
            "pool_class, status, reason, requested_size, filled_size, fee_status, "
            "fee_source, source_api_lag_ms, signal_delay_ms, evaluated_at) VALUES ("
            "'exp-1', 'poll-1', 'event-1', 'follower', 'wallet-1', 'ALPHA', "
            "'SIMULATED', 'filled', '5', '5', 'VERIFIED', 'official', 0, 0, "
            "'2026-08-25T00:01:00+00:00')"
        )
        connection.execute(
            "INSERT INTO continuous_shadow_ledger ("
            "experiment_id, entry_id, poll_run_id, portfolio_id, event_id, "
            "entry_type, market_reference, outcome_reference, quantity_delta, "
            "cash_delta, cost_basis_delta, realized_pnl_delta, fee_delta, "
            "created_at) VALUES ("
            "'exp-1', 'close-1', 'poll-1', 'follower', 'event-1', 'CLOSE', "
            "'market-1', 'yes', '-5', '2.5', '-2', '0.5', '0', "
            "'2026-08-25T00:01:00+00:00')"
        )
        connection.execute(
            "INSERT INTO continuous_shadow_ledger ("
            "experiment_id, entry_id, poll_run_id, portfolio_id, event_id, "
            "entry_type, market_reference, outcome_reference, quantity_delta, "
            "cash_delta, cost_basis_delta, realized_pnl_delta, fee_delta, "
            "created_at) VALUES ("
            "'exp-1', 'settle-1', 'poll-1', 'follower', NULL, 'SETTLEMENT', "
            "'market-2', 'yes', '-1', '1', '-1', '0', '0', "
            "'2026-08-25T00:02:00+00:00')"
        )

    ContinuousShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
        kinds = {
            str(row[0])
            for row in connection.execute(
                "SELECT kind FROM continuous_shadow_portfolios"
            ).fetchall()
        }
        cache = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'continuous_shadow_terminal_book_cache'"
        ).fetchone()
        attribution = connection.execute(
            "SELECT portfolio_id, pool_class FROM continuous_shadow_follower_attribution"
        ).fetchone()
        close_row = connection.execute(
            "SELECT wallet_id, pool_class FROM continuous_shadow_ledger "
            "WHERE entry_id = 'close-1'"
        ).fetchone()
        settlement_row = connection.execute(
            "SELECT wallet_id FROM continuous_shadow_ledger WHERE entry_id = 'settle-1'"
        ).fetchone()
        config = json.loads(
            str(
                connection.execute(
                    "SELECT config_json FROM continuous_shadow_experiments"
                ).fetchone()[0]
            )
        )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert version == 4
    assert kinds == {"FOLLOWER", "FOLLOWER_ALPHA", "FOLLOWER_STRESS"}
    assert cache is not None
    assert attribution is not None
    assert attribution[0] == "follower"
    assert attribution[1] == "UNKNOWN"
    assert close_row == ("wallet-1", "ALPHA")
    assert settlement_row == (None,)
    assert config["price_drift_max_ratio"] is None
    assert config["negative_cache_ttl_seconds"] == 21_600
    assert config == ContinuousShadowConfig().to_dict()
    assert integrity == "ok"
