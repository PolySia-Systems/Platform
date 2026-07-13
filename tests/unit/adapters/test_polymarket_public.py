from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from polymarket import PolymarketError, RequestRejectedError, TransportError

from polysia.adapters.polymarket.diagnostics import ReadRetryPolicy
from polysia.adapters.polymarket.public import (
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
        order_book: Any | None = None,
        search_results: tuple[Any, ...] = (),
    ) -> None:
        self.markets = markets
        self.market = market
        self.order_book = order_book
        self.search_results = search_results
        self.list_markets_kwargs: dict[str, Any] | None = None
        self.get_market_kwargs: dict[str, Any] | None = None
        self.search_kwargs: dict[str, Any] | None = None
        self.order_book_token_id: str | None = None

    def list_markets(self, **kwargs: Any) -> FakePaginator:
        self.list_markets_kwargs = kwargs
        return FakePaginator(self.markets)

    async def get_market(self, **kwargs: Any) -> Any:
        self.get_market_kwargs = kwargs
        return self.market

    def search(self, **kwargs: Any) -> FakePaginator:
        self.search_kwargs = kwargs
        return FakePaginator(self.search_results)

    async def get_order_book(self, *, token_id: str) -> Any:
        self.order_book_token_id = token_id
        return self.order_book


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
        events=(SimpleNamespace(markets=(open_market, duplicate_market, closed_market)),)
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
async def test_get_order_book_returns_canonical_rules_and_depth() -> None:
    client = FakeClient(
        order_book=SimpleNamespace(
            token_id="token",
            market="condition",
            timestamp="1783771200000",
            bids=(SimpleNamespace(price="0.48", size="5"),),
            asks=(SimpleNamespace(price="0.50", size="4"),),
            min_order_size="1",
            tick_size="0.01",
            neg_risk=False,
            hash="hash",
        )
    )
    adapter = PolymarketPublicAdapter(client_factory=lambda: FakeClientContext(client))

    book = await adapter.get_order_book("token")

    assert client.order_book_token_id == "token"
    assert book.tick_size == Decimal("0.01")
    assert book.best_ask is not None and book.best_ask.price == Decimal("0.50")


@pytest.mark.asyncio
async def test_polymarket_errors_are_wrapped() -> None:
    class FailingClient:
        def list_markets(self, **kwargs: Any) -> FakePaginator:
            raise PolymarketError("rate limited")

    adapter = PolymarketPublicAdapter(client_factory=lambda: FakeClientContext(FailingClient()))

    with pytest.raises(PolymarketPublicAdapterError):
        await adapter.list_active_markets()


@pytest.mark.asyncio
async def test_public_read_retries_transient_failure_but_not_auth_failure() -> None:
    class IntermittentClient:
        calls = 0

        def list_markets(self, **kwargs: Any) -> FakePaginator:
            del kwargs
            self.calls += 1
            if self.calls == 1:
                raise TransportError("connection reset")
            return FakePaginator((make_market(),))

    client = IntermittentClient()
    adapter = PolymarketPublicAdapter(
        client_factory=lambda: FakeClientContext(client),
        read_retry_policy=ReadRetryPolicy(max_attempts=2, backoff_seconds=0),
    )

    assert len(await adapter.list_active_markets()) == 1
    assert client.calls == 2

    class RejectedClient:
        calls = 0

        def list_markets(self, **kwargs: Any) -> FakePaginator:
            del kwargs
            self.calls += 1
            raise RequestRejectedError("unauthorized", status=401)

    rejected = RejectedClient()
    rejected_adapter = PolymarketPublicAdapter(
        client_factory=lambda: FakeClientContext(rejected),
        read_retry_policy=ReadRetryPolicy(max_attempts=3, backoff_seconds=0),
    )

    with pytest.raises(PolymarketPublicAdapterError) as raised:
        await rejected_adapter.list_active_markets()

    assert rejected.calls == 1
    assert raised.value.diagnostic is not None
    assert raised.value.diagnostic.category.value == "AUTHENTICATION_FAILURE"
