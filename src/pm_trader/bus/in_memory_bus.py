from __future__ import annotations

import asyncio
from contextlib import suppress
from types import TracebackType
from typing import Self

from pm_trader.bus.events import MarketDataEvent


class _ClosedSentinel:
    __slots__ = ()


_CLOSED = _ClosedSentinel()


class EventSubscription:
    """Async iterator for events published after subscription."""

    def __init__(self, bus: InMemoryEventBus, *, max_queue_size: int) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        self._bus = bus
        self._queue: asyncio.Queue[MarketDataEvent | _ClosedSentinel] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._closed = False
        self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    def _push(self, event: MarketDataEvent) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            self._dropped += 1

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._unsubscribe(self)
        try:
            self._queue.put_nowait(_CLOSED)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self._queue.put_nowait(_CLOSED)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> MarketDataEvent:
        item = await self._queue.get()
        if isinstance(item, _ClosedSentinel):
            raise StopAsyncIteration
        return item

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()


class InMemoryEventBus:
    """Small async pub/sub bus for one-process pipelines."""

    def __init__(self) -> None:
        self._subscriptions: set[EventSubscription] = set()

    def subscribe(self, *, max_queue_size: int = 1000) -> EventSubscription:
        subscription = EventSubscription(self, max_queue_size=max_queue_size)
        self._subscriptions.add(subscription)
        return subscription

    async def publish(self, event: MarketDataEvent) -> None:
        for subscription in tuple(self._subscriptions):
            subscription._push(event)

    async def close(self) -> None:
        for subscription in tuple(self._subscriptions):
            await subscription.close()

    def _unsubscribe(self, subscription: EventSubscription) -> None:
        self._subscriptions.discard(subscription)
