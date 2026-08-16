from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

from polymarket import AsyncPublicClient, PolymarketError

from polysia.adapters.polymarket.capabilities import POLYMARKET_CAPABILITIES
from polysia.adapters.polymarket.diagnostics import (
    PolymarketErrorDiagnostic,
    ReadRetryPolicy,
    classify_polymarket_error,
)
from polysia.adapters.polymarket.mappers import PolymarketMarketMapper
from polysia.config.structured_logging import get_logger
from polysia.domain.market import (
    MarketDetails,
    MarketOrderBookSnapshot,
    MarketSummary,
    VenueCapabilityProfile,
)

ClientFactory = Callable[[], AbstractAsyncContextManager[Any]]


class PolymarketPublicAdapterError(RuntimeError):
    """Raised when a public Polymarket read fails."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic: PolymarketErrorDiagnostic | None = None,
    ) -> None:
        self.diagnostic = diagnostic
        detail = f" [{diagnostic.safe_summary()}]" if diagnostic is not None else ""
        super().__init__(f"{message}{detail}")


def _default_client_factory() -> AbstractAsyncContextManager[Any]:
    return cast(AbstractAsyncContextManager[Any], AsyncPublicClient())


class PolymarketPublicAdapter:
    """Public read adapter around the official Polymarket Python SDK."""

    def __init__(
        self,
        client_factory: ClientFactory | None = None,
        mapper: PolymarketMarketMapper | None = None,
        read_retry_policy: ReadRetryPolicy | None = None,
        logger: Any | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._mapper = mapper or PolymarketMarketMapper()
        self._read_retry_policy = read_retry_policy or ReadRetryPolicy()
        self._logger = logger or get_logger(__name__)

    @property
    def capabilities(self) -> VenueCapabilityProfile:
        return POLYMARKET_CAPABILITIES

    async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]:
        """Return one page of active markets without requiring credentials."""

        async def read() -> list[MarketSummary]:
            async with self._client_factory() as client:
                paginator = client.list_markets(
                    closed=False,
                    include_tag=True,
                    page_size=page_size,
                )
                page = await paginator.first_page()
                return [self._mapper.to_summary(market) for market in page.items]

        try:
            return await self._read_retry_policy.run("list_active_markets", read)
        except PolymarketError as error:
            raise self._adapter_error(
                "list_active_markets",
                "Could not list active Polymarket markets.",
                error,
            ) from error

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        """Fetch one market by slug and normalize it to internal fields."""

        async def read() -> MarketDetails:
            async with self._client_factory() as client:
                market = await client.get_market(slug=slug, include_tag=True)
                return self._mapper.to_details(market)

        try:
            return await self._read_retry_policy.run("get_market_by_slug", read)
        except PolymarketError as error:
            raise self._adapter_error(
                "get_market_by_slug",
                f"Could not fetch Polymarket market: {slug}",
                error,
                slug=slug,
            ) from error

    async def get_market_by_id(self, market_id: str) -> MarketDetails:
        """Fetch one market by canonical condition/market id."""

        async def read() -> MarketDetails:
            async with self._client_factory() as client:
                market = await client.get_market(id=market_id, include_tag=True)
                return self._mapper.to_details(market)

        try:
            return await self._read_retry_policy.run("get_market_by_id", read)
        except PolymarketError as error:
            raise self._adapter_error(
                "get_market_by_id",
                "Could not fetch Polymarket market by id.",
                error,
            ) from error

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
        """Search active events and return their normalized markets."""

        async def read() -> list[MarketSummary]:
            async with self._client_factory() as client:
                paginator = client.search(
                    q=query,
                    events_status="active",
                    search_profiles=False,
                    search_tags=False,
                    page_size=page_size,
                )
                page = await paginator.first_page()
                return self._markets_from_search_results(page.items, limit=page_size)

        try:
            return await self._read_retry_policy.run("search_markets", read)
        except PolymarketError as error:
            raise self._adapter_error(
                "search_markets",
                "Could not search Polymarket markets.",
                error,
                query=query,
            ) from error

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        """Fetch and normalize one public CLOB order book."""

        async def read() -> MarketOrderBookSnapshot:
            async with self._client_factory() as client:
                book = await client.get_order_book(token_id=token_id)
                return self._mapper.to_order_book(book)

        try:
            return await self._read_retry_policy.run("get_order_book", read)
        except (PolymarketError, ValueError) as error:
            raise self._adapter_error(
                "get_order_book",
                "Could not fetch a valid Polymarket order book.",
                error,
                token_id=token_id,
            ) from error

    def _adapter_error(
        self,
        operation: str,
        message: str,
        error: BaseException,
        **context: str,
    ) -> PolymarketPublicAdapterError:
        diagnostic = classify_polymarket_error(operation, error)
        self._logger.warning(
            "polymarket_public_sdk_error",
            **diagnostic.to_dict(),
            **context,
        )
        return PolymarketPublicAdapterError(message, diagnostic=diagnostic)

    def _markets_from_search_results(
        self,
        search_results: Any,
        *,
        limit: int,
    ) -> list[MarketSummary]:
        markets: list[MarketSummary] = []
        seen_ids: set[str] = set()

        for result in search_results:
            for event in getattr(result, "events", ()):
                for market in getattr(event, "markets", ()):
                    summary = self._mapper.to_summary(market)
                    if summary.closed is True or summary.id in seen_ids:
                        continue
                    seen_ids.add(summary.id)
                    markets.append(summary)
                    if len(markets) >= limit:
                        return markets

        return markets
