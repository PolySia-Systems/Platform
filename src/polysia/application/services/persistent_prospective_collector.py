"""Continuously running prospective collector with rolling VALID windows.

Keeps source tasks alive across window rotation. DATA_ONLY research only.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from polysia.application.ports.research_evidence import ResearchObservationSource
from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.domain.research_evidence.collector import CollectorPolicy
from polysia.domain.research_evidence.models import (
    EvidenceClassification,
    IntervalValidity,
    ObservationKind,
    ResearchInterval,
    payload_digest,
)
from polysia.storage.research_evidence import (
    ResearchEvidenceStore,
    ResearchEvidenceStoreError,
    ResearchWriterLockError,
)

Clock = Callable[[], datetime]
SERVICE_POLICY_VERSION = "persistent-prospective-collector-v1"
DEFAULT_WINDOW = timedelta(minutes=10)
STALE_AFTER = timedelta(seconds=120)
MAX_WINDOW_REPORTS = 36
QUIET_SOURCE_STATUSES = frozenset({"healthy", "quiet", "unavailable", "insufficient"})


@dataclass(frozen=True, slots=True)
class PersistentCollectorConfig:
    window: timedelta = DEFAULT_WINDOW
    health_path: Path | None = None
    report_dir: Path | None = None
    required_source_ids: tuple[str, ...] = ()
    optional_source_ids: tuple[str, ...] = ()
    code_sha: str | None = None
    stale_after: timedelta = STALE_AFTER
    fatal_idle: bool = True


class PersistentProspectiveCollector:
    """Single-writer rolling-window collector."""

    def __init__(
        self,
        store: ResearchEvidenceStore,
        sources: tuple[ResearchObservationSource, ...],
        *,
        config: PersistentCollectorConfig | None = None,
        policy: CollectorPolicy | None = None,
        clock: Clock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        run_id: str | None = None,
    ) -> None:
        self._store = store
        self._sources = sources
        self._config = config or PersistentCollectorConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._service_id = uuid4().hex
        self._stop = asyncio.Event()
        self._fatal_reason: str | None = None
        self._source_status: dict[str, str] = {
            source.candidate.candidate_id: _initial_status(source) for source in sources
        }
        self._source_progress: dict[str, str | None] = {
            source.candidate.candidate_id: None for source in sources
        }
        self._queue_depth = 0
        self._windows_closed = 0
        self._policy = policy
        self._run_id_override = run_id
        self._configuration_digest = payload_digest(
            {
                "policy_version": SERVICE_POLICY_VERSION,
                "window_seconds": int(self._config.window.total_seconds()),
                "required_source_ids": list(self._config.required_source_ids),
                "optional_source_ids": list(self._config.optional_source_ids),
            }
        )
        self._collector: ProspectiveCollector | None = None
        self._latest_closed: ResearchInterval | None = None

    @property
    def run_id(self) -> str:
        if self._collector is None:
            return self._run_id_override or self._service_id
        return self._collector.run_id

    @property
    def interval(self) -> ResearchInterval:
        return self._active().interval

    def _active(self) -> ProspectiveCollector:
        collector = self._collector
        if collector is None:
            raise RuntimeError("persistent collector has not acquired the writer")
        return collector

    def _bind_collector(self) -> ProspectiveCollector:
        collector = ProspectiveCollector(
            self._store,
            policy=self._policy,
            clock=self._clock,
            code_sha=self._config.code_sha,
            configuration_digest=self._configuration_digest,
            run_id=self._run_id_override,
            recover_orphans=True,
        )
        self._collector = collector
        return collector

    async def run(self, *, cycles: int | None = None) -> None:
        try:
            self._store.acquire_writer()
        except ResearchWriterLockError:
            self._fatal_reason = "second_writer_rejected"
            self._write_health()
            if self._config.fatal_idle:
                await self._wait_until_stop()
                return
            raise
        try:
            self._bind_collector()
            self._write_health()
            tasks = [
                asyncio.create_task(
                    self._drain_source(source),
                    name=source.candidate.candidate_id,
                )
                for source in self._sources
            ]
            rotator = asyncio.create_task(self._rotate_windows(cycles=cycles))
            try:
                await rotator
            finally:
                self._stop.set()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, rotator, return_exceptions=True)
                if self._collector is not None and self._collector.open:
                    closed = self._collector.close_window(
                        complete=False,
                        summary=self._window_summary(),
                    )
                    self._latest_closed = closed
                    self._write_window_report(closed)
                self._write_health()
        finally:
            self._store.release_writer()

    def request_stop(self) -> None:
        self._stop.set()

    def health_payload(self) -> dict[str, object]:
        collector = self._collector
        latest = self._latest_closed
        now = self._clock()
        if collector is None:
            return {
                "service_id": self._service_id,
                "run_id": self.run_id,
                "window_id": None,
                "lifecycle": "STOPPED",
                "reason": self._fatal_reason or "not_started",
                "policy_version": SERVICE_POLICY_VERSION,
                "code_sha": self._config.code_sha,
                "last_source_progress": dict(self._source_progress),
                "last_successful_persistence": None,
                "source_status": dict(self._source_status),
                "queue_depth": self._queue_depth,
                "storage": self._store.storage_file_stats(),
                "latest_closed_window_id": None if latest is None else latest.interval_id,
                "latest_closed_validity": None if latest is None else latest.validity.value,
                "latest_closed_reason": None if latest is None else latest.reason,
                "stale": False,
                "fatal": self._fatal_reason,
                "windows_closed": self._windows_closed,
                "trading_mode": "DATA_ONLY",
                "live_trading_enabled": False,
            }
        interval = collector.interval
        last_persist = collector.last_persist_at
        if last_persist is None:
            stale = interval.started_at + self._config.stale_after < now
        else:
            stale = last_persist + self._config.stale_after < now
        return {
            "service_id": self._service_id,
            "run_id": collector.run_id,
            "window_id": interval.interval_id,
            "lifecycle": interval.validity.value,
            "reason": interval.reason,
            "policy_version": SERVICE_POLICY_VERSION,
            "code_sha": self._config.code_sha,
            "last_source_progress": dict(self._source_progress),
            "last_successful_persistence": None
            if last_persist is None
            else last_persist.isoformat(),
            "source_status": dict(self._source_status),
            "queue_depth": self._queue_depth,
            "storage": self._store.storage_file_stats(),
            "latest_closed_window_id": None if latest is None else latest.interval_id,
            "latest_closed_validity": None if latest is None else latest.validity.value,
            "latest_closed_reason": None if latest is None else latest.reason,
            "stale": stale,
            "fatal": self._fatal_reason,
            "windows_closed": self._windows_closed,
            "trading_mode": "DATA_ONLY",
            "live_trading_enabled": False,
        }

    async def _rotate_windows(self, *, cycles: int | None) -> None:
        completed = 0
        await asyncio.sleep(0)
        while not self._stop.is_set():
            if self._fatal_reason is not None:
                if self._config.fatal_idle:
                    await self._wait_until_stop()
                return
            deadline = self._clock() + self._config.window
            await self._wait_until(deadline)
            if self._stop.is_set():
                return
            required_missing = self._required_sources_missing()
            complete = not required_missing and self._fatal_reason is None
            if required_missing:
                self._active().mark_drain_failed("required_source_unavailable")
            closed = self._active().close_window(
                complete=complete,
                summary=self._window_summary(),
            )
            self._latest_closed = closed
            self._windows_closed += 1
            self._write_window_report(closed)
            completed += 1
            if cycles is not None and completed >= cycles:
                self._stop.set()
                return
            self._active().start_window()
            self._write_health()

    async def _drain_source(self, source: ResearchObservationSource) -> None:
        candidate_id = source.candidate.candidate_id
        required = candidate_id in self._config.required_source_ids
        backoff = 1.0
        far_deadline = self._clock() + timedelta(days=3650)
        try:
            async for event in source.run(
                run_id=self._active().run_id,
                deadline=far_deadline,
            ):
                if self._stop.is_set() or self._fatal_reason is not None:
                    return
                self._queue_depth = self._active().queue_depth
                try:
                    persisted = await self._active().ingest_async(event)
                except (ResearchEvidenceStoreError, OSError) as error:
                    self._fatal_from_storage(error)
                    return
                self._queue_depth = self._active().queue_depth
                self._source_progress[candidate_id] = persisted.observed_time.isoformat()
                if (
                    persisted.classification is EvidenceClassification.INCOMPLETE
                    and persisted.event_kind is ObservationKind.CONTROL
                ):
                    self._source_status[candidate_id] = "retrying"
                    await self._sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                backoff = 1.0
                if persisted.event_kind in {
                    ObservationKind.WALLET_TRADE,
                    ObservationKind.MARKET_STATE,
                }:
                    self._source_status[candidate_id] = "healthy"
                else:
                    self._source_status.setdefault(candidate_id, "quiet")
        except asyncio.CancelledError:
            self._source_status[candidate_id] = "stopped"
            raise
        except Exception:
            self._source_status[candidate_id] = "failed"
            if required:
                self._active().mark_drain_failed(f"required_source_failed:{candidate_id}")
            return
        if not self._stop.is_set() and required:
            self._source_status[candidate_id] = "failed"
            self._active().mark_drain_failed(f"required_source_ended:{candidate_id}")

    def _required_sources_missing(self) -> bool:
        for source_id in self._config.required_source_ids:
            status = self._source_status.get(source_id, "missing")
            if status not in QUIET_SOURCE_STATUSES and status != "retrying":
                return True
        return False

    def _window_summary(self) -> dict[str, object]:
        events = self._store.load_events(interval_id=self._active().interval.interval_id)
        wallet_tokens = {
            event.outcome_reference
            for event in events
            if event.event_kind is ObservationKind.WALLET_TRADE
            and event.classification is EvidenceClassification.ACCEPTED
            and event.outcome_reference
        }
        market_tokens = {
            event.outcome_reference
            for event in events
            if event.event_kind is ObservationKind.MARKET_STATE
            and event.classification is EvidenceClassification.ACCEPTED
            and event.outcome_reference
        }
        overlap = sorted(wallet_tokens & market_tokens)
        quotes = [
            event
            for event in events
            if event.event_kind is ObservationKind.MARKET_STATE
            and event.classification is EvidenceClassification.ACCEPTED
        ]
        quote_present = 0
        depth_present = 0
        for event in quotes:
            if event.provenance.get("quote_status") == "present":
                quote_present += 1
            if event.provenance.get("depth_status") == "present":
                depth_present += 1
        return {
            "accepted_wallet_events": sum(
                1
                for event in events
                if event.event_kind is ObservationKind.WALLET_TRADE
                and event.classification is EvidenceClassification.ACCEPTED
            ),
            "accepted_market_events": len(quotes),
            "wallet_tokens": sorted(wallet_tokens),
            "market_tokens": sorted(market_tokens),
            "overlap_tokens": overlap,
            "overlap_count": len(overlap),
            "overlap_status": "present" if overlap else "UNKNOWN",
            "quote_status": "present" if quote_present else "UNKNOWN",
            "depth_status": "present" if depth_present else "UNKNOWN",
            "executable_price_inputs": quote_present,
            "required_depth_present": depth_present,
            "empty": len(events) == 0,
        }

    def _fatal_from_storage(self, error: BaseException) -> None:
        del error
        self._fatal_reason = "storage_failure"
        try:
            self._active()._invalidate(IntervalValidity.INVALID_DISK, "storage_failure")
        except Exception:
            self._active().mark_drain_failed("storage_failure")
        self._write_health()

    async def _wait_until(self, deadline: datetime) -> None:
        while not self._stop.is_set() and self._clock() < deadline:
            remaining = (deadline - self._clock()).total_seconds()
            await self._sleep(max(0.01, min(1.0, remaining)))

    async def _wait_until_stop(self) -> None:
        while not self._stop.is_set():
            await self._sleep(1.0)

    def _write_health(self) -> None:
        path = self._config.health_path
        if path is None:
            return
        _atomic_json(path, self.health_payload())

    def _write_window_report(self, interval: ResearchInterval) -> None:
        directory = self._config.report_dir
        if directory is None:
            return
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "interval_id": interval.interval_id,
            "validity": interval.validity.value,
            "reason": interval.reason,
            "started_at": interval.started_at.isoformat(),
            "ended_at": None if interval.ended_at is None else interval.ended_at.isoformat(),
            "run_id": self.run_id,
            "code_sha": self._config.code_sha,
            "summary": interval.summary or {},
        }
        path = directory / f"research-window-{interval.interval_id}.json"
        _atomic_json(path, payload)
        reports = sorted(directory.glob("research-window-*.json"), key=lambda item: item.name)
        for stale in reports[:-MAX_WINDOW_REPORTS]:
            stale.unlink(missing_ok=True)


def _initial_status(source: ResearchObservationSource) -> str:
    status = source.candidate.status.value.lower()
    if status == "unavailable":
        return "unavailable"
    if status == "insufficient":
        return "insufficient"
    return "quiet"


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    text = json.dumps(dict(payload), sort_keys=True, default=str)
    temporary.write_text(f"{text}\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name != "nt":
        path.chmod(0o600)


def install_signal_handlers(collector: PersistentProspectiveCollector) -> None:
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        collector.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: _stop())
