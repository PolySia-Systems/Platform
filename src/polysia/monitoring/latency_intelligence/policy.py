"""Versioned initial engineering policy for latency intelligence v0.1.

These thresholds are not scientific constants. Revise them only from measured
evidence without changing architecture.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

PERFORMANCE_CONTRACT_VERSION = "1.0"
PERFORMANCE_POLICY_VERSION = "latency-intelligence-v0.1"
CONFIGURATION_VERSION = "latency-intelligence-v0.1"
LATENCY_TELEMETRY_SCHEMA_VERSION = 1

UNKNOWN = "UNKNOWN"

SAMPLE_P50_MIN = 20
SAMPLE_P95_MIN = 100
SAMPLE_P99_MIN = 1_000

DETAIL_RETENTION_DAYS = 7
AGGREGATE_RETENTION_DAYS = 90
AGGREGATE_BUCKET_HOURS = 1

DEFAULT_BUFFER_CAPACITY = 2_048
FLUSH_BATCH_SIZE = 128
CLEANUP_BATCH_SIZE = 500
TELEMETRY_BUSY_TIMEOUT_MS = 0
PROBE_TIMEOUT_SECONDS = 2.0
PROBE_MIN_REMAINING_SECONDS = 3.0

OVERHEAD_P95_RELATIVE = 0.02
OVERHEAD_P95_ABSOLUTE_MS = 5.0
BEST_OBSERVED_PERCENTILE = 5
BEST_OBSERVED_MIN_SAMPLES = 20
FRESHNESS_HIGH_SECONDS = 15 * 60
FRESHNESS_MEDIUM_SECONDS = 6 * 60 * 60
CLOCK_SKEW_WARN_MS = 5_000

# Canonical stage names. Unavailable stages stay UNKNOWN, never zero.
INSTRUMENTED_STAGES: tuple[str, ...] = (
    "source_observation",
    "source_fetch",
    "decode",
    "normalize",
    "db_read",
    "db_write",
    "candidate_lookup",
    "evaluation",
    "strategy",
    "risk",
    "pricing",
    "execution_preparation",
    "persistence",
    "marking",
    "settlement",
    "submit",
    "ack",
    "first_fill",
    "final_fill",
)

CURRENT_RUNTIME_STAGES: frozenset[str] = frozenset(
    {
        "source_observation",
        "source_fetch",
        "db_read",
        "db_write",
        "candidate_lookup",
        "evaluation",
        "persistence",
        "marking",
        "settlement",
    }
)

UNSUPPORTED_STAGES: frozenset[str] = frozenset(INSTRUMENTED_STAGES) - CURRENT_RUNTIME_STAGES

# Budgets are engineering starting points in nanoseconds.
STAGE_BUDGETS_NS: Mapping[str, int] = MappingProxyType(
    {
        "source_fetch": 2_000_000_000,
        "db_read": 200_000_000,
        "db_write": 250_000_000,
        "candidate_lookup": 50_000_000,
        "evaluation": 500_000_000,
        "persistence": 250_000_000,
        "marking": 100_000_000,
        "settlement": 100_000_000,
        "poll": 5_000_000_000,
    }
)

LATENCY_BUCKETS_MS: tuple[tuple[int, int | None], ...] = (
    (0, 250),
    (250, 1_000),
    (1_000, 5_000),
    (5_000, None),
)


@dataclass(frozen=True, slots=True)
class LatencyPolicy:
    contract_version: str = PERFORMANCE_CONTRACT_VERSION
    policy_version: str = PERFORMANCE_POLICY_VERSION
    configuration_version: str = CONFIGURATION_VERSION
    sample_p50_min: int = SAMPLE_P50_MIN
    sample_p95_min: int = SAMPLE_P95_MIN
    sample_p99_min: int = SAMPLE_P99_MIN
    detail_retention_days: int = DETAIL_RETENTION_DAYS
    aggregate_retention_days: int = AGGREGATE_RETENTION_DAYS
    buffer_capacity: int = DEFAULT_BUFFER_CAPACITY
    flush_batch_size: int = FLUSH_BATCH_SIZE
    cleanup_batch_size: int = CLEANUP_BATCH_SIZE
    probe_timeout_seconds: float = PROBE_TIMEOUT_SECONDS
    probe_min_remaining_seconds: float = PROBE_MIN_REMAINING_SECONDS
    stage_budgets_ns: Mapping[str, int] = STAGE_BUDGETS_NS
    latency_buckets_ms: tuple[tuple[int, int | None], ...] = LATENCY_BUCKETS_MS
    best_observed_percentile: int = BEST_OBSERVED_PERCENTILE
    best_observed_min_samples: int = BEST_OBSERVED_MIN_SAMPLES
    overhead_p95_relative: float = OVERHEAD_P95_RELATIVE
    overhead_p95_absolute_ms: float = OVERHEAD_P95_ABSOLUTE_MS
