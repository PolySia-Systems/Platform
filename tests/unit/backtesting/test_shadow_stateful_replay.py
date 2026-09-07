from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.backtesting.shadow_stateful_replay import (
    CutoffMark,
    ShadowReplayError,
    ShadowReplayEvent,
    ShadowReplayKind,
    replay_shadow_events,
)
from polysia.domain.copytrading.target_exposure import TargetExposurePolicy

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
POLICY = TargetExposurePolicy()
INITIAL = Decimal("1000")


def _event(
    *,
    entry_id: str,
    seconds: int,
    entry_type: str,
    quantity: str,
    cash: str,
    cost: str,
    realized: str = "0",
    fee: str = "0",
    market: str = "market-a",
    outcome: str = "yes",
    price: str | None = None,
    filled: str | None = None,
    eval_fee: str | None = None,
) -> ShadowReplayEvent:
    created = NOW + timedelta(seconds=seconds)
    return ShadowReplayEvent(
        entry_id=entry_id,
        created_at=created,
        entry_type=entry_type,
        market_reference=market,
        outcome_reference=outcome,
        quantity_delta=Decimal(quantity),
        cash_delta=Decimal(cash),
        cost_basis_delta=Decimal(cost),
        realized_pnl_delta=Decimal(realized),
        fee_delta=Decimal(fee),
        event_id=entry_id,
        follower_price=None if price is None else Decimal(price),
        filled_size=None if filled is None else Decimal(filled),
        evaluation_fee=None if eval_fee is None else Decimal(eval_fee),
        evaluated_at=created,
        evaluation_status="SIMULATED",
    )


def _losing_pyramid() -> tuple[ShadowReplayEvent, ...]:
    return (
        _event(
            entry_id="e1",
            seconds=1,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="e2",
            seconds=2,
            entry_type="INCREASE",
            quantity="10",
            cash="-2",
            cost="2",
            price="0.20",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="e3",
            seconds=3,
            entry_type="CLOSE",
            quantity="-20",
            cash="2",
            cost="-7",
            realized="-5",
            price="0.10",
            filled="20",
            eval_fee="0",
        ),
    )


def test_current_control_reproduces_recorded_ledger_identities() -> None:
    snapshot = replay_shadow_events(
        _losing_pyramid(),
        kind=ShadowReplayKind.CURRENT_CONTROL,
        initial_cash=INITIAL,
    )

    assert snapshot.cash == Decimal("995")
    assert snapshot.realized_pnl == Decimal("-5")
    assert snapshot.exposure == Decimal("0")
    assert snapshot.fees == Decimal("0")
    assert snapshot.book_nav == Decimal("995")
    assert snapshot.open_count == 1
    assert snapshot.increase_count == 1
    assert snapshot.close_count == 1


def test_target_exposure_does_not_pyramid_or_rebalance() -> None:
    snapshot = replay_shadow_events(
        _losing_pyramid(),
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
    )

    assert snapshot.skipped_rebalance == 1
    assert snapshot.increase_count == 0
    assert snapshot.open_count == 1
    assert snapshot.realized_pnl == Decimal("-4")
    assert snapshot.cash == Decimal("996")
    assert snapshot.coverage_admitted_buys == 1


