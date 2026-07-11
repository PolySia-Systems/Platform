from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

OrderSide = Literal["BUY", "SELL"]


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """A strategy's intent to trade, before risk approval or broker handling."""

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
    """Risk-approved order intent accepted by brokers."""

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
