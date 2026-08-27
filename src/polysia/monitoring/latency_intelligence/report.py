"""Canonical latency_performance_intelligence object and renderers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape

from polysia.monitoring.latency_intelligence.contract import Confidence, PerformanceSpan
from polysia.monitoring.latency_intelligence.intelligence import (
    before_after,
    best_observed,
    budget_gap,
    critical_path,
    economic_correlation,
    freshness_seconds,
    percentiles,
    reference_from_evidence,
    trend,
    unsupported_stage_payload,
)
from polysia.monitoring.latency_intelligence.policy import (
    PERFORMANCE_CONTRACT_VERSION,
    PERFORMANCE_POLICY_VERSION,
    UNKNOWN,
    LatencyPolicy,
)
from polysia.storage.latency_telemetry import LatencyTelemetryStore

CANONICAL_SECTIONS: tuple[str, ...] = (
    "identity",
    "infrastructure",
    "source_detection",
    "network",
    "venue",
    "application",
    "execution",
    "end_to_end",
    "critical_path",
    "baselines",
    "budgets",
    "bottlenecks",
    "economic_impact",
    "telemetry_health",
    "confidence",
)


def insufficient_report(
    *,
    identity: dict[str, object] | None = None,
    health: dict[str, object] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    moment = generated_at or datetime.now(UTC)
    unknown_metric = {
        "confidence": Confidence.INSUFFICIENT_DATA.value,
        "p50_ms": None,
        "p50_ns": None,
        "p95_ms": None,
        "p95_ns": None,
        "p99_ms": None,
        "p99_ns": None,
        "sample_count": 0,
        "status": "INSUFFICIENT_DATA",
    }
    return {
        "application": {"poll": unknown_metric, "unsupported": unsupported_stage_payload()},
        "baselines": {
            "actual": unknown_metric,
            "best_observed": {
                "confidence": Confidence.INSUFFICIENT_DATA.value,
                "status": "INSUFFICIENT_DATA",
                "value_ms": None,
                "value_ns": None,
            },
            "reference": reference_from_evidence(None),
        },
        "bottlenecks": {
            "primary": None,
            "status": "INSUFFICIENT_DATA",
        },
        "budgets": {},
        "confidence": Confidence.INSUFFICIENT_DATA.value,
        "critical_path": {
            "primary_bottleneck": None,
            "stages": [],
            "status": "INSUFFICIENT_DATA",
            "total_ms": None,
            "total_ns": None,
            "trace_id": UNKNOWN,
        },
        "economic_impact": {
            "confidence": Confidence.INSUFFICIENT_DATA.value,
            "note": "correlation_not_causation",
            "status": "INSUFFICIENT_DATA",
        },
        "end_to_end": unknown_metric,
        "execution": unsupported_stage_payload(),
        "generated_at": moment.isoformat(),
        "identity": identity or _unknown_identity(),
        "infrastructure": {
            "docker_versus_native": {
                "status": "not_run",
                "verdict": "INSUFFICIENT_DATA",
            }
        },
        "network": unknown_metric,
        "performance_contract_version": PERFORMANCE_CONTRACT_VERSION,
        "policy_version": PERFORMANCE_POLICY_VERSION,
        "source_detection": {
            "source_api_lag_is_not_network": True,
            "source_to_observation": unknown_metric,
        },
        "telemetry_health": health or {"status": "UNKNOWN"},
        "venue": unknown_metric,
    }


def build_latency_performance_intelligence(
    store: LatencyTelemetryStore,
    *,
    policy: LatencyPolicy | None = None,
    now: datetime | None = None,
    health: dict[str, object] | None = None,
    economic_pairs: list[tuple[int, float]] | None = None,
    previous_deploy_sha: str | None = None,
) -> dict[str, object]:
    policy = policy or LatencyPolicy()
    moment = now or datetime.now(UTC)
    try:
        spans = store.load_spans(limit=20_000)
        measurements = store.load_measurements(limit=20_000)
        stored_health = store.load_health()
    except Exception:
        return insufficient_report(health=health, generated_at=moment)
    if not spans and not measurements:
        return insufficient_report(
            health=health or _health_view(stored_health, health, moment),
            generated_at=moment,
        )
    identity = _identity_from_spans(spans)
    by_operation: dict[str, list[int]] = {}
    latest_by_operation: dict[str, datetime] = {}
    deploys: set[str] = set()
    for span in spans:
        if span.duration_ns is None:
            continue
        by_operation.setdefault(span.operation, []).append(span.duration_ns)
        latest_by_operation[span.operation] = max(
            latest_by_operation.get(span.operation, span.started_at_utc),
            span.started_at_utc,
        )
        deploys.add(span.deploy_sha)
    by_kind: dict[str, list[int]] = {}
    for row in measurements:
        value = row.get("value_ns")
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        by_kind.setdefault(str(row["kind"]), []).append(value)

    deploy_consistent = len(deploys) <= 1
    poll_samples = by_operation.get("poll", [])
    end_to_end = percentiles(
        poll_samples,
        policy=policy,
        freshness_seconds=freshness_seconds(latest_by_operation.get("poll"), now=moment),
        deploy_consistent=deploy_consistent,
    )
    application: dict[str, object] = {
        name: percentiles(
            samples,
            policy=policy,
            freshness_seconds=freshness_seconds(latest_by_operation.get(name), now=moment),
            deploy_consistent=deploy_consistent,
        ).to_dict()
        for name, samples in sorted(by_operation.items())
    }
    if "persistence" in application and "db_write" not in by_operation:
        application["db_write"] = application["persistence"]
    application["unsupported"] = unsupported_stage_payload()
    source = percentiles(
        by_kind.get("source_to_observation_ms", []),
        policy=policy,
        deploy_consistent=deploy_consistent,
    )
    network = percentiles(
        by_kind.get("http_total_duration_ms", []),
        policy=policy,
        deploy_consistent=deploy_consistent,
    )
    venue = percentiles(
        by_kind.get("request_duration_ms", []),
        policy=policy,
        deploy_consistent=deploy_consistent,
    )
    traces = _group_traces(spans)
    path = critical_path(max(traces.values(), key=len) if traces else ())
    observed = best_observed(
        poll_samples,
        policy=policy,
        window_start=min((span.started_at_utc for span in spans), default=None),
        window_end=max((span.started_at_utc for span in spans), default=None),
        deploy_sha=str(identity.get("deploy_sha", UNKNOWN)),
        host_id=str(identity.get("host_id", UNKNOWN)),
    )
    budgets = {
        operation: budget_gap(
            percentiles(samples, policy=policy).p50_ns,
            operation=operation,
            policy=policy,
            confidence=percentiles(samples, policy=policy).confidence,
        )
        for operation, samples in sorted(by_operation.items())
        if operation in policy.stage_budgets_ns
    }
    previous_samples = [
        span.duration_ns
        for span in spans
        if span.operation == "poll"
        and span.duration_ns is not None
        and previous_deploy_sha
        and span.deploy_sha == previous_deploy_sha
    ]
    current_samples = [
        span.duration_ns
        for span in spans
        if span.operation == "poll"
        and span.duration_ns is not None
        and span.deploy_sha == identity.get("deploy_sha")
    ]
    comparison = before_after(
        previous_samples,
        current_samples,
        policy=policy,
        before_deploy=previous_deploy_sha or UNKNOWN,
        after_deploy=str(identity.get("deploy_sha", UNKNOWN)),
    )
    network_detail = {
        **network.to_dict(),
        "dns_duration_ms": percentiles(by_kind.get("dns_duration_ms", []), policy=policy).to_dict(),
        "tcp_connect_duration_ms": percentiles(
            by_kind.get("tcp_connect_duration_ms", []), policy=policy
        ).to_dict(),
        "tls_handshake_duration_ms": percentiles(
            by_kind.get("tls_handshake_duration_ms", []), policy=policy
        ).to_dict(),
        "ttfb_ms": percentiles(by_kind.get("ttfb_ms", []), policy=policy).to_dict(),
        "websocket_rtt_ms": {
            "confidence": Confidence.INSUFFICIENT_DATA.value,
            "status": "UNKNOWN",
            "note": "websocket_not_used_in_current_runtime",
            "p50_ms": None,
            "p50_ns": None,
            "sample_count": 0,
        },
    }
    report = {
        "application": application,
        "baselines": {
            "actual": end_to_end.to_dict(),
            "best_observed": observed,
            "before_after": comparison,
            "reference": reference_from_evidence(None),
            "trend": trend(poll_samples),
        },
        "bottlenecks": {
            "primary": path.primary_bottleneck,
            "status": path.status,
        },
        "budgets": budgets,
        "confidence": end_to_end.confidence.value,
        "critical_path": path.to_dict(),
        "economic_impact": economic_correlation(economic_pairs or [], policy=policy),
        "end_to_end": end_to_end.to_dict(),
        "execution": unsupported_stage_payload(),
        "generated_at": moment.isoformat(),
        "identity": identity,
        "infrastructure": {
            "docker_versus_native": {
                "status": "not_run",
                "verdict": "INSUFFICIENT_DATA",
            },
            "host_id": identity.get("host_id"),
            "image_digest": identity.get("image_digest"),
            "provider": identity.get("provider"),
            "region": identity.get("region"),
            "runtime_version": identity.get("runtime_version"),
        },
        "network": network_detail,
        "performance_contract_version": PERFORMANCE_CONTRACT_VERSION,
        "policy_version": PERFORMANCE_POLICY_VERSION,
        "source_detection": {
            "poll_wait_component": percentiles(
                by_kind.get("poll_wait_component_ms", []), policy=policy
            ).to_dict(),
            "source_api_lag_is_not_network": True,
            "source_to_observation": source.to_dict(),
        },
        "telemetry_health": _health_view(stored_health, health, moment),
        "venue": venue.to_dict(),
    }
    return report


def render_latency_report_json(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def render_latency_report_markdown(report: dict[str, object]) -> str:
    identity = _mapping(report.get("identity"))
    end_to_end = _mapping(report.get("end_to_end"))
    path = _mapping(report.get("critical_path"))
    health = _mapping(report.get("telemetry_health"))
    source = _mapping(_mapping(report.get("source_detection")).get("source_to_observation"))
    return "\n".join(
        (
            "# PolySia Latency & Performance Intelligence",
            "",
            f"- Generated at: {report.get('generated_at')}",
            f"- Contract: {report.get('performance_contract_version')}",
            f"- Policy: {report.get('policy_version')}",
            f"- Confidence: {report.get('confidence')}",
            f"- Host: {identity.get('host_id')}",
            f"- Deploy: {identity.get('deploy_sha')}",
            f"- Venue: {identity.get('venue_id')}",
            "",
            "## End to end",
            "",
            _metric_table(end_to_end),
            "",
            "## Source to observation (not network RTT)",
            "",
            _metric_table(source),
            "",
            "## Critical path",
            "",
            f"- Status: {path.get('status')}",
            f"- Primary bottleneck: {path.get('primary_bottleneck')}",
            f"- Total ms: {path.get('total_ms')}",
            "",
            "## Telemetry health",
            "",
            _metric_table(health),
            "",
            "Financial records remain authoritative. Telemetry is disposable.",
            "",
        )
    )


def render_latency_report_html(report: dict[str, object]) -> str:
    identity = _mapping(report.get("identity"))
    sections = {
        "Identity": identity,
        "End to end": _mapping(report.get("end_to_end")),
        "Source detection": _mapping(report.get("source_detection")),
        "Network": _mapping(report.get("network")),
        "Venue": _mapping(report.get("venue")),
        "Critical path": _mapping(report.get("critical_path")),
        "Baselines": _mapping(report.get("baselines")),
        "Bottlenecks": _mapping(report.get("bottlenecks")),
        "Telemetry health": _mapping(report.get("telemetry_health")),
        "Confidence": {"confidence": report.get("confidence")},
    }
    body = "".join(
        f"<section><h2>{escape(title)}</h2><pre>{escape(_compact(values))}</pre></section>"
        for title, values in sections.items()
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>PolySia Latency Intelligence</title></head><body>"
        "<h1>PolySia Latency &amp; Performance Intelligence</h1>"
        f"<p>{escape(str(report.get('generated_at')))}</p>"
        f"{body}</body></html>"
    )


def _identity_from_spans(spans: tuple[PerformanceSpan, ...]) -> dict[str, object]:
    if not spans:
        return _unknown_identity()
    latest = max(spans, key=lambda item: item.started_at_utc)
    return {
        "configuration_version": latest.configuration_version,
        "deploy_sha": latest.deploy_sha,
        "host_id": latest.host_id,
        "image_digest": latest.image_digest,
        "policy_version": latest.policy_version,
        "provider": latest.provider,
        "region": latest.region,
        "runtime_version": latest.runtime_version,
        "venue_id": latest.venue_id,
    }


def _unknown_identity() -> dict[str, object]:
    return {
        "configuration_version": UNKNOWN,
        "deploy_sha": UNKNOWN,
        "host_id": UNKNOWN,
        "image_digest": UNKNOWN,
        "policy_version": PERFORMANCE_POLICY_VERSION,
        "provider": UNKNOWN,
        "region": UNKNOWN,
        "runtime_version": UNKNOWN,
        "venue_id": UNKNOWN,
    }


def _group_traces(spans: tuple[PerformanceSpan, ...]) -> dict[str, list[PerformanceSpan]]:
    grouped: dict[str, list[PerformanceSpan]] = {}
    for span in spans:
        grouped.setdefault(span.trace_id, []).append(span)
    return grouped


def _health_view(
    stored: dict[str, object],
    live: dict[str, object] | None,
    now: datetime,
) -> dict[str, object]:
    merged = dict(stored)
    if live:
        merged.update(live)
    written = merged.get("artifact_written_at_utc") or merged.get("last_successful_flush_utc")
    age = None
    if isinstance(written, str):
        try:
            parsed = datetime.fromisoformat(written)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age = max(0, int((now - parsed.astimezone(UTC)).total_seconds()))
        except ValueError:
            age = None
    return {
        "artifact_age_seconds": age,
        "buffer_capacity": merged.get("buffer_capacity"),
        "buffer_usage": merged.get("buffer_usage"),
        "dropped_measurements": merged.get("dropped_measurements"),
        "last_successful_flush": merged.get("last_successful_flush")
        or merged.get("last_successful_flush_utc"),
        "last_successful_probe": merged.get("last_successful_probe")
        or merged.get("last_successful_probe_utc"),
        "probe_failures": merged.get("probe_failures"),
        "status": merged.get("status") or "active",
        "telemetry_errors": merged.get("telemetry_errors"),
        "telemetry_write_duration_ns": merged.get("telemetry_write_duration_ns")
        or merged.get("last_telemetry_write_duration_ns"),
    }


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _metric_table(values: dict[str, object]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in sorted(values.items()))
    return "\n".join(("| Field | Value |", "| --- | --- |", rows))


def _compact(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)
