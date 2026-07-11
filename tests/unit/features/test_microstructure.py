from __future__ import annotations

from decimal import Decimal

from pm_trader.features.microstructure import calculate_microstructure_features
from pm_trader.orderbook.book import LocalOrderBook


def test_calculate_microstructure_features_from_orderbook() -> None:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=(("0.49", "100"),),
        asks=(("0.52", "10"),),
    )

    features = calculate_microstructure_features(book)

    assert features.token_id == "token-1"
    assert features.best_bid == Decimal("0.49")
    assert features.best_ask == Decimal("0.52")
    assert features.mid == Decimal("0.505")
    assert features.spread == Decimal("0.03")
    assert features.bid_depth == Decimal("100")
    assert features.ask_depth == Decimal("10")
    assert features.microprice is not None
    assert features.microprice_edge == features.microprice - Decimal("0.505")
