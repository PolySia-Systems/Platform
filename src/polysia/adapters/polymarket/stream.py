from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from polymarket import AsyncPublicClient, PolymarketError
from polymarket.streams import MarketSpec
from pydantic import BaseModel

from polysia.bus.events import MarketDataEvent
from polysia.bus.in_memory_bus import InMemoryEventBus
from polysia.config.logging import get_logger

ClientFactory = Callable[[], AbstractAsyncContextManager[Any]]
Sleep = Callable[[float], Awaitable[None]]


class MarketStreamError(RuntimeError):
    """Base market stream ingestion error."""


class MarketStreamDisconnected(MarketStreamError):
    """Raised when the upstream stream ends before ingestion is stopped."""


class StaleStreamError(MarketStreamError):
    """Raised when no stream event arrives before the stale timeout."""


@dataclass(frozen=True, slots=True)
class MarketStreamConfig:
    """Runtime controls for one market stream subscription."""

    token_ids: tuple[str, ...]
    custom_feature_enabled: bool = True
    stale_after: timedelta = timedelta(seconds=30)
    initial_backoff: float = 1.0
    max_backoff: float = 30.0
    max_reconnects: int | None = None

    def __post_init__(self) -> None:
        if not self.token_ids:
            raise ValueError("token_ids must not be empty")
        for token_id in self.token_ids:
            if not token_id:
                raise ValueError("token_ids must not contain empty values")
        if self.stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be positive")
        if self.initial_backoff <= 0:
            raise ValueError("initial_backoff must be positive")
        if self.max_backoff < self.initial_backoff:
            raise ValueError("max_backoff must be greater than or equal to initial_backoff")
        if self.max_reconnects is not None and self.max_reconnects < 0:
            raise ValueError("max_reconnects must be non-negative")


def _default_client_factory() -> AbstractAsyncContextManager[Any]:
    return cast(AbstractAsyncContextManager[Any], AsyncPublicClient())


def normalize_market_event(
    sdk_event: Any,
    *,
    received_at: datetime | None = None,
) -> list[MarketDataEvent]:
    """Normalize one SDK market event into one or more internal events."""
    received = received_at or datetime.now(UTC)
    event_type = str(getattr(sdk_event, "type", type(sdk_event).__name__))
    raw_payload = _model_dump(sdk_event)
    payload = getattr(sdk_event, "payload", sdk_event)
    exchange_ts = _timestamp_from(payload)

    if event_type == "price_change":
        return [
            MarketDataEvent(
                source="polymarket",
                event_type=event_type,
                token_id=str(change.token_id),
                received_at=received,
                exchange_ts=exchange_ts,
                payload={
                    "market": _optional_str(getattr(payload, "market", None)),
                    "price_change": _model_dump(change),
                    "timestamp": _jsonable_timestamp(exchange_ts),
                },
                raw_payload=raw_payload,
            )
            for change in getattr(payload, "price_changes", ())
        ]

    return [
        MarketDataEvent(
            source="polymarket",
            event_type=event_type,
            token_id=_extract_token_id(payload),
            received_at=received,
            exchange_ts=exchange_ts,
            payload=_model_dump(payload),
            raw_payload=raw_payload,
        )
    ]


