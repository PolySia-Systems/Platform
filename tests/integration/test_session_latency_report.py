"""Optional session recorder -> separate SQLite telemetry -> canonical report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from polysia.monitoring.latency_intelligence.contract import RuntimeIdentity
from polysia.monitoring.latency_intelligence.policy import LatencyPolicy
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.monitoring.latency_intelligence.report import (
    SESSION_STAGES,
    build_latency_performance_intelligence,
    financial_session_latency_view,
)
from polysia.monitoring.latency_intelligence.session import SessionLatency
from polysia.storage.latency_telemetry import LatencyTelemetryStore

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


class FrozenTelemetryStore(LatencyTelemetryStore):
    def cleanup(self, *, now: datetime | None = None) -> dict[str, int]:
        return super().cleanup(now=NOW if now is None else now)


def make_recorder(store: LatencyTelemetryStore, *, release: str = "release-a") -> LatencyRecorder:
    return LatencyRecorder(
        store,
        RuntimeIdentity(
            host_id="fixture-host", deploy_sha=release, configuration_version="fixture"
        ),
        wall_clock=lambda: NOW,
    )


def stage(view: dict, name: str) -> dict:
    return next(row for row in view["stages"] if row["stage"] == name)


def test_no_session_data_preserves_the_legacy_execution_contract(tmp_path: Path) -> None:
    store = FrozenTelemetryStore(tmp_path / "telemetry.sqlite3")
    store.initialize()
    empty = build_latency_performance_intelligence(store, now=NOW)
    assert "financial_session" not in empty["execution"]
    assert empty["execution"]["submit"]["status"] == "UNKNOWN"
    assert financial_session_latency_view(empty)["financial_event_denominator"] == "UNKNOWN"

    recorder = make_recorder(store)
    recorder.record_measurement(kind="http_total_duration_ms", value_ns=1_000, started_at_utc=NOW)
    recorder.flush()
    legacy = build_latency_performance_intelligence(store, now=NOW)
    assert legacy["execution"] == empty["execution"]
    assert financial_session_latency_view(legacy)["clock_quality"] == "UNKNOWN"


def test_real_report_exposes_recorded_stages_errors_missing_and_censored_spans(
    tmp_path: Path,
) -> None:
    store = FrozenTelemetryStore(tmp_path / "separate-telemetry.sqlite3")
    recorder = make_recorder(store)
    ticks = iter(range(0, 10_000_000_000, 1_000_000))
    latency = SessionLatency(recorder, clock=lambda: NOW, monotonic=lambda: next(ticks))
    for index in range(20):
        latency.bind(run_id="run-a", intent_id=f"intent-{index}")
        for name in SESSION_STAGES:
            if name == "source_to_observation":
                latency.record(name, 100_000_000, status="source_clock_quality_unknown")
            else:
                with latency.stage(name):
                    pass
    with pytest.raises(RuntimeError, match="fixture failure"), latency.stage("submit_to_ack"):
        raise RuntimeError("fixture failure")
    latency.record("submit_to_fill", None, status="censored_across_restart")
    latency.record("submit_to_finality", None, status="missing")
    latency.record("submit_to_ack", -1)
    recorder.flush()

    report = build_latency_performance_intelligence(store, now=NOW, session_run_id="run-a")
    view = financial_session_latency_view(report)
    assert view is report["execution"]["financial_session"]
    assert view["record_count"] == 124
    assert view["sample_count"] == 121
    assert view["missing_count"] == 3
    assert view["censored_count"] == 1
    assert view["error_count"] == 1
    assert view["unbound_record_count"] == 0
    assert view["bottleneck"] == "source_to_observation"
    assert view["window_start"] == view["window_end"] == NOW.isoformat()
    assert view["queue_pressure"] == view["ip_signer_capacity"] == "UNKNOWN"
    assert "not distinct orders" in view["denominator"]
    source = stage(view, "source_to_observation")
    assert source["p50_ms"] == 100
    assert source["confidence"] == "LOW"
    assert source["source_clock_unknown_count"] == 20
    assert stage(view, "submit_to_ack")["error_count"] == 1
    assert stage(view, "submit_to_ack")["clock_unhealthy_count"] == 1
    assert stage(view, "submit_to_fill")["censored_count"] == 1
    assert all(table.startswith("latency_") for table in store.financial_table_names())
    assert {row["experiment_id"] for row in store.load_measurements()} == {"run-a"}


@pytest.mark.parametrize("count", [19, 20, 100, 1000])
def test_session_report_reuses_the_existing_20_100_1000_sample_policy(
    tmp_path: Path,
    count: int,
) -> None:
    store = FrozenTelemetryStore(tmp_path / "telemetry.sqlite3")
    recorder = make_recorder(store)
    latency = SessionLatency(recorder, clock=lambda: NOW)
    latency.bind(run_id="run-a", intent_id="intent-a")
    for index in range(count):
        latency.record("submit_to_ack", 1_000_000 + index)
    recorder.flush()
    view = financial_session_latency_view(build_latency_performance_intelligence(store, now=NOW))
    ack = stage(view, "submit_to_ack")
    policy = LatencyPolicy()
    assert ack["sample_count"] == count
    assert (ack["p50_ns"] is not None) == (count >= policy.sample_p50_min)
    assert (ack["p95_ns"] is not None) == (count >= policy.sample_p95_min)
    assert (ack["p99_ns"] is not None) == (count >= policy.sample_p99_min)
    assert stage(view, "submit_to_finality")["record_count"] == 0
    assert stage(view, "submit_to_finality")["p50_ns"] is None


def test_run_filter_prevents_other_sessions_from_supplying_a_sample_threshold(
    tmp_path: Path,
) -> None:
    store = FrozenTelemetryStore(tmp_path / "telemetry.sqlite3")
    recorder = make_recorder(store)
    latency = SessionLatency(recorder, clock=lambda: NOW)
    for run in ("run-a", "run-b"):
        latency.bind(run_id=run, intent_id="intent-" + run)
        for _ in range(10):
            latency.record("submit_to_ack", 5_000_000)
    recorder.flush()
    scoped = build_latency_performance_intelligence(store, now=NOW, session_run_id="run-a")
    view = financial_session_latency_view(scoped)
    assert view["record_count"] == 10
    assert stage(view, "submit_to_ack")["p50_ns"] is None
    missing = build_latency_performance_intelligence(store, now=NOW, session_run_id="run-absent")
    assert "financial_session" not in missing["execution"]


def test_different_releases_do_not_create_pooled_session_percentiles(tmp_path: Path) -> None:
    store = FrozenTelemetryStore(tmp_path / "telemetry.sqlite3")
    for release in ("release-a", "release-b"):
        recorder = make_recorder(store, release=release)
        latency = SessionLatency(recorder, clock=lambda: NOW)
        latency.bind(run_id="run-a", intent_id=release)
        for _ in range(10):
            latency.record("submit_to_ack", 5_000_000)
        recorder.flush()
    view = financial_session_latency_view(build_latency_performance_intelligence(store, now=NOW))
    ack = stage(view, "submit_to_ack")
    assert ack["sample_count"] == 20
    assert ack["identity_segment_count"] == 2
    assert ack["identity_scope"] == "MIXED_IDENTITIES_NO_POOLED_PERCENTILES"
    assert ack["p50_ns"] is None


def test_missing_monotonic_clock_is_recorded_as_unknown_without_losing_the_body(
    tmp_path: Path,
) -> None:
    store = FrozenTelemetryStore(tmp_path / "telemetry.sqlite3")
    recorder = make_recorder(store)

    def broken_clock() -> int:
        raise RuntimeError("fixture clock failure")

    latency = SessionLatency(recorder, clock=lambda: NOW, monotonic=broken_clock)
    with latency.stage("decision_to_risk"):
        body_result = 2 + 2
    recorder.flush()
    view = financial_session_latency_view(build_latency_performance_intelligence(store, now=NOW))
    decision = stage(view, "decision_to_risk")
    assert body_result == 4
    assert decision["missing_count"] == decision["clock_unhealthy_count"] == 1
    assert decision["sample_count"] == 0


def test_binding_and_measurement_failures_stay_optional() -> None:
    class ExplodingRecorder:
        def begin_trace(self, **_kwargs: object) -> str:
            raise RuntimeError("fixture telemetry bind failure")

        def record_measurement(self, **_kwargs: object) -> None:
            raise RuntimeError("fixture telemetry write failure")

    latency = SessionLatency(ExplodingRecorder(), clock=lambda: NOW)  # type: ignore[arg-type]
    latency.bind(run_id="run-a", intent_id="intent-a")
    with latency.stage("submit_to_ack"):
        completed = True
    assert completed and latency.errors == 2
    with (
        pytest.raises(ValueError, match="financial failure"),
        latency.stage("decision_to_risk"),
    ):
        raise ValueError("financial failure")
