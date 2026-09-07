"""Chronological stateful replay of Stage 4B shadow ledger evidence.

Extends research replay without a parallel ledger or Live/Risk/Execution path.
Current Control applies recorded ledger deltas. Target Exposure v1 changes only
position construction. The report-time fill filter in
``continuous_shadow_experiments`` remains descriptive/non-stateful and is not
this engine.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from polysia.domain.copytrading.continuous_shadow import ZERO
from polysia.domain.copytrading.target_exposure import (
    TargetExposureDecision,
    TargetExposurePolicy,
    decide_entry,
    scale_exit_quantity,
)

_TOLERANCE = Decimal("0.000001")
ENTRY_TYPES = frozenset(
    {"OPEN", "INCREASE", "REDUCE", "CLOSE", "SETTLEMENT", "FEE", "MARK"}
)
BUY_TYPES = frozenset({"OPEN", "INCREASE"})
EXIT_TYPES = frozenset({"REDUCE", "CLOSE", "SETTLEMENT"})


class ShadowReplayKind(StrEnum):
    CURRENT_CONTROL = "current-control"
    TARGET_EXPOSURE_V1 = "target-exposure-v1"


class ShadowReplayError(ValueError):
    """Raised when replay evidence is unordered, contradictory, or incomplete."""


@dataclass(frozen=True, slots=True)
class ShadowReplayEvent:
    """One chronological ledger fact plus contemporaneous evaluation fields."""

    entry_id: str
    created_at: datetime
    entry_type: str
    market_reference: str | None
    outcome_reference: str | None
    quantity_delta: Decimal
    cash_delta: Decimal
    cost_basis_delta: Decimal
    realized_pnl_delta: Decimal
    fee_delta: Decimal
    event_id: str | None = None
    follower_price: Decimal | None = None
    filled_size: Decimal | None = None
    evaluation_fee: Decimal | None = None
    evaluated_at: datetime | None = None
    evaluation_status: str | None = None

    @property
    def order_key(self) -> tuple[datetime, str]:
        return (self.created_at, self.entry_id)

    @property
    def episode_key(self) -> tuple[str, str] | None:
        if self.market_reference is None or self.outcome_reference is None:
            return None
        return (self.market_reference, self.outcome_reference)


@dataclass(frozen=True, slots=True)
class CutoffMark:
    price: Decimal | None
    status: str
    marked_at: datetime | None


@dataclass
class _Episode:
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    entry_fees: Decimal = ZERO
    target_quantity: Decimal = ZERO
    first_entry_price: Decimal | None = None
    opened: bool = False
    closed: bool = False
    realized: Decimal = ZERO
    fees: Decimal = ZERO
    turnover: Decimal = ZERO
    unknown_unrealized: bool = False


@dataclass
class _Book:
    cash: Decimal
    fees: Decimal = ZERO
    realized: Decimal = ZERO
    high_water: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    unknown_rate_events: int = 0
    processed: set[str] = field(default_factory=set)
    episodes: dict[tuple[str, str], _Episode] = field(default_factory=dict)
    decisions: list[str] = field(default_factory=list)
    open_count: int = 0
    increase_count: int = 0
    reduce_count: int = 0
    close_count: int = 0
    settlement_count: int = 0
    skipped_repeat: int = 0
    skipped_rebalance: int = 0
    skipped_reentry: int = 0
    rejected: int = 0
    event_count: int = 0
    max_live_events: int = 0

    def episode(self, key: tuple[str, str]) -> _Episode:
        current = self.episodes.get(key)
        if current is None:
            current = _Episode()
            self.episodes[key] = current
        return current

    def market_exposure(self, market_reference: str, *, except_key: tuple[str, str]) -> Decimal:
        return sum(
            (
                item.cost_basis
                for key, item in self.episodes.items()
                if key[0] == market_reference and key != except_key
            ),
            ZERO,
        )

    def opposing_quantity(self, key: tuple[str, str]) -> Decimal:
        market, outcome = key
        return sum(
            (
                item.quantity
                for other, item in self.episodes.items()
                if other[0] == market and other[1] != outcome
            ),
            ZERO,
        )

    def exposure(self) -> Decimal:
        return sum((item.cost_basis for item in self.episodes.values()), ZERO)

    def open_quantity(self) -> Decimal:
        return sum((item.quantity for item in self.episodes.values()), ZERO)

    def book_nav(self) -> Decimal:
        return self.cash + self.exposure()

    def note_nav(self) -> None:
        nav = self.book_nav()
        if nav > self.high_water:
            self.high_water = nav
        if self.high_water > ZERO:
            drawdown = (self.high_water - nav) / self.high_water
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    kind: ShadowReplayKind
    event_count: int
    cash: Decimal
    fees: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    exposure: Decimal
    locked_capital: Decimal
    nav: Decimal | None
    book_nav: Decimal
    high_water_nav: Decimal
    max_drawdown: Decimal
    open_positions: int
    open_quantity: Decimal
    turnover: Decimal
    open_count: int
    increase_count: int
    reduce_count: int
    close_count: int
    settlement_count: int
    skipped_repeat: int
    skipped_rebalance: int
    skipped_reentry: int
    rejected_incomplete: int
    unknown_unrealized_positions: int
    unknown_rate: Decimal
    completed_episode_count: int
    expectancy_per_completed_episode: Decimal | None
    profit_factor: Decimal | None
    max_market_exposure: Decimal
    distinct_markets: int
    distinct_outcomes: int
    coverage_admitted_buys: int
    digest: str
    decisions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "book_nav": format(self.book_nav, "f"),
            "cash": format(self.cash, "f"),
            "close_count": self.close_count,
            "completed_episode_count": self.completed_episode_count,
            "coverage_admitted_buys": self.coverage_admitted_buys,
            "digest": self.digest,
            "distinct_markets": self.distinct_markets,
            "distinct_outcomes": self.distinct_outcomes,
            "event_count": self.event_count,
            "expectancy_per_completed_episode": _optional_decimal(
                self.expectancy_per_completed_episode
            ),
            "exposure": format(self.exposure, "f"),
            "fees": format(self.fees, "f"),
            "high_water_nav": format(self.high_water_nav, "f"),
            "increase_count": self.increase_count,
            "kind": self.kind.value,
            "locked_capital": format(self.locked_capital, "f"),
            "max_drawdown": format(self.max_drawdown, "f"),
            "max_market_exposure": format(self.max_market_exposure, "f"),
            "nav": _optional_decimal(self.nav),
            "open_count": self.open_count,
            "open_positions": self.open_positions,
            "open_quantity": format(self.open_quantity, "f"),
            "profit_factor": _optional_decimal(self.profit_factor),
            "realized_pnl": format(self.realized_pnl, "f"),
            "reduce_count": self.reduce_count,
            "rejected_incomplete": self.rejected_incomplete,
            "settlement_count": self.settlement_count,
            "skipped_rebalance": self.skipped_rebalance,
            "skipped_reentry": self.skipped_reentry,
            "skipped_repeat": self.skipped_repeat,
            "turnover": format(self.turnover, "f"),
            "unknown_rate": format(self.unknown_rate, "f"),
            "unknown_unrealized_positions": self.unknown_unrealized_positions,
            "unrealized_pnl": _optional_decimal(self.unrealized_pnl),
        }


def replay_shadow_events(
    events: Iterable[ShadowReplayEvent],
    *,
    kind: ShadowReplayKind,
    initial_cash: Decimal,
    policy: TargetExposurePolicy | None = None,
    cutoff_marks: Mapping[tuple[str, str], CutoffMark] | None = None,
) -> ReplaySnapshot:
    """Walk a chronological event stream without loading it as a list."""

    if kind is ShadowReplayKind.TARGET_EXPOSURE_V1 and policy is None:
        raise ShadowReplayError("Target Exposure replay requires the frozen policy")
    if kind is ShadowReplayKind.CURRENT_CONTROL:
        policy = None
    book = _Book(cash=initial_cash, high_water=initial_cash)
    previous: tuple[datetime, str] | None = None
    live = 0
    for event in events:
        live = 1
        if live > book.max_live_events:
            book.max_live_events = live
        _apply_event(book, event, kind=kind, policy=policy, previous=previous)
        previous = event.order_key
        live = 0
    return _snapshot(book, kind=kind, cutoff_marks=cutoff_marks or {})


def replay_twice_for_idempotency(
    events: Iterable[ShadowReplayEvent],
    **kwargs: object,
) -> tuple[ReplaySnapshot, ReplaySnapshot]:
    """Apply the same chronological stream twice through one book via copies."""

    materialized = tuple(events)
    first = replay_shadow_events(iter(materialized), **kwargs)  # type: ignore[arg-type]
    doubled: Iterator[ShadowReplayEvent] = _chain_twice(materialized)
    second = replay_shadow_events(doubled, **kwargs)  # type: ignore[arg-type]
    return first, second


def _chain_twice(events: tuple[ShadowReplayEvent, ...]) -> Iterator[ShadowReplayEvent]:
    yield from events
    yield from events


def _apply_event(
    book: _Book,
    event: ShadowReplayEvent,
    *,
    kind: ShadowReplayKind,
    policy: TargetExposurePolicy | None,
    previous: tuple[datetime, str] | None,
) -> None:
    if event.entry_id in book.processed:
        return
    if previous is not None and event.order_key < previous:
        raise ShadowReplayError("shadow replay events are not chronological")
    if event.entry_type not in ENTRY_TYPES:
        raise ShadowReplayError(f"unsupported ledger entry_type: {event.entry_type}")
    book.processed.add(event.entry_id)
    book.event_count += 1
    if event.entry_type == "MARK":
        book.note_nav()
        return
    if event.entry_type == "FEE":
        book.cash += event.cash_delta
        book.fees += event.fee_delta
        book.note_nav()
        return
    key = event.episode_key
    if key is None:
        raise ShadowReplayError(f"{event.entry_type} is missing market/outcome identity")
    if kind is ShadowReplayKind.CURRENT_CONTROL:
        _apply_recorded(book, event, key)
    else:
        assert policy is not None
        _apply_target_exposure(book, event, key, policy)
    book.note_nav()


def _apply_recorded(book: _Book, event: ShadowReplayEvent, key: tuple[str, str]) -> None:
    episode = book.episode(key)
    episode.quantity += event.quantity_delta
    episode.cost_basis += event.cost_basis_delta
    episode.realized += event.realized_pnl_delta
    episode.fees += event.fee_delta
    episode.turnover += abs(event.cost_basis_delta)
    book.cash += event.cash_delta
    book.fees += event.fee_delta
    book.realized += event.realized_pnl_delta
    if event.entry_type in BUY_TYPES:
        episode.opened = True
        if episode.quantity > ZERO:
            episode.closed = False
        if event.entry_type == "OPEN":
            book.open_count += 1
        else:
            book.increase_count += 1
        return
    if event.entry_type == "REDUCE":
        book.reduce_count += 1
    elif event.entry_type == "CLOSE":
        book.close_count += 1
    else:
        book.settlement_count += 1
    if episode.quantity <= ZERO:
        episode.closed = True


def _apply_target_exposure(
    book: _Book,
    event: ShadowReplayEvent,
    key: tuple[str, str],
    policy: TargetExposurePolicy,
) -> None:
    episode = book.episode(key)
    if event.entry_type in BUY_TYPES:
        requested = (
            event.filled_size
            if event.filled_size is not None and event.filled_size > ZERO
            else (event.quantity_delta if event.quantity_delta > ZERO else None)
        )
        price = _executable_price(event)
        recorded_fee = (
            event.evaluation_fee
            if event.evaluation_fee is not None
            else (event.fee_delta if event.fee_delta >= ZERO else None)
        )
        admission = decide_entry(
            policy,
            episode_open=episode.opened and not episode.closed,
            episode_closed=episode.closed,
            first_entry_price=episode.first_entry_price,
            executable_price=price,
            requested_quantity=requested,
            recorded_fee=recorded_fee,
            opposing_quantity=book.opposing_quantity(key),
            market_exposure=book.market_exposure(key[0], except_key=key),
            cash=book.cash,
        )
        book.decisions.append(admission.decision.value)
        _count_te_decision(book, admission.decision)
        if not admission.accepted:
            if admission.decision is TargetExposureDecision.REJECT_INCOMPLETE:
                book.unknown_rate_events += 1
            return
        episode.opened = True
        episode.target_quantity = admission.target_quantity
        episode.first_entry_price = admission.executable_price
        episode.quantity += admission.target_quantity
        episode.cost_basis += admission.notional
        episode.entry_fees += admission.fee
        episode.fees += admission.fee
        episode.turnover += admission.notional
        book.cash -= admission.notional + admission.fee
        book.fees += admission.fee
        book.open_count += 1
        return
    _apply_te_exit(book, episode, event)


def _count_te_decision(book: _Book, decision: TargetExposureDecision) -> None:
    if decision is TargetExposureDecision.SKIP_REPEAT_SIGNAL:
        book.skipped_repeat += 1
    elif decision is TargetExposureDecision.SKIP_REBALANCE:
        book.skipped_rebalance += 1
    elif decision is TargetExposureDecision.SKIP_REENTRY:
        book.skipped_reentry += 1
    elif decision is TargetExposureDecision.ADMIT:
        return
    else:
        book.rejected += 1


def _apply_te_exit(book: _Book, episode: _Episode, event: ShadowReplayEvent) -> None:
    recorded_exit = abs(event.quantity_delta)
    exit_qty = scale_exit_quantity(
        held_quantity=episode.quantity, recorded_exit_quantity=recorded_exit
    )
    if exit_qty <= ZERO or episode.quantity <= ZERO:
        if event.entry_type == "REDUCE":
            book.reduce_count += 1
        elif event.entry_type == "CLOSE":
            book.close_count += 1
        else:
            book.settlement_count += 1
        return
    ratio = exit_qty / episode.quantity
    allocated_cost = episode.cost_basis * ratio
    allocated_fees = episode.entry_fees * ratio
    recorded_qty = recorded_exit
    proceeds_ratio = exit_qty / recorded_qty
    recorded_proceeds = event.cash_delta + event.fee_delta
    proceeds = recorded_proceeds * proceeds_ratio
    fee = event.fee_delta * proceeds_ratio
    realized = proceeds - allocated_cost
    episode.quantity -= exit_qty
    episode.cost_basis -= allocated_cost
    episode.entry_fees -= allocated_fees
    episode.realized += realized
    episode.fees += fee
    episode.turnover += allocated_cost
    if episode.quantity <= _TOLERANCE:
        episode.quantity = ZERO
        episode.cost_basis = ZERO
        episode.entry_fees = ZERO
        episode.closed = True
    book.cash += proceeds - fee
    book.fees += fee
    book.realized += realized
    if event.entry_type == "REDUCE":
        book.reduce_count += 1
    elif event.entry_type == "CLOSE":
        book.close_count += 1
    else:
        book.settlement_count += 1


def _executable_price(event: ShadowReplayEvent) -> Decimal | None:
    if event.follower_price is not None and event.follower_price > ZERO:
        return event.follower_price
    if event.quantity_delta > ZERO and event.cost_basis_delta > ZERO:
        return event.cost_basis_delta / event.quantity_delta
    return None


def _snapshot(
    book: _Book,
    *,
    kind: ShadowReplayKind,
    cutoff_marks: Mapping[tuple[str, str], CutoffMark],
) -> ReplaySnapshot:
    unrealized = ZERO
    unknown = 0
    open_positions = 0
    market_exposure: dict[str, Decimal] = {}
    for key, episode in book.episodes.items():
        if episode.quantity <= _TOLERANCE:
            continue
        open_positions += 1
        market_exposure[key[0]] = market_exposure.get(key[0], ZERO) + episode.cost_basis
        mark = cutoff_marks.get(key)
        if mark is None or mark.price is None or mark.price < ZERO:
            episode.unknown_unrealized = True
            unknown += 1
            continue
        unrealized += episode.quantity * mark.price - episode.cost_basis
    completed = tuple(
        item for item in book.episodes.values() if item.closed and item.opened
    )
    wins = sum((item.realized for item in completed if item.realized > ZERO), ZERO)
    losses = sum((item.realized for item in completed if item.realized < ZERO), ZERO)
    profit_factor = None
    if wins > ZERO and losses < ZERO:
        profit_factor = wins / abs(losses)
    expectancy = None
    if completed:
        expectancy = sum((item.realized for item in completed), ZERO) / Decimal(
            len(completed)
        )
    exposure = book.exposure()
    book_nav = book.book_nav()
    nav = None if unknown else book.cash + exposure + unrealized
    unknown_rate = (
        ZERO
        if book.event_count == 0
        else Decimal(book.unknown_rate_events) / Decimal(book.event_count)
    )
    snapshot = ReplaySnapshot(
        kind=kind,
        event_count=book.event_count,
        cash=book.cash,
        fees=book.fees,
        realized_pnl=book.realized,
        unrealized_pnl=None if unknown else unrealized,
        exposure=exposure,
        locked_capital=exposure,
        nav=nav,
        book_nav=book_nav,
        high_water_nav=book.high_water,
        max_drawdown=book.max_drawdown,
        open_positions=open_positions,
        open_quantity=book.open_quantity(),
        turnover=sum((item.turnover for item in book.episodes.values()), ZERO),
        open_count=book.open_count,
        increase_count=book.increase_count,
        reduce_count=book.reduce_count,
        close_count=book.close_count,
        settlement_count=book.settlement_count,
        skipped_repeat=book.skipped_repeat,
        skipped_rebalance=book.skipped_rebalance,
        skipped_reentry=book.skipped_reentry,
        rejected_incomplete=book.rejected,
        unknown_unrealized_positions=unknown,
        unknown_rate=unknown_rate,
        completed_episode_count=len(completed),
        expectancy_per_completed_episode=expectancy,
        profit_factor=profit_factor,
        max_market_exposure=max(market_exposure.values(), default=ZERO),
        distinct_markets=len({key[0] for key, item in book.episodes.items() if item.opened}),
        distinct_outcomes=len({key[1] for key, item in book.episodes.items() if item.opened}),
        coverage_admitted_buys=book.open_count,
        digest="",
        decisions=tuple(book.decisions),
    )
    digest = hashlib.sha256(
        json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return replace(snapshot, digest=digest)


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def snapshots_match(left: ReplaySnapshot, right: ReplaySnapshot) -> bool:
    return left.digest == right.digest and left.to_dict() == right.to_dict()


__all__ = [
    "CutoffMark",
    "ReplaySnapshot",
    "ShadowReplayError",
    "ShadowReplayEvent",
    "ShadowReplayKind",
    "replay_shadow_events",
    "replay_twice_for_idempotency",
    "snapshots_match",
]
