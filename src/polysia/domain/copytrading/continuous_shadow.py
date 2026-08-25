from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from polysia.domain.copytrading.models import LeaderTradeAction
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot

ZERO = Decimal("0")
ONE = Decimal("1")
FEE_QUANTUM = Decimal("0.00001")


class ContinuousShadowLifecycle(StrEnum):
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    FINALIZED = "FINALIZED"


class ContinuousPortfolioKind(StrEnum):
    WALLET = "WALLET"
    FOLLOWER = "FOLLOWER"


class ContinuousEvaluationStatus(StrEnum):
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ContinuousShadowConfig:
    """Versioned synthetic-capital and execution assumptions for Stage 4B."""

    wallet_bankroll: Decimal = Decimal("100")
    follower_bankroll: Decimal = Decimal("1000")
    maximum_event_notional: Decimal = Decimal("5")
    wallet_maximum_exposure: Decimal = Decimal("100")
    follower_maximum_exposure: Decimal = Decimal("500")
    follower_maximum_wallet_exposure: Decimal = Decimal("25")
    follower_maximum_market_exposure: Decimal = Decimal("100")
    follower_maximum_positions: int = 100
    maximum_forward_delay_ms: int = 300_000
    maximum_quote_age_ms: int = 30_000
    initial_lookback_minutes: int = 15
    overlap_seconds: int = 30
    policy_version: str = "continuous-shadow-policy-v0.2"
    cost_model_version: str = "polymarket-fee-depth-delay-v0.2"
    bankroll_version: str = "synthetic-bankroll-v0.2"

    def __post_init__(self) -> None:
        decimal_values = (
            self.wallet_bankroll,
            self.follower_bankroll,
            self.maximum_event_notional,
            self.wallet_maximum_exposure,
            self.follower_maximum_exposure,
            self.follower_maximum_wallet_exposure,
            self.follower_maximum_market_exposure,
        )
        if any(not value.is_finite() or value <= ZERO for value in decimal_values):
            raise ValueError("continuous Shadow capital limits must be finite and positive")
        if self.maximum_event_notional > self.wallet_bankroll:
            raise ValueError("maximum_event_notional must not exceed wallet_bankroll")
        if self.wallet_maximum_exposure > self.wallet_bankroll:
            raise ValueError("wallet_maximum_exposure must not exceed wallet_bankroll")
        if self.follower_maximum_exposure > self.follower_bankroll:
            raise ValueError("follower_maximum_exposure must not exceed follower_bankroll")
        if not 1 <= self.follower_maximum_positions <= 10_000:
            raise ValueError("follower_maximum_positions must be within [1, 10000]")
        if not 1 <= self.maximum_forward_delay_ms <= 3_600_000:
            raise ValueError("maximum_forward_delay_ms must be within [1, 3600000]")
        if not 1 <= self.maximum_quote_age_ms <= 300_000:
            raise ValueError("maximum_quote_age_ms must be within [1, 300000]")
        if not 1 <= self.initial_lookback_minutes <= 1_440:
            raise ValueError("initial_lookback_minutes must be within [1, 1440]")
        if not 0 <= self.overlap_seconds <= 300:
            raise ValueError("overlap_seconds must be within [0, 300]")
        for value in (self.policy_version, self.cost_model_version, self.bankroll_version):
            if not value.strip():
                raise ValueError("continuous Shadow versions must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "bankroll_version": self.bankroll_version,
            "cost_model_version": self.cost_model_version,
            "follower_bankroll": format(self.follower_bankroll, "f"),
            "follower_maximum_exposure": format(
                self.follower_maximum_exposure, "f"
            ),
            "follower_maximum_market_exposure": format(
                self.follower_maximum_market_exposure, "f"
            ),
            "follower_maximum_positions": self.follower_maximum_positions,
            "follower_maximum_wallet_exposure": format(
                self.follower_maximum_wallet_exposure, "f"
            ),
            "initial_lookback_minutes": self.initial_lookback_minutes,
            "maximum_event_notional": format(self.maximum_event_notional, "f"),
            "maximum_forward_delay_ms": self.maximum_forward_delay_ms,
            "maximum_quote_age_ms": self.maximum_quote_age_ms,
            "overlap_seconds": self.overlap_seconds,
            "policy_version": self.policy_version,
            "wallet_bankroll": format(self.wallet_bankroll, "f"),
            "wallet_maximum_exposure": format(self.wallet_maximum_exposure, "f"),
        }


@dataclass(frozen=True, slots=True)
class ContinuousPosition:
    portfolio_id: str
    market_reference: str
    outcome_reference: str
    quantity: Decimal
    cost_basis: Decimal
    entry_fees: Decimal
    mark_price: Decimal | None
    marked_at: datetime | None

    @property
    def average_cost(self) -> Decimal:
        return ZERO if self.quantity == ZERO else self.cost_basis / self.quantity

    @property
    def market_value(self) -> Decimal | None:
        return None if self.mark_price is None else self.quantity * self.mark_price


@dataclass(frozen=True, slots=True)
class ContinuousPortfolio:
    portfolio_id: str
    kind: ContinuousPortfolioKind
    wallet_id: str | None
    initial_cash: Decimal
    cash: Decimal
    realized_pnl: Decimal
    fees: Decimal
    high_water_nav: Decimal
    drawdown: Decimal
    positions: tuple[ContinuousPosition, ...]

    @property
    def exposure(self) -> Decimal:
        return sum((item.cost_basis for item in self.positions), ZERO)


