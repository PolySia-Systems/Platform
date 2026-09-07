from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.backtesting.shadow_historical_baseline import (
    AUTHORITATIVE_ALPHA_SIMULATED_FILLS,
    HELSINKI_FINAL_BACKUP_FILES,
    POST_CUTOFF_LIVE_QUERY_FILLS,
    BaselineInventory,
    SufficiencyClass,
    classify_data_sufficiency,
    classify_economic_result,
    run_primary_comparison,
    verify_backup_digests,
)
from polysia.backtesting.shadow_stateful_replay import ReplaySnapshot, ShadowReplayKind
from polysia.storage.immutable_sqlite import sha256_file

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
BACKUP_DIR = Path(r"C:\Users\Siamak\Documents\PolySia-backups\helsinki-final-20260906T175930Z")


def _inventory(**overrides: object) -> BaselineInventory:
    base = BaselineInventory(
        experiment_id="exp-1",
        source_id="polycop",
        policy_version="continuous-shadow-policy-v0.2",
        cost_model_version="polymarket-fee-depth-delay-v0.2",
        bankroll_version="synthetic-bankroll-v0.2",
        lifecycle="RUNNING",
        schema_version=6,
        started_at=NOW.isoformat(),
        last_poll_at=NOW.isoformat(),
        event_count=10,
        evaluation_count=10,
        simulated_evaluation_count=3,
        alpha_simulated_fill_count=3,
        alpha_simulated_with_price=3,
        alpha_simulated_event_ids=3,
        ledger_count=5,
        alpha_ledger_count=5,
        open_count=1,
        increase_count=1,
        reduce_count=0,
        close_count=1,
        settlement_count=1,
        position_count=1,
        alpha_open_positions=1,
        mark_count=2,
        poll_count=4,
        initial_cash=Decimal("1000"),
        cash=Decimal("900"),
        realized_pnl=Decimal("-50"),
        unrealized_pnl=Decimal("-10"),
        fees=Decimal("1"),
        nav=Decimal("890"),
        high_water_nav=Decimal("1000"),
        drawdown=Decimal("0.11"),
        exposure=Decimal("40"),
        ledger_sum_qty=Decimal("8"),
        ledger_sum_cash=Decimal("-100"),
        ledger_sum_cost=Decimal("40"),
        ledger_sum_realized=Decimal("-50"),
        ledger_sum_fee=Decimal("1"),
        distinct_markets=1,
        distinct_outcomes=1,
        distinct_wallets=2,
        ledger_balanced=True,
        integrity_ok=True,
        has_per_event_order_books=False,
        has_subsecond_source_path=False,
        has_markouts=False,
        has_market_only_labels=False,
        has_structural_alpha_features=False,
        fill_count_resolution="450 is authoritative",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_sufficiency_matrix_classifies_unsupported_future_work() -> None:
    rows = {item.capability: item for item in classify_data_sufficiency(_inventory())}

    assert rows["exact_current_control_reconstruction"].classification is SufficiencyClass.SUPPORTED
    assert rows["target_exposure_reconstruction"].classification is SufficiencyClass.PARTIAL
    assert rows["market_confirmation"].classification is SufficiencyClass.PARTIAL
    assert rows["sub_second_latency_scenarios"].classification is SufficiencyClass.UNSUPPORTED
    assert rows["leader_follower_markouts"].classification is SufficiencyClass.UNSUPPORTED
    assert (
        rows["conditional_wallet_market_vs_market_state_only"].classification
        is SufficiencyClass.UNSUPPORTED
    )
    assert rows["true_independent_market_only"].classification is SufficiencyClass.UNSUPPORTED
    assert rows["follower_native_exits"].classification is SufficiencyClass.PARTIAL
    assert rows["structural_alpha"].classification is SufficiencyClass.UNSUPPORTED
    assert AUTHORITATIVE_ALPHA_SIMULATED_FILLS == 450
    assert POST_CUTOFF_LIVE_QUERY_FILLS == 455


def test_negative_target_nav_is_risk_improvement_not_alpha() -> None:
    control = _snapshot(nav=Decimal("700"))
    challenger = _snapshot(nav=Decimal("900"))

    assert (
        classify_economic_result(control, challenger, initial_cash=Decimal("1000"))
        == "risk_portfolio_improvement_not_alpha"
    )


def _snapshot(*, nav: Decimal) -> ReplaySnapshot:
    return ReplaySnapshot(
        kind=ShadowReplayKind.CURRENT_CONTROL,
        event_count=1,
        cash=nav,
        fees=Decimal("0"),
        realized_pnl=nav - Decimal("1000"),
        unrealized_pnl=Decimal("0"),
        exposure=Decimal("0"),
        locked_capital=Decimal("0"),
        nav=nav,
        book_nav=nav,
        high_water_nav=Decimal("1000"),
        max_drawdown=Decimal("0"),
        open_positions=0,
        open_quantity=Decimal("0"),
        turnover=Decimal("0"),
        open_count=0,
        increase_count=0,
        reduce_count=0,
        close_count=0,
        settlement_count=0,
        skipped_repeat=0,
        skipped_rebalance=0,
        skipped_reentry=0,
        rejected_incomplete=0,
        unknown_unrealized_positions=0,
        unknown_rate=Decimal("0"),
        completed_episode_count=0,
        expectancy_per_completed_episode=None,
        profit_factor=None,
        max_market_exposure=Decimal("0"),
        distinct_markets=0,
        distinct_outcomes=0,
        coverage_admitted_buys=0,
        digest="x",
        decisions=(),
    )


def _tiny_shadow(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE continuous_shadow_metadata(
            schema_version INTEGER PRIMARY KEY, initialized_at TEXT NOT NULL
        );
        CREATE TABLE continuous_shadow_experiments(
            experiment_id TEXT PRIMARY KEY, source_id TEXT, policy_version TEXT,
            cost_model_version TEXT, bankroll_version TEXT, lifecycle TEXT,
            started_at TEXT, last_successful_poll_at TEXT
        );
        CREATE TABLE continuous_shadow_portfolios(
            experiment_id TEXT, portfolio_id TEXT, initial_cash TEXT, cash TEXT,
            realized_pnl TEXT, unrealized_pnl TEXT, fees TEXT, nav TEXT,
            high_water_nav TEXT, drawdown TEXT, exposure TEXT
        );
        CREATE TABLE continuous_shadow_ledger(
            experiment_id TEXT, entry_id TEXT, portfolio_id TEXT, event_id TEXT,
            entry_type TEXT, market_reference TEXT, outcome_reference TEXT,
            quantity_delta TEXT, cash_delta TEXT, cost_basis_delta TEXT,
            realized_pnl_delta TEXT, fee_delta TEXT, created_at TEXT,
            wallet_id TEXT
        );
        CREATE TABLE continuous_shadow_evaluations(
            experiment_id TEXT, event_id TEXT, portfolio_id TEXT,
            follower_price TEXT, filled_size TEXT, fee TEXT, evaluated_at TEXT,
            status TEXT
        );
        CREATE TABLE continuous_shadow_positions(
            experiment_id TEXT, portfolio_id TEXT, market_reference TEXT,
            outcome_reference TEXT, quantity TEXT, cost_basis TEXT,
            mark_price TEXT, mark_status TEXT, marked_at TEXT
        );
        CREATE TABLE continuous_shadow_position_marks(
            experiment_id TEXT, portfolio_id TEXT
        );
        CREATE TABLE continuous_shadow_event_journal(event_id TEXT);
        CREATE TABLE continuous_shadow_poll_runs(experiment_id TEXT);
        """
    )
    connection.execute(
        "INSERT INTO continuous_shadow_metadata VALUES (6, ?)",
        (NOW.isoformat(),),
    )
    connection.execute(
        "INSERT INTO continuous_shadow_experiments VALUES "
        "(?,?,?,?,?,?,?,?)",
        (
            "exp-1",
            "polycop",
            "continuous-shadow-policy-v0.2",
            "polymarket-fee-depth-delay-v0.2",
            "synthetic-bankroll-v0.2",
            "RUNNING",
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    connection.execute(
        "INSERT INTO continuous_shadow_portfolios VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "exp-1",
            "follower-alpha",
            "1000",
            "995",
            "-5",
            "0",
            "0",
            "995",
            "1000",
            "0.005",
            "0",
        ),
    )
    rows = (
        (
            "e1",
            "OPEN",
            "10",
            "-5",
            "5",
            "0",
            "0",
            "0.50",
            NOW.replace(microsecond=0).isoformat(),
        ),
        (
            "e2",
            "INCREASE",
            "10",
            "-2",
            "2",
            "0",
            "0",
            "0.20",
            NOW.replace(microsecond=1).isoformat(),
        ),
        (
            "e3",
            "CLOSE",
            "-20",
            "2",
            "-7",
            "-5",
            "0",
            "0.10",
            NOW.replace(microsecond=2).isoformat(),
        ),
    )
    for entry_id, entry_type, qty, cash, cost, realized, fee, price, created in rows:
        connection.execute(
            "INSERT INTO continuous_shadow_ledger VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "exp-1",
                entry_id,
                "follower-alpha",
                entry_id,
                entry_type,
                "market-a",
                "yes",
                qty,
                cash,
                cost,
                realized,
                fee,
                created,
                None,
            ),
        )
        connection.execute(
            "INSERT INTO continuous_shadow_evaluations VALUES "
            "(?,?,?,?,?,?,?,?)",
            (
                "exp-1",
                entry_id,
                "follower-alpha",
                price,
                str(abs(Decimal(qty))),
                "0",
                created,
                "SIMULATED",
            ),
        )
        connection.execute(
            "INSERT INTO continuous_shadow_event_journal VALUES (?)",
            (entry_id,),
        )
    connection.commit()


def test_fixture_inventory_and_primary_comparison_parity() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _tiny_shadow(connection)
    inventory, comparison = run_primary_comparison(
        connection, file_digests={"continuous-shadow.sqlite3": "abc"}
    )

    assert inventory.alpha_simulated_fill_count == 3
    assert inventory.ledger_balanced is True
    assert comparison.parity.passed is True
    assert comparison.current_control.realized_pnl == Decimal("-5")
    assert comparison.target_exposure.realized_pnl == Decimal("-4")
    assert comparison.economic_class == "risk_portfolio_improvement_not_alpha"
    assert "Not a profitability claim." in comparison.claims
    assert comparison.current_control.digest != comparison.target_exposure.digest


@pytest.mark.skipif(
    not (BACKUP_DIR / "continuous-shadow.sqlite3").is_file(),
    reason="local immutable backup is not present",
)
def test_local_backup_hashes_match_frozen_digest() -> None:
    verified = verify_backup_digests(BACKUP_DIR)
    after = {
        name: sha256_file(BACKUP_DIR / name) for name in HELSINKI_FINAL_BACKUP_FILES
    }
    assert verified == after == HELSINKI_FINAL_BACKUP_FILES
