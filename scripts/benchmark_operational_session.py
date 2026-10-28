"""Synthetic local financial-owner volume probe; never a Live capacity receipt.

Run from the checkout. No SDK, secret, network or account access is constructed.
The three-day tape models one retained observation per minute, not a provider
request-rate claim. Actual composition request amplification is reported apart.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polysia.domain.financial_session import (
    AccountObservation,
    InstrumentScope,
    RuntimeBinding,
    SessionAuthorization,
    canonical_json,
    digest,
)
from polysia.monitoring.financial_session import financial_session_view
from polysia.storage.financial_session import FinancialSessionJournal


def benchmark(events: int, *, trace_memory: bool = False) -> dict:
    if not 100 <= events <= 10000:
        raise ValueError("bounded synthetic event count required")
    now = datetime.now(UTC)
    auth = SessionAuthorization(
        1,
        "synthetic-volume-probe",
        "SYNTHETIC_NO_EXTERNAL_AUTHORITY",
        True,
        RuntimeBinding("synthetic", "synthetic", "synthetic", "synthetic", "synthetic"),
        now - timedelta(seconds=1),
        now + timedelta(days=3),
        now + timedelta(days=4),
        frozenset({"synthetic"}),
        (InstrumentScope("synthetic", "synthetic", "synthetic", "synthetic"),),
        "synthetic",
        "synthetic",
        *([Decimal(10)] * 7),
        1,
        2,
        100,
        Decimal("0.01"),
        30,
        20,
        600,
        Decimal("0.000001"),
        1000000,
        1000,
        1_000_000_000,
        1_000_000_000,
        Decimal(0),
        "RECONCILE",
        frozenset({"CANCEL", "REDUCE"}),
    )
    timings: dict[str, list[float]] = {
        name: []
        for name in (
            "commit_ms",
            "retained_response_ms",
            "serialization_checksum_ms",
            "checkpoint_retention_ms",
            "cold_recovery_ms",
            "optional_projection_ms",
        )
    }
    if trace_memory:
        tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="polysia-synthetic-capacity-") as temporary:
        root = Path(temporary)
        journal = FinancialSessionJournal(root / "financial/state.sqlite3", root / "witness", auth)
        journal.provision(
            AccountObservation(
                "synthetic",
                now,
                Decimal(100),
                (),
                frozenset(),
                Decimal(0),
                True,
                "synthetic-flat-opening",
            )
        )
        journal.open()
        outbox = root / "checkpoint.json"
        raw = b"x" * 1024
        started = time.perf_counter()
        try:
            for index in range(events):
                tick = time.perf_counter()
                journal.mutate(
                    "SYNTHETIC_OBSERVATION",
                    {"index": index},
                    lambda state, index=index: state.setdefault("wire", {}).update(
                        {
                            str(index): {
                                "at": now + timedelta(minutes=index),
                                "actual_bytes": 1024,
                                "action": "SYNTHETIC",
                                "result": "FIXTURE_ONLY",
                            }
                        }
                    ),
                )
                timings["commit_ms"].append((time.perf_counter() - tick) * 1000)
                if index < 100 or index % 100 == 0:
                    tick = time.perf_counter()
                    journal.retain_response(str(index), raw)
                    timings["retained_response_ms"].append((time.perf_counter() - tick) * 1000)
                    tick = time.perf_counter()
                    state = journal.read()
                    encoded = canonical_json(state)
                    digest(state)
                    timings["serialization_checksum_ms"].append((time.perf_counter() - tick) * 1000)
                    tick = time.perf_counter()
                    pending = outbox.with_suffix(".pending")
                    with pending.open("w", encoding="utf-8") as stream:
                        stream.write(canonical_json(asdict(journal.checkpoint())))
                        stream.flush()
                        import os

                        os.fsync(stream.fileno())
                    pending.replace(outbox)
                    timings["checkpoint_retention_ms"].append((time.perf_counter() - tick) * 1000)
                    tick = time.perf_counter()
                    financial_session_view(state, auth, now=now)
                    timings["optional_projection_ms"].append((time.perf_counter() - tick) * 1000)
            duration = time.perf_counter() - started
            for _ in range(3):
                checkpoint = journal.checkpoint()
                journal.close()
                tick = time.perf_counter()
                journal.open(checkpoint=checkpoint)
                timings["cold_recovery_ms"].append((time.perf_counter() - tick) * 1000)
            sizes = {
                "financial_bytes": journal.path.stat().st_size,
                "witness_bytes": journal.witness.stat().st_size,
                "state_json_bytes": len(encoded.encode()),
            }
        finally:
            journal.close()
        peak = tracemalloc.get_traced_memory()[1] if trace_memory else None
        if trace_memory:
            tracemalloc.stop()
    summary = {}
    for name, samples in timings.items():
        ordered = sorted(samples)
        summary[name] = {
            "samples": len(samples),
            "mean": sum(samples) / len(samples),
            "max": max(samples),
            "p50": ordered[len(samples) // 2] if len(samples) >= 20 else None,
            "p95": ordered[int(len(samples) * 0.95)] if len(samples) >= 100 else None,
            "p99": ordered[int(len(samples) * 0.99)] if len(samples) >= 1000 else None,
        }
    return {
        "version": "synthetic-operational-benchmark/v1",
        "synthetic": True,
        "observed_at": now.isoformat(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "tracemalloc_enabled": trace_memory,
        },
        "workload": {
            "events": events,
            "cadence_seconds": 60,
            "calendar_days": events / 1440,
            "retained_response_bytes_per_sample": 1024,
            "actual_provider_requests": 0,
            "composition_requests_per_tick": "UNKNOWN_PENDING_BOUNDED_PROVIDER_QUALIFICATION",
        },
        "wall_seconds": duration,
        "python_peak_bytes": peak,
        "storage": sizes,
        "timings": summary,
        "independent_supervisor_ack_ms": None,
        "venue_latency_ms": None,
        "verified_production_capacity": None,
        "limits": [
            "flat synthetic account; no fill volume or provider acquisition",
            "snapshot JSON work grows with retained event count; no linear timing extrapolation",
            "cold recovery uses fixture checkpoints, not operational owner approval",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=4320)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace-memory", action="store_true")
    args = parser.parse_args()
    result = benchmark(args.events, trace_memory=args.trace_memory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "wall_seconds": result["wall_seconds"],
                "events": args.events,
                "production_capacity": "UNKNOWN",
            }
        )
    )
