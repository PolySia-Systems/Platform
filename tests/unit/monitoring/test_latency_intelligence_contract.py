from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from polysia.monitoring.latency_intelligence.buffer import BoundedTelemetryBuffer
from polysia.monitoring.latency_intelligence.contract import (
    PerformanceSpan,
    RuntimeIdentity,
    duration_ns_or_unknown,
)
from polysia.monitoring.latency_intelligence.policy import (
    PERFORMANCE_CONTRACT_VERSION,
    UNKNOWN,
)
from polysia.monitoring.latency_intelligence.recorder import (
    LatencyRecorder,
    _sanitize_endpoint,
)
from polysia.monitoring.latency_intelligence.report import (
    CANONICAL_SECTIONS,
    insufficient_report,
    render_latency_report_html,
    render_latency_report_json,
    render_latency_report_markdown,
)
from polysia.storage.latency_telemetry import LatencyTelemetryStore


def _span(**overrides: object) -> PerformanceSpan:
    values: dict[str, object] = {
        "performance_contract_version": PERFORMANCE_CONTRACT_VERSION,
        "trace_id": "trace-1",
        "span_id": "span-1",
        "parent_span_id": None,
        "component": "application",
        "operation": "poll",
        "status": "ok",
        "duration_ns": 1_000,
        "started_at_utc": datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
        "venue_id": "polymarket",
        "endpoint_id": None,
        "host_id": "host-a",
        "provider": "hetzner",
        "region": "helsinki",
        "deploy_sha": "abc",
        "runtime_version": "3.14.6",
        "image_digest": "sha256:test",
        "configuration_version": "latency-intelligence-v0.1",
        "policy_version": "latency-intelligence-v0.1",
    }
    values.update(overrides)
    return PerformanceSpan(**values)  # type: ignore[arg-type]


def test_contract_rejects_negative_and_impossible_durations() -> None:
    with pytest.raises(ValueError):
        duration_ns_or_unknown(-1)
    with pytest.raises(ValueError):
        _span(duration_ns=-8)
    assert duration_ns_or_unknown(None) is None
    assert duration_ns_or_unknown(0) == 0


def test_missing_identity_is_unknown_never_zero() -> None:
    report = insufficient_report()
    assert report["end_to_end"]["p50_ms"] is None
    assert report["end_to_end"]["p50_ns"] is None
    assert report["execution"]["submit"]["status"] == "UNKNOWN"
    assert report["execution"]["submit"]["duration_ns"] is None
    assert report["network"]["status"] == "INSUFFICIENT_DATA"
    assert report["identity"]["host_id"] == UNKNOWN


def test_span_parent_cannot_equal_child() -> None:
    with pytest.raises(ValueError):
        _span(span_id="same", parent_span_id="same")


def test_bounded_buffer_drops_overflow_and_keeps_capacity() -> None:
    buffer: BoundedTelemetryBuffer[int] = BoundedTelemetryBuffer(2)
    assert buffer.push(1)
    assert buffer.push(2)
    assert buffer.push(3) is False
    snapshot = buffer.snapshot()
    assert snapshot.usage == 2
    assert snapshot.dropped == 1
    assert buffer.pop_batch(10) == (1, 2)


def test_recorder_rejects_negative_measurement_and_stays_fail_open(tmp_path: Path) -> None:
    store = LatencyTelemetryStore(tmp_path / "db.sqlite3")
    recorder = LatencyRecorder(store, RuntimeIdentity())
    recorder.begin_trace(operation="poll")
    recorder.record_measurement(
        kind="source_to_observation_ms",
        value_ns=-12,
        started_at_utc=datetime.now(UTC),
    )
    health = recorder.health()
    assert health["telemetry_errors"] >= 1
    recorder.flush()
    assert store.load_measurements() == ()


def test_canonical_report_sections_and_renderer_parity() -> None:
    report = insufficient_report()
    for section in CANONICAL_SECTIONS:
        assert section in report
    rendered_json = render_latency_report_json(report)
    markdown = render_latency_report_markdown(report)
    html = render_latency_report_html(report)
    assert report["confidence"] in rendered_json
    assert report["confidence"] in markdown
    assert report["confidence"] in html
    assert "INSUFFICIENT_DATA" in markdown
    assert "source_api_lag_is_not_network" in rendered_json


def test_endpoint_redaction_rejects_urls_and_addresses() -> None:
    assert _sanitize_endpoint("https://data-api.polymarket.com/trades?user=0xabc") == UNKNOWN
    assert _sanitize_endpoint("polymarket:data-api") == "polymarket:data-api"


def test_contract_module_is_venue_neutral() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "polysia"
        / "monitoring"
        / "latency_intelligence"
        / "contract.py"
    ).read_text(encoding="utf-8")
    assert "polymarket" not in source
    assert "polysia.adapters" not in source
