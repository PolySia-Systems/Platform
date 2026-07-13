from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from polysia.adapters.polymarket.geoblock import PreLiveOrderGeoblockCheck
from polysia.monitoring.live_round_trip import LifecycleHealthSnapshot

SERVER_TIME_URL = "https://clob.polymarket.com/time"
Clock = Callable[[], datetime]
ClockDriftPreflightStatus = Literal["pass", "blocked"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class PolymarketServerTimeError(RuntimeError):
    """Raised when the official CLOB server-time response is unavailable or invalid."""


class ClockDriftReader(Protocol):
    async def read_clock_drift(self) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class ClockDriftPreflight:
    status: ClockDriftPreflightStatus
    drift_seconds: Decimal | None
    threshold_seconds: Decimal
    reason: str
    error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "drift_seconds": (None if self.drift_seconds is None else str(self.drift_seconds)),
            "error_type": self.error_type,
            "reason": self.reason,
            "status": self.status,
            "threshold_seconds": str(self.threshold_seconds),
        }


async def evaluate_clock_drift(
    reader: ClockDriftReader,
    *,
    threshold_seconds: Decimal,
) -> ClockDriftPreflight:
    if threshold_seconds <= 0 or threshold_seconds > Decimal("5"):
        raise ValueError("clock drift threshold must be within (0, 5]")
    try:
        drift = await reader.read_clock_drift()
    except PolymarketServerTimeError as error:
        return ClockDriftPreflight(
            status="blocked",
            drift_seconds=None,
            threshold_seconds=threshold_seconds,
            reason="official CLOB server time is unavailable",
            error_type=type(error.__cause__ or error).__name__,
        )
    if not drift.is_finite():
        return ClockDriftPreflight(
            status="blocked",
            drift_seconds=None,
            threshold_seconds=threshold_seconds,
            reason="official CLOB server time is invalid",
            error_type="InvalidServerTime",
        )
    if abs(drift) > threshold_seconds:
        return ClockDriftPreflight(
            status="blocked",
            drift_seconds=drift,
            threshold_seconds=threshold_seconds,
            reason="local clock drift exceeds the approved threshold",
        )
    return ClockDriftPreflight(
        status="pass",
        drift_seconds=drift,
        threshold_seconds=threshold_seconds,
        reason="local clock drift is within the approved threshold",
    )


class PolymarketServerTimeReader:
    """Read official CLOB server time and calculate midpoint-adjusted local drift."""

    def __init__(
        self,
        *,
        url: str = SERVER_TIME_URL,
        timeout_seconds: float = 5.0,
        max_attempts: int = 2,
        backoff_seconds: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Clock = utc_now,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("server-time max_attempts must be within [1, 3]")
        if not 0 <= backoff_seconds <= 2:
            raise ValueError("server-time backoff_seconds must be within [0, 2]")
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleeper = sleeper
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
        payload: str | None = None
        last_error: BaseException | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    payload = response.read().decode("utf-8").strip()
                break
            except HTTPError as error:
                last_error = error
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt >= self._max_attempts:
                    break
            except (URLError, OSError, TimeoutError) as error:
                last_error = error
                if attempt >= self._max_attempts:
                    break
            self._sleeper(self._backoff_seconds * attempt)
        if payload is None:
            raise PolymarketServerTimeError("CLOB server time is unavailable") from last_error
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
    "ClockDriftPreflight",
    "ClockDriftReader",
    "PolymarketLifecycleHealthReader",
    "PolymarketServerTimeError",
    "PolymarketServerTimeReader",
    "SERVER_TIME_URL",
    "evaluate_clock_drift",
]
