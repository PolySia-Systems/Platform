from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

from polymarket import AsyncPublicClient, PolymarketError

from polysia.config.logging import get_logger
from polysia.domain.market import MarketDetails, MarketOutcomeSummary, MarketSummary

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
        logger: Any | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._logger = logger or get_logger(__name__)

    async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]:
        """Return one page of active markets without requiring credentials."""
        try:
            async with self._client_factory() as client:
                paginator = client.list_markets(closed=False, include_tag=True, page_size=page_size)
                page = await paginator.first_page()
                return [self._to_market_summary(market) for market in page.items]
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
                return self._to_market_details(market)
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
                    summary = self._to_market_summary(market)
                    if summary.closed is True or summary.id in seen_ids:
                        continue
                    seen_ids.add(summary.id)
                    markets.append(summary)
                    if len(markets) >= limit:
                        return markets

        return markets

    def _to_market_summary(self, market: Any) -> MarketSummary:
        state = getattr(market, "state", None)
        metrics = getattr(market, "metrics", None)
        prices = getattr(market, "prices", None)

        return MarketSummary(
            id=str(market.id),
            slug=self._optional_str(getattr(market, "slug", None)),
            question=self._optional_str(getattr(market, "question", None)),
            category=self._optional_str(getattr(market, "category", None)),
            active=getattr(state, "active", None),
            closed=getattr(state, "closed", None),
            accepting_orders=getattr(state, "accepting_orders", None),
            end_date=getattr(state, "end_date", None),
            liquidity=(
                getattr(metrics, "liquidity_num", None)
                or getattr(metrics, "liquidity", None)
            ),
            volume=getattr(metrics, "volume_num", None) or getattr(metrics, "volume", None),
            best_bid=getattr(prices, "best_bid", None),
            best_ask=getattr(prices, "best_ask", None),
            outcomes=self._to_outcome_summaries(market),
        )

    def _to_market_details(self, market: Any) -> MarketDetails:
        summary = self._to_market_summary(market)
        trading = getattr(market, "trading", None)

        return MarketDetails(
            **summary.model_dump(),
            condition_id=self._optional_str(getattr(market, "condition_id", None)),
            description=self._optional_str(getattr(market, "description", None)),
            image=self._optional_str(getattr(market, "image", None)),
            icon=self._optional_str(getattr(market, "icon", None)),
            minimum_order_size=getattr(trading, "minimum_order_size", None),
            minimum_tick_size=getattr(trading, "minimum_tick_size", None),
            tags=self._to_tag_labels(market),
        )

    def _to_outcome_summaries(self, market: Any) -> tuple[MarketOutcomeSummary, ...]:
        outcomes = getattr(market, "outcomes", None)
        normalized: list[MarketOutcomeSummary] = []

        for default_label, attribute_name in (("Yes", "yes"), ("No", "no")):
            outcome = getattr(outcomes, attribute_name, None)
            if outcome is None:
                continue
            normalized.append(
                MarketOutcomeSummary(
                    label=self._optional_str(getattr(outcome, "label", None)) or default_label,
                    token_id=self._optional_str(getattr(outcome, "token_id", None)),
                    price=getattr(outcome, "price", None),
                )
            )

        return tuple(normalized)

    def _to_tag_labels(self, market: Any) -> tuple[str, ...]:
        tags: list[str] = []
        for tag in getattr(market, "tags", ()):
            label = self._optional_str(getattr(tag, "label", None))
            slug = self._optional_str(getattr(tag, "slug", None))
            if label is not None:
                tags.append(label)
            elif slug is not None:
                tags.append(slug)
        return tuple(tags)

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text or None
