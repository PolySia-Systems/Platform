from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from polysia.adapters.polymarket.geoblock import PreLiveOrderGeoblockCheck
from polysia.monitoring.live_round_trip import LifecycleHealthSnapshot

SERVER_TIME_URL = "https://clob.polymarket.com/time"
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class PolymarketServerTimeError(RuntimeError):
    """Raised when the official CLOB server-time response is unavailable or invalid."""


class PolymarketServerTimeReader:
    """Read official CLOB server time and calculate midpoint-adjusted local drift."""

    def __init__(
        self,
        *,
        url: str = SERVER_TIME_URL,
        timeout_seconds: float = 5.0,
        clock: Clock = utc_now,
    ) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._clock = clock

    async def read_clock_drift(self) -> Decimal:
        return await asyncio.to_thread(self.read_clock_drift_sync)

    def read_clock_drift_sync(self) -> Decimal:
        started_at = _as_utc(self._clock())
        request = Request(
            self._url,
            headers={"Accept": "application/json", "User-Agent": "polysia-clock/1.0"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read().decode("utf-8").strip()
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            raise PolymarketServerTimeError("CLOB server time is unavailable") from error
        finished_at = _as_utc(self._clock())
        try:
            server_timestamp = Decimal(payload)
        except InvalidOperation as error:
            raise PolymarketServerTimeError("CLOB server time is invalid") from error
        midpoint = started_at + ((finished_at - started_at) / 2)
        local_timestamp = Decimal(str(midpoint.timestamp()))
        return server_timestamp - local_timestamp


class PolymarketLifecycleHealthReader:
    """Read public clock and geoblock health for lifecycle monitoring."""

    def __init__(
        self,
        *,
        server_time_reader: PolymarketServerTimeReader | None = None,
        geoblock_check: PreLiveOrderGeoblockCheck | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._server_time_reader = server_time_reader or PolymarketServerTimeReader()
        self._geoblock_check = geoblock_check or PreLiveOrderGeoblockCheck()
        self._clock = clock

    async def read_health(self) -> LifecycleHealthSnapshot:
        error_types: list[str] = []
        drift: Decimal | None = None
        try:
            drift = await self._server_time_reader.read_clock_drift()
        except PolymarketServerTimeError as error:
            error_types.append(type(error.__cause__ or error).__name__)

        geoblock = await self._geoblock_check.check()
        if geoblock.status in {"error", "not_checked"}:
            error_types.append(geoblock.error_type or "GeoblockUnavailable")
        return LifecycleHealthSnapshot(
            checked_at=_as_utc(self._clock()),
            server_time_readable=drift is not None,
            clock_drift_seconds=drift,
            geoblock_status=geoblock.status,
            geoblocked=geoblock.blocked,
            error_types=tuple(dict.fromkeys(error_types)),
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "PolymarketLifecycleHealthReader",
    "PolymarketServerTimeError",
    "PolymarketServerTimeReader",
    "SERVER_TIME_URL",
]
