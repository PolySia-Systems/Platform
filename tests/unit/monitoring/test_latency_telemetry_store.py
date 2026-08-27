from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polysia.monitoring.latency_intelligence.contract import (
    PerformanceMeasurement,
    PerformanceSpan,
    RuntimeIdentity,
)
from polysia.monitoring.latency_intelligence.policy import (
    PERFORMANCE_CONTRACT_VERSION,
    LatencyPolicy,
)
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from polysia.storage.dynamic_shadow import DynamicShadowRepository
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


def _financial_counts(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'latency_%' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
    finally:
        connection.close()


def test_telemetry_migration_is_additive_and_keeps_cs_schema_v4(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()

    connection = sqlite3.connect(database)
    try:
        cs_version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
        telemetry_version = connection.execute(
            "SELECT schema_version FROM latency_telemetry_metadata"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()

    assert cs_version == 4
    assert telemetry_version == 1
    assert "latency_spans" in tables
    assert "continuous_shadow_ledger" in tables


def test_telemetry_cleanup_does_not_modify_financial_tables(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()
    before = _financial_counts(database)
    store = LatencyTelemetryStore(
        database,
        policy=LatencyPolicy(detail_retention_days=1, cleanup_batch_size=10),
    )
    old = datetime.now(UTC) - timedelta(days=8)
    store.insert_batch(
        (_span(span_id="old", started_at_utc=old),),
        (),
        health={"dropped_measurements": 0, "buffer_capacity": 8, "buffer_usage": 0},
    )
    deleted = store.cleanup(now=datetime.now(UTC))
    after = _financial_counts(database)
    connection = sqlite3.connect(database)
    try:
        remaining = connection.execute("SELECT COUNT(*) FROM latency_spans").fetchone()[0]
        cs_version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
    finally:
        connection.close()

    assert deleted["spans_deleted"] >= 1
    assert remaining == 0
    assert cs_version == 4
    assert after == before


def test_sqlite_busy_drops_telemetry_without_retry_delay(tmp_path: Path) -> None:
    database = tmp_path / "telemetry.sqlite3"
    store = LatencyTelemetryStore(database)
    store.initialize()
    locker = sqlite3.connect(database, timeout=0)
    locker.execute("BEGIN EXCLUSIVE")
    recorder = LatencyRecorder(store, RuntimeIdentity())
    recorder.begin_trace(operation="poll")
    with recorder.span(component="application", operation="poll"):
        pass
    recorder.flush()
    health = recorder.health()
    locker.rollback()
    locker.close()
    assert health["dropped_measurements"] >= 1 or health["telemetry_errors"] >= 1


def test_insert_batch_is_idempotent(tmp_path: Path) -> None:
    store = LatencyTelemetryStore(tmp_path / "db.sqlite3")
    store.initialize()
    span = _span()
    first = store.insert_batch((span,), (), health={"buffer_capacity": 4, "buffer_usage": 0})
    second = store.insert_batch((span,), (), health={"buffer_capacity": 4, "buffer_usage": 0})
    assert first == 1
    assert second == 0
    assert len(store.load_spans()) == 1


def test_measurement_unknown_is_null_not_zero(tmp_path: Path) -> None:
    store = LatencyTelemetryStore(tmp_path / "db.sqlite3")
    item = PerformanceMeasurement(
        measurement_id="m1",
        kind="websocket_rtt_ms",
        status="UNKNOWN",
        value_ns=None,
        started_at_utc=datetime.now(UTC),
        identity=RuntimeIdentity(),
        endpoint_id="polymarket:data-api",
    )
    store.insert_batch((), (item,), health={"buffer_capacity": 1, "buffer_usage": 0})
    loaded = store.load_measurements()[0]
    assert loaded["value_ns"] is None
    assert loaded["value_ns"] != 0
