from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol, TypeVar

from polysia.domain.events import MarketDataEvent
from polysia.domain.market import MarketDetails, MarketSummary, VenueCapabilityProfile
from polysia.domain.orders import ApprovedOrderIntent, ExternalOrderReference

T_contra = TypeVar("T_contra", contravariant=True)


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class MarketCatalogPort(Protocol):
    async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]: ...

    async def get_market_by_slug(self, slug: str) -> MarketDetails: ...

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]: ...


class MarketDataProviderPort(Protocol):
    def events(self) -> AsyncIterator[MarketDataEvent]: ...


class ExecutionVenuePort(Protocol):
    @property
    def capabilities(self) -> VenueCapabilityProfile: ...

    async def submit(self, intent: ApprovedOrderIntent) -> ExternalOrderReference: ...

    async def cancel(self, reference: ExternalOrderReference) -> None: ...


class AccountReadPort(Protocol):
    async def get_open_orders(self, **filters: str | None) -> list[Any]: ...

    async def list_positions(self) -> list[Any]: ...


class RepositoryPort(Protocol[T_contra]):
    def add(self, item: T_contra) -> Any: ...


class EventBusPort(Protocol):
    async def publish(self, event: MarketDataEvent) -> None: ...


class EmergencyControlPort(Protocol):
    def activate(self, reason: str) -> None: ...

    def deactivate(self) -> None: ...

    def is_active(self) -> bool: ...
