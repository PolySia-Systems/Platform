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
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.domain.research_evidence.models import (
    EvidenceClassification,
    IntervalValidity,
    ObservationKind,
    ResearchInterval,
    payload_digest,
)
from polysia.storage.research_evidence import (
    ResearchEvidenceMaintenanceError,
    ResearchEvidenceStore,
    ResearchEvidenceStoreError,
    ResearchExperiment,
    ResearchExperimentBudgetError,
    ResearchWriterLockError,
)

Clock = Callable[[], datetime]
SERVICE_POLICY_VERSION = "persistent-prospective-collector-v3"
DEFAULT_WINDOW = timedelta(minutes=10)
DEFAULT_EXPERIMENT_DURATION = timedelta(hours=4)
DEFAULT_EXPERIMENT_MAX_EVENTS = 750_000
DEFAULT_EXPERIMENT_MAX_BYTES = 768 * 1024 * 1024
STALE_AFTER = timedelta(seconds=120)
HEALTH_WRITE_INTERVAL = timedelta(seconds=30)
MAX_WINDOW_REPORTS = 36
QUIET_SOURCE_STATUSES = frozenset({"healthy", "quiet"})


@dataclass(frozen=True, slots=True)
class PersistentCollectorConfig:
    window: timedelta = DEFAULT_WINDOW
    health_path: Path | None = None
    report_dir: Path | None = None
    required_source_ids: tuple[str, ...] = ()
    optional_source_ids: tuple[str, ...] = ()
    tracked_wallet_aliases: tuple[str, ...] = ()
    tracked_market_tokens: tuple[str, ...] = ()
    code_sha: str | None = None
    stale_after: timedelta = STALE_AFTER
    fatal_idle: bool = True
    experiment_duration: timedelta = DEFAULT_EXPERIMENT_DURATION
    experiment_max_events: int = DEFAULT_EXPERIMENT_MAX_EVENTS
    experiment_max_bytes: int = DEFAULT_EXPERIMENT_MAX_BYTES

    def __post_init__(self) -> None:
        if self.window.total_seconds() <= 0 or self.stale_after.total_seconds() <= 0:
            raise ValueError("collector time bounds must be positive")
        if (
            self.experiment_duration.total_seconds() <= 0
            or self.experiment_max_events < 1
            or self.experiment_max_bytes < 1
        ):
            raise ValueError("experiment bounds must be positive")


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
        self._lifecycle_lock = asyncio.Lock()
        self._fatal_reason: str | None = None
        self._fatal_stage: str | None = None
        self._fatal_error_code: str | None = None
        self._last_health_write: datetime | None = None
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
                "economic_contract_version": CONTRACT_V1.version,
                "economic_contract_digest": CONTRACT_V1.digest,
                "window_seconds": int(self._config.window.total_seconds()),
                "required_source_ids": list(self._config.required_source_ids),
                "optional_source_ids": list(self._config.optional_source_ids),
                "tracked_wallet_aliases": list(self._config.tracked_wallet_aliases),
                "tracked_market_tokens": list(self._config.tracked_market_tokens),
                "experiment_duration_seconds": int(
                    self._config.experiment_duration.total_seconds()
                ),
                "experiment_max_events": self._config.experiment_max_events,
                "experiment_max_bytes": self._config.experiment_max_bytes,
            }
        )
        self._collector: ProspectiveCollector | None = None
        self._latest_closed: ResearchInterval | None = None
        self._experiment: ResearchExperiment | None = None

    def _source_health(self) -> dict[str, dict[str, object]]:
        health: dict[str, dict[str, object]] = {}
        for source in self._sources:
            candidate_id = source.candidate.candidate_id
            snapshot = getattr(source, "health_snapshot", None)
            if callable(snapshot):
                health[candidate_id] = dict(snapshot())
            else:
                health[candidate_id] = {
                    "availability": self._source_status.get(candidate_id, "missing"),
                    "last_request_outcome": "unreported",
                    "last_successful_request_at": self._source_progress.get(candidate_id),
                    "last_successful_event_at": self._source_progress.get(candidate_id),
                    "last_failure_at": None,
                    "failure_class": None,
                    "retry_at": None,
                    "recovery_count": 0,
                }
        return health

    def _source_status_payload(self) -> dict[str, str]:
        statuses = dict(self._source_status)
        for source_id, details in self._source_health().items():
            availability = details.get("availability")
            if availability == "available":
                statuses[source_id] = (
                    "healthy" if details.get("last_successful_event_at") else "quiet"
                )
            elif availability in {"not_started", "recovering", "unavailable"}:
                statuses[source_id] = "retrying"
        return statuses

    @property
    def run_id(self) -> str:
        if self._collector is None:
            return self._run_id_override or self._service_id
        return self._collector.run_id

    @property
    def configuration_digest(self) -> str:
        return self._configuration_digest

    @property
    def interval(self) -> ResearchInterval:
        return self._active().interval

    def _active(self) -> ProspectiveCollector:
        collector = self._collector
        if collector is None:
            raise RuntimeError("persistent collector has not acquired the writer")
        return collector

    def _bind_collector(self) -> ProspectiveCollector:
        experiment = self._store.start_or_resume_experiment(
            requested_run_id=self._run_id_override or self._service_id,
            duration=self._config.experiment_duration,
            max_events=self._config.experiment_max_events,
            max_bytes=self._config.experiment_max_bytes,
            code_sha=self._config.code_sha,
            configuration_digest=self._configuration_digest,
        )
        self._experiment = experiment
        collector = ProspectiveCollector(
            self._store,
            policy=self._policy,
            clock=self._clock,
            code_sha=self._config.code_sha,
            configuration_digest=self._configuration_digest,
            run_id=experiment.run_id,
            recover_orphans=True,
        )
        self._collector = collector
        return collector

    async def run(self, *, cycles: int | None = None) -> None:
        try:
            self._store.acquire_writer()
        except ResearchWriterLockError:
            self._fatal_reason = "second_writer_rejected"
            self._write_health(force=True)
            if self._config.fatal_idle:
                await self._wait_until_stop()
                return
            raise
        try:
            self._bind_collector()
            self._write_health(force=True)
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
                self._write_health(force=True)
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
                "source_status": self._source_status_payload(),
                "source_health": self._source_health(),
                "research_data_eligible": False,
                "research_data_eligibility": {
                    "eligible": False,
                    "ineligible_required_sources": list(self._config.required_source_ids),
                },
                "service_health": "fatal" if self._fatal_reason else "stopped",
                "queue_depth": self._queue_depth,
                "storage": self._store.storage_file_stats(),
                "latest_closed_window_id": None if latest is None else latest.interval_id,
                "latest_closed_validity": None if latest is None else latest.validity.value,
                "latest_closed_reason": None if latest is None else latest.reason,
                "stale": False,
                "fatal": self._fatal_reason,
                "fatal_stage": self._fatal_stage,
                "fatal_error_code": self._fatal_error_code,
                "maintenance": None,
                "windows_closed": self._windows_closed,
                "experiment": self._experiment_payload(),
                "trading_mode": "DATA_ONLY",
                "live_trading_enabled": False,
            }
        interval = collector.interval
        last_persist = collector.last_persist_at
        if last_persist is None:
            stale = interval.started_at + self._config.stale_after < now
        else:
            stale = last_persist + self._config.stale_after < now
        ineligible_sources = self._ineligible_required_sources()
        service_health = (
            "fatal"
            if self._fatal_reason
            else (
                "stale"
                if stale
                else (
                    "degraded"
                    if collector.maintenance_health["status"] == "degraded"
                    else "healthy"
                )
            )
        )
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
            "source_status": self._source_status_payload(),
            "source_health": self._source_health(),
            "research_data_eligible": not ineligible_sources,
            "research_data_eligibility": {
                "eligible": not ineligible_sources,
                "ineligible_required_sources": ineligible_sources,
            },
            "service_health": service_health,
            "queue_depth": self._queue_depth,
            "storage": self._store.storage_file_stats(),
            "latest_closed_window_id": None if latest is None else latest.interval_id,
            "latest_closed_validity": None if latest is None else latest.validity.value,
            "latest_closed_reason": None if latest is None else latest.reason,
            "stale": stale,
            "fatal": self._fatal_reason,
            "fatal_stage": self._fatal_stage,
            "fatal_error_code": self._fatal_error_code,
            "maintenance": collector.maintenance_health,
            "windows_closed": self._windows_closed,
            "experiment": self._experiment_payload(),
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
            try:
                self._store.require_experiment_within_bounds(self._active().run_id)
            except ResearchExperimentBudgetError as error:
                self._fatal_reason = "experiment_budget_reached"
                self._fatal_stage = error.limit
                self._active().mark_drain_failed(self._fatal_reason)
                self._write_health(force=True)
                return
            deadline = self._clock() + self._config.window
            experiment = self._experiment
            if experiment is not None:
                deadline = min(deadline, experiment.collection_ends_at)
            terminal_window = (
                cycles is not None and completed + 1 >= cycles
            ) or (experiment is not None and deadline >= experiment.collection_ends_at)
            await self._wait_until(deadline)
            if self._stop.is_set():
                return
            required_missing = self._required_sources_missing()
            complete = not required_missing and self._fatal_reason is None
            try:
                async with self._lifecycle_lock:
                    if terminal_window:
                        await self._capture_terminal_evidence()
                        self._stop.set()
                    if required_missing:
                        self._active().mark_drain_failed("required_source_unavailable")
                    closed = self._active().close_window(
                        complete=complete,
                        summary=self._window_summary(),
                    )
                    if not terminal_window:
                        self._active().start_window()
            except (ResearchEvidenceStoreError, OSError) as error:
                self._fatal_from_storage(error)
                return
            self._latest_closed = closed
            self._windows_closed += 1
            self._write_window_report(closed)
            completed += 1
            if terminal_window:
                self._stop.set()
                return
            self._write_health(force=True)

    async def _capture_terminal_evidence(self) -> None:
        token_markets = dict(
            self._store.load_latest_wallet_token_markets(
                run_id=self._active().run_id,
            )
        )
        for source in self._sources:
            capture = getattr(source, "capture_terminal_evidence", None)
            if not callable(capture):
                continue
            events = await capture(
                run_id=self._active().run_id,
                token_markets=token_markets,
            )
            for event in events:
                await self._active().ingest_async(event)

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
                    async with self._lifecycle_lock:
                        if self._stop.is_set() or self._fatal_reason is not None:
                            return
                        persisted = await self._active().ingest_async(event)
                except ResearchExperimentBudgetError as error:
                    self._fatal_reason = "experiment_budget_reached"
                    self._fatal_stage = error.limit
                    self._fatal_error_code = None
                    self._active().mark_drain_failed(self._fatal_reason)
                    self._write_health(force=True)
                    return
                except (ResearchEvidenceStoreError, OSError) as error:
                    self._fatal_from_storage(error)
                    return
                self._queue_depth = self._active().queue_depth
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
                    self._source_progress[candidate_id] = persisted.observed_time.isoformat()
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
        return bool(self._ineligible_required_sources())

    def _ineligible_required_sources(self) -> list[str]:
        source_health = self._source_health()
        window_started = None if self._collector is None else self._active().interval.started_at
        missing: list[str] = []
        for source_id in self._config.required_source_ids:
            details = source_health.get(source_id, {})
            last_request = details.get("last_successful_request_at")
            if details.get("last_request_outcome") != "unreported" and not isinstance(
                last_request, str
            ):
                missing.append(source_id)
                continue
            if isinstance(last_request, str) and window_started is not None:
                try:
                    observed = datetime.fromisoformat(last_request.replace("Z", "+00:00"))
                except ValueError:
                    missing.append(source_id)
                    continue
                if observed >= window_started and details.get("availability") == "available":
                    continue
                missing.append(source_id)
                continue
            status = self._source_status.get(source_id, "missing")
            if status not in QUIET_SOURCE_STATUSES or status == "retrying":
                missing.append(source_id)
        return missing

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
        source_health = self._source_health()
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
            "source_health": source_health,
            "research_data_eligible": not self._required_sources_missing(),
        }

    def _fatal_from_storage(self, error: BaseException) -> None:
        if isinstance(error, ResearchEvidenceMaintenanceError):
            self._fatal_reason = "maintenance_failure"
            self._fatal_stage = error.stage
            self._fatal_error_code = error.sqlite_errorname
        else:
            self._fatal_reason = "storage_failure"
            self._fatal_stage = "persist"
            self._fatal_error_code = getattr(error, "sqlite_errorname", None)
        try:
            self._active()._invalidate(IntervalValidity.INVALID_DISK, self._fatal_reason)
        except Exception:
            self._active().mark_drain_failed(self._fatal_reason)
        self._write_health(force=True)

    def _experiment_payload(self) -> dict[str, object] | None:
        experiment = self._experiment
        if experiment is None:
            return None
        return {
            "run_id": experiment.run_id,
            "status": experiment.status,
            "started_at": experiment.started_at.isoformat(),
            "collection_ends_at": experiment.collection_ends_at.isoformat(),
            "max_events": experiment.max_events,
            "max_bytes": experiment.max_bytes,
            "event_count": self._store.experiment_event_count(experiment.run_id),
        }

    async def _wait_until(self, deadline: datetime) -> None:
        while not self._stop.is_set() and self._clock() < deadline:
            remaining = (deadline - self._clock()).total_seconds()
            await self._sleep(max(0.01, min(1.0, remaining)))
            self._write_health()

    async def _wait_until_stop(self) -> None:
        while not self._stop.is_set():
            await self._sleep(1.0)

    def _write_health(self, *, force: bool = False) -> None:
        path = self._config.health_path
        if path is None:
            return
        now = self._clock()
        if (
            not force
            and self._last_health_write is not None
            and now < self._last_health_write + HEALTH_WRITE_INTERVAL
        ):
            return
        _atomic_json(path, self.health_payload())
        self._last_health_write = now

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
        reports = sorted(directory.glob("research-window-*.json"), key=_report_time)
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


def _report_time(path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            ended = payload.get("ended_at")
            started = payload.get("started_at")
            if isinstance(ended, str) or isinstance(started, str):
                return (str(ended or started), path.name)
    except (OSError, json.JSONDecodeError):
        pass
    return ("", path.name)


def install_signal_handlers(collector: PersistentProspectiveCollector) -> None:
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        collector.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: _stop())
