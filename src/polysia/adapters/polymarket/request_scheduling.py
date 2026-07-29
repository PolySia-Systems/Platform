from __future__ import annotations

import asyncio
import bisect
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from polysia.application.ports.copytrading import LeaderReadPurpose

MAX_TRADES_ATTEMPTS_PER_10_SECONDS = 100
DISCOVERY_BUDGET_PER_10_SECONDS = 80
RESERVED_TRADES_BUDGET_PER_10_SECONDS = 20
MAX_TRADES_IN_FLIGHT = 4
TRADES_WINDOW_SECONDS = 10.0
DISCOVERY_SPACING_SECONDS = 0.125
POSITIONS_SPACING_SECONDS = 0.1
RETRY_AFTER_MIN_SECONDS = 1
RETRY_AFTER_MAX_SECONDS = 60
FALLBACK_BACKOFF_SECONDS = (1, 2, 4, 8, 16, 30)

MonotonicClock = Callable[[], float]
WallClock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
Jitter = Callable[[int], float]


class TradesSourceUnavailableError(RuntimeError):
    """Safe, shared `/trades` outage signal without request or response content."""

    def __init__(
        self,
        *,
        outage_started_at: datetime,
        retry_at: datetime,
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.outage_started_at = outage_started_at
        self.retry_at = retry_at


@dataclass(slots=True)
class _RouteState:
    limit: int
    window_seconds: float
    minimum_spacing_seconds: float
    maximum_in_flight: int
    request_times: list[float] = field(default_factory=list)
    discovery_times: list[float] = field(default_factory=list)
    next_start_at: float = 0.0
    next_discovery_at: float = 0.0
    next_priority_at: float = 0.0
    attempts: int = 0
    retries: int = 0
    probes: int = 0
    current_in_flight: int = 0
    maximum_observed_in_flight: int = 0
    total_scheduling_delay_seconds: float = 0.0
    maximum_scheduling_delay_seconds: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    semaphore: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.semaphore = asyncio.Semaphore(self.maximum_in_flight)


class EndpointRequestScheduler:
    """Route-isolated pacing and one shared `/trades` cooldown circuit."""

    def __init__(
        self,
        *,
        monotonic_clock: MonotonicClock = time.monotonic,
        wall_clock: WallClock = lambda: datetime.now(UTC),
        sleeper: Sleeper = asyncio.sleep,
        jitter: Jitter | None = None,
    ) -> None:
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._sleeper = sleeper
        self._jitter = jitter or _deterministic_jitter
        self._routes = {
            "trades": _RouteState(
                limit=MAX_TRADES_ATTEMPTS_PER_10_SECONDS,
                window_seconds=TRADES_WINDOW_SECONDS,
                minimum_spacing_seconds=0.0,
                maximum_in_flight=MAX_TRADES_IN_FLIGHT,
            ),
            "positions": _RouteState(
                limit=100,
                window_seconds=TRADES_WINDOW_SECONDS,
                minimum_spacing_seconds=POSITIONS_SPACING_SECONDS,
                maximum_in_flight=4,
            ),
            "gamma": _RouteState(
                limit=100,
                window_seconds=TRADES_WINDOW_SECONDS,
                minimum_spacing_seconds=0.02,
                maximum_in_flight=5,
            ),
            "other": _RouteState(
                limit=100,
                window_seconds=TRADES_WINDOW_SECONDS,
                minimum_spacing_seconds=0.05,
                maximum_in_flight=4,
            ),
        }
        self._circuit_lock = asyncio.Lock()
        self._outage_started_at: datetime | None = None
        self._retry_at: datetime | None = None
        self._probe_in_flight = False
        self._fallback_index = 0
        self._rate_limits = 0
        self._cooldowns = 0
        self._recoveries = 0
        self._retry_after_source = "none"

    @asynccontextmanager
    async def request(
        self,
        route: str,
        *,
        purpose: LeaderReadPurpose,
        retry: bool = False,
    ) -> AsyncIterator[None]:
        route_name = _route_name(route)
        state = self._routes[route_name]
        await self._assert_circuit_allows(purpose, claim_probe=False)
        delay = await self._reserve_slot(
            route_name,
            state,
            purpose=purpose,
        )
        await self._sleeper(delay)
        await state.semaphore.acquire()
        try:
            await self._assert_circuit_allows(purpose, claim_probe=True)
        except Exception:
            state.semaphore.release()
            raise
        async with state.lock:
            state.attempts += 1
            state.retries += int(retry)
            state.probes += int(purpose is LeaderReadPurpose.RECOVERY)
            state.current_in_flight += 1
            state.maximum_observed_in_flight = max(
                state.maximum_observed_in_flight,
                state.current_in_flight,
            )
        try:
            yield
        finally:
            async with state.lock:
                state.current_in_flight -= 1
            state.semaphore.release()

    async def record_rate_limit(self, retry_after: str | None) -> None:
        now = _aware(self._wall_clock())
        delay = parse_retry_after(retry_after, now=now)
        source = "header"
        async with self._circuit_lock:
            self._rate_limits += 1
            if self._outage_started_at is not None and not self._probe_in_flight:
                return
            if delay is None:
                source = "fallback"
                delay = self._next_fallback_delay()
            if self._outage_started_at is None:
                self._outage_started_at = now
            self._retry_at = now + timedelta(seconds=delay)
            self._probe_in_flight = False
            self._retry_after_source = source
            self._cooldowns += 1

    async def record_trades_failure(self) -> None:
        now = _aware(self._wall_clock())
        async with self._circuit_lock:
            if self._outage_started_at is not None and not self._probe_in_flight:
                return
            delay = self._next_fallback_delay()
            if self._outage_started_at is None:
                self._outage_started_at = now
            self._retry_at = now + timedelta(seconds=delay)
            self._probe_in_flight = False
            self._retry_after_source = "fallback"
            self._cooldowns += 1

    async def unavailable_error(self, *, reason: str) -> TradesSourceUnavailableError:
        async with self._circuit_lock:
            if self._outage_started_at is None or self._retry_at is None:
                raise RuntimeError("trades circuit is not open")
            return TradesSourceUnavailableError(
                outage_started_at=self._outage_started_at,
                retry_at=self._retry_at,
                reason=reason,
            )

    async def restore_circuit(
        self,
        *,
        outage_started_at: datetime,
        retry_at: datetime,
        cooldown_attempt: int,
    ) -> None:
        if cooldown_attempt < 1:
            raise ValueError("cooldown_attempt must be positive")
        async with self._circuit_lock:
            self._outage_started_at = _aware(outage_started_at)
            self._retry_at = _aware(retry_at)
            self._probe_in_flight = False
            self._fallback_index = min(
                cooldown_attempt,
                len(FALLBACK_BACKOFF_SECONDS) - 1,
            )
            self._retry_after_source = "durable"

    async def record_success(
        self,
        route: str,
        *,
        purpose: LeaderReadPurpose,
    ) -> None:
        if _route_name(route) != "trades" or purpose is not LeaderReadPurpose.RECOVERY:
            return
        async with self._circuit_lock:
            if self._outage_started_at is not None:
                self._recoveries += 1
            self._outage_started_at = None
            self._retry_at = None
            self._probe_in_flight = False
            self._fallback_index = 0
            self._retry_after_source = "none"

    def circuit_snapshot(self) -> dict[str, object]:
        return {
            "open": self._outage_started_at is not None,
            "outage_started_at": (
                None if self._outage_started_at is None else self._outage_started_at.isoformat()
            ),
            "retry_at": None if self._retry_at is None else self._retry_at.isoformat(),
            "retry_after_source": self._retry_after_source,
            "single_probe_in_flight": self._probe_in_flight,
        }

    def telemetry_snapshot(self) -> dict[str, object]:
        now = self._monotonic_clock()
        routes: dict[str, object] = {}
        for name, state in self._routes.items():
            rolling = sum(
                timestamp > now - state.window_seconds
                for timestamp in state.request_times
                if timestamp <= now
            )
            discovery_rolling = sum(
                timestamp > now - state.window_seconds
                for timestamp in state.discovery_times
                if timestamp <= now
            )
            routes[name] = {
                "attempts": state.attempts,
                "current_rolling_attempts": rolling,
                "current_rolling_discovery_attempts": discovery_rolling,
                "maximum_in_flight": state.maximum_observed_in_flight,
                "probes": state.probes,
                "retries": state.retries,
                "scheduling_delay_seconds": round(
                    state.total_scheduling_delay_seconds,
                    6,
                ),
                "maximum_scheduling_delay_seconds": round(
                    state.maximum_scheduling_delay_seconds,
                    6,
                ),
            }
        return {
            "budgets": {
                "discovery_attempts_per_10_seconds": (DISCOVERY_BUDGET_PER_10_SECONDS),
                "maximum_trades_attempts_per_10_seconds": (MAX_TRADES_ATTEMPTS_PER_10_SECONDS),
                "maximum_trades_in_flight": MAX_TRADES_IN_FLIGHT,
                "reserved_trades_attempts_per_10_seconds": (RESERVED_TRADES_BUDGET_PER_10_SECONDS),
            },
            "circuit": self.circuit_snapshot(),
            "cooldowns": self._cooldowns,
            "rate_limits": self._rate_limits,
            "recoveries": self._recoveries,
            "routes": routes,
        }

    async def _reserve_slot(
        self,
        route_name: str,
        state: _RouteState,
        *,
        purpose: LeaderReadPurpose,
    ) -> float:
        async with state.lock:
            now = self._monotonic_clock()
            cutoff = now - state.window_seconds
            while state.request_times and state.request_times[0] <= cutoff:
                state.request_times.pop(0)
            while state.discovery_times and state.discovery_times[0] <= cutoff:
                state.discovery_times.pop(0)
            slot = now
            if len(state.request_times) >= state.limit:
                slot = max(slot, state.request_times[0] + state.window_seconds)
            if purpose is LeaderReadPurpose.DISCOVERY:
                slot = max(slot, state.next_discovery_at)
                if len(state.discovery_times) >= DISCOVERY_BUDGET_PER_10_SECONDS:
                    slot = max(
                        slot,
                        state.discovery_times[0] + state.window_seconds,
                    )
                state.next_discovery_at = slot + DISCOVERY_SPACING_SECONDS
                bisect.insort(state.discovery_times, slot)
            elif route_name == "trades":
                slot = max(slot, state.next_priority_at)
                state.next_priority_at = slot + (
                    TRADES_WINDOW_SECONDS / RESERVED_TRADES_BUDGET_PER_10_SECONDS
                )
            else:
                slot = max(slot, state.next_start_at)
                state.next_start_at = slot + state.minimum_spacing_seconds
            bisect.insort(state.request_times, slot)
            delay = max(0.0, slot - now)
            state.total_scheduling_delay_seconds += delay
            state.maximum_scheduling_delay_seconds = max(
                state.maximum_scheduling_delay_seconds,
                delay,
            )
            return delay

    async def _assert_circuit_allows(
        self,
        purpose: LeaderReadPurpose,
        *,
        claim_probe: bool,
    ) -> None:
        async with self._circuit_lock:
            if self._outage_started_at is None:
                return
            assert self._retry_at is not None
            now = _aware(self._wall_clock())
            allowed_probe = (
                purpose is LeaderReadPurpose.RECOVERY
                and now >= self._retry_at
                and not self._probe_in_flight
            )
            if not allowed_probe:
                raise TradesSourceUnavailableError(
                    outage_started_at=self._outage_started_at,
                    retry_at=self._retry_at,
                    reason="Public /trades source is in shared cooldown.",
                )
            if claim_probe:
                self._probe_in_flight = True

    def _next_fallback_delay(self) -> int:
        index = min(self._fallback_index, len(FALLBACK_BACKOFF_SECONDS) - 1)
        base = FALLBACK_BACKOFF_SECONDS[index]
        attempt = index + 1
        fraction = self._jitter(attempt)
        if not 0 <= fraction <= 0.1:
            raise ValueError("injected jitter must be within [0, 0.1]")
        self._fallback_index = min(
            self._fallback_index + 1,
            len(FALLBACK_BACKOFF_SECONDS) - 1,
        )
        return max(1, math.ceil(base * (1 + fraction)))


def parse_retry_after(value: str | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = int(text)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        seconds = math.ceil((parsed.astimezone(UTC) - _aware(now)).total_seconds())
    return max(RETRY_AFTER_MIN_SECONDS, min(RETRY_AFTER_MAX_SECONDS, seconds))


def _route_name(route: str) -> str:
    if route.endswith("/trades"):
        return "trades"
    if route.endswith("/positions"):
        return "positions"
    if route.startswith("gamma:"):
        return "gamma"
    return "other"


def _deterministic_jitter(attempt: int) -> float:
    return ((attempt * 7) % 11) / 100


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("scheduler wall clock must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "DISCOVERY_BUDGET_PER_10_SECONDS",
    "EndpointRequestScheduler",
    "FALLBACK_BACKOFF_SECONDS",
    "MAX_TRADES_ATTEMPTS_PER_10_SECONDS",
    "MAX_TRADES_IN_FLIGHT",
    "RESERVED_TRADES_BUDGET_PER_10_SECONDS",
    "TradesSourceUnavailableError",
    "parse_retry_after",
]
