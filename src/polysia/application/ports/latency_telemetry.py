"""Venue-neutral observational timing port.

Telemetry must never participate in financial authority. Implementations must
fail open: buffer overflow, SQLite busy, and probe errors drop measurements
instead of delaying or rolling back trading state.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol


class LatencyRecorderPort(Protocol):
    """Optional observational recorder injected beside Stage 4B runtime."""

    def begin_trace(self, *, operation: str) -> str:
        """Start a local trace and return its trace_id."""

    def bind_poll(self, *, poll_run_id: str | None, experiment_id: str | None) -> None:
        """Attach the current trace to a poll without joining financial rows."""

    def span(
        self,
        *,
        component: str,
        operation: str,
        parent_span_id: str | None = None,
        endpoint_id: str | None = None,
        venue_id: str | None = None,
    ) -> AbstractContextManager[str]:
        """Record one existing runtime boundary. Yields span_id."""

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
        """Record a derived duration. None means UNKNOWN, never zero-filled."""

    def flush(self) -> None:
        """Persist a bounded batch outside any financial transaction."""

    def health(self) -> dict[str, object]:
        """Return sanitized self-health counters."""


class NullLatencyRecorder:
    """No-op recorder used when telemetry is disabled."""

    def begin_trace(self, *, operation: str) -> str:
        return "UNKNOWN"

    def bind_poll(self, *, poll_run_id: str | None, experiment_id: str | None) -> None:
        return None

    def span(
        self,
        *,
        component: str,
        operation: str,
        parent_span_id: str | None = None,
        endpoint_id: str | None = None,
        venue_id: str | None = None,
    ) -> AbstractContextManager[str]:
        return _null_span()

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
        return None

    def flush(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {
            "artifact_age_seconds": None,
            "buffer_capacity": 0,
            "buffer_usage": 0,
            "dropped_measurements": 0,
            "last_successful_flush": None,
            "last_successful_probe": None,
            "probe_failures": 0,
            "status": "disabled",
            "telemetry_errors": 0,
            "telemetry_write_duration_ns": None,
        }


def _null_span() -> AbstractContextManager[str]:
    from contextlib import contextmanager

    @contextmanager
    def _span() -> Iterator[str]:
        yield "UNKNOWN"

    return _span()
