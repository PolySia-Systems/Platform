"""Bounded DATA_ONLY workload probe; never certifies operational capacity."""

from __future__ import annotations

import asyncio
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from polysia.application.ports.research_evidence import ResearchObservationSource


async def probe_wallet_workload(
    sources: Sequence[ResearchObservationSource],
    discovery: Mapping[str, object],
    *,
    requested_count: int,
    duration_seconds: int,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Exercise existing sources under a hard clock without making admission claims."""

    if not 30 <= duration_seconds <= 180:
        raise ValueError("capacity probe duration must be within [30, 180] seconds")
    if discovery.get("wallet_count") != requested_count:
        raise ValueError("capacity probe frozen selection count differs from request")
    if not sources:
        raise ValueError("capacity probe requires composed sources")
    deadline = clock() + timedelta(seconds=duration_seconds)
    run_id = f"capacity-probe-{uuid4().hex}"
    started = time.monotonic()
    tracemalloc.start()

    async def consume(source: ResearchObservationSource) -> dict[str, object]:
        events = 0
        error: str | None = None
        try:
            async for _event in source.run(run_id=run_id, deadline=deadline):
                events += 1
        except (OSError, TimeoutError, TypeError, ValueError, RuntimeError) as failure:
            error = type(failure).__name__
        health = source.health_snapshot()
        return {"events": events, "error_class": error, "health": dict(health)}

    timed_out = False
    results: list[dict[str, object]] = []
    try:
        async with asyncio.timeout(duration_seconds + 10):
            results = list(await asyncio.gather(*(consume(source) for source in sources)))
    except TimeoutError:
        timed_out = True
    finally:
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return {
        "version": "wallet-capacity-probe-v1",
        "status": "CANDIDATE_ONLY",
        "requested_count": requested_count,
        "frozen_count": discovery["wallet_count"],
        "duration_seconds": duration_seconds,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "python_peak_bytes": peak,
        "timed_out": timed_out,
        "source_results": results,
        "unmeasured": [
            "other_processes_on_shared_ip", "host_total_memory",
            "sqlite_growth", "future_market_mix",
        ],
        "admission_note": "Probe output is never an operational PASS record.",
    }