class MarketStream:
    """Subscribe to Polymarket market streams and publish normalized events."""

    def __init__(
        self,
        *,
        bus: InMemoryEventBus,
        config: MarketStreamConfig,
        client_factory: ClientFactory | None = None,
        logger: Any | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._bus = bus
        self._config = config
        self._client_factory = client_factory or _default_client_factory
        self._logger = logger or get_logger(__name__)
        self._sleep = sleep
        self.event_count = 0
        self.error_count = 0

    async def run(self, *, max_events: int | None = None) -> None:
        """Run ingestion until cancelled or until max_events have been published."""
        reconnect_count = 0

        while max_events is None or self.event_count < max_events:
            try:
                emitted = await self._run_once(max_events=max_events)
                if max_events is not None and self.event_count >= max_events:
                    return
                if emitted == 0:
                    raise MarketStreamDisconnected("stream ended without events")
                raise MarketStreamDisconnected("stream ended")
            except asyncio.CancelledError:
                self._logger.info(
                    "market_stream_cancelled",
                    event_count=self.event_count,
                    error_count=self.error_count,
                )
                raise
            except (MarketStreamError, PolymarketError, OSError) as error:
                self.error_count += 1
                if (
                    self._config.max_reconnects is not None
                    and reconnect_count >= self._config.max_reconnects
                ):
                    self._logger.error(
                        "market_stream_reconnect_exhausted",
                        error=str(error),
                        error_count=self.error_count,
                        event_count=self.event_count,
                        reconnect_count=reconnect_count,
                    )
                    if isinstance(error, MarketStreamError):
                        raise
                    raise MarketStreamError(
                        "Polymarket market stream failed after reconnect attempts."
                    ) from error

                delay = self._next_backoff(reconnect_count)
                reconnect_count += 1
                self._logger.warning(
                    "market_stream_reconnect",
                    delay_seconds=delay,
                    error=str(error),
                    error_count=self.error_count,
                    event_count=self.event_count,
                    reconnect_count=reconnect_count,
                )
                await self._sleep(delay)

    async def _run_once(self, *, max_events: int | None) -> int:
        emitted = 0
        self._logger.info(
            "market_stream_connect",
            custom_feature_enabled=self._config.custom_feature_enabled,
            token_count=len(self._config.token_ids),
        )
        async with self._client_factory() as client:
            stream = await client.subscribe(
                MarketSpec(
                    token_ids=self._config.token_ids,
                    custom_feature_enabled=self._config.custom_feature_enabled,
                )
            )
            self._logger.info(
                "market_stream_connected",
                custom_feature_enabled=self._config.custom_feature_enabled,
                token_count=len(self._config.token_ids),
            )
            async with stream:
                async for sdk_event in self._iter_stream(stream):
                    for event in normalize_market_event(sdk_event):
                        await self._bus.publish(event)
                        emitted += 1
                        self.event_count += 1
                        self._logger.debug(
                            "market_stream_event",
                            event_count=self.event_count,
                            event_type=event.event_type,
                            token_id=event.token_id,
                        )
                        if max_events is not None and self.event_count >= max_events:
                            self._logger.info(
                                "market_stream_max_events_reached",
                                event_count=self.event_count,
                            )
                            return emitted
        self._logger.warning(
            "market_stream_disconnected",
            emitted=emitted,
            event_count=self.event_count,
        )
        return emitted

    async def _iter_stream(self, stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        iterator = stream.__aiter__()
        timeout_seconds = self._config.stale_after.total_seconds()

        while True:
            try:
                yield await asyncio.wait_for(anext(iterator), timeout=timeout_seconds)
            except StopAsyncIteration:
                return
            except TimeoutError as error:
                raise StaleStreamError(
                    f"no market stream events received for {timeout_seconds:g} seconds"
                ) from error

    def _next_backoff(self, reconnect_count: int) -> float:
        return min(
            self._config.initial_backoff * (2**reconnect_count),
            self._config.max_backoff,
        )


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {"repr": repr(value)}


def _timestamp_from(payload: Any) -> datetime | None:
    timestamp = getattr(payload, "timestamp", None)
    return timestamp if isinstance(timestamp, datetime) else None


def _jsonable_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _extract_token_id(payload: Any) -> str:
    for attribute in ("token_id", "winning_token_id"):
        token_id = _optional_str(getattr(payload, attribute, None))
        if token_id is not None:
            return token_id

    for attribute in ("token_ids", "clob_token_ids"):
        token_ids = getattr(payload, attribute, None)
        if token_ids:
            return str(token_ids[0])

    market = _optional_str(getattr(payload, "market", None))
    if market is not None:
        return f"market:{market}"
    return "unknown"
