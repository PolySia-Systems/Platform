from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from polymarket.models.clob.market_events import parse_market_event

from polysia.bus.in_memory_bus import InMemoryEventBus
from polysia.streams.market_stream import (
    MarketStream,
    MarketStreamConfig,
    StaleStreamError,
    normalize_market_event,
)


class FakeStream:
    def __init__(self, events: list[Any], *, error: BaseException | None = None) -> None:
        self._events = events
        self._error = error

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> FakeStream:
        return self

    async def __anext__(self) -> Any:
        if self._events:
            return self._events.pop(0)
        if self._error is not None:
            raise self._error
        raise StopAsyncIteration


class NeverEventStream:
    async def __aenter__(self) -> NeverEventStream:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> NeverEventStream:
        return self

    async def __anext__(self) -> Any:
        await asyncio.sleep(60)
        raise StopAsyncIteration


class FakeClientContext:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def __aenter__(self) -> Any:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeClient:
    def __init__(self, streams: list[Any]) -> None:
        self._streams = streams
        self.subscribe_calls: list[Any] = []

    async def subscribe(self, spec: Any) -> Any:
        self.subscribe_calls.append(spec)
        return self._streams.pop(0)


def raw_book_event(token_id: str = "token-1") -> dict[str, Any]:
    return {
        "event_type": "book",
        "market": "market-1",
        "asset_id": token_id,
        "bids": [],
        "asks": [],
        "timestamp": "1710000000000",
    }


def raw_price_change_event() -> dict[str, Any]:
    return {
        "event_type": "price_change",
        "market": "market-1",
        "price_changes": [
            {
                "asset_id": "token-1",
                "price": "0.40",
                "size": "10",
                "side": "BUY",
            },
            {
                "asset_id": "token-2",
                "price": "0.60",
                "size": "5",
                "side": "SELL",
            },
        ],
        "timestamp": "1710000000000",
    }


def test_book_event_normalization_preserves_timestamps_and_raw_payload() -> None:
    sdk_event = parse_market_event(raw_book_event())
    received_at = datetime(2026, 1, 1, tzinfo=UTC)

    events = normalize_market_event(sdk_event, received_at=received_at)

    assert len(events) == 1
    event = events[0]
    assert event.source == "polymarket"
    assert event.event_type == "book"
    assert event.token_id == "token-1"
    assert event.received_at == received_at
    assert event.exchange_ts == datetime(2024, 3, 9, 16, 0, tzinfo=UTC)
    assert event.payload["market"] == "market-1"
    assert event.raw_payload["type"] == "book"


def test_price_change_event_normalizes_to_one_event_per_token() -> None:
    sdk_event = parse_market_event(raw_price_change_event())

    events = normalize_market_event(sdk_event)

    assert [event.token_id for event in events] == ["token-1", "token-2"]
    assert events[0].payload["price_change"]["price"] == "0.40"
    assert events[1].payload["price_change"]["side"] == "SELL"


@pytest.mark.asyncio
async def test_market_stream_publishes_normalized_events() -> None:
    sdk_event = parse_market_event(raw_book_event())
    client = FakeClient([FakeStream([sdk_event])])
    bus = InMemoryEventBus()
    stream = MarketStream(
        bus=bus,
        config=MarketStreamConfig(
            token_ids=("token-1",),
            stale_after=timedelta(seconds=1),
        ),
        client_factory=lambda: FakeClientContext(client),
    )

    async with bus.subscribe() as subscription:
        await stream.run(max_events=1)
        event = await asyncio.wait_for(anext(subscription), timeout=0.1)

    assert event.token_id == "token-1"
    assert client.subscribe_calls[0].token_ids == ("token-1",)


@pytest.mark.asyncio
async def test_market_stream_reconnects_after_disconnect() -> None:
    sdk_event = parse_market_event(raw_book_event())
    client = FakeClient([FakeStream([]), FakeStream([sdk_event])])
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    stream = MarketStream(
        bus=InMemoryEventBus(),
        config=MarketStreamConfig(
            token_ids=("token-1",),
            stale_after=timedelta(seconds=1),
            initial_backoff=0.25,
            max_backoff=1,
        ),
        client_factory=lambda: FakeClientContext(client),
        sleep=fake_sleep,
    )

    await stream.run(max_events=1)

    assert delays == [0.25]
    assert stream.error_count == 1
    assert stream.event_count == 1


@pytest.mark.asyncio
async def test_market_stream_raises_after_stale_timeout_when_reconnects_exhausted() -> None:
    client = FakeClient([NeverEventStream()])
    stream = MarketStream(
        bus=InMemoryEventBus(),
        config=MarketStreamConfig(
            token_ids=("token-1",),
            stale_after=timedelta(milliseconds=10),
            initial_backoff=0.01,
            max_backoff=0.01,
            max_reconnects=0,
        ),
        client_factory=lambda: FakeClientContext(client),
    )

    with pytest.raises(StaleStreamError):
        await stream.run()
