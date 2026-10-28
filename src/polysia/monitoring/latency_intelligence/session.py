"""Continuous-session timings through the existing optional telemetry recorder."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from time import monotonic_ns

from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder


class SessionLatency:
    def __init__(
        self,
        recorder: LatencyRecorder | None,
        *,
        clock: Callable[[], datetime],
        monotonic: Callable[[], int] = monotonic_ns,
    ) -> None:
        self.recorder, self.clock, self.monotonic = recorder, clock, monotonic
        self.errors = 0

    def bind(self, *, run_id: str, intent_id: str) -> None:
        """Bind optional observations to the durable identities, never grant authority."""
        if self.recorder is None:
            return
        try:
            if not run_id.strip() or not intent_id.strip():
                raise ValueError("session timing requires run and intent identities")
            self.recorder.begin_trace(operation="financial_session")
            self.recorder.bind_poll(poll_run_id=intent_id, experiment_id=run_id)
        except Exception:
            self.errors += 1

    def record(self, kind: str, value_ns: int | None, *, status: str = "ok") -> None:
        if self.recorder is None:
            return
        try:
            if value_ns is not None and (type(value_ns) is not int or value_ns < 0):
                value_ns, status = None, "clock_unhealthy"
            self.recorder.record_measurement(
                kind="financial_session." + kind,
                value_ns=value_ns,
                started_at_utc=self.clock(),
                status=status,
            )
        except Exception:
            # Only optional instrumentation is isolated here. Financial journal
            # and independent supervision errors always propagate to the caller.
            self.errors += 1

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        try:
            started = self.monotonic()
        except Exception:
            started = None
        status = "ok" if started is not None else "clock_unhealthy"
        try:
            yield
        except BaseException:
            status = "error"
            raise
        finally:
            try:
                duration = None if started is None else self.monotonic() - started
                if duration is not None and duration < 0:
                    duration, status = None, "clock_unhealthy"
                self.record(name, duration, status=status)
            except Exception:
                self.errors += 1
