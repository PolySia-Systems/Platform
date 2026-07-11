from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

from polymarket import AsyncPublicClient, PolymarketError

from polysia.adapters.polymarket.capabilities import POLYMARKET_CAPABILITIES
from polysia.adapters.polymarket.mappers import PolymarketMarketMapper
from polysia.config.logging import get_logger
from polysia.domain.market import MarketDetails, MarketSummary, VenueCapabilityProfile

ClientFactory = Callable[[], AbstractAsyncContextManager[Any]]


class PolymarketPublicAdapterError(RuntimeError):
    """Raised when a public Polymarket read fails."""


def _default_client_factory() -> AbstractAsyncContextManager[Any]:
    return cast(AbstractAsyncContextManager[Any], AsyncPublicClient())


class PolymarketPublicAdapter:
    """Public read adapter around the official Polymarket Python SDK."""

    def __init__(
        self,
        client_factory: ClientFactory | None = None,
        mapper: PolymarketMarketMapper | None = None,
        logger: Any | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._mapper = mapper or PolymarketMarketMapper()
        self._logger = logger or get_logger(__name__)

    @property
    def capabilities(self) -> VenueCapabilityProfile:
        return POLYMARKET_CAPABILITIES

    async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]:
        """Return one page of active markets without requiring credentials."""
        try:
            async with self._client_factory() as client:
                paginator = client.list_markets(closed=False, include_tag=True, page_size=page_size)
                page = await paginator.first_page()
                return [self._mapper.to_summary(market) for market in page.items]
        except PolymarketError as error:
            self._log_sdk_error("list_active_markets", error)
            raise PolymarketPublicAdapterError(
                "Could not list active Polymarket markets."
            ) from error

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        """Fetch one market by slug and normalize it to internal fields."""
        try:
            async with self._client_factory() as client:
                market = await client.get_market(slug=slug, include_tag=True)
                return self._mapper.to_details(market)
        except PolymarketError as error:
            self._log_sdk_error("get_market_by_slug", error, slug=slug)
            raise PolymarketPublicAdapterError(
                f"Could not fetch Polymarket market: {slug}"
            ) from error

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
        """Search active events and return their normalized markets."""
        try:
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
        except PolymarketError as error:
            self._log_sdk_error("search_markets", error, query=query)
            raise PolymarketPublicAdapterError("Could not search Polymarket markets.") from error

    def _log_sdk_error(self, operation: str, error: PolymarketError, **context: str) -> None:
        self._logger.warning(
            "polymarket_public_sdk_error",
            operation=operation,
            error=str(error),
            **context,
        )

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