@dataclass(frozen=True, slots=True)
class FeeEvidence:
    amount: Decimal | None
    status: str
    source: str
    rate: Decimal | None
    exponent: Decimal | None
    taker_only: bool | None


@dataclass(frozen=True, slots=True)
class BookWalk:
    requested_size: Decimal
    filled_size: Decimal
    follower_price: Decimal | None
    gross_notional: Decimal
    available_liquidity: Decimal
    top_price: Decimal | None
    midpoint: Decimal | None
    spread_cost: Decimal
    depth_impact: Decimal
    consumed: tuple[tuple[Decimal, Decimal], ...]


def calculate_verified_taker_fee(
    market: MarketDetails | None,
    *,
    price: Decimal,
    size: Decimal,
) -> FeeEvidence:
    """Calculate only a venue-reported market fee; missing provenance stays UNKNOWN."""

    if market is None or market.fee_schedule is None:
        return FeeEvidence(None, "UNKNOWN", "market_fee_schedule_unavailable", None, None, None)
    schedule = market.fee_schedule
    if not schedule.enabled:
        return FeeEvidence(
            ZERO,
            "VERIFIED",
            "official_sdk_market_feeSchedule_disabled",
            ZERO,
            ZERO,
            schedule.taker_only,
        )
    if (
        schedule.rate is None
        or schedule.exponent is None
        or schedule.rate < ZERO
        or schedule.exponent < ZERO
        or schedule.taker_only is not True
    ):
        return FeeEvidence(
            None,
            "UNKNOWN",
            "official_sdk_market_feeSchedule_incomplete",
            schedule.rate,
            schedule.exponent,
            schedule.taker_only,
        )
    try:
        per_share = schedule.rate * ((price * (ONE - price)) ** schedule.exponent)
        amount = (size * per_share).quantize(FEE_QUANTUM)
    except (InvalidOperation, ValueError):
        return FeeEvidence(
            None,
            "UNKNOWN",
            "official_sdk_market_feeSchedule_invalid",
            schedule.rate,
            schedule.exponent,
            schedule.taker_only,
        )
    return FeeEvidence(
        amount,
        "VERIFIED",
        "official_sdk_market_feeSchedule",
        schedule.rate,
        schedule.exponent,
        schedule.taker_only,
    )


def walk_order_book(
    book: MarketOrderBookSnapshot,
    *,
    action: LeaderTradeAction,
    requested_size: Decimal,
    already_consumed: dict[Decimal, Decimal],
) -> BookWalk:
    """Walk remaining levels without reusing liquidity within one portfolio scope."""

    if requested_size <= ZERO:
        raise ValueError("requested_size must be positive")
    levels = (
        sorted(book.asks, key=lambda item: item.price)
        if action is LeaderTradeAction.BUY
        else sorted(book.bids, key=lambda item: item.price, reverse=True)
    )
    available = sum(
        (max(ZERO, level.size - already_consumed.get(level.price, ZERO)) for level in levels),
        ZERO,
    )
    remaining = requested_size
    notional = ZERO
    consumed: list[tuple[Decimal, Decimal]] = []
    for level in levels:
        if remaining <= ZERO:
            break
        level_available = max(ZERO, level.size - already_consumed.get(level.price, ZERO))
        take = min(remaining, level_available)
        if take <= ZERO:
            continue
        consumed.append((level.price, take))
        notional += level.price * take
        remaining -= take
    filled = requested_size - remaining
    follower_price = None if filled == ZERO else notional / filled
    top_price = None if not levels else levels[0].price
    midpoint = book.midpoint
    spread_cost = (
        ZERO
        if follower_price is None or midpoint is None
        else abs(top_price - midpoint) * filled
        if top_price is not None
        else ZERO
    )
    depth_impact = (
        ZERO
        if follower_price is None or top_price is None
        else abs(follower_price - top_price) * filled
    )
    return BookWalk(
        requested_size=requested_size,
        filled_size=filled,
        follower_price=follower_price,
        gross_notional=notional,
        available_liquidity=available,
        top_price=top_price,
        midpoint=midpoint,
        spread_cost=spread_cost,
        depth_impact=depth_impact,
        consumed=tuple(consumed),
    )


def quote_is_fresh(
    book: MarketOrderBookSnapshot,
    *,
    evaluated_at: datetime,
    maximum_age_ms: int,
) -> bool:
    age = evaluated_at - book.timestamp
    return timedelta(0) <= age <= timedelta(milliseconds=maximum_age_ms)


def verified_settlement_prices(market: MarketDetails | None) -> dict[str, Decimal] | None:
    """Accept final settlement only from an explicitly closed 0/1 outcome set."""

    if market is None or market.closed is not True or len(market.outcomes) < 2:
        return None
    prices: dict[str, Decimal] = {}
    for outcome in market.outcomes:
        if outcome.token_id is None or outcome.price not in {ZERO, ONE}:
            return None
        prices[outcome.token_id] = outcome.price
    if len(prices) != len(market.outcomes) or sum(prices.values(), ZERO) != ONE:
        return None
    return prices


__all__ = [
    "BookWalk",
    "ContinuousEvaluationStatus",
    "ContinuousPortfolio",
    "ContinuousPortfolioKind",
    "ContinuousPosition",
    "ContinuousShadowConfig",
    "ContinuousShadowLifecycle",
    "FeeEvidence",
    "calculate_verified_taker_fee",
    "quote_is_fresh",
    "verified_settlement_prices",
    "walk_order_book",
]
