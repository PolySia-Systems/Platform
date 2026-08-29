"""Isolated SQLite persistence for observational latency telemetry."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polysia.monitoring.latency_intelligence.contract import (
    PerformanceMeasurement,
    PerformanceSpan,
)
from polysia.monitoring.latency_intelligence.policy import (
    LATENCY_TELEMETRY_SCHEMA_VERSION,
    PERFORMANCE_POLICY_VERSION,
    LatencyPolicy,
)

LATENCY_TELEMETRY_SCHEMA_PATH = Path(__file__).with_name("latency_telemetry_schema.sql")
LATENCY_TELEMETRY_FILENAME = "wallet-intelligence-latency.sqlite3"
_COPY_TABLES = (
    "latency_telemetry_metadata",
    "latency_spans",
    "latency_measurements",
    "latency_aggregates",
    "latency_telemetry_health",
)


class LatencyTelemetryStoreError(RuntimeError):
    """Sanitized telemetry persistence failure. Never wraps financial errors."""


class LatencyTelemetryStore:
    def __init__(self, path: str | Path, *, policy: LatencyPolicy | None = None) -> None:
        self._path = Path(path)
        self._policy = policy or LatencyPolicy()

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        connection = self._connect()
        try:
            ensure_latency_telemetry_schema(connection, policy_version=self._policy.policy_version)
            connection.commit()
        finally:
            connection.close()

    def insert_batch(
        self,
        spans: Iterable[PerformanceSpan],
        measurements: Iterable[PerformanceMeasurement],
        *,
        health: dict[str, object],
    ) -> int:
        """Insert one bounded batch. Raises on busy/locked so callers can drop."""

        span_rows = tuple(spans)
        measurement_rows = tuple(measurements)
        connection = self._connect()
        try:
            ensure_latency_telemetry_schema(connection, policy_version=self._policy.policy_version)
            connection.execute("BEGIN IMMEDIATE")
            inserted = 0
            for span in span_rows:
                connection.execute(
                    "INSERT OR IGNORE INTO latency_spans ("
                    "span_id, trace_id, parent_span_id, performance_contract_version, "
                    "component, operation, status, duration_ns, started_at_utc, venue_id, "
                    "endpoint_id, host_id, provider, region, deploy_sha, runtime_version, "
                    "image_digest, configuration_version, policy_version, poll_run_id, "
                    "experiment_id, recorded_at_utc"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    _span_params(span),
                )
                inserted += connection.execute("SELECT changes()").fetchone()[0]
            for item in measurement_rows:
                connection.execute(
                    "INSERT OR IGNORE INTO latency_measurements ("
                    "measurement_id, kind, status, value_ns, started_at_utc, venue_id, "
                    "endpoint_id, host_id, provider, region, deploy_sha, runtime_version, "
                    "image_digest, configuration_version, policy_version, poll_run_id, "
                    "experiment_id, recorded_at_utc"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    _measurement_params(item),
                )
                inserted += connection.execute("SELECT changes()").fetchone()[0]
            _upsert_health(connection, health)
            connection.commit()
            return inserted
        except sqlite3.OperationalError:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cleanup(self, *, now: datetime | None = None) -> dict[str, int]:
        moment = _utc(now or datetime.now(UTC))
        detail_cutoff = _iso(moment - timedelta(days=self._policy.detail_retention_days))
        aggregate_cutoff = _iso(moment - timedelta(days=self._policy.aggregate_retention_days))
        limit = self._policy.cleanup_batch_size
        connection = self._connect()
        try:
            ensure_latency_telemetry_schema(connection, policy_version=self._policy.policy_version)
            connection.execute("BEGIN IMMEDIATE")
            spans_deleted = _bounded_delete(
                connection,
                "latency_spans",
                "span_id",
                "started_at_utc",
                detail_cutoff,
                limit,
            )
            measurements_deleted = _bounded_delete(
                connection,
                "latency_measurements",
                "measurement_id",
                "started_at_utc",
                detail_cutoff,
                limit,
            )
            aggregates_deleted = _bounded_delete(
                connection,
                "latency_aggregates",
                "rowid",
                "bucket_start_utc",
                aggregate_cutoff,
                limit,
            )
            connection.commit()
        except sqlite3.OperationalError:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {
            "aggregates_deleted": aggregates_deleted,
            "measurements_deleted": measurements_deleted,
            "spans_deleted": spans_deleted,
        }

    def upsert_aggregates(self, rows: Iterable[dict[str, object]]) -> None:
        connection = self._connect()
        try:
            ensure_latency_telemetry_schema(connection, policy_version=self._policy.policy_version)
            connection.execute("BEGIN IMMEDIATE")
            for row in rows:
                connection.execute(
                    "INSERT OR REPLACE INTO latency_aggregates ("
                    "bucket_start_utc, operation, deploy_sha, host_id, sample_count, "
                    "p50_ns, p95_ns, p99_ns, variance_ns2, best_observed_ns, confidence, "
                    "policy_version, recorded_at_utc"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row["bucket_start_utc"],
                        row["operation"],
                        row["deploy_sha"],
                        row["host_id"],
                        _as_int(row["sample_count"]),
                        row.get("p50_ns"),
                        row.get("p95_ns"),
                        row.get("p99_ns"),
                        row.get("variance_ns2"),
                        row.get("best_observed_ns"),
                        row["confidence"],
                        row.get("policy_version") or self._policy.policy_version,
                        row["recorded_at_utc"],
                    ),
                )
            connection.commit()
        except sqlite3.OperationalError:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load_spans(
        self,
        *,
        since_utc: datetime | None = None,
        operation: str | None = None,
        limit: int = 10_000,
    ) -> tuple[PerformanceSpan, ...]:
        connection = self._connect(read_only=True)
        try:
            clauses = ["1 = 1"]
            params: list[object] = []
            if since_utc is not None:
                clauses.append("started_at_utc >= ?")
                params.append(_iso(_utc(since_utc)))
            if operation is not None:
                clauses.append("operation = ?")
                params.append(operation)
            params.append(limit)
            rows = connection.execute(
                "SELECT * FROM latency_spans WHERE "
                + " AND ".join(clauses)
                + " ORDER BY started_at_utc ASC LIMIT ?",
                params,
            ).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return ()
            raise
        finally:
            connection.close()
        return tuple(_span_from_row(row) for row in rows)

    def load_measurements(
        self,
        *,
        kind: str | None = None,
        since_utc: datetime | None = None,
        limit: int = 10_000,
    ) -> tuple[dict[str, object], ...]:
        connection = self._connect(read_only=True)
        try:
            clauses = ["1 = 1"]
            params: list[object] = []
            if kind is not None:
                clauses.append("kind = ?")
                params.append(kind)
            if since_utc is not None:
                clauses.append("started_at_utc >= ?")
                params.append(_iso(_utc(since_utc)))
            params.append(limit)
            rows = connection.execute(
                "SELECT * FROM latency_measurements WHERE "
                + " AND ".join(clauses)
                + " ORDER BY started_at_utc ASC LIMIT ?",
                params,
            ).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return ()
            raise
        finally:
            connection.close()
        return tuple(dict(row) for row in rows)

    def load_health(self) -> dict[str, object]:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM latency_telemetry_health WHERE singleton = 1"
            ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return {}
            raise
        finally:
            connection.close()
        return {} if row is None else dict(row)

    def mark_artifact_written(self, *, written_at: datetime) -> None:
        connection = self._connect()
        try:
            ensure_latency_telemetry_schema(connection, policy_version=self._policy.policy_version)
            _upsert_health(
                connection,
                {"artifact_written_at_utc": _iso(_utc(written_at))},
            )
            connection.commit()
        except sqlite3.OperationalError:
            connection.rollback()
            raise
        finally:
            connection.close()

    def financial_table_names(self) -> frozenset[str]:
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        finally:
            connection.close()
        return frozenset(str(row[0]) for row in rows)

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                f"{self._path.resolve().as_uri()}?mode=ro", uri=True, timeout=0
            )
        else:
            connection = sqlite3.connect(self._path, timeout=0)
        connection.row_factory = sqlite3.Row
        connection.isolation_level = None
        connection.execute("PRAGMA busy_timeout = 0")
        if read_only:
            connection.execute("PRAGMA query_only = ON")
        return connection


def ensure_latency_telemetry_schema(
    connection: sqlite3.Connection,
    *,
    policy_version: str = PERFORMANCE_POLICY_VERSION,
) -> None:
    """Idempotent additive migration. Does not touch financial tables."""

    connection.executescript(LATENCY_TELEMETRY_SCHEMA_PATH.read_text(encoding="utf-8"))
    connection.execute(
        "INSERT OR IGNORE INTO latency_telemetry_metadata "
        "(schema_version, initialized_at, policy_version) VALUES (?, ?, ?)",
        (LATENCY_TELEMETRY_SCHEMA_VERSION, _iso(datetime.now(UTC)), policy_version),
    )
    rows = connection.execute(
        "SELECT schema_version FROM latency_telemetry_metadata"
    ).fetchall()
    if len(rows) != 1 or int(rows[0][0]) != LATENCY_TELEMETRY_SCHEMA_VERSION:
        raise LatencyTelemetryStoreError("Latency telemetry schema version is unsupported.")


def default_latency_telemetry_path(financial_database: Path) -> Path:
    """Place observational telemetry beside the financial database, never inside it."""

    return Path(financial_database).with_name(LATENCY_TELEMETRY_FILENAME)


def copy_latency_telemetry_from_financial(
    source: Path,
    destination: Path,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Copy existing telemetry out of the financial file without modifying it.

    The financial database is opened read-only. Destination writes are transactional
    and idempotent (`INSERT OR IGNORE`). After a successful copy, later restarts
    skip the data scan via `latency_telemetry_copy_state` and never rewrite sidecar
    health or newer sidecar rows.
    """

    source = Path(source)
    destination = Path(destination)
    copied = {table: 0 for table in _COPY_TABLES}
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file() or source.resolve() == destination.resolve():
        LatencyTelemetryStore(destination).initialize()
        return copied

    source_connection = sqlite3.connect(
        f"{source.resolve().as_uri()}?mode=ro",
        uri=True,
        timeout=0,
    )
    source_connection.row_factory = sqlite3.Row
    try:
        source_connection.execute("PRAGMA query_only = ON")
        source_tables = {
            str(row[0])
            for row in source_connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not source_tables.intersection(_COPY_TABLES):
            LatencyTelemetryStore(destination).initialize()
            return copied
        destination_connection = sqlite3.connect(destination, timeout=0)
        destination_connection.isolation_level = None
        try:
            ensure_latency_telemetry_schema(destination_connection)
            destination_connection.execute("BEGIN IMMEDIATE")
            fingerprint = str(source.resolve())
            existing_state = destination_connection.execute(
                "SELECT span_count, measurement_count FROM latency_telemetry_copy_state "
                "WHERE source_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing_state is not None:
                copied["latency_spans"] = int(existing_state[0])
                copied["latency_measurements"] = int(existing_state[1])
                destination_connection.commit()
                return copied
            dest_tables = {
                str(row[0])
                for row in destination_connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for table in _COPY_TABLES:
                if table not in source_tables or table not in dest_tables:
                    continue
                source_columns = [
                    str(row[1])
                    for row in source_connection.execute(f'PRAGMA table_info("{table}")')
                ]
                dest_columns = {
                    str(row[1])
                    for row in destination_connection.execute(
                        f'PRAGMA table_info("{table}")'
                    )
                }
                columns = [column for column in source_columns if column in dest_columns]
                if not columns:
                    continue
                column_sql = ", ".join(f'"{column}"' for column in columns)
                placeholders = ", ".join("?" for _ in columns)
                rows = list(
                    source_connection.execute(f'SELECT {column_sql} FROM "{table}"')
                )
                destination_connection.executemany(
                    f'INSERT OR IGNORE INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                    rows,
                )
                copied[table] = len(rows)
            moment = _iso(_utc(now or datetime.now(UTC)))
            destination_connection.execute(
                "INSERT OR REPLACE INTO latency_telemetry_copy_state ("
                "source_fingerprint, copied_at, span_count, measurement_count"
                ") VALUES (?, ?, ?, ?)",
                (
                    fingerprint,
                    moment,
                    copied.get("latency_spans", 0),
                    copied.get("latency_measurements", 0),
                ),
            )
            destination_connection.commit()
        except sqlite3.OperationalError:
            with suppress(sqlite3.Error):
                destination_connection.rollback()
            raise
        finally:
            destination_connection.close()
    finally:
        source_connection.close()
    return copied


def _bounded_delete(
    connection: sqlite3.Connection,
    table: str,
    key: str,
    column: str,
    cutoff: str,
    limit: int,
) -> int:
    cursor = connection.execute(
        f"DELETE FROM {table} WHERE {key} IN ("
        f"SELECT {key} FROM {table} WHERE {column} < ? ORDER BY {column} ASC LIMIT ?"
        ")",
        (cutoff, limit),
    )
    return int(cursor.rowcount or 0)


def _upsert_health(connection: sqlite3.Connection, health: dict[str, object]) -> None:
    existing = connection.execute(
        "SELECT * FROM latency_telemetry_health WHERE singleton = 1"
    ).fetchone()
    current = {} if existing is None else dict(existing)
    merged = {
        "singleton": 1,
        "telemetry_errors": _as_int(
            health.get("telemetry_errors", current.get("telemetry_errors", 0))
        ),
        "dropped_measurements": _as_int(
            health.get("dropped_measurements", current.get("dropped_measurements", 0))
        ),
        "buffer_capacity": _as_int(
            health.get("buffer_capacity", current.get("buffer_capacity", 0))
        ),
        "buffer_usage": _as_int(
            health.get("buffer_usage", current.get("buffer_usage", 0))
        ),
        "last_successful_flush_utc": health.get(
            "last_successful_flush_utc", current.get("last_successful_flush_utc")
        ),
        "last_telemetry_write_duration_ns": health.get(
            "last_telemetry_write_duration_ns",
            current.get("last_telemetry_write_duration_ns"),
        ),
        "probe_failures": _as_int(health.get("probe_failures", current.get("probe_failures", 0))),
        "last_successful_probe_utc": health.get(
            "last_successful_probe_utc", current.get("last_successful_probe_utc")
        ),
        "artifact_written_at_utc": health.get(
            "artifact_written_at_utc", current.get("artifact_written_at_utc")
        ),
    }
    connection.execute(
        "INSERT OR REPLACE INTO latency_telemetry_health ("
        "singleton, telemetry_errors, dropped_measurements, buffer_capacity, "
        "buffer_usage, last_successful_flush_utc, last_telemetry_write_duration_ns, "
        "probe_failures, last_successful_probe_utc, artifact_written_at_utc"
        ") VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            1,
            merged["telemetry_errors"],
            merged["dropped_measurements"],
            merged["buffer_capacity"],
            merged["buffer_usage"],
            merged["last_successful_flush_utc"],
            merged["last_telemetry_write_duration_ns"],
            merged["probe_failures"],
            merged["last_successful_probe_utc"],
            merged["artifact_written_at_utc"],
        ),
    )


def _span_params(span: PerformanceSpan) -> tuple[object, ...]:
    return (
        span.span_id,
        span.trace_id,
        span.parent_span_id,
        span.performance_contract_version,
        span.component,
        span.operation,
        span.status,
        span.duration_ns,
        _iso(span.started_at_utc),
        span.venue_id,
        span.endpoint_id,
        span.host_id,
        span.provider,
        span.region,
        span.deploy_sha,
        span.runtime_version,
        span.image_digest,
        span.configuration_version,
        span.policy_version,
        span.poll_run_id,
        span.experiment_id,
        _iso(datetime.now(UTC)),
    )


def _measurement_params(item: PerformanceMeasurement) -> tuple[object, ...]:
    identity = item.identity
    return (
        item.measurement_id,
        item.kind,
        item.status,
        item.value_ns,
        _iso(item.started_at_utc),
        identity.venue_id,
        item.endpoint_id,
        identity.host_id,
        identity.provider,
        identity.region,
        identity.deploy_sha,
        identity.runtime_version,
        identity.image_digest,
        identity.configuration_version,
        identity.policy_version,
        item.poll_run_id,
        item.experiment_id,
        _iso(datetime.now(UTC)),
    )


def _span_from_row(row: sqlite3.Row) -> PerformanceSpan:
    return PerformanceSpan(
        performance_contract_version=str(row["performance_contract_version"]),
        trace_id=str(row["trace_id"]),
        span_id=str(row["span_id"]),
        parent_span_id=None if row["parent_span_id"] is None else str(row["parent_span_id"]),
        component=str(row["component"]),
        operation=str(row["operation"]),
        status=str(row["status"]),
        duration_ns=None if row["duration_ns"] is None else int(row["duration_ns"]),
        started_at_utc=_parse(str(row["started_at_utc"])),
        venue_id=_optional_text(row["venue_id"]),
        endpoint_id=None if row["endpoint_id"] is None else str(row["endpoint_id"]),
        host_id=_optional_text(row["host_id"]),
        provider=_optional_text(row["provider"]),
        region=_optional_text(row["region"]),
        deploy_sha=_optional_text(row["deploy_sha"]),
        runtime_version=_optional_text(row["runtime_version"]),
        image_digest=_optional_text(row["image_digest"]),
        configuration_version=_optional_text(row["configuration_version"]),
        policy_version=_optional_text(row["policy_version"]),
        poll_run_id=None if row["poll_run_id"] is None else str(row["poll_run_id"]),
        experiment_id=None if row["experiment_id"] is None else str(row["experiment_id"]),
    )


def _optional_text(value: object) -> str:
    from polysia.monitoring.latency_intelligence.policy import UNKNOWN

    if value is None:
        return UNKNOWN
    text = str(value).strip()
    return text if text else UNKNOWN


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return int(str(value))
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
