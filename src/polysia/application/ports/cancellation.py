"""Venue-neutral contracts for cancellation finality evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol

OrderSide = Literal["BUY", "SELL"]


@dataclass(frozen=True, slots=True)
class CancellationResponse:
    """Canonical acknowledgement returned by a venue cancellation request."""

    canceled_order_ids: tuple[str, ...]
    not_canceled: dict[str, str]

    def __post_init__(self) -> None:
        if any(not order_id for order_id in self.canceled_order_ids) or any(
            not order_id for order_id in self.not_canceled
        ):
            raise ValueError("cancellation response identifiers must be non-empty")
        if len(self.canceled_order_ids) != len(set(self.canceled_order_ids)):
            raise ValueError("cancellation response contains duplicate canceled identifiers")
        if set(self.canceled_order_ids) & set(self.not_canceled):
            raise ValueError("cancellation response contains contradictory results")


@dataclass(frozen=True, slots=True)
class OpenOrderEvidence:
    """Canonical order fields needed by cancellation finality."""

    order_id: str
    token_id: str
    side: OrderSide
    status: str
    original_size: Decimal
    matched_size: Decimal
    associated_trade_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.order_id or not self.token_id or not self.status:
            raise ValueError("order evidence identifiers and status must be non-empty")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("order evidence side must be BUY or SELL")
        if (
            not self.original_size.is_finite()
            or not self.matched_size.is_finite()
            or self.original_size <= 0
            or self.matched_size < 0
            or self.matched_size > self.original_size
        ):
            raise ValueError("order evidence sizes are invalid")

    @property
    def remaining_size(self) -> Decimal:
        """Return the non-negative remainder reported by the venue."""

        return max(Decimal("0"), self.original_size - self.matched_size)


class OrderLookupStatus(StrEnum):
    """Whether an order-detail read returned a verified record or 404."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class OrderDetailEvidence:
    """Explicit result for a single-order detail lookup."""

    status: OrderLookupStatus
    order: OpenOrderEvidence | None = None

    def __post_init__(self) -> None:
        if (self.status is OrderLookupStatus.FOUND) != (self.order is not None):
            raise ValueError("found order detail must contain exactly one order")


@dataclass(frozen=True, slots=True)
class OrderTradeEvidence:
    """One order-linked trade contribution mapped at the venue boundary."""

    evidence_id: str
    order_id: str
    token_id: str
    status: str
    size: Decimal
    price: Decimal

    def __post_init__(self) -> None:
        if not all((self.evidence_id, self.order_id, self.token_id, self.status)):
            raise ValueError("trade evidence identifiers and status must be non-empty")
        if (
            not self.size.is_finite()
            or not self.price.is_finite()
            or self.size <= 0
            or self.price <= 0
        ):
            raise ValueError("trade evidence size and price must be finite and positive")


class CancellationEvidencePort(Protocol):
    """Read-only venue evidence consumed after a cancellation boundary."""

    async def observe_open_orders(
        self,
        *,
        order_id: str | None = None,
    ) -> tuple[OpenOrderEvidence, ...]: ...

    async def observe_order_detail(self, *, order_id: str) -> OrderDetailEvidence: ...

    async def observe_order_trades(
        self,
        *,
        order_id: str,
        token_id: str,
    ) -> tuple[OrderTradeEvidence, ...]: ...

    async def observe_position_size(self, *, token_id: str) -> Decimal: ...


__all__ = [
    "CancellationEvidencePort",
    "CancellationResponse",
    "OpenOrderEvidence",
    "OrderDetailEvidence",
    "OrderLookupStatus",
    "OrderSide",
    "OrderTradeEvidence",
]
