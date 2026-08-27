"""Deterministic Docker-versus-Native benchmark tooling.

The comparison itself must not join, remove, recreate, or disturb the active
Compose project. Run only against isolated snapshots after the baseline is
trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from polysia.monitoring.latency_intelligence.intelligence import percentiles
from polysia.monitoring.latency_intelligence.policy import UNKNOWN, LatencyPolicy


@dataclass(frozen=True, slots=True)
class ReplayObservation:
    duration_ns: int
    telemetry_enabled: bool


def compare_replay_overhead(
    disabled: tuple[int, ...] | list[int],
    enabled: tuple[int, ...] | list[int],
    *,
    policy: LatencyPolicy | None = None,
) -> dict[str, object]:
    """Blocking only when both relative and absolute P95 thresholds are exceeded."""

    policy = policy or LatencyPolicy()
    off = percentiles(disabled, policy=policy)
    on = percentiles(enabled, policy=policy)
    if off.p95_ns is None or on.p95_ns is None:
        return {
            "absolute_delta_ms": None,
            "relative_delta": None,
            "status": "INSUFFICIENT_DATA",
            "telemetry_disabled": off.to_dict(),
            "telemetry_enabled": on.to_dict(),
            "verdict": "INSUFFICIENT_DATA",
        }
    absolute_ns = on.p95_ns - off.p95_ns
    relative = absolute_ns / off.p95_ns if off.p95_ns else None
    blocking = (
        relative is not None
        and relative > policy.overhead_p95_relative
        and absolute_ns > int(policy.overhead_p95_absolute_ms * 1_000_000)
    )
    return {
        "absolute_delta_ms": int(absolute_ns // 1_000_000),
        "relative_delta": None if relative is None else round(relative, 6),
        "status": "ok",
        "telemetry_disabled": off.to_dict(),
        "telemetry_enabled": on.to_dict(),
        "verdict": "FAIL" if blocking else "PASS",
    }


def docker_versus_native_placeholder(
    *,
    host_id: str = UNKNOWN,
    deploy_sha: str = UNKNOWN,
) -> dict[str, object]:
    return {
        "commit": deploy_sha,
        "experiment_a_deterministic_replay": "not_run",
        "experiment_b_real_endpoint": "not_run",
        "host_id": host_id,
        "note": (
            "Run only after the Helsinki baseline is trustworthy. Use an isolated "
            "container or snapshot. Never compose run the live shadow-portfolio worker."
        ),
        "python": UNKNOWN,
        "status": "not_run",
        "verdict": "INSUFFICIENT_DATA",
    }


def mean_ns(samples: list[int]) -> int | None:
    if not samples:
        return None
    return int(mean(samples))
