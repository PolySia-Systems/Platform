from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from polymarket import PolymarketError

from polysia.adapters.polymarket_public import (
    PolymarketPublicAdapter,
    PolymarketPublicAdapterError,
)


class FakePaginator:
    def __init__(self, items: tuple[Any, ...]) -> None:
        self._items = items

    async def first_page(self) -> SimpleNamespace:
        return SimpleNamespace(items=self._items)


class FakeClientContext:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def __aenter__(self) -> Any:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeClient:
    def __init__(
        self,
        *,
        markets: tuple[Any, ...] = (),
        market: Any | None = None,
        search_results: tuple[Any, ...] = (),
    ) -> None:
        self.markets = markets
        self.market = market
        self.search_results = search_results
        self.list_markets_kwargs: dict[str, Any] | None = None
        self.get_market_kwargs: dict[str, Any] | None = None
        self.search_kwargs: dict[str, Any] | None = None

    def list_markets(self, **kwargs: Any) -> FakePaginator:
        self.list_markets_kwargs = kwargs
        return FakePaginator(self.markets)

    async def get_market(self, **kwargs: Any) -> Any:
        self.get_market_kwargs = kwargs
        return self.market

    def search(self, **kwargs: Any) -> FakePaginator:
        self.search_kwargs = kwargs
        return FakePaginator(self.search_results)


def make_market(
    market_id: str = "1",
    *,
    slug: str = "slug",
    closed: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=market_id,
        slug=slug,
        condition_id="0xcondition",
        question="Will the example happen?",
        description="Example market",
        category="Example",
        image="https://example.com/image.png",
        icon="https://example.com/icon.png",
        state=SimpleNamespace(
            active=not closed,
            closed=closed,
            accepting_orders=not closed,
            end_date=None,
        ),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(label="Yes", token_id="yes-token", price=Decimal("0.61")),
            no=SimpleNamespace(label="No", token_id="no-token", price=Decimal("0.39")),
        ),
        metrics=SimpleNamespace(liquidity_num=Decimal("100.5"), volume_num=Decimal("250")),
        prices=SimpleNamespace(best_bid=Decimal("0.60"), best_ask=Decimal("0.62")),
        trading=SimpleNamespace(
            minimum_order_size=Decimal("5"),
            minimum_tick_size=Decimal("0.01"),
        ),
        tags=(SimpleNamespace(label="Politics", slug="politics"),),
    )


@pytest.mark.asyncio
async def test_list_active_markets_normalizes_sdk_objects() -> None:
    client = FakeClient(markets=(make_market(),))
    adapter = PolymarketPublicAdapter(client_factory=lambda: FakeClientContext(client))

    markets = await adapter.list_active_markets(page_size=7)

    assert client.list_markets_kwargs == {
        "closed": False,
        "include_tag": True,
        "page_size": 7,
    }
    assert len(markets) == 1
    assert markets[0].id == "1"
    assert markets[0].outcomes[0].token_id == "yes-token"
    assert markets[0].best_ask == Decimal("0.62")


@pytest.mark.asyncio
async def test_get_market_by_slug_returns_details() -> None:
    client = FakeClient(market=make_market(slug="eth-flipped-in-2026"))
    adapter = PolymarketPublicAdapter(client_factory=lambda: FakeClientContext(client))

    details = await adapter.get_market_by_slug("eth-flipped-in-2026")

    assert client.get_market_kwargs == {
        "slug": "eth-flipped-in-2026",
        "include_tag": True,
    }
    assert details.slug == "eth-flipped-in-2026"
    assert details.condition_id == "0xcondition"
    assert details.minimum_tick_size == Decimal("0.01")
    assert details.tags == ("Politics",)


@pytest.mark.asyncio
async def test_search_markets_flattens_event_markets_and_deduplicates() -> None:
    open_market = make_market("1", slug="open-market")
    duplicate_market = make_market("1", slug="duplicate-market")
    closed_market = make_market("2", slug="closed-market", closed=True)
    search_result = SimpleNamespace(
        events=(
            SimpleNamespace(markets=(open_market, duplicate_market, closed_market)),
        )
    )
    client = FakeClient(search_results=(search_result,))
    adapter = PolymarketPublicAdapter(client_factory=lambda: FakeClientContext(client))

    markets = await adapter.search_markets("example", page_size=10)

    assert client.search_kwargs == {
        "q": "example",
        "events_status": "active",
        "search_profiles": False,
        "search_tags": False,
        "page_size": 10,
    }
    assert [market.slug for market in markets] == ["open-market"]


@pytest.mark.asyncio
async def test_polymarket_errors_are_wrapped() -> None:
    class FailingClient:
        def list_markets(self, **kwargs: Any) -> FakePaginator:
            raise PolymarketError("rate limited")

    adapter = PolymarketPublicAdapter(client_factory=lambda: FakeClientContext(FailingClient()))

    with pytest.raises(PolymarketPublicAdapterError):
        await adapter.list_active_markets()
