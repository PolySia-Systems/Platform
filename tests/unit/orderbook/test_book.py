from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from pm_trader.orderbook.book import BookSide, LocalOrderBook
from pm_trader.orderbook.validators import OrderBookValidationError


def test_snapshot_computes_top_of_book_metrics() -> None:
    book = LocalOrderBook(token_id="token-1")

    book.apply_snapshot(
        bids=(("0.49", "10"), ("0.48", "5")),
        asks=(("0.52", "20"), ("0.53", "4")),
    )

    assert book.best_bid == Decimal("0.49")
    assert book.best_ask == Decimal("0.52")
    assert book.mid == Decimal("0.505")
    assert book.spread == Decimal("0.03")
    assert book.bid_depth == Decimal("10")
    assert book.ask_depth == Decimal("20")
    assert book.orderbook_imbalance == Decimal("10") / Decimal("30")
    assert book.microprice == Decimal("0.5")
    assert [level.price for level in book.bids] == [Decimal("0.49"), Decimal("0.48")]
    assert [level.price for level in book.asks] == [Decimal("0.52"), Decimal("0.53")]


def test_incremental_update_inserts_replaces_and_deletes_levels() -> None:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(bids=(("0.49", "10"),), asks=(("0.52", "20"),))

    book.apply_update(side="BUY", price="0.50", size="3")
    book.apply_update(side="SELL", price="0.52", size="15")
    book.apply_update(side="BUY", price="0.49", size="0")

    assert book.best_bid == Decimal("0.50")
    assert book.bid_depth == Decimal("3")
    assert book.best_ask == Decimal("0.52")
    assert book.ask_depth == Decimal("15")
    assert [level.price for level in book.bids] == [Decimal("0.50")]


def test_empty_book_metrics_are_none_or_zero() -> None:
    book = LocalOrderBook(token_id="token-1")

    assert book.best_bid is None
    assert book.best_ask is None
    assert book.mid is None
    assert book.spread is None
    assert book.bid_depth == Decimal("0")
    assert book.ask_depth == Decimal("0")
    assert book.orderbook_imbalance is None
    assert book.microprice is None


def test_rejects_invalid_prices_and_negative_sizes() -> None:
    book = LocalOrderBook(token_id="token-1")

    with pytest.raises(OrderBookValidationError, match="within"):
        book.apply_update(side="BUY", price="1.01", size="1")

    with pytest.raises(OrderBookValidationError, match="negative"):
        book.apply_update(side="SELL", price="0.50", size="-1")

    with pytest.raises(OrderBookValidationError, match="BUY or SELL"):
        book.apply_update(side=cast(BookSide, "HOLD"), price="0.50", size="1")


def test_rejects_crossed_updates_and_restores_previous_state() -> None:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(bids=(("0.49", "10"),), asks=(("0.52", "20"),))

    with pytest.raises(OrderBookValidationError, match="crossed"):
        book.apply_update(side="BUY", price="0.53", size="1")

    assert book.best_bid == Decimal("0.49")
    assert book.best_ask == Decimal("0.52")


def test_rejects_crossed_snapshot_unless_diagnostic_mode_allows_it() -> None:
    book = LocalOrderBook(token_id="token-1")

    with pytest.raises(OrderBookValidationError, match="crossed"):
        book.apply_snapshot(bids=(("0.60", "1"),), asks=(("0.50", "1"),))

    diagnostic_book = LocalOrderBook(token_id="token-1", allow_crossed=True)
    diagnostic_book.apply_snapshot(bids=(("0.60", "1"),), asks=(("0.50", "1"),))

    assert diagnostic_book.best_bid == Decimal("0.60")
    assert diagnostic_book.best_ask == Decimal("0.50")
