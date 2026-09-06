from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from polysia.domain.orders.models import OrderIntent, OrderSide


class CanonicalOrderError(ValueError):
    """Raised when a market-order request is not a canonical side-aware request."""


@dataclass(frozen=True, slots=True)
class CanonicalMarketOrderRequest:
    """Venue-neutral market-order request Risk evaluates and Execution must submit exactly."""

    token_id: str
    side: OrderSide
    order_type: str
    amount: Decimal | None
    shares: Decimal | None
    max_spend: Decimal | None
    max_price: Decimal | None
    min_price: Decimal | None

    def as_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "token_id": self.token_id,
            "side": self.side,
            "order_type": self.order_type,
        }
        if self.amount is not None:
            payload["amount"] = self.amount
        if self.shares is not None:
            payload["shares"] = self.shares
        if self.max_spend is not None:
            payload["max_spend"] = self.max_spend
        if self.max_price is not None:
            payload["max_price"] = self.max_price
        if self.min_price is not None:
            payload["min_price"] = self.min_price
        return payload

    def as_adapter_kwargs(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "side": self.side,
            "amount": self.amount,
            "shares": self.shares,
            "max_spend": self.max_spend,
            "max_price": self.max_price,
            "min_price": self.min_price,
            "order_type": self.order_type,
        }


@dataclass(frozen=True, slots=True)
class ApprovedOrder:
    """Immutable Risk-approved market request. Execution may submit only this request."""

    request: CanonicalMarketOrderRequest
    risk_reason: str
    approved_at: datetime
    approved_exposure: Decimal


def canonicalize_market_order(
    intent: OrderIntent,
    *,
    amount: Decimal | None = None,
    shares: Decimal | None = None,
    max_spend: Decimal | None = None,
    max_price: Decimal | None = None,
    min_price: Decimal | None = None,
    order_type: str = "FAK",
) -> CanonicalMarketOrderRequest:
    """Translate raw intent plus constraints into a side-aware canonical request.

    Transformations must happen here, before Risk approval. Polymarket 0.7.1:
    BUY uses amount/max_spend spend exposure and max_price protection; SELL uses
    shares quantity exposure and min_price protection.
    """

    if order_type not in {"FAK", "FOK"}:
        raise CanonicalOrderError(f"unsupported market order_type {order_type!r}")
    if intent.side == "BUY":
        _reject_if_set("BUY", shares=shares, min_price=min_price)
        if amount is None and max_spend is None:
            raise CanonicalOrderError("BUY market order requires amount or max_spend")
        if max_price is None:
            raise CanonicalOrderError("BUY market order requires max_price protection")
        if max_price != intent.price:
            raise CanonicalOrderError("BUY max_price must match the order intent price")
    elif intent.side == "SELL":
        _reject_if_set("SELL", amount=amount, max_spend=max_spend, max_price=max_price)
        if shares is None:
            raise CanonicalOrderError("SELL market order requires shares")
        if min_price is None:
            raise CanonicalOrderError("SELL market order requires min_price protection")
        if shares != intent.size:
            raise CanonicalOrderError("SELL shares must match the order intent size")
        if min_price != intent.price:
            raise CanonicalOrderError("SELL min_price must match the order intent price")
    else:
        raise CanonicalOrderError(f"unsupported side {intent.side!r}")
    if intent.token_id.strip() == "":
        raise CanonicalOrderError("token_id is required")
    return CanonicalMarketOrderRequest(
        token_id=intent.token_id,
        side=intent.side,
        order_type=order_type,
        amount=amount,
        shares=shares,
        max_spend=max_spend,
        max_price=max_price,
        min_price=min_price,
    )


def risk_intent_from_canonical(
    intent: OrderIntent,
    request: CanonicalMarketOrderRequest,
) -> OrderIntent:
    """Map canonical maximum economic exposure onto the existing Risk OrderIntent."""

    size = canonical_risk_size(request)
    price = canonical_risk_price(request)
    return OrderIntent(
        strategy_id=intent.strategy_id,
        token_id=request.token_id,
        side=request.side,
        price=price,
        size=size,
        reason=intent.reason,
        confidence=intent.confidence,
    )


def canonical_risk_size(request: CanonicalMarketOrderRequest) -> Decimal:
    if request.side == "BUY":
        return _buy_risk_size(
            amount=request.amount,
            max_spend=request.max_spend,
            max_price=request.max_price,
        )
    if request.shares is None:
        raise CanonicalOrderError("SELL market order requires shares")
    return request.shares


def canonical_risk_price(request: CanonicalMarketOrderRequest) -> Decimal:
    if request.side == "BUY":
        if request.max_price is None:
            raise CanonicalOrderError("BUY market order requires max_price protection")
        return request.max_price
    if request.min_price is None:
        raise CanonicalOrderError("SELL market order requires min_price protection")
    return request.min_price


def bind_approved_order(
    request: CanonicalMarketOrderRequest,
    *,
    adjusted_size: Decimal,
    risk_reason: str,
    approved_at: datetime,
) -> ApprovedOrder:
    original = canonical_risk_size(request)
    if adjusted_size <= Decimal("0"):
        raise CanonicalOrderError("approved exposure must be positive")
    if adjusted_size > original:
        raise CanonicalOrderError("approved exposure must not exceed the canonical request")
    bound = request if adjusted_size == original else _scale_canonical(request, adjusted_size)
    return ApprovedOrder(
        request=bound,
        risk_reason=risk_reason,
        approved_at=approved_at,
        approved_exposure=adjusted_size,
    )


def assert_exact_approved_request(
    approved: ApprovedOrder,
    requested: CanonicalMarketOrderRequest,
) -> None:
    if requested != approved.request:
        raise CanonicalOrderError(
            "requested market order does not exactly match the Risk-approved request"
        )


def _buy_risk_size(
    *,
    amount: Decimal | None,
    max_spend: Decimal | None,
    max_price: Decimal | None,
) -> Decimal:
    if max_price is None or max_price <= Decimal("0"):
        raise CanonicalOrderError("BUY market order requires a positive max_price")
    spend = max_spend if max_spend is not None else amount
    if spend is None or spend <= Decimal("0"):
        raise CanonicalOrderError("BUY market order requires positive amount or max_spend")
    return spend / max_price


def _scale_canonical(
    request: CanonicalMarketOrderRequest,
    adjusted_size: Decimal,
) -> CanonicalMarketOrderRequest:
    if request.side == "SELL":
        return replace(request, shares=adjusted_size)
    ratio = adjusted_size / canonical_risk_size(request)
    amount = None if request.amount is None else request.amount * ratio
    max_spend = None if request.max_spend is None else request.max_spend * ratio
    return replace(request, amount=amount, max_spend=max_spend)


def _reject_if_set(side: str, **fields: Decimal | None) -> None:
    present = [name for name, value in fields.items() if value is not None]
    if present:
        raise CanonicalOrderError(
            f"{side} market order forbids {', '.join(present)}"
        )
