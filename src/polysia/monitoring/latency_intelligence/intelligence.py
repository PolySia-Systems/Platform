"""Deterministic latency intelligence over recorded spans and measurements."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from statistics import mean, pstdev

from polysia.monitoring.latency_intelligence.contract import (
    Confidence,
    PerformanceSpan,
)
from polysia.monitoring.latency_intelligence.policy import (
    FRESHNESS_HIGH_SECONDS,
    FRESHNESS_MEDIUM_SECONDS,
    UNKNOWN,
    UNSUPPORTED_STAGES,
    LatencyPolicy,
)


@dataclass(frozen=True, slots=True)
class PercentileResult:
    sample_count: int
    p50_ns: int | None
    p95_ns: int | None
    p99_ns: int | None
    variance_ns2: float | None
    confidence: Confidence
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence.value,
            "p50_ns": self.p50_ns,
            "p50_ms": _ns_ms(self.p50_ns),
            "p95_ns": self.p95_ns,
            "p95_ms": _ns_ms(self.p95_ns),
            "p99_ns": self.p99_ns,
            "p99_ms": _ns_ms(self.p99_ns),
            "sample_count": self.sample_count,
            "status": self.status,
            "variance_ns2": None if self.variance_ns2 is None else format(self.variance_ns2, "f"),
        }


@dataclass(frozen=True, slots=True)
class CriticalPathResult:
    trace_id: str
    total_ns: int | None
    stages: tuple[dict[str, object], ...]
    primary_bottleneck: str | None
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "primary_bottleneck": self.primary_bottleneck,
            "stages": list(self.stages),
            "status": self.status,
            "total_ms": _ns_ms(self.total_ns),
            "total_ns": self.total_ns,
            "trace_id": self.trace_id,
        }


def percentiles(
    samples_ns: list[int] | tuple[int, ...],
    *,
    policy: LatencyPolicy | None = None,
    freshness_seconds: int | None = None,
    missing_evidence: bool = False,
    clock_unhealthy: bool = False,
    deploy_consistent: bool = True,
) -> PercentileResult:
    policy = policy or LatencyPolicy()
    valid = sorted(value for value in samples_ns if value >= 0)
    count = len(valid)
    if count == 0 or missing_evidence:
        return PercentileResult(
            sample_count=count,
            p50_ns=None,
            p95_ns=None,
            p99_ns=None,
            variance_ns2=None,
            confidence=Confidence.INSUFFICIENT_DATA,
            status="INSUFFICIENT_DATA",
        )
    p50 = _percentile(valid, 50) if count >= policy.sample_p50_min else None
    p95 = _percentile(valid, 95) if count >= policy.sample_p95_min else None
    p99 = _percentile(valid, 99) if count >= policy.sample_p99_min else None
    variance = None if count < 2 else pstdev(valid) ** 2
    status = "INSUFFICIENT_DATA" if p50 is None else "ok"
    confidence = classify_confidence(
        sample_count=count,
        freshness_seconds=freshness_seconds,
        missing_evidence=missing_evidence,
        variance_ns2=variance,
        mean_ns=None if count == 0 else mean(valid),
        clock_unhealthy=clock_unhealthy,
        measurement_quality_ok=p50 is not None,
        deploy_consistent=deploy_consistent,
        policy=policy,
    )
    return PercentileResult(
        sample_count=count,
        p50_ns=p50,
        p95_ns=p95,
        p99_ns=p99,
        variance_ns2=variance,
        confidence=confidence,
        status=status,
    )


def classify_confidence(
    *,
    sample_count: int,
    freshness_seconds: int | None,
    missing_evidence: bool,
    variance_ns2: float | None,
    mean_ns: float | None,
    clock_unhealthy: bool,
    measurement_quality_ok: bool,
    deploy_consistent: bool,
    policy: LatencyPolicy | None = None,
) -> Confidence:
    policy = policy or LatencyPolicy()
    if missing_evidence or sample_count < policy.sample_p50_min or not measurement_quality_ok:
        return Confidence.INSUFFICIENT_DATA
    if clock_unhealthy or not deploy_consistent:
        return Confidence.LOW
    if freshness_seconds is None or freshness_seconds > FRESHNESS_MEDIUM_SECONDS:
        return Confidence.LOW
    high_variance = False
    if variance_ns2 is not None and mean_ns and mean_ns > 0:
        high_variance = sqrt(variance_ns2) / mean_ns > 1.0
    if sample_count >= policy.sample_p95_min and freshness_seconds <= FRESHNESS_HIGH_SECONDS:
        return Confidence.MEDIUM if high_variance else Confidence.HIGH
    if freshness_seconds <= FRESHNESS_MEDIUM_SECONDS:
        return Confidence.LOW if high_variance else Confidence.MEDIUM
    return Confidence.LOW


def best_observed(
    samples_ns: list[int] | tuple[int, ...],
    *,
    policy: LatencyPolicy | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    deploy_sha: str = UNKNOWN,
    host_id: str = UNKNOWN,
) -> dict[str, object]:
    policy = policy or LatencyPolicy()
    valid = sorted(value for value in samples_ns if value >= 0)
    if len(valid) < policy.best_observed_min_samples:
        return {
            "confidence": Confidence.INSUFFICIENT_DATA.value,
            "deploy_sha": deploy_sha,
            "host_id": host_id,
            "sample_count": len(valid),
            "status": "INSUFFICIENT_DATA",
            "value_ms": None,
            "value_ns": None,
            "window_end": None if window_end is None else window_end.isoformat(),
            "window_start": None if window_start is None else window_start.isoformat(),
        }
    confidence = (
        Confidence.MEDIUM.value
        if len(valid) < policy.sample_p95_min
        else Confidence.HIGH.value
    )
    value = _percentile(valid, policy.best_observed_percentile)
    return {
        "confidence": confidence,
        "deploy_sha": deploy_sha,
        "host_id": host_id,
        "sample_count": len(valid),
        "status": "ok",
        "value_ms": _ns_ms(value),
        "value_ns": value,
        "window_end": None if window_end is None else window_end.isoformat(),
        "window_start": None if window_start is None else window_start.isoformat(),
    }


def before_after(
    before_ns: list[int] | tuple[int, ...],
    after_ns: list[int] | tuple[int, ...],
    *,
    policy: LatencyPolicy | None = None,
    before_deploy: str = UNKNOWN,
    after_deploy: str = UNKNOWN,
) -> dict[str, object]:
    policy = policy or LatencyPolicy()
    before = percentiles(before_ns, policy=policy)
    after = percentiles(after_ns, policy=policy)
    if before.p50_ns is None or after.p50_ns is None:
        verdict = "INSUFFICIENT_DATA"
        delta = None
    else:
        delta = after.p50_ns - before.p50_ns
        if delta > 0:
            verdict = "regressed"
        elif delta < 0:
            verdict = "improved"
        else:
            verdict = "unchanged"
    return {
        "after": after.to_dict(),
        "after_deploy": after_deploy,
        "before": before.to_dict(),
        "before_deploy": before_deploy,
        "delta_p50_ms": _ns_ms(delta),
        "delta_p50_ns": delta,
        "status": verdict,
    }


def budget_gap(
    actual_ns: int | None,
    *,
    operation: str,
    policy: LatencyPolicy | None = None,
    confidence: Confidence = Confidence.INSUFFICIENT_DATA,
) -> dict[str, object]:
    policy = policy or LatencyPolicy()
    budget = policy.stage_budgets_ns.get(operation)
    if actual_ns is None or budget is None:
        gap = None
        status = "INSUFFICIENT_DATA" if actual_ns is None else "UNKNOWN"
        if budget is None:
            status = "UNKNOWN"
    else:
        gap = actual_ns - budget
        status = "ok"
    return {
        "actual_ms": _ns_ms(actual_ns),
        "actual_ns": actual_ns,
        "budget_ms": _ns_ms(budget),
        "budget_ns": budget,
        "confidence": confidence.value,
        "gap_ms": _ns_ms(gap),
        "gap_ns": gap,
        "operation": operation,
        "status": status,
    }


def critical_path(spans: tuple[PerformanceSpan, ...] | list[PerformanceSpan]) -> CriticalPathResult:
    """Exclusive-time critical path. Nested and overlapping spans are not summed."""

    items = tuple(span for span in spans if span.duration_ns is not None)
    if not items:
        return CriticalPathResult(
            trace_id=UNKNOWN,
            total_ns=None,
            stages=(),
            primary_bottleneck=None,
            status="INSUFFICIENT_DATA",
        )
    by_parent: dict[str | None, list[PerformanceSpan]] = defaultdict(list)
    by_id = {span.span_id: span for span in items}
    for span in items:
        by_parent[span.parent_span_id].append(span)
    roots = by_parent.get(None, [])
    if not roots:
        known_parents = {span.span_id for span in items}
        roots = [span for span in items if span.parent_span_id not in known_parents]
    if not roots:
        return CriticalPathResult(
            trace_id=items[0].trace_id,
            total_ns=None,
            stages=(),
            primary_bottleneck=None,
            status="INSUFFICIENT_DATA",
        )
    root = max(roots, key=lambda item: item.duration_ns or 0)
    exclusive = _exclusive_durations(root, by_parent, by_id)
    total = root.duration_ns
    stages: list[dict[str, object]] = []
    bottleneck_name = None
    bottleneck_ns = -1
    for span, duration in exclusive:
        if span.span_id == root.span_id:
            continue
        contribution = None if total in {None, 0} else duration / total
        if contribution is not None and contribution > 1:
            contribution = 1.0
        if duration > bottleneck_ns:
            bottleneck_ns = duration
            bottleneck_name = span.operation
        stages.append(
            {
                "contribution": contribution,
                "duration_ms": _ns_ms(duration),
                "duration_ns": duration,
                "operation": span.operation,
                "span_id": span.span_id,
            }
        )
    contribution_sum = 0.0
    for item in stages:
        raw = item["contribution"]
        contribution_sum += 0.0 if raw is None else float(str(raw))
    if contribution_sum > 1.0000001 and total:
        scale = 1.0 / contribution_sum
        for item in stages:
            raw = item["contribution"]
            if raw is not None:
                item["contribution"] = float(str(raw)) * scale
    return CriticalPathResult(
        trace_id=root.trace_id,
        total_ns=total,
        stages=tuple(stages),
        primary_bottleneck=bottleneck_name,
        status="ok",
    )


def unsupported_stage_payload() -> dict[str, dict[str, object]]:
    return {
        stage: {
            "confidence": Confidence.INSUFFICIENT_DATA.value,
            "duration_ms": None,
            "duration_ns": None,
            "status": "UNKNOWN",
        }
        for stage in sorted(UNSUPPORTED_STAGES)
    }


def economic_correlation(
    pairs: list[tuple[int, float]],
    *,
    policy: LatencyPolicy | None = None,
) -> dict[str, object]:
    """Pearson correlation only. Never reports causation."""

    policy = policy or LatencyPolicy()
    if len(pairs) < policy.sample_p50_min:
        return {
            "confidence": Confidence.INSUFFICIENT_DATA.value,
            "correlation": None,
            "note": "correlation_not_causation",
            "sample_count": len(pairs),
            "status": "INSUFFICIENT_DATA",
        }
    xs = [float(item[0]) for item in pairs]
    ys = [item[1] for item in pairs]
    correlation = _pearson(xs, ys)
    return {
        "confidence": Confidence.LOW.value,
        "correlation": None if correlation is None else round(correlation, 6),
        "note": "correlation_not_causation",
        "sample_count": len(pairs),
        "status": "ok" if correlation is not None else "INSUFFICIENT_DATA",
    }


def trend(values_ns: list[int], *, window: int = 5) -> str:
    if len(values_ns) < window * 2:
        return "INSUFFICIENT_DATA"
    first = mean(values_ns[:window])
    last = mean(values_ns[-window:])
    if last > first * 1.1:
        return "increasing"
    if last < first * 0.9:
        return "decreasing"
    return "stable"


def _exclusive_durations(
    root: PerformanceSpan,
    by_parent: dict[str | None, list[PerformanceSpan]],
    _by_id: dict[str, PerformanceSpan],
) -> list[tuple[PerformanceSpan, int]]:
    result: list[tuple[PerformanceSpan, int]] = []

    def visit(span: PerformanceSpan) -> int:
        children = by_parent.get(span.span_id, [])
        child_union = _union_coverage_ns(span, children)
        exclusive = max(0, (span.duration_ns or 0) - child_union)
        result.append((span, exclusive))
        for child in children:
            visit(child)
        return exclusive

    visit(root)
    return result


def _union_coverage_ns(parent: PerformanceSpan, children: list[PerformanceSpan]) -> int:
    if not children or parent.duration_ns is None:
        return 0
    parent_start = parent.started_at_utc
    intervals: list[tuple[int, int]] = []
    for child in children:
        if child.duration_ns is None:
            continue
        start = int((child.started_at_utc - parent_start).total_seconds() * 1_000_000_000)
        end = start + child.duration_ns
        start = max(0, start)
        end = min(parent.duration_ns, max(start, end))
        if end > start:
            intervals.append((start, end))
    if not intervals:
        return 0
    intervals.sort()
    merged_start, merged_end = intervals[0]
    total = 0
    for start, end in intervals[1:]:
        if start <= merged_end:
            merged_end = max(merged_end, end)
        else:
            total += merged_end - merged_start
            merged_start, merged_end = start, end
    total += merged_end - merged_start
    return total


def _percentile(sorted_samples: list[int], percentile: int) -> int:
    if not sorted_samples:
        raise ValueError("percentile requires samples")
    if percentile <= 0:
        return sorted_samples[0]
    if percentile >= 100:
        return sorted_samples[-1]
    rank = (percentile / 100) * (len(sorted_samples) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_samples) - 1)
    fraction = rank - lower
    value = sorted_samples[lower] * (1 - fraction) + sorted_samples[upper] * fraction
    return int(round(value))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = mean(xs)
    mean_y = mean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den_x = sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _ns_ms(value: int | None) -> int | None:
    if value is None:
        return None
    return int(value // 1_000_000)


def hour_bucket(started_at: datetime) -> datetime:
    utc = started_at.astimezone(UTC)
    return utc.replace(minute=0, second=0, microsecond=0)


def freshness_seconds(latest: datetime | None, *, now: datetime) -> int | None:
    if latest is None:
        return None
    return max(0, int((now - latest).total_seconds()))


def reference_from_evidence(value_ns: int | None, *, estimated: bool = False) -> dict[str, object]:
    if value_ns is None:
        return {
            "label": UNKNOWN,
            "status": UNKNOWN,
            "value_ms": None,
            "value_ns": None,
        }
    return {
        "label": "ESTIMATED" if estimated else "measured",
        "status": "ok",
        "value_ms": _ns_ms(value_ns),
        "value_ns": value_ns,
    }
