"""Immutable Stage 4B historical baseline, sufficiency gate, and primary comparison.

This module streams the frozen backup. It does not copy databases into Git, emit
wallet addresses, or authorize Live/Risk/Execution behavior.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from polysia.backtesting.shadow_stateful_replay import (
    CutoffMark,
    ReplaySnapshot,
    ShadowReplayEvent,
    ShadowReplayKind,
    replay_shadow_events,
)
from polysia.domain.copytrading.continuous_shadow import ZERO
from polysia.domain.copytrading.target_exposure import TargetExposurePolicy
from polysia.storage.immutable_sqlite import (
    ImmutableSqliteError,
    open_immutable_sqlite,
    sha256_file,
    verify_file_digest,
)

HELSINKI_FINAL_BACKUP_ID = "helsinki-final-20260906T175930Z"
HELSINKI_FINAL_BACKUP_FILES: dict[str, str] = {
    "continuous-shadow.sqlite3": (
        "7505496e4fd3cc2dd9860720899c860b272649dcbd969d558c9263c69c14406e"
    ),
    "wallet-intelligence.sqlite3": (
        "16b80a19b61cc830dc1d31d45a4b71ba3ff8c75f09dfffd3e805192222bd33fc"
    ),
    "wallet-intelligence-latency.sqlite3": (
        "dcb652c35012c4a2095f6d4915cc23d802137df3cb426658d65de7aac8521462"
    ),
}
AUTHORITATIVE_ALPHA_SIMULATED_FILLS = 450
POST_CUTOFF_LIVE_QUERY_FILLS = 455
ALPHA_PORTFOLIO_ID = "follower-alpha"
_TOLERANCE = Decimal("0.000001")
PRIMARY_COMPARISON = (ShadowReplayKind.CURRENT_CONTROL, ShadowReplayKind.TARGET_EXPOSURE_V1)
_COUNT_TABLES = frozenset(
    {
        "continuous_shadow_event_journal",
        "continuous_shadow_evaluations",
        "continuous_shadow_ledger",
        "continuous_shadow_positions",
        "continuous_shadow_position_marks",
        "continuous_shadow_poll_runs",
    }
)
_COUNT_COLUMNS = frozenset({"market_reference", "outcome_reference", "wallet_id"})


class SufficiencyClass(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


class HistoricalBaselineError(RuntimeError):
    """Raised when baseline evidence is incomplete or the digest does not match."""


@dataclass(frozen=True, slots=True)
class SufficiencyRow:
    capability: str
    classification: SufficiencyClass
    available_evidence: str
    missing_evidence: str
    permitted_conclusion: str

    def to_dict(self) -> dict[str, str]:
        return {
            "available_evidence": self.available_evidence,
            "capability": self.capability,
            "classification": self.classification.value,
            "missing_evidence": self.missing_evidence,
            "permitted_conclusion": self.permitted_conclusion,
        }


@dataclass(frozen=True, slots=True)
class BaselineInventory:
    experiment_id: str
    source_id: str
    policy_version: str
    cost_model_version: str
    bankroll_version: str
    lifecycle: str
    schema_version: int
    started_at: str
    last_poll_at: str | None
    event_count: int
    evaluation_count: int
    simulated_evaluation_count: int
    alpha_simulated_fill_count: int
    alpha_simulated_with_price: int
    alpha_simulated_event_ids: int
    ledger_count: int
    alpha_ledger_count: int
    open_count: int
    increase_count: int
    reduce_count: int
    close_count: int
    settlement_count: int
    position_count: int
    alpha_open_positions: int
    mark_count: int
    poll_count: int
    initial_cash: Decimal
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees: Decimal
    nav: Decimal
    high_water_nav: Decimal
    drawdown: Decimal
    exposure: Decimal
    ledger_sum_qty: Decimal
    ledger_sum_cash: Decimal
    ledger_sum_cost: Decimal
    ledger_sum_realized: Decimal
    ledger_sum_fee: Decimal
    distinct_markets: int
    distinct_outcomes: int
    distinct_wallets: int
    ledger_balanced: bool
    integrity_ok: bool
    has_per_event_order_books: bool
    has_subsecond_source_path: bool
    has_markouts: bool
    has_market_only_labels: bool
    has_structural_alpha_features: bool
    fill_count_resolution: str

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha_ledger_count": self.alpha_ledger_count,
            "alpha_open_positions": self.alpha_open_positions,
            "alpha_simulated_event_ids": self.alpha_simulated_event_ids,
            "alpha_simulated_fill_count": self.alpha_simulated_fill_count,
            "alpha_simulated_with_price": self.alpha_simulated_with_price,
            "authoritative_alpha_simulated_fills": AUTHORITATIVE_ALPHA_SIMULATED_FILLS,
            "bankroll_version": self.bankroll_version,
            "cash": format(self.cash, "f"),
            "close_count": self.close_count,
            "cost_model_version": self.cost_model_version,
            "distinct_markets": self.distinct_markets,
            "distinct_outcomes": self.distinct_outcomes,
            "distinct_wallets": self.distinct_wallets,
            "drawdown": format(self.drawdown, "f"),
            "evaluation_count": self.evaluation_count,
            "event_count": self.event_count,
            "experiment_id": self.experiment_id,
            "exposure": format(self.exposure, "f"),
            "fees": format(self.fees, "f"),
            "fill_count_resolution": self.fill_count_resolution,
            "has_markouts": self.has_markouts,
            "has_market_only_labels": self.has_market_only_labels,
            "has_per_event_order_books": self.has_per_event_order_books,
            "has_structural_alpha_features": self.has_structural_alpha_features,
            "has_subsecond_source_path": self.has_subsecond_source_path,
            "high_water_nav": format(self.high_water_nav, "f"),
            "increase_count": self.increase_count,
            "initial_cash": format(self.initial_cash, "f"),
            "integrity_ok": self.integrity_ok,
            "last_poll_at": self.last_poll_at,
            "ledger_balanced": self.ledger_balanced,
            "ledger_count": self.ledger_count,
            "ledger_sum_cash": format(self.ledger_sum_cash, "f"),
            "ledger_sum_cost": format(self.ledger_sum_cost, "f"),
            "ledger_sum_fee": format(self.ledger_sum_fee, "f"),
            "ledger_sum_qty": format(self.ledger_sum_qty, "f"),
            "ledger_sum_realized": format(self.ledger_sum_realized, "f"),
            "lifecycle": self.lifecycle,
            "mark_count": self.mark_count,
            "nav": format(self.nav, "f"),
            "open_count": self.open_count,
            "policy_version": self.policy_version,
            "poll_count": self.poll_count,
            "position_count": self.position_count,
            "post_cutoff_live_query_fills": POST_CUTOFF_LIVE_QUERY_FILLS,
            "realized_pnl": format(self.realized_pnl, "f"),
            "reduce_count": self.reduce_count,
            "schema_version": self.schema_version,
            "settlement_count": self.settlement_count,
            "simulated_evaluation_count": self.simulated_evaluation_count,
            "source_id": self.source_id,
            "started_at": self.started_at,
            "unrealized_pnl": format(self.unrealized_pnl, "f"),
        }


@dataclass(frozen=True, slots=True)
class ControlParity:
    passed: bool
    cash_ok: bool
    realized_ok: bool
    fees_ok: bool
    exposure_ok: bool
    nav_ok: bool
    quantity_ok: bool
    details: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "cash_ok": self.cash_ok,
            "details": self.details,
            "exposure_ok": self.exposure_ok,
            "fees_ok": self.fees_ok,
            "nav_ok": self.nav_ok,
            "passed": self.passed,
            "quantity_ok": self.quantity_ok,
            "realized_ok": self.realized_ok,
        }


@dataclass(frozen=True, slots=True)
class PrimaryComparison:
    current_control: ReplaySnapshot
    target_exposure: ReplaySnapshot
    parity: ControlParity
    economic_class: str
    claims: tuple[str, ...]
    dataset_digest: str
    policy: TargetExposurePolicy
    sufficiency: tuple[SufficiencyRow, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "claims": list(self.claims),
            "current_control": self.current_control.to_dict(),
            "dataset_digest": self.dataset_digest,
            "economic_class": self.economic_class,
            "parity": self.parity.to_dict(),
            "policy": self.policy.to_dict(),
            "primary_comparison": [item.value for item in PRIMARY_COMPARISON],
            "sufficiency": [row.to_dict() for row in self.sufficiency],
            "target_exposure": self.target_exposure.to_dict(),
        }


def classify_data_sufficiency(inventory: BaselineInventory) -> tuple[SufficiencyRow, ...]:
    exact_control = (
        SufficiencyClass.SUPPORTED
        if (
            inventory.integrity_ok
            and inventory.ledger_balanced
            and inventory.alpha_ledger_count > 0
            and inventory.alpha_simulated_fill_count == inventory.alpha_simulated_event_ids
        )
        else SufficiencyClass.PARTIAL
    )
    target = (
        SufficiencyClass.PARTIAL
        if (
            inventory.alpha_simulated_with_price == inventory.alpha_simulated_fill_count
            and inventory.alpha_simulated_fill_count > 0
            and not inventory.has_per_event_order_books
        )
        else SufficiencyClass.UNSUPPORTED
        if inventory.alpha_simulated_with_price == 0
        else SufficiencyClass.PARTIAL
    )
    confirmation = (
        SufficiencyClass.PARTIAL
        if inventory.close_count + inventory.settlement_count > 0
        else SufficiencyClass.UNSUPPORTED
    )
    native_exits = (
        SufficiencyClass.PARTIAL
        if inventory.close_count + inventory.reduce_count > 0
        else SufficiencyClass.UNSUPPORTED
    )
    return (
        SufficiencyRow(
            "exact_current_control_reconstruction",
            exact_control,
            "Alpha ledger deltas, portfolio snapshot, Decimal identities, integrity_check",
            "poll-by-poll mark path is not streamed into intra-event drawdown",
            "Reproduce cutoff cash, fees, realized P&L, exposure, NAV, and open inventory",
        ),
        SufficiencyRow(
            "target_exposure_reconstruction",
            target,
            "First-fill executable prices, fees, and quantities on Alpha SIMULATED events",
            "Order books at skipped later increases; settlement rows have null event_id",
            "Replay TE v1 from recorded first-fill evidence; do not invent missing books",
        ),
        SufficiencyRow(
            "market_confirmation",
            confirmation,
            "Recorded CLOSE and SETTLEMENT ledger rows",
            "No independent confirmation feed separate from Stage 4B settlement",
            "Use recorded close/settlement only; missing confirmation stays UNKNOWN",
        ),
        SufficiencyRow(
            "sub_second_latency_scenarios",
            SufficiencyClass.UNSUPPORTED,
            "Minute-scale poll windows and evaluation timestamps",
            "No sub-second source-to-eval path in this backup",
            "Do not estimate one-second latency P&L from this dataset",
        ),
        SufficiencyRow(
            "leader_follower_markouts",
            (
                SufficiencyClass.UNSUPPORTED
                if not inventory.has_markouts
                else SufficiencyClass.PARTIAL
            ),
            "Follower executable prices at evaluation time",
            "No paired leader/follower markout horizon series",
            "UNKNOWN/INSUFFICIENT_DATA for markout Alpha",
        ),
        SufficiencyRow(
            "conditional_wallet_market_vs_market_state_only",
            SufficiencyClass.UNSUPPORTED,
            "Wallet-attributed journal and evaluations",
            "No frozen market-state-only counterfactual labels at decision time",
            "Do not claim Wallet+Market versus Market-state-only separation",
        ),
        SufficiencyRow(
            "true_independent_market_only",
            SufficiencyClass.UNSUPPORTED,
            "None",
            "No independent market-only experiment identity",
            "UNSUPPORTED; record only in this matrix",
        ),
        SufficiencyRow(
            "follower_native_exits",
            native_exits,
            "Recorded REDUCE/CLOSE using leader-sell evidence",
            "No follower-native exit policy distinct from Current Control",
            "Reuse Current Control exits; do not claim a new exit strategy",
        ),
        SufficiencyRow(
            "structural_alpha",
            SufficiencyClass.UNSUPPORTED,
            "None",
            "No structural scanner features or placebo suite in this backup",
            "UNSUPPORTED; next-stage work only",
        ),
    )


def dataset_digest(file_digests: Mapping[str, str], inventory: BaselineInventory) -> str:
    payload = {
        "backup_id": HELSINKI_FINAL_BACKUP_ID,
        "cost_model_version": inventory.cost_model_version,
        "experiment_id": inventory.experiment_id,
        "files": dict(sorted(file_digests.items())),
        "last_poll_at": inventory.last_poll_at,
        "policy_version": inventory.policy_version,
        "simulated_fills": inventory.alpha_simulated_fill_count,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verify_backup_digests(backup_dir: Path) -> dict[str, str]:
    verified: dict[str, str] = {}
    for name, expected in HELSINKI_FINAL_BACKUP_FILES.items():
        path = backup_dir / name
        verified[name] = verify_file_digest(path, expected)
    return verified


def load_baseline_inventory(connection: sqlite3.Connection) -> BaselineInventory:
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    fk_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    schema = int(connection.execute(
        "SELECT schema_version FROM continuous_shadow_metadata"
    ).fetchone()[0])
    experiment = connection.execute(
        "SELECT experiment_id, source_id, policy_version, cost_model_version, "
        "bankroll_version, lifecycle, started_at, last_successful_poll_at "
        "FROM continuous_shadow_experiments"
    ).fetchone()
    if experiment is None:
        raise HistoricalBaselineError("backup contains no continuous-shadow experiment")
    experiment_id = str(experiment["experiment_id"])
    portfolio = connection.execute(
        "SELECT initial_cash, cash, realized_pnl, unrealized_pnl, fees, nav, "
        "high_water_nav, drawdown, exposure FROM continuous_shadow_portfolios "
        "WHERE experiment_id = ? AND portfolio_id = ?",
        (experiment_id, ALPHA_PORTFOLIO_ID),
    ).fetchone()
    if portfolio is None:
        raise HistoricalBaselineError("follower-alpha portfolio is missing")
    type_counts = {
        str(row["entry_type"]): int(row["n"])
        for row in connection.execute(
            "SELECT entry_type, COUNT(*) AS n FROM continuous_shadow_ledger "
            "WHERE experiment_id = ? AND portfolio_id = ? GROUP BY entry_type",
            (experiment_id, ALPHA_PORTFOLIO_ID),
        )
    }
    simulated = connection.execute(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT event_id) AS events, "
        "COUNT(CASE WHEN follower_price IS NOT NULL THEN 1 END) AS priced "
        "FROM continuous_shadow_evaluations WHERE experiment_id = ? "
        "AND portfolio_id = ? AND status = 'SIMULATED'",
        (experiment_id, ALPHA_PORTFOLIO_ID),
    ).fetchone()
    # SQLite SUM of integer CASE is a count, not a financial SUM.
    ledger_rows = connection.execute(
        "SELECT quantity_delta, cash_delta, cost_basis_delta, realized_pnl_delta, "
        "fee_delta FROM continuous_shadow_ledger WHERE experiment_id = ? "
        "AND portfolio_id = ?",
        (experiment_id, ALPHA_PORTFOLIO_ID),
    )
    sum_qty = sum_cash = sum_cost = sum_realized = sum_fee = ZERO
    alpha_ledger_count = 0
    for row in ledger_rows:
        alpha_ledger_count += 1
        sum_qty += Decimal(str(row["quantity_delta"]))
        sum_cash += Decimal(str(row["cash_delta"]))
        sum_cost += Decimal(str(row["cost_basis_delta"]))
        sum_realized += Decimal(str(row["realized_pnl_delta"]))
        sum_fee += Decimal(str(row["fee_delta"]))
    cash = Decimal(str(portfolio["cash"]))
    initial = Decimal(str(portfolio["initial_cash"]))
    realized = Decimal(str(portfolio["realized_pnl"]))
    fees = Decimal(str(portfolio["fees"]))
    exposure = Decimal(str(portfolio["exposure"]))
    ledger_balanced = (
        abs(initial + sum_cash - cash) <= _TOLERANCE
        and abs(sum_realized - realized) <= _TOLERANCE
        and abs(sum_fee - fees) <= _TOLERANCE
        and abs(sum_cost - exposure) <= _TOLERANCE
    )
    fill_count = int(simulated["n"])
    resolution = (
        f"Authoritative frozen Alpha SIMULATED fills are {fill_count}. "
        f"{POST_CUTOFF_LIVE_QUERY_FILLS} is a later live query after this snapshot "
        "and is not this baseline."
    )
    return BaselineInventory(
        experiment_id=experiment_id,
        source_id=str(experiment["source_id"]),
        policy_version=str(experiment["policy_version"]),
        cost_model_version=str(experiment["cost_model_version"]),
        bankroll_version=str(experiment["bankroll_version"]),
        lifecycle=str(experiment["lifecycle"]),
        schema_version=schema,
        started_at=str(experiment["started_at"]),
        last_poll_at=(
            None
            if experiment["last_successful_poll_at"] is None
            else str(experiment["last_successful_poll_at"])
        ),
        event_count=_count(connection, "continuous_shadow_event_journal"),
        evaluation_count=_count(
            connection,
            "continuous_shadow_evaluations",
            "experiment_id = ?",
            (experiment_id,),
        ),
        simulated_evaluation_count=_count(
            connection,
            "continuous_shadow_evaluations",
            "experiment_id = ? AND status = 'SIMULATED'",
            (experiment_id,),
        ),
        alpha_simulated_fill_count=fill_count,
        alpha_simulated_with_price=int(simulated["priced"] or 0),
        alpha_simulated_event_ids=int(simulated["events"]),
        ledger_count=_count(
            connection,
            "continuous_shadow_ledger",
            "experiment_id = ?",
            (experiment_id,),
        ),
        alpha_ledger_count=alpha_ledger_count,
        open_count=type_counts.get("OPEN", 0),
        increase_count=type_counts.get("INCREASE", 0),
        reduce_count=type_counts.get("REDUCE", 0),
        close_count=type_counts.get("CLOSE", 0),
        settlement_count=type_counts.get("SETTLEMENT", 0),
        position_count=_count(
            connection,
            "continuous_shadow_positions",
            "experiment_id = ?",
            (experiment_id,),
        ),
        alpha_open_positions=_count(
            connection,
            "continuous_shadow_positions",
            "experiment_id = ? AND portfolio_id = ?",
            (experiment_id, ALPHA_PORTFOLIO_ID),
        ),
        mark_count=_count(
            connection,
            "continuous_shadow_position_marks",
            "experiment_id = ? AND portfolio_id = ?",
            (experiment_id, ALPHA_PORTFOLIO_ID),
        ),
        poll_count=_count(
            connection,
            "continuous_shadow_poll_runs",
            "experiment_id = ?",
            (experiment_id,),
        ),
        initial_cash=initial,
        cash=cash,
        realized_pnl=realized,
        unrealized_pnl=Decimal(str(portfolio["unrealized_pnl"])),
        fees=fees,
        nav=Decimal(str(portfolio["nav"])),
        high_water_nav=Decimal(str(portfolio["high_water_nav"])),
        drawdown=Decimal(str(portfolio["drawdown"])),
        exposure=exposure,
        ledger_sum_qty=sum_qty,
        ledger_sum_cash=sum_cash,
        ledger_sum_cost=sum_cost,
        ledger_sum_realized=sum_realized,
        ledger_sum_fee=sum_fee,
        distinct_markets=_count_distinct(
            connection,
            "continuous_shadow_ledger",
            "market_reference",
            "experiment_id = ? AND portfolio_id = ? AND market_reference IS NOT NULL",
            (experiment_id, ALPHA_PORTFOLIO_ID),
        ),
        distinct_outcomes=_count_distinct(
            connection,
            "continuous_shadow_ledger",
            "outcome_reference",
            "experiment_id = ? AND portfolio_id = ? AND outcome_reference IS NOT NULL",
            (experiment_id, ALPHA_PORTFOLIO_ID),
        ),
        distinct_wallets=_count_distinct(
            connection,
            "continuous_shadow_ledger",
            "wallet_id",
            "experiment_id = ? AND portfolio_id = ? AND wallet_id IS NOT NULL",
            (experiment_id, ALPHA_PORTFOLIO_ID),
        ),
        ledger_balanced=ledger_balanced,
        integrity_ok=integrity == "ok" and not fk_rows,
        has_per_event_order_books=False,
        has_subsecond_source_path=False,
        has_markouts=False,
        has_market_only_labels=False,
        has_structural_alpha_features=False,
        fill_count_resolution=resolution,
    )


def iter_alpha_ledger_events(connection: sqlite3.Connection) -> Iterator[ShadowReplayEvent]:
    """Stream Alpha ledger rows joined to contemporaneous evaluation prices."""

    cursor = connection.execute(
        "SELECT l.entry_id, l.event_id, l.entry_type, l.created_at, "
        "l.market_reference, l.outcome_reference, l.quantity_delta, l.cash_delta, "
        "l.cost_basis_delta, l.realized_pnl_delta, l.fee_delta, "
        "e.follower_price, e.filled_size, e.fee AS evaluation_fee, "
        "e.evaluated_at, e.status AS evaluation_status "
        "FROM continuous_shadow_ledger l "
        "LEFT JOIN continuous_shadow_evaluations e "
        "ON e.experiment_id = l.experiment_id AND e.event_id = l.event_id "
        "AND e.portfolio_id = l.portfolio_id "
        "WHERE l.portfolio_id = ? "
        "ORDER BY l.created_at, l.entry_id",
        (ALPHA_PORTFOLIO_ID,),
    )
    for row in cursor:
        yield ShadowReplayEvent(
            entry_id=str(row["entry_id"]),
            created_at=_parse_time(str(row["created_at"])),
            entry_type=str(row["entry_type"]),
            market_reference=(
                None if row["market_reference"] is None else str(row["market_reference"])
            ),
            outcome_reference=(
                None
                if row["outcome_reference"] is None
                else str(row["outcome_reference"])
            ),
            quantity_delta=Decimal(str(row["quantity_delta"])),
            cash_delta=Decimal(str(row["cash_delta"])),
            cost_basis_delta=Decimal(str(row["cost_basis_delta"])),
            realized_pnl_delta=Decimal(str(row["realized_pnl_delta"])),
            fee_delta=Decimal(str(row["fee_delta"])),
            event_id=None if row["event_id"] is None else str(row["event_id"]),
            follower_price=_optional_decimal(row["follower_price"]),
            filled_size=_optional_decimal(row["filled_size"]),
            evaluation_fee=_optional_decimal(row["evaluation_fee"]),
            evaluated_at=(
                None
                if row["evaluated_at"] is None
                else _parse_time(str(row["evaluated_at"]))
            ),
            evaluation_status=(
                None if row["evaluation_status"] is None else str(row["evaluation_status"])
            ),
        )


def load_cutoff_marks(connection: sqlite3.Connection) -> dict[tuple[str, str], CutoffMark]:
    marks: dict[tuple[str, str], CutoffMark] = {}
    rows = connection.execute(
        "SELECT market_reference, outcome_reference, mark_price, mark_status, marked_at "
        "FROM continuous_shadow_positions WHERE portfolio_id = ?",
        (ALPHA_PORTFOLIO_ID,),
    )
    for row in rows:
        marks[(str(row["market_reference"]), str(row["outcome_reference"]))] = CutoffMark(
            price=_optional_decimal(row["mark_price"]),
            status=str(row["mark_status"] or "MISSING"),
            marked_at=(
                None if row["marked_at"] is None else _parse_time(str(row["marked_at"]))
            ),
        )
    return marks


def control_parity(snapshot: ReplaySnapshot, inventory: BaselineInventory) -> ControlParity:
    cash_ok = abs(snapshot.cash - inventory.cash) <= _TOLERANCE
    realized_ok = abs(snapshot.realized_pnl - inventory.realized_pnl) <= _TOLERANCE
    fees_ok = abs(snapshot.fees - inventory.fees) <= _TOLERANCE
    exposure_ok = abs(snapshot.exposure - inventory.exposure) <= _TOLERANCE
    quantity_ok = abs(snapshot.open_quantity - inventory.ledger_sum_qty) <= _TOLERANCE
    nav_ok = (
        snapshot.nav is not None and abs(snapshot.nav - inventory.nav) <= _TOLERANCE
    )
    details = {
        "cash": f"{snapshot.cash} vs {inventory.cash}",
        "exposure": f"{snapshot.exposure} vs {inventory.exposure}",
        "fees": f"{snapshot.fees} vs {inventory.fees}",
        "nav": f"{snapshot.nav} vs {inventory.nav}",
        "open_quantity": f"{snapshot.open_quantity} vs {inventory.ledger_sum_qty}",
        "realized_pnl": f"{snapshot.realized_pnl} vs {inventory.realized_pnl}",
    }
    return ControlParity(
        passed=cash_ok and realized_ok and fees_ok and exposure_ok and quantity_ok and nav_ok,
        cash_ok=cash_ok,
        realized_ok=realized_ok,
        fees_ok=fees_ok,
        exposure_ok=exposure_ok,
        nav_ok=nav_ok,
        quantity_ok=quantity_ok,
        details=details,
    )


def classify_economic_result(
    control: ReplaySnapshot,
    challenger: ReplaySnapshot,
    *,
    initial_cash: Decimal,
) -> str:
    if control.nav is None or challenger.nav is None:
        return "insufficient_marks_not_an_alpha_result"
    if challenger.nav > control.nav and challenger.nav < initial_cash:
        return "risk_portfolio_improvement_not_alpha"
    if challenger.nav >= initial_cash:
        return "not_out_of_sample_alpha_and_not_live_ready"
    return "descriptive_comparison_not_alpha"


def run_primary_comparison(
    connection: sqlite3.Connection,
    *,
    file_digests: Mapping[str, str],
    policy: TargetExposurePolicy | None = None,
) -> tuple[BaselineInventory, PrimaryComparison]:
    inventory = load_baseline_inventory(connection)
    sufficiency = classify_data_sufficiency(inventory)
    policy = policy or TargetExposurePolicy(
        cost_model_version=inventory.cost_model_version,
        control_policy_version=inventory.policy_version,
    )
    marks = load_cutoff_marks(connection)
    control = replay_shadow_events(
        iter_alpha_ledger_events(connection),
        kind=ShadowReplayKind.CURRENT_CONTROL,
        initial_cash=inventory.initial_cash,
        cutoff_marks=marks,
    )
    challenger = replay_shadow_events(
        iter_alpha_ledger_events(connection),
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=inventory.initial_cash,
        policy=policy,
        cutoff_marks=marks,
    )
    parity = control_parity(control, inventory)
    comparison = PrimaryComparison(
        current_control=control,
        target_exposure=challenger,
        parity=parity,
        economic_class=classify_economic_result(
            control, challenger, initial_cash=inventory.initial_cash
        ),
        claims=(
            "Not a profitability claim.",
            "Not out-of-sample Alpha.",
            "Not independent Market-only Alpha.",
            "Not Live ready.",
            "SignalArbiter remains leader-relative execution advantage, not P(alpha).",
            "walk_forward_policy_report is descriptive/non-stateful and is not this replay.",
        ),
        dataset_digest=dataset_digest(file_digests, inventory),
        policy=policy,
        sufficiency=sufficiency,
    )
    return inventory, comparison


def run_backup_research(backup_dir: Path) -> dict[str, object]:
    before = verify_backup_digests(backup_dir)
    shadow = backup_dir / "continuous-shadow.sqlite3"
    with open_immutable_sqlite(
        shadow, expected_sha256=HELSINKI_FINAL_BACKUP_FILES[shadow.name]
    ) as connection:
        inventory, comparison = run_primary_comparison(connection, file_digests=before)
    after = {name: sha256_file(backup_dir / name) for name in HELSINKI_FINAL_BACKUP_FILES}
    if after != before:
        raise ImmutableSqliteError("backup SHA-256 changed after read-only research")
    if inventory.alpha_simulated_fill_count != AUTHORITATIVE_ALPHA_SIMULATED_FILLS:
        raise HistoricalBaselineError(
            "authoritative Alpha SIMULATED fill count is "
            f"{AUTHORITATIVE_ALPHA_SIMULATED_FILLS}, found "
            f"{inventory.alpha_simulated_fill_count}"
        )
    return {
        "backup_id": HELSINKI_FINAL_BACKUP_ID,
        "comparison": comparison.to_dict(),
        "file_digests_after": after,
        "file_digests_before": before,
        "inventory": inventory.to_dict(),
        "status": "ok" if comparison.parity.passed else "parity_failed",
    }


def _count(
    connection: sqlite3.Connection,
    table: str,
    where: str | None = None,
    params: tuple[object, ...] = (),
) -> int:
    if table not in _COUNT_TABLES:
        raise HistoricalBaselineError(f"refusing to count unknown table {table}")
    sql = f"SELECT COUNT(*) FROM {table}" if where is None else (
        f"SELECT COUNT(*) FROM {table} WHERE {where}"
    )
    return int(connection.execute(sql, params).fetchone()[0])


def _count_distinct(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    where: str,
    params: tuple[object, ...],
) -> int:
    if table not in _COUNT_TABLES or column not in _COUNT_COLUMNS:
        raise HistoricalBaselineError("refusing to count unknown table or column")
    return int(
        connection.execute(
            f"SELECT COUNT(DISTINCT {column}) FROM {table} WHERE {where}",
            params,
        ).fetchone()[0]
    )


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    parsed = Decimal(str(value))
    return parsed


__all__ = [
    "ALPHA_PORTFOLIO_ID",
    "AUTHORITATIVE_ALPHA_SIMULATED_FILLS",
    "BaselineInventory",
    "ControlParity",
    "HELSINKI_FINAL_BACKUP_FILES",
    "HELSINKI_FINAL_BACKUP_ID",
    "HistoricalBaselineError",
    "POST_CUTOFF_LIVE_QUERY_FILLS",
    "PRIMARY_COMPARISON",
    "PrimaryComparison",
    "SufficiencyClass",
    "SufficiencyRow",
    "classify_data_sufficiency",
    "classify_economic_result",
    "control_parity",
    "dataset_digest",
    "iter_alpha_ledger_events",
    "load_baseline_inventory",
    "load_cutoff_marks",
    "run_backup_research",
    "run_primary_comparison",
    "verify_backup_digests",
]
