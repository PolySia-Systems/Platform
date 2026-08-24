from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from polysia.domain.copytrading.models import LeaderTradeAction, LeaderTradeEvent
from polysia.domain.market import MarketOrderBookSnapshot

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")


class DynamicShadowMode(StrEnum):
    HISTORICAL = "HISTORICAL"
    FORWARD = "FORWARD"


class ShadowEvaluationStatus(StrEnum):
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class DynamicShadowConfig:
    fee_bps: Decimal = Decimal("200")
    historical_slippage_bps: Decimal = Decimal("100")
    historical_delay_ms: int = 2_000
    maximum_forward_delay_ms: int = 30_000
    maximum_notional: Decimal = Decimal("5")
    modeled_liquidity_size: Decimal = Decimal("100")
    policy_version: str = "dynamic-shadow-v0.1"
    cost_model_version: str = "fee-slip-delay-liquidity-v0.1"

    def __post_init__(self) -> None:
        if not ZERO <= self.fee_bps <= BPS:
            raise ValueError("fee_bps must be within [0, 10000]")
        if not ZERO <= self.historical_slippage_bps <= BPS:
            raise ValueError("historical_slippage_bps must be within [0, 10000]")
        if self.historical_delay_ms < 0 or self.maximum_forward_delay_ms < 1:
            raise ValueError("delay limits are invalid")
        if self.maximum_notional <= ZERO or self.modeled_liquidity_size <= ZERO:
            raise ValueError("notional and liquidity limits must be positive")
        if not self.policy_version or not self.cost_model_version:
            raise ValueError("policy and cost-model versions must not be empty")

    @property
    def effective_cost_model_version(self) -> str:
        inputs = {
            "fee_bps": format(self.fee_bps, "f"),
            "historical_delay_ms": self.historical_delay_ms,
            "historical_slippage_bps": format(self.historical_slippage_bps, "f"),
            "maximum_forward_delay_ms": self.maximum_forward_delay_ms,
            "maximum_notional": format(self.maximum_notional, "f"),
            "modeled_liquidity_size": format(self.modeled_liquidity_size, "f"),
        }
        digest = hashlib.sha256(
            json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:12]
        return f"{self.cost_model_version}+{digest}"


@dataclass(frozen=True, slots=True)
class ShadowBookLevel:
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        if not ZERO < self.price <= ONE or self.size <= ZERO:
            raise ValueError("shadow book level is invalid")


@dataclass(frozen=True, slots=True)
class ShadowQuoteEvidence:
    token_id: str
    observed_at: datetime
    bids: tuple[ShadowBookLevel, ...]
    asks: tuple[ShadowBookLevel, ...]
    source: str = "polymarket-current-book"

    def __post_init__(self) -> None:
        _require_utc("observed_at", self.observed_at)
        if not self.token_id or not self.source:
            raise ValueError("quote identity must not be empty")


@dataclass(frozen=True, slots=True)
class ShadowPosition:
    quantity: Decimal = ZERO
    total_cost: Decimal = ZERO

    @property
    def average_cost(self) -> Decimal | None:
        return None if self.quantity == ZERO else self.total_cost / self.quantity


@dataclass(frozen=True, slots=True)
class ShadowEventEvaluation:
    event_id: str
    wallet_id: str
    market_reference: str
    outcome_reference: str
    action: LeaderTradeAction
    status: ShadowEvaluationStatus
    reason: str
    mode: DynamicShadowMode
    leader_price: Decimal
    requested_size: Decimal
    filled_size: Decimal
    follower_price: Decimal | None
    gross_notional: Decimal | None
    fee: Decimal | None
    slippage: Decimal | None
    delay_ms: int
    available_liquidity: Decimal | None
    realized_pnl: Decimal | None
    quote_source: str
    executed_at: datetime
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class ShadowWalletSummary:
    wallet_id: str
    event_count: int
    simulated_count: int
    unknown_count: int
    rejected_count: int
    buy_count: int
    sell_count: int
    realized_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    open_notional: Decimal


