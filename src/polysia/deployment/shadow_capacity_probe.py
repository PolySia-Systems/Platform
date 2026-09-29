"""Isolated Shadow writer probe; observations never become admission evidence alone."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from polysia.application.services.continuous_shadow import ContinuousShadowService
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot
from polysia.storage.continuous_shadow import ContinuousShadowRepository


class _BatchMarketRead(Protocol):
    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot: ...

    async def get_order_books(
        self, token_ids: tuple[str, ...]
    ) -> dict[str, MarketOrderBookSnapshot]: ...

    async def get_market_by_condition_id(self, condition_id: str) -> MarketDetails: ...


class CountingMarketRead:
    """Count actual public market reads without changing the adapter contract."""

    def __init__(self, delegate: _BatchMarketRead, *, token_budget: int = 500) -> None:
        self._delegate = delegate
        self._token_budget = token_budget
        self.book_requests = 0
        self.book_tokens = 0
        self.market_requests = 0
        self.fee_schedule_reads = 0

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        self._reserve_tokens(1)
        self.book_requests += 1
        self.book_tokens += 1
        return await self._delegate.get_order_book(token_id)

    async def get_order_books(
        self, token_ids: tuple[str, ...]
    ) -> dict[str, MarketOrderBookSnapshot]:
        self._reserve_tokens(len(token_ids))
        self.book_requests += 1
        self.book_tokens += len(token_ids)
        return await self._delegate.get_order_books(token_ids)

    async def get_market_by_condition_id(self, condition_id: str) -> MarketDetails:
        self._reserve_tokens(1)
        self.market_requests += 1
        details = await self._delegate.get_market_by_condition_id(condition_id)
        if details.fee_schedule is not None:
            self.fee_schedule_reads += 1
        return details

    def _reserve_tokens(self, count: int) -> None:
        if self.book_tokens + self.market_requests + count > self._token_budget:
            raise ValueError("Shadow probe market-token budget exhausted")


def _data_attempts(telemetry: object) -> int:
    if not isinstance(telemetry, dict):
        raise ValueError("Shadow probe Data API telemetry is malformed")
    routes = telemetry.get("routes", telemetry)
    if not isinstance(routes, dict) or not routes:
        raise ValueError("Shadow probe Data API telemetry is missing")
    total = 0
    for name, value in routes.items():
        if not isinstance(value, dict):
            continue
        attempts = value.get("attempts", value.get("requests"))
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise ValueError(f"Shadow probe Data API telemetry is invalid for {name}")
        total += attempts
    return total


async def probe_shadow_path(
    source_id: str,
    service_factory: Callable[[Path], ContinuousShadowService],
    *,
    config: ContinuousShadowConfig,
    duration_seconds: int,
    poll_interval_seconds: int,
    scratch_root: Path | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    market_path_observed: Callable[[], bool] | None = None,
    max_data_requests: int = 1000,
) -> dict[str, object]:
    """Run real source → market → ledger polls against only a fresh temporary DB."""

    if not 30 <= duration_seconds <= 1800:
        raise ValueError("Shadow probe duration must be within [30, 1800] seconds")
    if not 5 <= poll_interval_seconds <= 60:
        raise ValueError("Shadow probe interval must be within [5, 60] seconds")
    if not 1 <= max_data_requests <= 1000:
        raise ValueError("Shadow probe Data API budget must be within [1, 1000]")
    with tempfile.TemporaryDirectory(dir=scratch_root, prefix="polysia-shadow-probe-") as name:
        database = Path(name) / "continuous-shadow.sqlite3"
        store = ContinuousShadowRepository(database)
        store.initialize()
        service = service_factory(database)
        selection = service.selection_for_isolated_probe(source_id)
        if config.runtime_version != "continuous-shadow-runtime-v2":
            raise ValueError("Shadow capacity probe requires v2 runtime")
        wallet_count = config.wallet_count
        if wallet_count is None:
            raise ValueError("Shadow capacity probe requires an explicit wallet count")
        experiment = store.start_experiment(
            selection=selection, config=config,
            started_at=clock(),
        )
        initial_bytes = database.stat().st_size
        deadline = monotonic() + duration_seconds
        cpu_started = time.process_time()
        tracemalloc.start()
        polls: list[dict[str, object]] = []
        poll_elapsed_ms: list[int] = []
        error_class: str | None = None
        stopped_after_full_path = False
        data_requests = 0
        budget_exhausted = False
        try:
            while monotonic() < deadline:
                if (
                    data_requests + wallet_count * config.source_max_requests
                    > max_data_requests
                ):
                    budget_exhausted = True
                    break
                try:
                    poll_started = monotonic()
                    outcome = await asyncio.wait_for(
                        service.poll(source_id), timeout=max(0.001, deadline - poll_started)
                    )
                    poll_elapsed_ms.append(round((monotonic() - poll_started) * 1000))
                    data_requests += _data_attempts(outcome.request_telemetry)
                except (OSError, TimeoutError, TypeError, ValueError, RuntimeError) as error:
                    error_class = type(error).__name__
                    break
                polls.append({
                    "new_event_count": outcome.new_event_count,
                    "simulated_count": outcome.simulated_count,
                    "unknown_count": outcome.unknown_count,
                    "request_telemetry": outcome.request_telemetry,
                })
                if market_path_observed is not None and len(polls) >= 2:
                    observed_events = sum(int(str(p["new_event_count"])) for p in polls)
                    simulated = sum(int(str(p["simulated_count"])) for p in polls)
                    if (
                        observed_events > 0 and simulated > 0
                        and market_path_observed()
                        and store.period_usage(experiment.experiment_id)[0] == observed_events
                        and store.invariant_report(experiment.experiment_id).ledger_balanced
                    ):
                        stopped_after_full_path = True
                        break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                await sleeper(min(poll_interval_seconds, remaining))
        finally:
            _current, peak_python_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        event_count = sum(int(str(poll["new_event_count"])) for poll in polls)
        persisted_event_count, stored_bytes = store.period_usage(experiment.experiment_id)
        invariant = store.invariant_report(experiment.experiment_id)
        if event_count != persisted_event_count:
            error_class = "source_writer_count_mismatch"
        if not invariant.ledger_balanced:
            error_class = "ledger_unbalanced"
        simulated_count = sum(int(str(poll["simulated_count"])) for poll in polls)
        full_path_observed = (
            len(polls) >= 2 and persisted_event_count > 0 and simulated_count > 0
            and market_path_observed is not None and market_path_observed()
            and invariant.ledger_balanced
        )
        process_peak_rss_bytes = None
        if os.name == "posix":
            try:
                for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
                    if line.startswith("VmHWM:"):
                        parts = line.split()
                        if len(parts) == 3 and parts[2] == "kB":
                            process_peak_rss_bytes = int(parts[1]) * 1024
                        break
            except OSError:
                pass
        return {
            "version": "shadow-capacity-probe-v1",
            "status": (
                "FAILED" if error_class is not None else
                "SHADOW_PATH_NONEMPTY_UNREVIEWED" if full_path_observed
                else "INSUFFICIENT_NONEMPTY_EVIDENCE"
            ),
            "wallet_count": config.wallet_count,
            "polls_observed": len(polls),
            "stopped_after_full_path": stopped_after_full_path,
            "data_requests": data_requests,
            "data_request_budget": max_data_requests,
            "budget_exhausted": budget_exhausted,
            "new_event_count": event_count,
            "persisted_event_count": persisted_event_count,
            "ledger_balanced": invariant.ledger_balanced,
            "simulated_count": simulated_count,
            "unknown_count": sum(int(str(poll["unknown_count"])) for poll in polls),
            "storage_growth_bytes": max(0, stored_bytes - initial_bytes),
            "python_peak_bytes": peak_python_bytes,
            "process_peak_rss_bytes": process_peak_rss_bytes,
            "process_cpu_seconds": round(time.process_time() - cpu_started, 3),
            "poll_elapsed_ms": poll_elapsed_ms,
            "polls": polls,
            "error_class": error_class,
            "unmeasured": [
                "shared_ip_other_consumers", "host_total_memory", "future_market_mix",
            ],
            "admission_note": "A matching, reviewed host capacity record is still required.",
        }
