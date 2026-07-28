from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


class LeaderTradeAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class LeaderPositionEffect(StrEnum):
    OPEN = "OPEN"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LeaderTradeEvent:
    """Normalized, venue-neutral evidence of one executed leader trade."""

    event_id: str
    source_id: str
    leader_id: str
    market_reference: str
    outcome_reference: str
    trade_action: LeaderTradeAction
    position_effect: LeaderPositionEffect
    executed_price: Decimal
    executed_size: Decimal
    executed_at: datetime
    observed_at: datetime
    external_evidence_reference: str | None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "source_id",
            "leader_id",
            "market_reference",
            "outcome_reference",
            "schema_version",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if _WALLET_PATTERN.fullmatch(self.leader_id):
            raise ValueError("leader_id must be a safe alias, not a wallet address")
        if not Decimal("0") < self.executed_price <= Decimal("1"):
            raise ValueError("executed_price must be within (0, 1]")
        if self.executed_size <= Decimal("0"):
            raise ValueError("executed_size must be positive")
        _require_utc("executed_at", self.executed_at)
        _require_utc("observed_at", self.observed_at)
        if self.observed_at < self.executed_at:
            raise ValueError("observed_at must not precede executed_at")


def deduplicate_leader_trade_events(
    events: tuple[LeaderTradeEvent, ...] | list[LeaderTradeEvent],
) -> tuple[tuple[LeaderTradeEvent, ...], int]:
    """Return stable first-seen events and the number of duplicate event IDs."""

    unique: list[LeaderTradeEvent] = []
    seen: set[str] = set()
    duplicate_count = 0
    for event in events:
        if event.event_id in seen:
            duplicate_count += 1
            continue
        seen.add(event.event_id)
        unique.append(event)
    return tuple(unique), duplicate_count


def classify_position_effects(
    events: tuple[LeaderTradeEvent, ...] | list[LeaderTradeEvent],
    *,
    opening_inventory: Mapping[tuple[str, str], Decimal] | None = None,
) -> tuple[LeaderTradeEvent, ...]:
    """Classify effects only when the opening inventory is explicitly known."""

    ordered = sorted(events, key=lambda event: (event.executed_at, event.event_id))
    inventory = dict(opening_inventory or {})
    if any(value < Decimal("0") for value in inventory.values()):
        raise ValueError("opening inventory must not be negative")
    ambiguous: set[tuple[str, str]] = set()
    classified: list[LeaderTradeEvent] = []

    for event in ordered:
        key = (event.market_reference, event.outcome_reference)
        current = inventory.get(key)

        if key in ambiguous:
            effect = LeaderPositionEffect.UNKNOWN
        elif current is None:
            effect = LeaderPositionEffect.UNKNOWN
            ambiguous.add(key)
        elif event.trade_action is LeaderTradeAction.BUY:
            effect = (
                LeaderPositionEffect.OPEN
                if current == Decimal("0")
                else LeaderPositionEffect.INCREASE
            )
            inventory[key] = current + event.executed_size
        elif event.executed_size < current:
            effect = LeaderPositionEffect.REDUCE
            inventory[key] = current - event.executed_size
        elif event.executed_size == current:
            effect = LeaderPositionEffect.CLOSE
            inventory[key] = Decimal("0")
        else:
            effect = LeaderPositionEffect.UNKNOWN
            ambiguous.add(key)

        classified.append(replace(event, position_effect=effect))

    return tuple(classified)


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")
