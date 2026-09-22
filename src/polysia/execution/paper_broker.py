from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polysia.domain.copytrading.continuous_shadow import (
    ZERO,
    calculate_taker_fee_amount,
    consume_book_levels,
)
from polysia.domain.market import MarketDetails
from polysia.execution.intents import ApprovedOrderIntent
from polysia.execution.order_state import OrderStatus, PaperFill, PaperOrder
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.positions import PositionLedger

Clock = Callable[[], datetime]
PAPER_FILL_ECONOMICS_VERSION = "paper-limit-walk-v1"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class PaperBroker:
    """Paper limit broker. It never calls live trading APIs or discovers fees."""

    ledger: PositionLedger
    clock: Clock = utc_now
    orders: dict[str, PaperOrder] = field(default_factory=dict)
    fills: list[PaperFill] = field(default_factory=list)
    audit_log: list[dict[str, object]] = field(default_factory=list)

    def submit_limit_order(
        self,
        approved_intent: ApprovedOrderIntent,
        orderbook: LocalOrderBook,
        market: MarketDetails | None = None,
    ) -> PaperOrder:
        created_at = self.clock()
        order = PaperOrder(
            order_id=f"paper-{uuid4().hex}",
            approved_intent=approved_intent,
            status=OrderStatus.NEW,
            created_at=created_at,
            updated_at=created_at,
        )
        self.orders[order.order_id] = order
        self._audit("order_new", order=order)

        if orderbook.token_id != approved_intent.token_id:
            return self._reject(order, "orderbook token_id does not match approved intent")

        if approved_intent.side == "BUY":
            self._handle_buy(order, orderbook, market)
        else:
            self._handle_sell(order, orderbook, market)

        self._audit("order_state", order=order)
        return order

    def _handle_buy(
        self,
        order: PaperOrder,
        orderbook: LocalOrderBook,
        market: MarketDetails | None,
    ) -> None:
        levels = _crossing_levels(
            orderbook,
            side="BUY",
            limit_price=order.approved_intent.price,
        )
        if not levels:
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting buy order; price below best ask"
            return
        consumed, notional = consume_book_levels(
            levels,
            requested_size=order.remaining_size,
            already_consumed={},
        )
        if not consumed or notional <= ZERO:
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting buy order; no ask depth"
            return
        fee = _verified_level_fee(market, consumed)
        if fee is None:
            self._reject(order, "market_specific_fee_provenance_unknown")
            return
        if notional + fee > self.ledger.cash:
            self._reject(order, "insufficient paper cash")
            return
        self._fill(order, consumed=consumed, notional=notional, fee=fee)

    def _handle_sell(
        self,
        order: PaperOrder,
        orderbook: LocalOrderBook,
        market: MarketDetails | None,
    ) -> None:
        levels = _crossing_levels(
            orderbook,
            side="SELL",
            limit_price=order.approved_intent.price,
        )
        if not levels:
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting sell order; price above best bid"
            return
        consumed, notional = consume_book_levels(
            levels,
            requested_size=order.remaining_size,
            already_consumed={},
        )
        if not consumed or notional <= ZERO:
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting sell order; no bid depth"
            return
        filled = sum((size for _, size in consumed), ZERO)
        position = self.ledger.get(order.approved_intent.token_id)
        if filled > position.size:
            self._reject(order, "insufficient paper position")
            return
        fee = _verified_level_fee(market, consumed)
        if fee is None:
            self._reject(order, "market_specific_fee_provenance_unknown")
            return
        if fee > notional:
            self._reject(order, "verified fee exceeds sell notional")
            return
        self._fill(order, consumed=consumed, notional=notional, fee=fee)

    def _fill(
        self,
        order: PaperOrder,
        *,
        consumed: tuple[tuple[Decimal, Decimal], ...],
        notional: Decimal,
        fee: Decimal,
    ) -> None:
        filled = sum((size for _, size in consumed), ZERO)
        price = notional / filled
        fill = PaperFill(
            fill_id=f"fill-{uuid4().hex}",
            order_id=order.order_id,
            token_id=order.approved_intent.token_id,
            side=order.approved_intent.side,
            price=price,
            size=filled,
            created_at=self.clock(),
            fee=fee,
        )
        order.add_fill(fill)
        self.fills.append(fill)
        self.ledger.apply_fill(fill)
        self._audit("fill", order=order, fill=fill)

    def _reject(self, order: PaperOrder, reason: str) -> PaperOrder:
        order.status = OrderStatus.REJECTED
        order.reason = reason
        order.updated_at = self.clock()
        self._audit("order_rejected", order=order)
        return order

    def _audit(self, event: str, *, order: PaperOrder, fill: PaperFill | None = None) -> None:
        record: dict[str, object] = {
            "economics": PAPER_FILL_ECONOMICS_VERSION,
            "event": event,
            "order_id": order.order_id,
            "status": order.status.value,
            "strategy_id": order.approved_intent.strategy_id,
            "token_id": order.approved_intent.token_id,
            "side": order.approved_intent.side,
            "price": str(order.approved_intent.price),
            "size": str(order.approved_intent.approved_size),
            "filled_size": str(order.filled_size),
            "reason": order.reason,
            "timestamp": self.clock().isoformat(),
        }
        if fill is not None:
            record["fill_fee"] = str(fill.fee)
            record["fill_id"] = fill.fill_id
            record["fill_price"] = str(fill.price)
            record["fill_size"] = str(fill.size)
        self.audit_log.append(record)


def _crossing_levels(
    book: LocalOrderBook,
    *,
    side: str,
    limit_price: Decimal,
) -> tuple[tuple[Decimal, Decimal], ...]:
    if side == "BUY":
        return tuple(
            (level.price, level.size) for level in book.asks if level.price <= limit_price
        )
    return tuple((level.price, level.size) for level in book.bids if level.price >= limit_price)


def _verified_level_fee(
    market: MarketDetails | None,
    consumed: tuple[tuple[Decimal, Decimal], ...],
) -> Decimal | None:
    """Sum per-level taker fees when provenance matches verified shadow rules."""

    if market is None or market.fee_schedule is None:
        return None
    schedule = market.fee_schedule
    if not schedule.enabled:
        return ZERO
    if (
        schedule.rate is None
        or schedule.exponent is None
        or schedule.rate < ZERO
        or schedule.exponent < ZERO
        or schedule.taker_only is not True
    ):
        return None
    total = ZERO
    for price, size in consumed:
        amount = calculate_taker_fee_amount(
            price=price,
            size=size,
            rate=schedule.rate,
            exponent=schedule.exponent,
        )
        if amount is None:
            return None
        total += amount
    return total


__all__ = ["PAPER_FILL_ECONOMICS_VERSION", "PaperBroker"]
