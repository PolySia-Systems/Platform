"""Verify the recorded wallet Control path with the production Shadow policy."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from polysia.application.services.continuous_shadow import (
    _MutableAttribution,
    _MutablePortfolio,
    apply_shadow_event,
)
from polysia.domain.copytrading import LeaderPositionEffect, LeaderTradeAction, LeaderTradeEvent
from polysia.domain.copytrading.continuous_shadow import (
    FOLLOWER_KINDS,
    ContinuousPortfolioKind,
    ContinuousShadowConfig,
    ContinuousShadowLifecycle,
    follower_accepts_pool,
)
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    OrderBookLevel,
)

ZERO = Decimal("0")
_LEDGER_FIELDS = (
    "quantity_delta", "cash_delta", "cost_basis_delta", "realized_pnl_delta", "fee_delta"
)


def verify_matched_wallet_control(
    *,
    opportunities: tuple[dict[str, object], ...],
    evaluations: tuple[dict[str, object], ...],
    ledger: tuple[dict[str, object], ...],
    portfolios: tuple[dict[str, object], ...],
    positions: tuple[dict[str, object], ...],
    poll_order: tuple[str, ...],
    config: ContinuousShadowConfig,
) -> dict[str, object]:
    """Recreate Shadow portfolios from zero state; compare each decision and delta.

    The recorded policy is distinct from the prospective counterfactual policies.
    Legacy v1 opportunities cannot prove parity.
    """

    if any(row.get("version") != "shadow-opportunity-v2" for row in opportunities):
        return {"status": "UNKNOWN", "reason": "legacy_opportunity_lacks_policy_inputs"}
    if not opportunities:
        return {"status": "UNKNOWN", "reason": "no_admitted_opportunities"}
    by_evaluation = {
        (str(row["event_id"]), str(row["portfolio_id"])): row for row in evaluations
    }
    by_ledger = {
        (str(row["event_id"]), str(row["portfolio_id"])): row
        for row in ledger if row.get("event_id") is not None
    }
    actual_portfolios = {str(row["portfolio_id"]): row for row in portfolios}
    replayed: dict[str, _MutablePortfolio] = {}
    for portfolio_id, row in actual_portfolios.items():
        kind = ContinuousPortfolioKind(str(row["kind"]))
        bankroll = (
            config.wallet_bankroll
            if kind is ContinuousPortfolioKind.WALLET else config.follower_bankroll
        )
        replayed[portfolio_id] = _MutablePortfolio(
            portfolio_id=portfolio_id, kind=kind,
            wallet_id=None if row["wallet_id"] is None else str(row["wallet_id"]),
            initial_cash=bankroll, cash=bankroll, realized_pnl=ZERO, fees=ZERO,
            high_water_nav=bankroll, drawdown=ZERO, positions={},
        )
    attributions: dict[tuple[str, str, str, str], _MutableAttribution] = {}
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    settlements_by_poll: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in opportunities:
        groups[str(row["poll_run_id"])].append(row)
    for row in ledger:
        if row.get("entry_type") == "SETTLEMENT":
            poll_id = str(row["poll_run_id"])
            groups.setdefault(poll_id, [])
            settlements_by_poll[poll_id].append(row)
    mismatches: list[str] = []
    checked_evaluations: set[tuple[str, str]] = set()
    checked_ledger: set[tuple[str, str]] = set()
    simulated = rejected = unknown = partial = settled = 0
    for portfolio_id, row in actual_portfolios.items():
        if Decimal(str(row["initial_cash"])) != replayed[portfolio_id].initial_cash:
            mismatches.append(f"opening_capital:{portfolio_id}")
    if set(groups) - set(poll_order):
        mismatches.append("evidence_poll_not_successful")
    for poll_id in (item for item in poll_order if item in groups):
        consumed: dict[tuple[str, str], dict[Decimal, Decimal]] = {}
        settlement_groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
        for recorded in settlements_by_poll[poll_id]:
            settlement_groups[(
                str(recorded["portfolio_id"]), str(recorded["market_reference"]),
                str(recorded["outcome_reference"]),
            )].append(recorded)
        for (portfolio_id, market_ref, token_ref), recorded_rows in settlement_groups.items():
            portfolio = replayed.get(portfolio_id)
            if portfolio is None:
                mismatches.append(f"settlement_without_opening:{portfolio_id}")
                continue
            key = (market_ref, token_ref)
            position = portfolio.positions.get(key)
            if position is None:
                mismatches.append(f"settlement_without_position:{portfolio_id}")
                continue
            marks = {str(row.get("verified_mark_price")) for row in recorded_rows}
            if len(marks) != 1 or next(iter(marks)) not in {"0", "1"}:
                mismatches.append(f"settlement_without_verified_terminal:{portfolio_id}")
                continue
            mark = next(iter(marks))
            proceeds = position.quantity * Decimal(str(mark))
            matching = [
                (attr_key, attr) for attr_key, attr in attributions.items()
                if attr_key[0] == portfolio_id and attr_key[2:] == key
            ]
            expected_rows: list[tuple[str | None, dict[str, Decimal]]] = []
            if matching and portfolio.kind in FOLLOWER_KINDS:
                remaining_qty = position.quantity
                remaining_cost = position.cost_basis
                remaining_proceeds = proceeds
                for index, (attr_key, attr) in enumerate(matching):
                    last = index == len(matching) - 1
                    qty = remaining_qty if last else attr.quantity
                    cost = remaining_cost if last else attr.cost_basis
                    share_proceeds = remaining_proceeds if last else qty * Decimal(mark)
                    remaining_qty -= qty
                    remaining_cost -= cost
                    remaining_proceeds -= share_proceeds
                    expected_rows.append((attr_key[1], {
                        "quantity_delta": -qty, "cash_delta": share_proceeds,
                        "cost_basis_delta": -cost,
                        "realized_pnl_delta": share_proceeds - cost, "fee_delta": ZERO,
                    }))
                    del attributions[attr_key]
            else:
                expected_rows.append((portfolio.wallet_id, {
                    "quantity_delta": -position.quantity, "cash_delta": proceeds,
                    "cost_basis_delta": -position.cost_basis,
                    "realized_pnl_delta": proceeds - position.cost_basis,
                    "fee_delta": ZERO,
                }))
            if len(expected_rows) != len(recorded_rows):
                mismatches.append(f"settlement_entry_count:{portfolio_id}")
            for wallet, expected in expected_rows:
                matches = [row for row in recorded_rows if row["wallet_id"] == wallet]
                if len(matches) != 1:
                    mismatches.append(f"settlement_wallet_identity:{portfolio_id}:{wallet}")
                else:
                    _compare_ledger(
                        matches[0], expected, mismatches, f"settlement:{portfolio_id}:{wallet}"
                    )
            portfolio.cash += proceeds
            portfolio.realized_pnl += proceeds - position.cost_basis
            del portfolio.positions[key]
            settled += 1
        for row in sorted(groups[poll_id], key=lambda item: (
            str(item["source_at"]), str(item["event_id"])
        )):
            event_id = str(row["event_id"])
            event = _event(row)
            pool_class = str(row["pool_class"])
            targets = [f"wallet:{row['wallet_id']}"]
            for candidate in replayed.values():
                if candidate.kind not in FOLLOWER_KINDS:
                    continue
                if event.trade_action is LeaderTradeAction.BUY:
                    selected = follower_accepts_pool(candidate.kind, pool_class)
                else:
                    selected = follower_accepts_pool(candidate.kind, pool_class) or any(
                        key[0] == candidate.portfolio_id
                        and key[1] == event.leader_id
                        and key[2] == event.market_reference
                        and key[3] == event.outcome_reference
                        for key in attributions
                    )
                if selected:
                    targets.append(candidate.portfolio_id)
            for portfolio_id in targets:
                portfolio = replayed.get(portfolio_id)
                if portfolio is None:
                    mismatches.append(f"missing_opening_portfolio:{portfolio_id}")
                    continue
                key = (event_id, portfolio_id)
                recorded_evaluation = by_evaluation.get(key)
                if recorded_evaluation is None:
                    mismatches.append(f"missing_evaluation:{event_id}")
                    continue
                checked_evaluations.add(key)
                evaluation, entry = apply_shadow_event(
                    config, portfolio, event,
                    pool_class=str(row["pool_class"]),
                    lifecycle=ContinuousShadowLifecycle(str(row["lifecycle_at_decision"])),
                    exposure_increase_allowed=_boolean(row["exposure_increase_allowed"]),
                    market=_market(row), book=_book(row),
                    attributions=attributions, consumed_by_scope=consumed,
                    evaluated_at=_time(row["decision_at"]),
                )
                if str(recorded_evaluation["status"]) != evaluation.status.value:
                    mismatches.append(f"status:{event_id}")
                if str(recorded_evaluation["reason"]) != evaluation.reason:
                    mismatches.append(f"reason:{event_id}")
                for field in ("wallet_id", "pool_class", "fee_status", "fee_source"):
                    if str(recorded_evaluation[field]) != str(getattr(evaluation, field)):
                        mismatches.append(f"evaluation_{field}:{event_id}")
                for field in (
                    "requested_size", "filled_size", "follower_price", "gross_notional",
                    "fee", "fee_rate", "fee_exponent", "realized_pnl",
                ):
                    actual = recorded_evaluation.get(field)
                    expected_value = getattr(evaluation, field)
                    if (None if actual is None else Decimal(str(actual))) != expected_value:
                        mismatches.append(f"evaluation_{field}:{event_id}")
                if evaluation.status.value == "SIMULATED":
                    simulated += 1
                    if evaluation.reason == "partial_fill_after_shared_liquidity":
                        partial += 1
                elif evaluation.status.value == "REJECTED":
                    rejected += 1
                else:
                    unknown += 1
                recorded_entry = by_ledger.get(key)
                if entry is None:
                    if recorded_entry is not None:
                        mismatches.append(f"unexpected_ledger:{event_id}")
                elif recorded_entry is None:
                    mismatches.append(f"missing_ledger:{event_id}")
                else:
                    checked_ledger.add(key)
                    if str(recorded_entry["entry_type"]) != entry.entry_type:
                        mismatches.append(f"entry_type:{event_id}")
                    for field in (
                        "wallet_id", "pool_class", "market_reference", "outcome_reference"
                    ):
                        if str(recorded_entry[field]) != str(getattr(entry, field)):
                            mismatches.append(f"ledger_{field}:{event_id}")
                    _compare_ledger(recorded_entry, {
                        field: getattr(entry, field) for field in _LEDGER_FIELDS
                    }, mismatches, event_id)
    for key in by_evaluation.keys() - checked_evaluations:
        mismatches.append(f"unmatched_evaluation:{key[0]}")
    for key in by_ledger.keys() - checked_ledger:
        mismatches.append(f"unmatched_ledger:{key[0]}")
    for portfolio_id, portfolio in replayed.items():
        stored_portfolio = actual_portfolios.get(portfolio_id)
        if stored_portfolio is None:
            mismatches.append(f"missing_portfolio:{portfolio_id}")
            continue
        for field in ("cash", "realized_pnl", "fees"):
            if Decimal(str(stored_portfolio[field])) != getattr(portfolio, field):
                mismatches.append(f"portfolio_{field}:{portfolio_id}")
        expected_positions = portfolio.positions
        actual_positions = {
            (str(row["market_reference"]), str(row["outcome_reference"])): row
            for row in positions if row["portfolio_id"] == portfolio_id
        }
        if expected_positions.keys() != actual_positions.keys():
            mismatches.append(f"position_identity:{portfolio_id}")
        for key, expected_position in expected_positions.items():
            actual = actual_positions.get(key)
            if actual is not None and any(
                Decimal(str(actual[field])) != getattr(expected_position, field)
                for field in ("quantity", "cost_basis", "entry_fees")
            ):
                mismatches.append(f"position_balance:{portfolio_id}:{key[1]}")
    return {
        "status": "VERIFIED" if not mismatches else "MISMATCH",
        "scope": "wallet_and_follower_production_policy_from_zero_opening_state",
        "opportunities": len(opportunities),
        "simulated": simulated,
        "rejected": rejected,
        "unknown": unknown,
        "partial_fills": partial,
        "settlements": settled,
        "mismatches": sorted(set(mismatches)),
    }


def _compare_ledger(
    actual: dict[str, object], expected: dict[str, Decimal],
    mismatches: list[str], identity: str,
) -> None:
    for field in _LEDGER_FIELDS:
        if Decimal(str(actual[field])) != expected[field]:
            mismatches.append(f"ledger_{field}:{identity}")


def _event(row: dict[str, object]) -> LeaderTradeEvent:
    return LeaderTradeEvent(
        event_id=str(row["event_id"]), source_id=str(row["source_id"]),
        leader_id=str(row["wallet_id"]),
        market_reference=str(row["market_reference"]),
        outcome_reference=str(row["outcome_reference"]),
        trade_action=LeaderTradeAction(str(row["side"])),
        position_effect=LeaderPositionEffect.UNKNOWN,
        executed_price=Decimal(str(row["price"])),
        executed_size=Decimal(str(row["size"])),
        executed_at=_time(row["source_at"]),
        observed_at=_time(row["first_observed_at"]),
        external_evidence_reference=None,
    )


def _market(row: dict[str, object]) -> MarketDetails | None:
    if row.get("market_token_binding") != "VERIFIED":
        return None
    enabled = row.get("fee_enabled")
    schedule = None if enabled is None else MarketFeeSchedule(
        enabled=_boolean(enabled),
        rate=None if row.get("fee_rate") is None else Decimal(str(row["fee_rate"])),
        exponent=None if row.get("fee_exponent") is None else Decimal(str(row["fee_exponent"])),
        taker_only=None if row.get("fee_taker_only") is None else _boolean(row["fee_taker_only"]),
    )
    return MarketDetails(
        id=str(row["market_reference"]),
        condition_id=str(row["market_reference"]),
        outcomes=(MarketOutcomeSummary(label="recorded", token_id=str(row["outcome_reference"])),),
        fee_schedule=schedule,
    )


def _book(row: dict[str, object]) -> MarketOrderBookSnapshot | None:
    if row.get("book_at") is None:
        return None
    minimum = row.get("book_minimum_order_size")
    tick = row.get("book_tick_size")
    if minimum is None or tick is None:
        raise ValueError("v2 opportunity is missing book trading rules")
    levels = row.get("book_levels")
    bids = row.get("book_bids")
    asks = row.get("book_asks")
    if not isinstance(levels, list) or not isinstance(bids, list) or not isinstance(asks, list):
        raise ValueError("v2 opportunity book levels are malformed")
    bid_levels = tuple(
        OrderBookLevel(price=Decimal(str(item["price"])), size=Decimal(str(item["size"])))
        for item in bids
    )
    ask_levels = tuple(
        OrderBookLevel(price=Decimal(str(item["price"])), size=Decimal(str(item["size"])))
        for item in asks
    )
    if levels != (asks if row["side"] == "BUY" else bids):
        raise ValueError("v2 opportunity executable side differs from full book")
    return MarketOrderBookSnapshot(
        token_id=str(row["outcome_reference"]),
        market_id=str(row["market_reference"]),
        timestamp=_time(row["book_at"]),
        asks=ask_levels,
        bids=bid_levels,
        minimum_order_size=Decimal(str(minimum)), tick_size=Decimal(str(tick)),
        book_hash=None if row.get("book_hash") is None else str(row["book_hash"]),
    )


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("matched Control timestamp is missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    offset = result.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("matched Control timestamp must be UTC")
    return result


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("matched Control boolean evidence is malformed")
    return value
