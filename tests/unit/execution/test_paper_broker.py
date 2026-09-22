from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from polysia.domain.copytrading.continuous_shadow import calculate_taker_fee_amount
from polysia.domain.market import MarketDetails, MarketFeeSchedule
from polysia.execution.intents import ApprovedOrderIntent, OrderIntent
from polysia.execution.order_state import OrderStatus
from polysia.execution.paper_broker import PAPER_FILL_ECONOMICS_VERSION, PaperBroker
from polysia.execution.paper_context import paper_risk_context
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.positions import Position, PositionLedger


def fee_free_market() -> MarketDetails:
    return MarketDetails(id="paper-test", fee_schedule=MarketFeeSchedule(enabled=False))


def enabled_fee_market() -> MarketDetails:
    return MarketDetails(
        id="paper-test",
        fee_schedule=MarketFeeSchedule(
            enabled=True,
            rate=Decimal("0.10"),
            exponent=Decimal("1"),
            taker_only=True,
        ),
    )


def make_book(
    *,
    bid_size: str = "10",
    ask_size: str = "10",
    bids: tuple[tuple[str, str], ...] | None = None,
    asks: tuple[tuple[str, str], ...] | None = None,
) -> LocalOrderBook:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=bids if bids is not None else (("0.49", bid_size),),
        asks=asks if asks is not None else (("0.52", ask_size),),
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

    order = broker.submit_limit_order(make_approved_intent(), make_book(), fee_free_market())

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
        fee_free_market(),
    )

    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_size == Decimal("2")
    assert order.remaining_size == Decimal("3")
    assert ledger.get("token-1").size == Decimal("2")


def test_paper_broker_rejects_buy_when_cash_is_insufficient() -> None:
    ledger = PositionLedger(cash=Decimal("1"))
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(
        make_approved_intent(size="5"),
        make_book(),
        fee_free_market(),
    )

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
        fee_free_market(),
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


def test_paper_broker_rejects_crossing_fill_without_fee_provenance() -> None:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger)

    order = broker.submit_limit_order(make_approved_intent(), make_book())

    assert order.status == OrderStatus.REJECTED
    assert order.reason == "market_specific_fee_provenance_unknown"
    assert ledger.cash == Decimal("100")
    assert ledger.get("token-1").size == Decimal("0")
    assert ledger.fees == Decimal("0")
    assert broker.audit_log[-1]["economics"] == PAPER_FILL_ECONOMICS_VERSION


def test_paper_broker_sums_per_level_fees_and_keeps_gross_vwap() -> None:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger)
    book = make_book(
        bids=(("0.10", "10"),),
        asks=(("0.20", "1"), ("0.40", "1"), ("0.80", "5")),
    )
    order = broker.submit_limit_order(
        make_approved_intent(price="0.40", size="2"),
        book,
        enabled_fee_market(),
    )
    level_fee = calculate_taker_fee_amount(
        price=Decimal("0.20"),
        size=Decimal("1"),
        rate=Decimal("0.10"),
        exponent=Decimal("1"),
    ) + calculate_taker_fee_amount(
        price=Decimal("0.40"),
        size=Decimal("1"),
        rate=Decimal("0.10"),
        exponent=Decimal("1"),
    )
    vwap_fee = calculate_taker_fee_amount(
        price=Decimal("0.30"),
        size=Decimal("2"),
        rate=Decimal("0.10"),
        exponent=Decimal("1"),
    )

    assert order.status == OrderStatus.FILLED
    assert order.avg_fill_price == Decimal("0.30")
    assert order.fills[0].fee == level_fee
    assert level_fee != vwap_fee
    assert ledger.cash == Decimal("100") - Decimal("0.60") - level_fee
    assert ledger.realized_pnl == Decimal("0")
    assert ledger.fees == level_fee
    assert ledger.get("token-1").avg_price == Decimal("0.30")
    context = paper_risk_context(
        ledger=ledger,
        token_id="token-1",
        orders=broker.orders.values(),
        market_data_age_ms=0,
    )
    assert context.daily_pnl == ledger.realized_pnl
    assert context.daily_pnl == Decimal("0")
    assert context.current_position == Decimal("2")
    assert context.current_market_position == Decimal("2")
    assert context.open_orders_count == 0
