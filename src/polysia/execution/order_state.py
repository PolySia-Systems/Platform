from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from polysia.execution.intents import ApprovedOrderIntent, OrderSide


class OrderStatus(StrEnum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(slots=True)
class PaperOrder:
    order_id: str
    approved_intent: ApprovedOrderIntent
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    filled_size: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    reason: str | None = None
    fills: list[PaperFill] = field(default_factory=list)

    @property
    def remaining_size(self) -> Decimal:
        return self.approved_intent.approved_size - self.filled_size

    def add_fill(self, fill: PaperFill) -> None:
        total_notional = (self.avg_fill_price or Decimal("0")) * self.filled_size
        total_notional += fill.price * fill.size
        self.filled_size += fill.size
        self.avg_fill_price = total_notional / self.filled_size
        self.fills.append(fill)
        self.updated_at = fill.created_at
        if self.remaining_size == Decimal("0"):
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def to_dict(self) -> dict[str, object]:
        return {
            "avg_fill_price": str(self.avg_fill_price) if self.avg_fill_price is not None else None,
            "created_at": _datetime_to_text(self.created_at),
            "filled_size": str(self.filled_size),
            "fills": [fill.to_dict() for fill in self.fills],
            "order_id": self.order_id,
            "reason": self.reason,
            "remaining_size": str(self.remaining_size),
            "status": self.status.value,
            "token_id": self.approved_intent.token_id,
            "side": self.approved_intent.side,
            "price": str(self.approved_intent.price),
            "size": str(self.approved_intent.approved_size),
            "updated_at": _datetime_to_text(self.updated_at),
        }


@dataclass(frozen=True, slots=True)
class PaperFill:
    fill_id: str
    order_id: str
    token_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "created_at": _datetime_to_text(self.created_at),
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "price": str(self.price),
            "side": self.side,
            "size": str(self.size),
            "token_id": self.token_id,
        }


def _datetime_to_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
