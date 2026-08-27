from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from polysia.application.ports.latency_telemetry import NullLatencyRecorder
from polysia.monitoring.latency_intelligence.contract import RuntimeIdentity
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.storage.latency_telemetry import LatencyTelemetryStore


class _ExplodingStore(LatencyTelemetryStore):
    def insert_batch(self, *args: object, **kwargs: object) -> int:
        raise RuntimeError("sqlite busy")

    def initialize(self) -> None:
        return None

    def cleanup(self, *, now: datetime | None = None) -> dict[str, int]:
        raise RuntimeError("cleanup failed")


def test_telemetry_failure_does_not_raise_into_caller(tmp_path: Path) -> None:
    recorder = LatencyRecorder(_ExplodingStore(tmp_path / "x.sqlite3"), RuntimeIdentity())
    recorder.begin_trace(operation="poll")
    with recorder.span(component="application", operation="poll"):
        marker = "poll-body"
    recorder.flush()
    health = recorder.health()
    assert marker == "poll-body"
    assert health["dropped_measurements"] >= 1 or health["telemetry_errors"] >= 1


def test_disabled_recorder_is_a_no_op() -> None:
    recorder = NullLatencyRecorder()
    recorder.begin_trace(operation="poll")
    with recorder.span(component="application", operation="poll") as span_id:
        assert span_id == "UNKNOWN"
    recorder.record_measurement(
        kind="source_to_observation_ms",
        value_ns=12,
        started_at_utc=datetime.now(UTC),
    )
    recorder.flush()
    assert recorder.health()["status"] == "disabled"


def test_enabled_and_disabled_span_bodies_are_equivalent(tmp_path: Path) -> None:
    enabled = LatencyRecorder(
        LatencyTelemetryStore(tmp_path / "db.sqlite3"),
        RuntimeIdentity(),
    )
    disabled = NullLatencyRecorder()
    results: list[int] = []
    for recorder in (disabled, enabled):
        recorder.begin_trace(operation="poll")
        with recorder.span(component="application", operation="poll"):
            results.append(2 + 2)
        recorder.flush()
    assert results == [4, 4]