def evaluate_shadow_events(
    wallet_id: str,
    events: tuple[LeaderTradeEvent, ...],
    *,
    mode: DynamicShadowMode,
    config: DynamicShadowConfig,
    quotes: dict[str, ShadowQuoteEvidence | None],
    evaluated_at: datetime,
) -> tuple[tuple[ShadowEventEvaluation, ...], ShadowWalletSummary]:
    if not wallet_id:
        raise ValueError("wallet_id must not be empty")
    _require_utc("evaluated_at", evaluated_at)
    positions: dict[tuple[str, str], ShadowPosition] = {}
    evaluations: list[ShadowEventEvaluation] = []
    for event in sorted(events, key=lambda item: (item.executed_at, item.event_id)):
        key = (event.market_reference, event.outcome_reference)
        position = positions.get(key, ShadowPosition())
        quote = quotes.get(event.event_id)
        evaluation, updated = _evaluate_event(
            wallet_id,
            event,
            position=position,
            mode=mode,
            config=config,
            quote=quote,
            evaluated_at=evaluated_at,
        )
        evaluations.append(evaluation)
        positions[key] = updated

    simulated = tuple(
        item for item in evaluations if item.status is ShadowEvaluationStatus.SIMULATED
    )
    open_notional = sum((item.total_cost for item in positions.values()), ZERO)
    summary = ShadowWalletSummary(
        wallet_id=wallet_id,
        event_count=len(evaluations),
        simulated_count=len(simulated),
        unknown_count=sum(item.status is ShadowEvaluationStatus.UNKNOWN for item in evaluations),
        rejected_count=sum(item.status is ShadowEvaluationStatus.REJECTED for item in evaluations),
        buy_count=sum(item.action is LeaderTradeAction.BUY for item in simulated),
        sell_count=sum(item.action is LeaderTradeAction.SELL for item in simulated),
        realized_pnl=sum(
            (item.realized_pnl for item in simulated if item.realized_pnl is not None),
            ZERO,
        ),
        fees=sum((item.fee for item in simulated if item.fee is not None), ZERO),
        slippage=sum((item.slippage for item in simulated if item.slippage is not None), ZERO),
        open_notional=open_notional,
    )
    return tuple(evaluations), summary


def _evaluate_event(
    wallet_id: str,
    event: LeaderTradeEvent,
    *,
    position: ShadowPosition,
    mode: DynamicShadowMode,
    config: DynamicShadowConfig,
    quote: ShadowQuoteEvidence | None,
    evaluated_at: datetime,
) -> tuple[ShadowEventEvaluation, ShadowPosition]:
    delay_ms = (
        config.historical_delay_ms
        if mode is DynamicShadowMode.HISTORICAL
        else max(0, int((evaluated_at - event.executed_at).total_seconds() * 1000))
    )
    if mode is DynamicShadowMode.FORWARD and delay_ms > config.maximum_forward_delay_ms:
        return (
            _unknown(
                wallet_id,
                event,
                mode=mode,
                reason="forward_signal_stale",
                delay_ms=delay_ms,
                evaluated_at=evaluated_at,
            ),
            position,
        )
    if event.trade_action is LeaderTradeAction.SELL and position.quantity <= ZERO:
        return (
            _unknown(
                wallet_id,
                event,
                mode=mode,
                reason="no_shadow_position_to_sell",
                delay_ms=delay_ms,
                evaluated_at=evaluated_at,
            ),
            position,
        )

    requested = event.executed_size
    if event.trade_action is LeaderTradeAction.SELL:
        requested = min(requested, position.quantity)
    if mode is DynamicShadowMode.FORWARD:
        if quote is None or quote.token_id != event.outcome_reference:
            return (
                _unknown(
                    wallet_id,
                    event,
                    mode=mode,
                    reason="current_order_book_unavailable",
                    delay_ms=delay_ms,
                    evaluated_at=evaluated_at,
                ),
                position,
            )
        quote_age = evaluated_at - quote.observed_at
        if quote_age > timedelta(
            milliseconds=config.maximum_forward_delay_ms
        ) or quote_age < -timedelta(seconds=5):
            return (
                _unknown(
                    wallet_id,
                    event,
                    mode=mode,
                    reason="current_order_book_stale",
                    delay_ms=delay_ms,
                    evaluated_at=evaluated_at,
                    quote_source=quote.source,
                ),
                position,
            )
        levels = quote.asks if event.trade_action is LeaderTradeAction.BUY else quote.bids
        quote_source = quote.source
    else:
        levels = _modeled_levels(event, config=config)
        quote_source = "historical-cost-model"

    fill_size, follower_price, available = _walk_levels(
        levels,
        requested=requested,
        action=event.trade_action,
        maximum_notional=config.maximum_notional,
    )
    if fill_size <= ZERO or follower_price is None:
        return (
            _unknown(
                wallet_id,
                event,
                mode=mode,
                reason="insufficient_executable_liquidity",
                delay_ms=delay_ms,
                evaluated_at=evaluated_at,
                available_liquidity=available,
                quote_source=quote_source,
            ),
            position,
        )
    gross = follower_price * fill_size
    fee = gross * config.fee_bps / BPS
    if event.trade_action is LeaderTradeAction.BUY:
        slippage = max(ZERO, (follower_price - event.executed_price) * fill_size)
        updated = ShadowPosition(
            quantity=position.quantity + fill_size,
            total_cost=position.total_cost + gross + fee,
        )
        realized = None
    else:
        slippage = max(ZERO, (event.executed_price - follower_price) * fill_size)
        average_cost = position.average_cost
        assert average_cost is not None
        allocated_cost = average_cost * fill_size
        realized = gross - fee - allocated_cost
        remaining_quantity = position.quantity - fill_size
        updated = ShadowPosition(
            quantity=remaining_quantity,
            total_cost=ZERO if remaining_quantity == ZERO else position.total_cost - allocated_cost,
        )
    return (
        ShadowEventEvaluation(
            event_id=event.event_id,
            wallet_id=wallet_id,
            market_reference=event.market_reference,
            outcome_reference=event.outcome_reference,
            action=event.trade_action,
            status=ShadowEvaluationStatus.SIMULATED,
            reason="modeled_historical_fill"
            if mode is DynamicShadowMode.HISTORICAL
            else "current_book_shadow_fill",
            mode=mode,
            leader_price=event.executed_price,
            requested_size=requested,
            filled_size=fill_size,
            follower_price=follower_price,
            gross_notional=gross,
            fee=fee,
            slippage=slippage,
            delay_ms=delay_ms,
            available_liquidity=available,
            realized_pnl=realized,
            quote_source=quote_source,
            executed_at=event.executed_at,
            evaluated_at=evaluated_at,
        ),
        updated,
    )


