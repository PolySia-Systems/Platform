from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pm_trader.orderbook.book import LocalOrderBook


@dataclass(frozen=True, slots=True)
class MicrostructureFeatures:
    token_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    mid: Decimal | None
    spread: Decimal | None
    bid_depth: Decimal
    ask_depth: Decimal
    imbalance: Decimal | None
    microprice: Decimal | None
    microprice_edge: Decimal | None


def calculate_microstructure_features(book: LocalOrderBook) -> MicrostructureFeatures:
    """Calculate top-of-book features from a local orderbook."""
    microprice_edge = None
    if book.microprice is not None and book.mid is not None:
        microprice_edge = book.microprice - book.mid

    return MicrostructureFeatures(
        token_id=book.token_id,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        mid=book.mid,
        spread=book.spread,
        bid_depth=book.bid_depth,
        ask_depth=book.ask_depth,
        imbalance=book.orderbook_imbalance,
        microprice=book.microprice,
        microprice_edge=microprice_edge,
    )
