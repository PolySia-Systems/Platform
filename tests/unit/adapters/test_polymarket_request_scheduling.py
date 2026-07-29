from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from polysia.adapters.polymarket.request_scheduling import (
    EndpointRequestScheduler,
    TradesSourceUnavailableError,
    parse_retry_after,
)
from polysia.application.ports.copytrading import LeaderReadPurpose


class RecordingClock:
    def __init__(self) -> None:
        self.monotonic = 0.0
        self.wall = datetime(2026, 7, 29, 12, tzinfo=UTC)
        self.delays: list[float] = []

    def monotonic_now(self) -> float:
        return self.monotonic

    def wall_now(self) -> datetime:
        return self.wall

    async def record_sleep(self, seconds: float) -> None:
        self.delays.append(seconds)

    def advance(self, seconds: float) -> None:
        self.monotonic += seconds
        self.wall += timedelta(seconds=seconds)


def _scheduler(clock: RecordingClock) -> EndpointRequestScheduler:
    return EndpointRequestScheduler(
        monotonic_clock=clock.monotonic_now,
        wall_clock=clock.wall_now,
        sleeper=clock.record_sleep,
        jitter=lambda attempt: ((attempt * 7) % 11) / 100,
    )


async def _request_once(
    scheduler: EndpointRequestScheduler,
    purpose: LeaderReadPurpose,
    *,
    route: str = "data:/trades",
    retry: bool = False,
) -> None:
    async with scheduler.request(route, purpose=purpose, retry=retry):
        return


def test_retry_after_supports_integer_http_date_clamp_and_invalid_values() -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)

    assert parse_retry_after("7", now=now) == 7
    assert parse_retry_after("0", now=now) == 1
    assert parse_retry_after("999", now=now) == 60
    assert (
        parse_retry_after(
            "Wed, 29 Jul 2026 12:00:12 GMT",
            now=now,
        )
        == 12
    )
    assert parse_retry_after("malformed", now=now) is None
    assert parse_retry_after(None, now=now) is None


@pytest.mark.asyncio
async def test_discovery_is_evenly_spread_and_reserved_capacity_remains_available() -> None:
    clock = RecordingClock()
    scheduler = _scheduler(clock)

    for _ in range(48):
        await _request_once(scheduler, LeaderReadPurpose.DISCOVERY)
    discovery_delays = list(clock.delays)
    for _ in range(20):
        await _request_once(scheduler, LeaderReadPurpose.SELECTED_LEADER)
    priority_delays = clock.delays[48:]

    assert discovery_delays == pytest.approx([index * 0.125 for index in range(48)])
    assert priority_delays == pytest.approx([index * 0.5 for index in range(20)])
    assert max(discovery_delays) < 6
    assert max(priority_delays) < 10


@pytest.mark.asyncio
async def test_rolling_budgets_count_retries_and_probes_without_catch_up() -> None:
    clock = RecordingClock()
    scheduler = _scheduler(clock)

    for _ in range(80):
        await _request_once(scheduler, LeaderReadPurpose.DISCOVERY)
    for _ in range(20):
        await _request_once(scheduler, LeaderReadPurpose.SELECTED_LEADER)
    await _request_once(
        scheduler,
        LeaderReadPurpose.RECOVERY,
        retry=True,
    )

    assert clock.delays[80 + 20] >= 10
    metrics = scheduler.telemetry_snapshot()
    trades = metrics["routes"]["trades"]  # type: ignore[index]
    assert trades["attempts"] == 101  # type: ignore[index]
    assert trades["retries"] == 1  # type: ignore[index]
    assert trades["probes"] == 1  # type: ignore[index]

    clock.advance(30)
    clock.delays.clear()
    await _request_once(scheduler, LeaderReadPurpose.DISCOVERY)
    await _request_once(scheduler, LeaderReadPurpose.DISCOVERY)
    assert clock.delays == pytest.approx([0, 0.125])


