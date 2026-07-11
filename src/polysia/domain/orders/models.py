from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

OrderSide = Literal["BUY", "SELL"]


class OrderStatus(StrEnum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """A strategy intent before independent risk approval."""

    strategy_id: str
    token_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    reason: str
    confidence: Decimal

    def __post_init__(self) -> None:
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {self.side!r}")
        if self.price < Decimal("0") or self.price > Decimal("1"):
            raise ValueError("price must be within [0, 1]")
        if self.size <= Decimal("0"):
            raise ValueError("size must be positive")
        if self.confidence < Decimal("0") or self.confidence > Decimal("1"):
            raise ValueError("confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class ApprovedOrderIntent:
    """Risk-approved order intent accepted by execution services."""

    intent: OrderIntent
    approved_size: Decimal
    risk_reason: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if self.approved_size <= Decimal("0"):
            raise ValueError("approved_size must be positive")
        if self.approved_size > self.intent.size:
            raise ValueError("approved_size must not exceed original intent size")
        if self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))

    @property
    def strategy_id(self) -> str:
        return self.intent.strategy_id

    @property
    def token_id(self) -> str:
        return self.intent.token_id

    @property
    def side(self) -> OrderSide:
        return self.intent.side

    @property
    def price(self) -> Decimal:
        return self.intent.price


@dataclass(frozen=True, slots=True)
class ExternalOrderReference:
    venue_id: str
    external_order_id: str


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    intent: ApprovedOrderIntent
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    external_reference: ExternalOrderReference | None = None
    filled_size: Decimal = Decimal("0")
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    order_id: str
    instrument_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    fee: Decimal = Decimal("0")
    occurred_at: datetime | None = None

