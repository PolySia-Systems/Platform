from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polysia.execution.intents import ApprovedOrderIntent
from polysia.execution.order_state import OrderStatus, PaperFill, PaperOrder
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.positions import PositionLedger

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class PaperBroker:
    """Conservative paper broker that never calls live trading APIs."""

    ledger: PositionLedger
    clock: Clock = utc_now
    orders: dict[str, PaperOrder] = field(default_factory=dict)
    fills: list[PaperFill] = field(default_factory=list)
    audit_log: list[dict[str, object]] = field(default_factory=list)

    def submit_limit_order(
        self,
        approved_intent: ApprovedOrderIntent,
        orderbook: LocalOrderBook,
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
            self._handle_buy(order, orderbook)
        else:
            self._handle_sell(order, orderbook)

        self._audit("order_state", order=order)
        return order

    def _handle_buy(self, order: PaperOrder, orderbook: LocalOrderBook) -> None:
        best_ask = orderbook.best_ask
        if best_ask is None or order.approved_intent.price < best_ask:
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting buy order; price below best ask"
            return

        fill_size = min(order.remaining_size, orderbook.ask_depth)
        if fill_size <= Decimal("0"):
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting buy order; no ask depth"
            return

        required_cash = best_ask * fill_size
        if required_cash > self.ledger.cash:
            self._reject(order, "insufficient paper cash")
            return

        self._fill(order, price=best_ask, size=fill_size)

    def _handle_sell(self, order: PaperOrder, orderbook: LocalOrderBook) -> None:
        best_bid = orderbook.best_bid
        if best_bid is None or order.approved_intent.price > best_bid:
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting sell order; price above best bid"
            return

        fill_size = min(order.remaining_size, orderbook.bid_depth)
        if fill_size <= Decimal("0"):
            order.status = OrderStatus.ACCEPTED
            order.reason = "resting sell order; no bid depth"
            return

        position = self.ledger.get(order.approved_intent.token_id)
        if fill_size > position.size:
            self._reject(order, "insufficient paper position")
            return

        self._fill(order, price=best_bid, size=fill_size)

    def _fill(self, order: PaperOrder, *, price: Decimal, size: Decimal) -> None:
        fill = PaperFill(
            fill_id=f"fill-{uuid4().hex}",
            order_id=order.order_id,
            token_id=order.approved_intent.token_id,
            side=order.approved_intent.side,
            price=price,
            size=size,
            created_at=self.clock(),
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
            record["fill_id"] = fill.fill_id
            record["fill_price"] = str(fill.price)
            record["fill_size"] = str(fill.size)
        self.audit_log.append(record)
