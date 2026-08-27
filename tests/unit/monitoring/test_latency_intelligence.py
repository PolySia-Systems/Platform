from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysia.monitoring.latency_intelligence.benchmark import compare_replay_overhead
from polysia.monitoring.latency_intelligence.contract import PerformanceSpan
from polysia.monitoring.latency_intelligence.intelligence import (
    before_after,
    best_observed,
    critical_path,
    economic_correlation,
    percentiles,
)
from polysia.monitoring.latency_intelligence.policy import (
    PERFORMANCE_CONTRACT_VERSION,
    LatencyPolicy,
)


def _span(
    *,
    span_id: str,
    parent_span_id: str | None,
    duration_ns: int,
    started_at: datetime,
    operation: str,
    trace_id: str = "trace-a",
) -> PerformanceSpan:
    return PerformanceSpan(
        performance_contract_version=PERFORMANCE_CONTRACT_VERSION,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        component="application",
        operation=operation,
        status="ok",
        duration_ns=duration_ns,
        started_at_utc=started_at,
        venue_id="polymarket",
        endpoint_id=None,
        host_id="host-a",
        provider="hetzner",
        region="helsinki",
        deploy_sha="abc",
        runtime_version="3.14.6",
        image_digest="sha256:test",
        configuration_version="latency-intelligence-v0.1",
        policy_version="latency-intelligence-v0.1",
    )


def test_percentiles_require_versioned_sample_thresholds() -> None:
    policy = LatencyPolicy()
    short = list(range(1_000_000, 1_000_000 + 19))
    result = percentiles(short, policy=policy)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.p50_ns is None
    assert result.p95_ns is None

    p50_ready = list(range(1_000_000, 1_000_000 + 20))
    ready = percentiles(p50_ready, policy=policy)
    expected_p50 = int(round(1_000_009 * 0.5 + 1_000_010 * 0.5))
    assert ready.p50_ns == expected_p50
    assert ready.p95_ns is None
    assert ready.p99_ns is None

    p95_ready = list(range(100))
    dense = percentiles(p95_ready, policy=policy)
    rank = 0.95 * 99
    lower = int(rank)
    fraction = rank - lower
    expected_p95 = int(round(p95_ready[lower] * (1 - fraction) + p95_ready[lower + 1] * fraction))
    assert dense.p95_ns == expected_p95
    assert dense.p99_ns is None


def test_critical_path_does_not_double_count_nested_or_concurrent_spans() -> None:
    start = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    root = _span(
        span_id="root",
        parent_span_id=None,
        duration_ns=100_000_000,
        started_at=start,
        operation="poll",
    )
    nested = _span(
        span_id="eval",
        parent_span_id="root",
        duration_ns=40_000_000,
        started_at=start,
        operation="evaluation",
    )
    concurrent_a = _span(
        span_id="fetch-a",
        parent_span_id="root",
        duration_ns=50_000_000,
        started_at=start + timedelta(milliseconds=10),
        operation="source_fetch",
    )
    concurrent_b = _span(
        span_id="fetch-b",
        parent_span_id="root",
        duration_ns=50_000_000,
        started_at=start + timedelta(milliseconds=20),
        operation="source_fetch",
    )
    result = critical_path((root, nested, concurrent_a, concurrent_b))
    assert result.status == "ok"
    contributions = [float(item["contribution"] or 0) for item in result.stages]
    assert sum(contributions) <= 1.0000001
    assert result.total_ns == 100_000_000
    raw_child_sum = 40_000_000 + 50_000_000 + 50_000_000
    assert raw_child_sum > result.total_ns
    assert result.primary_bottleneck in {"evaluation", "source_fetch"}


def test_confidence_and_before_after_are_insufficient_until_thresholds() -> None:
    comparison = before_after([1, 2, 3], [4, 5, 6])
    assert comparison["status"] == "INSUFFICIENT_DATA"
    observed = best_observed(list(range(10)))
    assert observed["status"] == "INSUFFICIENT_DATA"
    improved = before_after(list(range(20, 40)), list(range(1, 21)))
    assert improved["status"] == "improved"


def test_economic_analysis_is_correlation_not_causation() -> None:
    payload = economic_correlation([(1, 1.0), (2, 2.0)])
    assert payload["status"] == "INSUFFICIENT_DATA"
    pairs = [(index, float(index)) for index in range(20)]
    ready = economic_correlation(pairs)
    assert ready["note"] == "correlation_not_causation"
    assert ready["correlation"] == 1.0


def test_overhead_gate_requires_both_relative_and_absolute_p95() -> None:
    disabled = [1_000_000] * 100
    enabled = [1_001_000] * 100
    result = compare_replay_overhead(disabled, enabled)
    assert result["verdict"] == "PASS"
    noisy = compare_replay_overhead([1] * 10, [2] * 10)
    assert noisy["verdict"] == "INSUFFICIENT_DATA"
    blocking = compare_replay_overhead([10_000_000] * 100, [20_000_000] * 100)
    assert blocking["verdict"] == "FAIL"
