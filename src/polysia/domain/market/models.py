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
    tags: tuple[str, ...] = ()
