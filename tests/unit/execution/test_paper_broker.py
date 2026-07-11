from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pm_trader.execution.intents import ApprovedOrderIntent, OrderIntent
from pm_trader.execution.order_state import OrderStatus
from pm_trader.execution.paper_broker import PaperBroker
from pm_trader.orderbook.book import LocalOrderBook
from pm_trader.portfolio.positions import Position, PositionLedger


def make_book(*, bid_size: str = "10", ask_size: str = "10") -> LocalOrderBook:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=(("0.49", bid_size),),
        asks=(("0.52", ask_size),),
    )
    return book


def make_approved_intent(
    *,
    side: str = "BUY",
    price: str = "0.52",
    size: str = "5",
) -> ApprovedOrderIntent:
    intent = OrderIntent(
        strategy_id="strategy-1",
        token_id="token-1",
        side=side,  # type: ignore[arg-type]
        price=Decimal(price),
        size=Decimal(size),
        reason="test",
        confidence=Decimal("0.5"),
    )
    return ApprovedOrderIntent(
        intent=intent,
        approved_size=Decimal(size),
        risk_reason="approved",
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_paper_broker_fills_crossing_buy_order_and_updates_position() -> None:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(make_approved_intent(), make_book())

    assert order.status == OrderStatus.FILLED
    assert order.filled_size == Decimal("5")
    assert order.avg_fill_price == Decimal("0.52")
    assert ledger.cash == Decimal("97.40")
    assert ledger.get("token-1").size == Decimal("5")
    assert ledger.get("token-1").avg_price == Decimal("0.52")
    assert len(broker.audit_log) == 3


def test_paper_broker_keeps_non_crossing_buy_order_resting() -> None:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(
        make_approved_intent(price="0.51"),
        make_book(),
    )

    assert order.status == OrderStatus.ACCEPTED
    assert order.fills == []
    assert ledger.cash == Decimal("100")
    assert "resting buy" in str(order.reason)


def test_paper_broker_partially_fills_when_top_depth_is_smaller_than_order() -> None:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(
        make_approved_intent(size="5"),
        make_book(ask_size="2"),
    )

    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_size == Decimal("2")
    assert order.remaining_size == Decimal("3")
    assert ledger.get("token-1").size == Decimal("2")


def test_paper_broker_rejects_buy_when_cash_is_insufficient() -> None:
    ledger = PositionLedger(cash=Decimal("1"))
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(make_approved_intent(size="5"), make_book())

    assert order.status == OrderStatus.REJECTED
    assert order.fills == []
    assert "cash" in str(order.reason)


def test_paper_broker_fills_sell_order_and_realizes_pnl() -> None:
    ledger = PositionLedger(
        cash=Decimal("100"),
        positions={
            "token-1": Position(
                token_id="token-1",
                size=Decimal("5"),
                avg_price=Decimal("0.40"),
            )
        },
    )
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(
        make_approved_intent(side="SELL", price="0.49", size="3"),
        make_book(),
    )

    assert order.status == OrderStatus.FILLED
    assert ledger.cash == Decimal("101.47")
    assert ledger.realized_pnl == Decimal("0.27")
    assert ledger.get("token-1").size == Decimal("2")


def test_paper_broker_rejects_sell_when_position_is_insufficient() -> None:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(
        make_approved_intent(side="SELL", price="0.49", size="3"),
        make_book(),
    )

    assert order.status == OrderStatus.REJECTED
    assert "position" in str(order.reason)
