from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
    classify_position_effects,
    deduplicate_leader_trade_events,
)


def _event(
    event_id: str,
    *,
    action: LeaderTradeAction = LeaderTradeAction.BUY,
    size: str = "5",
    outcome: str = "up-token",
    second: int = 0,
) -> LeaderTradeEvent:
    return LeaderTradeEvent(
        event_id=event_id,
        source_id="fixture",
        leader_id="leader-001",
        market_reference="market-1",
        outcome_reference=outcome,
        trade_action=action,
        position_effect=LeaderPositionEffect.UNKNOWN,
        executed_price=Decimal("0.45"),
        executed_size=Decimal(size),
        executed_at=datetime(2026, 7, 28, 16, 0, second, tzinfo=UTC),
        observed_at=datetime(2026, 7, 28, 16, 1, tzinfo=UTC),
        external_evidence_reference="sha256:evidence",
    )


def test_leader_event_requires_decimal_bounds_utc_and_safe_alias() -> None:
    valid = _event("event-1")

    assert valid.executed_price == Decimal("0.45")
    with pytest.raises(ValueError, match="safe alias"):
        replace(
            valid,
            leader_id="0x1111111111111111111111111111111111111111",
        )


def test_deduplication_is_stable_and_counts_repeated_event_ids() -> None:
    first = _event("event-1")
    second = _event("event-2", second=1)

    unique, duplicate_count = deduplicate_leader_trade_events(
        [first, second, first]
    )

    assert unique == (first, second)
    assert duplicate_count == 1


def test_position_effects_fail_closed_for_unknown_inventory() -> None:
    events = [
        _event(
            "unknown-sell",
            action=LeaderTradeAction.SELL,
            size="1",
            outcome="down-token",
        ),
        _event("open", size="5", second=1),
        _event("increase", size="2", second=2),
        _event("reduce", action=LeaderTradeAction.SELL, size="3", second=3),
        _event("close", action=LeaderTradeAction.SELL, size="4", second=4),
    ]

    effects = [
        event.position_effect
        for event in classify_position_effects(
            events,
            opening_inventory={("market-1", "up-token"): Decimal("0")},
        )
    ]

    assert effects == [
        LeaderPositionEffect.UNKNOWN,
        LeaderPositionEffect.OPEN,
        LeaderPositionEffect.INCREASE,
        LeaderPositionEffect.REDUCE,
        LeaderPositionEffect.CLOSE,
    ]


def test_first_buy_is_unknown_without_proven_opening_inventory() -> None:
    classified = classify_position_effects([_event("first-buy")])

    assert classified[0].position_effect is LeaderPositionEffect.UNKNOWN