def _modeled_levels(
    event: LeaderTradeEvent,
    *,
    config: DynamicShadowConfig,
) -> tuple[ShadowBookLevel, ...]:
    adjustment = event.executed_price * config.historical_slippage_bps / BPS
    price = (
        min(ONE, event.executed_price + adjustment)
        if event.trade_action is LeaderTradeAction.BUY
        else max(Decimal("0.00000001"), event.executed_price - adjustment)
    )
    return (ShadowBookLevel(price=price, size=config.modeled_liquidity_size),)


def _walk_levels(
    levels: tuple[ShadowBookLevel, ...],
    *,
    requested: Decimal,
    action: LeaderTradeAction,
    maximum_notional: Decimal,
) -> tuple[Decimal, Decimal | None, Decimal]:
    ordered = sorted(
        levels,
        key=lambda item: item.price,
        reverse=action is LeaderTradeAction.SELL,
    )
    available = sum((item.size for item in ordered), ZERO)
    remaining = requested
    filled = ZERO
    notional = ZERO
    for level in ordered:
        affordable = (maximum_notional - notional) / level.price
        take = min(level.size, remaining, max(ZERO, affordable))
        if take <= ZERO:
            break
        filled += take
        notional += take * level.price
        remaining -= take
        if remaining <= ZERO or notional >= maximum_notional:
            break
    return filled, None if filled == ZERO else notional / filled, available


def _unknown(
    wallet_id: str,
    event: LeaderTradeEvent,
    *,
    mode: DynamicShadowMode,
    reason: str,
    delay_ms: int,
    evaluated_at: datetime,
    available_liquidity: Decimal | None = None,
    quote_source: str = "none",
) -> ShadowEventEvaluation:
    return ShadowEventEvaluation(
        event_id=event.event_id,
        wallet_id=wallet_id,
        market_reference=event.market_reference,
        outcome_reference=event.outcome_reference,
        action=event.trade_action,
        status=ShadowEvaluationStatus.UNKNOWN,
        reason=reason,
        mode=mode,
        leader_price=event.executed_price,
        requested_size=event.executed_size,
        filled_size=ZERO,
        follower_price=None,
        gross_notional=None,
        fee=None,
        slippage=None,
        delay_ms=delay_ms,
        available_liquidity=available_liquidity,
        realized_pnl=None,
        quote_source=quote_source,
        executed_at=event.executed_at,
        evaluated_at=evaluated_at,
    )


def quote_from_order_book(book: MarketOrderBookSnapshot) -> ShadowQuoteEvidence:
    token_id = str(book.token_id)
    observed_at = book.timestamp
    bids = tuple(
        ShadowBookLevel(price=Decimal(str(level.price)), size=Decimal(str(level.size)))
        for level in book.bids
    )
    asks = tuple(
        ShadowBookLevel(price=Decimal(str(level.price)), size=Decimal(str(level.size)))
        for level in book.asks
    )
    return ShadowQuoteEvidence(
        token_id=token_id,
        observed_at=observed_at,
        bids=bids,
        asks=asks,
    )


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")
