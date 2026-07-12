from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Venue(BaseModel):
    """Stable venue identity independent of an SDK."""

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str


class VenueCapabilityProfile(BaseModel):
    """Explicitly describes behavior supported by one venue adapter."""

    model_config = ConfigDict(frozen=True)

    venue: Venue
    supported_order_types: tuple[str, ...]
    supports_market_data_stream: bool
    supports_authenticated_reads: bool
    supports_order_cancellation: bool
    supports_live_execution: bool
    requires_geoblock_check: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


class MarketIdentifier(BaseModel):
    """Canonical identity plus an adapter-owned external identifier."""

    model_config = ConfigDict(frozen=True)

    value: str
    venue_id: str
    external_id: str | None = None


class MarketOutcomeSummary(BaseModel):
    """Normalized tradable outcome metadata."""

    model_config = ConfigDict(frozen=True)

    label: str
    token_id: str | None = None
    price: Decimal | None = None


class OrderBookLevel(BaseModel):
    """Canonical executable price level."""

    model_config = ConfigDict(frozen=True)

    price: Decimal
    size: Decimal


class MarketOrderBookSnapshot(BaseModel):
    """Venue-neutral order-book snapshot with venue trading rules."""

    model_config = ConfigDict(frozen=True)

    token_id: str
    market_id: str | None = None
    timestamp: datetime
    bids: tuple[OrderBookLevel, ...] = ()
    asks: tuple[OrderBookLevel, ...] = ()
    minimum_order_size: Decimal
    tick_size: Decimal
    negative_risk: bool = False
    book_hash: str | None = None

    @property
    def best_bid(self) -> OrderBookLevel | None:
        return max(self.bids, key=lambda level: level.price, default=None)

    @property
    def best_ask(self) -> OrderBookLevel | None:
        return min(self.asks, key=lambda level: level.price, default=None)

    @property
    def midpoint(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid.price + self.best_ask.price) / Decimal("2")

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask.price - self.best_bid.price


class MarketFeeSchedule(BaseModel):
    """Canonical per-market fee inputs reported by the venue."""

    model_config = ConfigDict(frozen=True)

    enabled: bool
    rate: Decimal | None = None
    exponent: Decimal | None = None
    taker_only: bool | None = None
    rebate_rate: Decimal | None = None


class MarketSummary(BaseModel):
    """Venue-neutral market fields used by the core."""

    model_config = ConfigDict(frozen=True)

    id: str
    slug: str | None = None
    question: str | None = None
    category: str | None = None
    active: bool | None = None
    closed: bool | None = None
    accepting_orders: bool | None = None
    end_date: datetime | None = None
    liquidity: Decimal | None = None
    volume: Decimal | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    outcomes: tuple[MarketOutcomeSummary, ...] = ()


class MarketDetails(MarketSummary):
    """Canonical details for one event market."""

    condition_id: str | None = None
    description: str | None = None
    image: str | None = None
    icon: str | None = None
    minimum_order_size: Decimal | None = None
    minimum_tick_size: Decimal | None = None
    enable_order_book: bool | None = None
    archived: bool | None = None
    start_date: datetime | None = None
    fee_schedule: MarketFeeSchedule | None = None
    fee_type: str | None = None
    seconds_delay: int | None = None
    tags: tuple[str, ...] = ()