def test_additional_wallet_agreement_does_not_increase_notional() -> None:
    events = (
        _event(
            entry_id="w1",
            seconds=1,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="w2",
            seconds=2,
            entry_type="INCREASE",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
    )
    snapshot = replay_shadow_events(
        events,
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
    )

    assert snapshot.exposure == Decimal("5")
    assert snapshot.open_quantity == Decimal("10")
    assert snapshot.skipped_repeat == 1


def test_conflict_expiry_close_and_settlement() -> None:
    events = (
        _event(
            entry_id="yes",
            seconds=1,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="no",
            seconds=2,
            entry_type="OPEN",
            quantity="10",
            cash="-4",
            cost="4",
            market="market-a",
            outcome="no",
            price="0.40",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="close",
            seconds=3,
            entry_type="CLOSE",
            quantity="-10",
            cash="1",
            cost="-5",
            realized="-4",
            price="0.10",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="reopen",
            seconds=4,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="settle",
            seconds=5,
            entry_type="SETTLEMENT",
            quantity="-10",
            cash="0",
            cost="-5",
            realized="-5",
            filled="10",
            eval_fee="0",
        ),
    )
    snapshot = replay_shadow_events(
        events,
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
    )

    assert "REJECT_CONFLICT" in snapshot.decisions
    assert snapshot.skipped_reentry == 1
    assert snapshot.close_count == 1
    assert snapshot.settlement_count == 1
    assert snapshot.open_positions == 0


def test_missing_marks_remain_unknown_and_open_nav_is_not_invented() -> None:
    events = (
        _event(
            entry_id="open",
            seconds=1,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
    )
    snapshot = replay_shadow_events(
        events,
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
    )

    assert snapshot.unrealized_pnl is None
    assert snapshot.nav is None
    assert snapshot.unknown_unrealized_positions == 1
    assert snapshot.locked_capital == Decimal("5")
    assert snapshot.cash == Decimal("995")
    assert snapshot.book_nav == Decimal("1000")


def test_cutoff_marks_do_not_leak_into_entry_quantity() -> None:
    events = (
        _event(
            entry_id="open",
            seconds=1,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
    )
    future_mark = CutoffMark(
        price=Decimal("0.01"),
        status="VERIFIED_EXECUTABLE_BID",
        marked_at=NOW + timedelta(hours=5),
    )
    snapshot = replay_shadow_events(
        events,
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
        cutoff_marks={("market-a", "yes"): future_mark},
    )

    assert snapshot.open_quantity == Decimal("10")
    assert snapshot.exposure == Decimal("5")
    assert snapshot.unrealized_pnl == Decimal("10") * Decimal("0.01") - Decimal("5")


def test_replay_is_deterministic_and_idempotent() -> None:
    events = _losing_pyramid()
    first = replay_shadow_events(
        events,
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
    )
    second = replay_shadow_events(
        events,
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
    )
    doubled = replay_shadow_events(
        (*events, *events),
        kind=ShadowReplayKind.TARGET_EXPOSURE_V1,
        initial_cash=INITIAL,
        policy=POLICY,
    )

    assert first.digest == second.digest == doubled.digest
    assert first.cash == doubled.cash
    assert first.to_dict() == doubled.to_dict()


def test_out_of_order_events_fail_closed() -> None:
    events = (
        _event(
            entry_id="late",
            seconds=5,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
        _event(
            entry_id="early",
            seconds=1,
            entry_type="OPEN",
            quantity="10",
            cash="-5",
            cost="5",
            price="0.50",
            filled="10",
            eval_fee="0",
        ),
    )
    with pytest.raises(ShadowReplayError, match="chronological"):
        replay_shadow_events(
            events,
            kind=ShadowReplayKind.CURRENT_CONTROL,
            initial_cash=INITIAL,
        )


def test_streaming_iterator_is_consumed_without_materializing_a_list() -> None:
    seen = {"max": 0, "current": 0}

    def stream() -> Iterator[ShadowReplayEvent]:
        for item in _losing_pyramid():
            seen["current"] += 1
            seen["max"] = max(seen["max"], seen["current"])
            yield item
            seen["current"] -= 1

    snapshot = replay_shadow_events(
        stream(),
        kind=ShadowReplayKind.CURRENT_CONTROL,
        initial_cash=INITIAL,
    )

    assert seen["max"] == 1
    assert snapshot.event_count == 3


def test_decimal_nav_identity_with_known_marks() -> None:
    events = (
        _event(
            entry_id="open",
            seconds=1,
            entry_type="OPEN",
            quantity="10",
            cash="-5.10",
            cost="5",
            fee="0.10",
            price="0.50",
            filled="10",
            eval_fee="0.10",
        ),
    )
    snapshot = replay_shadow_events(
        events,
        kind=ShadowReplayKind.CURRENT_CONTROL,
        initial_cash=INITIAL,
        cutoff_marks={
            ("market-a", "yes"): CutoffMark(
                price=Decimal("0.40"),
                status="VERIFIED_EXECUTABLE_BID",
                marked_at=NOW,
            )
        },
    )

    assert snapshot.nav == snapshot.cash + snapshot.exposure + snapshot.unrealized_pnl
    assert snapshot.unrealized_pnl == Decimal("-1")
    assert snapshot.fees == Decimal("0.10")
