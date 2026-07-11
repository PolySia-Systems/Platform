from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from polysia.bus.events import MarketDataEvent
from polysia.orderbook.builder import BookBuilder


def make_event(
    event_type: str,
    *,
    payload: dict[str, object],
    token_id: str = "token-1",
) -> MarketDataEvent:
    return MarketDataEvent(
        source="polymarket",
        event_type=event_type,
        token_id=token_id,
        received_at=datetime.now(UTC),
        exchange_ts=None,
        payload=payload,
        raw_payload={"type": event_type},
    )


def test_builder_applies_book_snapshot_event() -> None:
    builder = BookBuilder()
    event = make_event(
        "book",
        payload={
            "asks": [{"price": "0.52", "size": "20"}],
            "bids": [{"price": "0.49", "size": "10"}],
        },
    )

    book = builder.apply(event)

    assert builder.get_book("token-1") is book
    assert book.best_bid == Decimal("0.49")
    assert book.best_ask == Decimal("0.52")


def test_builder_applies_price_change_event() -> None:
    builder = BookBuilder()
    builder.apply(
        make_event(
            "book",
            payload={
                "asks": [{"price": "0.52", "size": "20"}],
                "bids": [{"price": "0.49", "size": "10"}],
            },
        )
    )

    book = builder.apply(
        make_event(
            "price_change",
            payload={
                "price_change": {
                    "price": "0.50",
                    "side": "BUY",
                    "size": "7",
                    "token_id": "token-1",
                }
            },
        )
    )

    assert book.best_bid == Decimal("0.50")
    assert book.bid_depth == Decimal("7")


def test_builder_ignores_non_orderbook_events_after_creating_book() -> None:
    builder = BookBuilder()

    book = builder.apply(make_event("last_trade_price", payload={"price": "0.50"}))

    assert book.token_id == "token-1"
    assert book.best_bid is None
    assert book.best_ask is None