@pytest.mark.asyncio
async def test_route_limiters_are_isolated_and_positions_are_evenly_spread() -> None:
    clock = RecordingClock()
    scheduler = _scheduler(clock)

    for _ in range(6):
        await _request_once(
            scheduler,
            LeaderReadPurpose.BASELINE,
            route="data:/positions",
        )
    position_delays = list(clock.delays)
    await _request_once(scheduler, LeaderReadPurpose.DISCOVERY)

    assert position_delays == pytest.approx([0, 0.1, 0.2, 0.3, 0.4, 0.5])
    assert clock.delays[-1] == 0
    metrics = scheduler.telemetry_snapshot()
    assert metrics["routes"]["positions"]["attempts"] == 6  # type: ignore[index]
    assert metrics["routes"]["trades"]["attempts"] == 1  # type: ignore[index]


@pytest.mark.asyncio
async def test_trades_never_exceeds_four_calls_in_flight() -> None:
    clock = RecordingClock()
    scheduler = _scheduler(clock)
    release = asyncio.Event()
    four_entered = asyncio.Event()
    active = 0

    async def worker() -> None:
        nonlocal active
        async with scheduler.request(
            "data:/trades",
            purpose=LeaderReadPurpose.DISCOVERY,
        ):
            active += 1
            if active == 4:
                four_entered.set()
            await release.wait()
            active -= 1

    tasks = [asyncio.create_task(worker()) for _ in range(8)]
    await asyncio.wait_for(four_entered.wait(), timeout=1)
    assert active == 4
    assert (
        scheduler.telemetry_snapshot()["routes"]["trades"]["maximum_in_flight"]  # type: ignore[index]
        == 4
    )
    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_shared_circuit_allows_exactly_one_recovery_probe() -> None:
    clock = RecordingClock()
    scheduler = _scheduler(clock)
    await scheduler.record_rate_limit("1")

    with pytest.raises(TradesSourceUnavailableError):
        await _request_once(scheduler, LeaderReadPurpose.DISCOVERY)

    clock.advance(1)
    async with scheduler.request(
        "data:/trades",
        purpose=LeaderReadPurpose.RECOVERY,
    ):
        with pytest.raises(TradesSourceUnavailableError):
            await _request_once(scheduler, LeaderReadPurpose.RECOVERY)
        await scheduler.record_success(
            "data:/trades",
            purpose=LeaderReadPurpose.RECOVERY,
        )

    assert scheduler.circuit_snapshot()["open"] is False
    metrics = scheduler.telemetry_snapshot()
    assert metrics["rate_limits"] == 1
    assert metrics["recoveries"] == 1


@pytest.mark.asyncio
async def test_missing_retry_after_uses_bounded_deterministic_fallback() -> None:
    clock = RecordingClock()
    scheduler = _scheduler(clock)
    observed: list[int] = []

    await scheduler.record_rate_limit("invalid")
    for attempt in range(6):
        retry_at = datetime.fromisoformat(str(scheduler.circuit_snapshot()["retry_at"]))
        observed.append(int((retry_at - clock.wall).total_seconds()))
        clock.advance(observed[-1])
        if attempt < 5:
            async with scheduler.request(
                "data:/trades",
                purpose=LeaderReadPurpose.RECOVERY,
            ):
                await scheduler.record_rate_limit("invalid")

    assert observed == [2, 3, 5, 9, 17, 33]


@pytest.mark.asyncio
async def test_trailing_concurrent_429s_do_not_advance_shared_cooldown() -> None:
    clock = RecordingClock()
    scheduler = _scheduler(clock)

    await scheduler.record_rate_limit(None)
    first_retry = scheduler.circuit_snapshot()["retry_at"]
    await asyncio.gather(
        scheduler.record_rate_limit(None),
        scheduler.record_rate_limit(None),
        scheduler.record_rate_limit(None),
    )

    assert scheduler.circuit_snapshot()["retry_at"] == first_retry
    metrics = scheduler.telemetry_snapshot()
    assert metrics["rate_limits"] == 4
    assert metrics["cooldowns"] == 1
