"""Fail-open latency recorder. Never raises into the trading path."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Lock

from polysia.monitoring.latency_intelligence.buffer import BoundedTelemetryBuffer
from polysia.monitoring.latency_intelligence.contract import (
    PerformanceMeasurement,
    PerformanceSpan,
    RuntimeIdentity,
    SpanStatus,
    duration_ns_or_unknown,
)
from polysia.monitoring.latency_intelligence.policy import (
    PERFORMANCE_CONTRACT_VERSION,
    UNKNOWN,
    LatencyPolicy,
)
from polysia.storage.latency_telemetry import LatencyTelemetryStore, LatencyTelemetryStoreError

_BUFFER_ITEM = PerformanceSpan | PerformanceMeasurement


class LatencyRecorder:
    def __init__(
        self,
        store: LatencyTelemetryStore,
        identity: RuntimeIdentity,
        *,
        policy: LatencyPolicy | None = None,
        monotonic_ns: Callable[[], int] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._identity = identity.sanitized()
        self._policy = policy or LatencyPolicy()
        self._monotonic_ns = monotonic_ns or time.perf_counter_ns
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._buffer: BoundedTelemetryBuffer[_BUFFER_ITEM] = BoundedTelemetryBuffer(
            self._policy.buffer_capacity
        )
        self._lock = Lock()
        self._trace_id = UNKNOWN
        self._poll_run_id: str | None = None
        self._experiment_id: str | None = None
        self._errors = 0
        self._probe_failures = 0
        self._last_flush: datetime | None = None
        self._last_write_duration_ns: int | None = None
        self._last_probe: datetime | None = None

    @property
    def store(self) -> LatencyTelemetryStore:
        return self._store

    def begin_trace(self, *, operation: str) -> str:
        try:
            trace_id = uuid.uuid4().hex
            with self._lock:
                self._trace_id = trace_id
                self._poll_run_id = None
                self._experiment_id = None
            return trace_id
        except Exception:
            self._bump_errors()
            return UNKNOWN

    def bind_poll(self, *, poll_run_id: str | None, experiment_id: str | None) -> None:
        try:
            with self._lock:
                self._poll_run_id = poll_run_id
                self._experiment_id = experiment_id
        except Exception:
            self._bump_errors()

    @contextmanager
    def span(
        self,
        *,
        component: str,
        operation: str,
        parent_span_id: str | None = None,
        endpoint_id: str | None = None,
        venue_id: str | None = None,
    ) -> Iterator[str]:
        span_id = uuid.uuid4().hex
        started_wall = self._wall_clock()
        started_mono = self._monotonic_ns()
        status = SpanStatus.OK.value
        try:
            yield span_id
        except Exception:
            status = SpanStatus.ERROR.value
            raise
        finally:
            self._close_span(
                span_id=span_id,
                parent_span_id=parent_span_id,
                component=component,
                operation=operation,
                status=status,
                started_wall=started_wall,
                started_mono=started_mono,
                endpoint_id=endpoint_id,
                venue_id=venue_id,
            )

    def record_measurement(
        self,
        *,
        kind: str,
        value_ns: int | None,
        started_at_utc: datetime,
        endpoint_id: str | None = None,
        venue_id: str | None = None,
        status: str = "ok",
    ) -> None:
        try:
            duration = duration_ns_or_unknown(value_ns)
        except ValueError:
            self._bump_errors()
            return
        try:
            with self._lock:
                identity = self._identity
                poll_run_id = self._poll_run_id
                experiment_id = self._experiment_id
            item = PerformanceMeasurement(
                measurement_id=uuid.uuid4().hex,
                kind=kind,
                status=status,
                value_ns=duration,
                started_at_utc=started_at_utc,
                identity=_identity_with_venue(identity, venue_id),
                endpoint_id=_sanitize_endpoint(endpoint_id),
                poll_run_id=poll_run_id,
                experiment_id=experiment_id,
            )
            if not self._buffer.push(item):
                return
        except Exception:
            self._bump_errors()

    def record_probe_outcome(self, *, success: bool) -> None:
        try:
            with self._lock:
                if success:
                    self._last_probe = self._wall_clock()
                else:
                    self._probe_failures += 1
        except Exception:
            self._bump_errors()

    def flush(self) -> None:
        try:
            self._store.initialize()
        except Exception:
            self._bump_errors()
            self._drop_pending()
            return
        while True:
            batch = self._buffer.pop_batch(self._policy.flush_batch_size)
            if not batch:
                try:
                    self._store.cleanup()
                except sqlite3.OperationalError:
                    self._bump_errors()
                except LatencyTelemetryStoreError:
                    self._bump_errors()
                except Exception:
                    self._bump_errors()
                return
            spans = tuple(item for item in batch if isinstance(item, PerformanceSpan))
            measurements = tuple(
                item for item in batch if isinstance(item, PerformanceMeasurement)
            )
            started = self._monotonic_ns()
            try:
                self._store.insert_batch(spans, measurements, health=self._health_payload())
            except sqlite3.OperationalError:
                self._buffer.increment_dropped(len(batch))
                self._bump_errors()
                return
            except Exception:
                self._buffer.increment_dropped(len(batch))
                self._bump_errors()
                return
            elapsed = self._monotonic_ns() - started
            write_duration: int | None = elapsed
            if elapsed < 0:
                self._bump_errors()
                write_duration = None
            with self._lock:
                self._last_flush = self._wall_clock()
                self._last_write_duration_ns = write_duration

    def health(self) -> dict[str, object]:
        snapshot = self._buffer.snapshot()
        with self._lock:
            last_flush = self._last_flush
            last_probe = self._last_probe
            write_duration = self._last_write_duration_ns
            errors = self._errors
            probe_failures = self._probe_failures
        artifact_age = None
        if last_flush is not None:
            artifact_age = int((self._wall_clock() - last_flush).total_seconds())
        return {
            "artifact_age_seconds": artifact_age,
            "buffer_capacity": snapshot.capacity,
            "buffer_usage": snapshot.usage,
            "dropped_measurements": snapshot.dropped,
            "last_successful_flush": None if last_flush is None else last_flush.isoformat(),
            "last_successful_probe": None if last_probe is None else last_probe.isoformat(),
            "probe_failures": probe_failures,
            "status": "disabled" if snapshot.capacity == 0 else "active",
            "telemetry_errors": errors,
            "telemetry_write_duration_ns": write_duration,
        }

    def _close_span(
        self,
        *,
        span_id: str,
        parent_span_id: str | None,
        component: str,
        operation: str,
        status: str,
        started_wall: datetime,
        started_mono: int,
        endpoint_id: str | None,
        venue_id: str | None,
    ) -> None:
        try:
            duration = duration_ns_or_unknown(self._monotonic_ns() - started_mono)
        except ValueError:
            self._bump_errors()
            return
        try:
            with self._lock:
                trace_id = self._trace_id
                identity = self._identity
                poll_run_id = self._poll_run_id
                experiment_id = self._experiment_id
            if trace_id in {"", UNKNOWN}:
                trace_id = uuid.uuid4().hex
            parent = None if parent_span_id in {None, "", UNKNOWN} else parent_span_id
            span = PerformanceSpan(
                performance_contract_version=PERFORMANCE_CONTRACT_VERSION,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent,
                component=component,
                operation=operation,
                status=status,
                duration_ns=duration,
                started_at_utc=started_wall,
                venue_id=_identity_with_venue(identity, venue_id).venue_id,
                endpoint_id=_sanitize_endpoint(endpoint_id),
                host_id=identity.host_id,
                provider=identity.provider,
                region=identity.region,
                deploy_sha=identity.deploy_sha,
                runtime_version=identity.runtime_version,
                image_digest=identity.image_digest,
                configuration_version=identity.configuration_version,
                policy_version=identity.policy_version,
                poll_run_id=poll_run_id,
                experiment_id=experiment_id,
            )
            self._buffer.push(span)
        except Exception:
            self._bump_errors()

    def _health_payload(self) -> dict[str, object]:
        payload = self.health()
        return {
            "buffer_capacity": payload["buffer_capacity"],
            "buffer_usage": payload["buffer_usage"],
            "dropped_measurements": payload["dropped_measurements"],
            "last_successful_flush_utc": payload["last_successful_flush"],
            "last_successful_probe_utc": payload["last_successful_probe"],
            "last_telemetry_write_duration_ns": payload["telemetry_write_duration_ns"],
            "probe_failures": payload["probe_failures"],
            "telemetry_errors": payload["telemetry_errors"],
        }

    def _drop_pending(self) -> None:
        dropped = self._buffer.pop_batch(self._policy.buffer_capacity)
        if dropped:
            self._buffer.increment_dropped(len(dropped))

    def _bump_errors(self) -> None:
        with self._lock:
            self._errors += 1


def _identity_with_venue(identity: RuntimeIdentity, venue_id: str | None) -> RuntimeIdentity:
    if venue_id is None or not venue_id.strip():
        return identity
    return RuntimeIdentity(
        host_id=identity.host_id,
        provider=identity.provider,
        region=identity.region,
        deploy_sha=identity.deploy_sha,
        runtime_version=identity.runtime_version,
        image_digest=identity.image_digest,
        configuration_version=identity.configuration_version,
        policy_version=identity.policy_version,
        venue_id=venue_id.strip(),
    )


def _sanitize_endpoint(endpoint_id: str | None) -> str | None:
    if endpoint_id is None:
        return None
    text = endpoint_id.strip()
    if not text:
        return None
    lowered = text.lower()
    if any(token in lowered for token in ("http://", "https://", "?", "authorization", "0x")):
        return UNKNOWN
    return text
