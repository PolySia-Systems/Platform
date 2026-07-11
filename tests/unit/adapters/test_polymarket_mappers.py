from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from polysia.adapters.polymarket.mappers import PolymarketMarketMapper


def test_mapper_translates_sdk_shaped_market_without_leaking_sdk_types() -> None:
    market = SimpleNamespace(
        id="external-market",
        slug="event-slug",
        question="Will it map?",
        category="test",
        state=SimpleNamespace(active=True, closed=False, accepting_orders=True, end_date=None),
        metrics=SimpleNamespace(liquidity_num=Decimal("10"), volume_num=Decimal("20")),
        prices=SimpleNamespace(best_bid=Decimal("0.4"), best_ask=Decimal("0.6")),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(label="Yes", token_id="yes-token", price=Decimal("0.55")),
            no=SimpleNamespace(label="No", token_id="no-token", price=Decimal("0.45")),
        ),
    )

    summary = PolymarketMarketMapper().to_summary(market)

    assert summary.id == "external-market"
    assert summary.best_bid == Decimal("0.4")
    assert summary.outcomes[0].token_id == "yes-token"
    assert type(summary).__module__ == "polysia.domain.market.models"
