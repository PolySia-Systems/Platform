from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from pm_trader.bus.events import MarketDataEvent
from pm_trader.bus.in_memory_bus import InMemoryEventBus


def make_event(token_id: str = "token-1") -> MarketDataEvent:
    return MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id=token_id,
        received_at=datetime.now(UTC),
        exchange_ts=None,
        payload={"token_id": token_id},
        raw_payload={"type": "book"},
    )


@pytest.mark.asyncio
async def test_publish_delivers_event_to_subscriber() -> None:
    bus = InMemoryEventBus()

    async with bus.subscribe() as subscription:
        expected = make_event()
        await bus.publish(expected)

        received = await asyncio.wait_for(anext(subscription), timeout=0.1)

    assert received == expected


@pytest.mark.asyncio
async def test_subscription_drops_oldest_event_when_queue_is_full() -> None:
    bus = InMemoryEventBus()

    async with bus.subscribe(max_queue_size=1) as subscription:
        await bus.publish(make_event("old"))
        await bus.publish(make_event("new"))

        received = await asyncio.wait_for(anext(subscription), timeout=0.1)

    assert received.token_id == "new"
    assert subscription.dropped == 1
