"""Single-writer prospective collector with explicit backpressure."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from polysia.application.ports.research_evidence import ResearchObservationSource
from polysia.domain.research_evidence.collector import (
    COLLECTOR_POLICY_VERSION,
    CollectorPolicy,
    apply_classification,
    classify_observation,
    gap_detected,
)
from polysia.domain.research_evidence.models import (
    INVALID_INTERVAL_STATES,
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    DecisionRecord,
    EvidenceClassification,
    IntervalValidity,
    ObservationKind,
    ResearchInterval,
    payload_digest,
    stable_evidence_id,
)
from polysia.storage.research_evidence import (
    ResearchEvidenceMaintenanceError,
    ResearchEvidenceStore,
    ResearchEvidenceStoreError,
)

Clock = Callable[[], datetime]
MonotonicNs = Callable[[], int]
MAX_CONSECUTIVE_PRUNE_FAILURES = 3


class ProspectiveCollector:
    """Bounded collector. Missing decision evidence invalidates the interval."""

    def __init__(
        self,
        store: ResearchEvidenceStore,
        *,
        policy: CollectorPolicy | None = None,
        clock: Clock | None = None,
        monotonic_ns: MonotonicNs | None = None,
        code_sha: str | None = None,
        configuration_digest: str | None = None,
        run_id: str | None = None,
        recover_orphans: bool = False,
    ) -> None:
        self._store = store
        self._policy = policy or CollectorPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or _perf_ns
        self._code_sha = code_sha
        self._configuration_digest = configuration_digest
        self._run_id = run_id or uuid4().hex
        self._window_failed = False
        self._drain_failed = False
        self._last_persist_at: datetime | None = None
        self._interval = self._new_open_interval()
        self._queue: asyncio.Queue[CanonicalResearchEvent] = asyncio.Queue(
            maxsize=self._policy.max_queue_depth
        )
        self._write_lock = asyncio.Lock()
        self._reconnect_pending: dict[str, bool] = {}
        self._maintenance_status = "healthy"
        self._maintenance_stage: str | None = None
        self._maintenance_error_code: str | None = None
        self._maintenance_failures = 0
        self._checkpoint_log_frames = 0
        self._checkpointed_frames = 0
        self._store.initialize()
        if recover_orphans:
            self._store.invalidate_open_intervals(reason="orphan_open_after_restart")
        self._store.persist_interval(self._interval)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def interval(self) -> ResearchInterval:
        return self._interval

    @property
    def valid(self) -> bool:
        return self._interval.validity is IntervalValidity.VALID

    @property
    def open(self) -> bool:
        return self._interval.validity is IntervalValidity.OPEN

    @property
    def last_persist_at(self) -> datetime | None:
        return self._last_persist_at

    @property
    def maintenance_health(self) -> dict[str, object]:
        return {
            "status": self._maintenance_status,
            "stage": self._maintenance_stage,
            "sqlite_error_code": self._maintenance_error_code,
            "consecutive_failures": self._maintenance_failures,
            "checkpoint_log_frames": self._checkpoint_log_frames,
            "checkpointed_frames": self._checkpointed_frames,
        }

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    def recover_orphans(self) -> int:
        return self._store.invalidate_open_intervals(reason="orphan_open_after_restart")

    def ingest(self, candidate: CanonicalResearchEvent) -> CanonicalResearchEvent:
        """Classify and persist one observation. Overload invalidates the interval."""

        stamped = replace(candidate, run_id=self._run_id)
        try:
            self._queue.put_nowait(stamped)
        except asyncio.QueueFull:
            classified = apply_classification(stamped, EvidenceClassification.OVERLOAD)
            self._invalidate(IntervalValidity.INVALID_OVERLOAD, "queue_overload")
            self._persist_or_invalidate(classified)
            return classified
        try:
            return self._persist_classified(stamped)
        except (ResearchEvidenceStoreError, OSError):
            self._invalidate(IntervalValidity.INVALID_DISK, "persistence_failure")
            raise
        finally:
            self._queue.get_nowait()
            self._queue.task_done()

    async def ingest_async(self, candidate: CanonicalResearchEvent) -> CanonicalResearchEvent:
        async with self._write_lock:
            return self.ingest(candidate)

    def record_reconnect(self, source_id: str) -> None:
        observed = self._clock()
        self._store.record_reconnect(source_id, observed_at=observed)
        self._reconnect_pending[source_id] = True
        control = self._control_event(
            EvidenceClassification.ACCEPTED,
            source_id=source_id,
            reason="reconnect",
            event_kind=ObservationKind.CONTROL,
        )
        self._store.persist_event(control, interval_id=self._interval.interval_id)

    def record_decision(self, decision: DecisionRecord) -> None:
        try:
            self._store.persist_decision(decision)
        except ResearchEvidenceStoreError:
            self._invalidate(
                IntervalValidity.INVALID_MISSING_EVIDENCE,
                "missing_decision_evidence",
            )
            raise

    def mark_drain_failed(self, reason: str = "source_drain_failure") -> None:
        self._drain_failed = True
        self._invalidate(IntervalValidity.INVALID_DRAIN, reason)

    def close(self) -> ResearchInterval:
        return self.close_window(complete=not self._window_failed and not self._drain_failed)

    def close_window(
        self,
        *,
        complete: bool,
        summary: dict[str, object] | None = None,
    ) -> ResearchInterval:
        if self._interval.validity is IntervalValidity.OPEN:
            if complete and not self._drain_failed:
                validity = IntervalValidity.VALID
                reason = "closed"
            elif self._drain_failed:
                validity = IntervalValidity.INVALID_DRAIN
                reason = "source_drain_failure"
            else:
                validity = IntervalValidity.INVALID_SHUTDOWN
                reason = "incomplete_window"
        else:
            validity = self._interval.validity
            reason = self._interval.reason
        closed = ResearchInterval(
            interval_id=self._interval.interval_id,
            started_at=self._interval.started_at,
            ended_at=self._clock(),
            validity=validity,
            reason=reason,
            code_sha=self._code_sha,
            configuration_digest=self._configuration_digest,
            policy_version=self._policy.policy_version,
            summary=summary if summary is not None else self._interval.summary,
        )
        self._interval = closed
        self._store.persist_interval(closed)
        self._maintain_if_due(force=True)
        return closed

    def start_window(self) -> ResearchInterval:
        self._window_failed = False
        self._drain_failed = False
        self._interval = self._new_open_interval()
        self._store.persist_interval(self._interval)
        return self._interval

    async def collect_from(
        self,
        sources: tuple[ResearchObservationSource, ...],
        *,
        deadline: datetime,
    ) -> ResearchInterval:
        tasks = [
            asyncio.create_task(
                self._drain_source(source, deadline=deadline),
                name=source.candidate.candidate_id,
            )
            for source in sources
        ]
        try:
            await asyncio.gather(*tasks)
        except Exception:
            self.mark_drain_failed()
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return self.close()

    async def _drain_source(
        self,
        source: ResearchObservationSource,
        *,
        deadline: datetime,
    ) -> None:
        async for event in source.run(run_id=self._run_id, deadline=deadline):
            await self.ingest_async(event)

    def _persist_or_invalidate(self, event: CanonicalResearchEvent) -> None:
        try:
            self._store.persist_event(event, interval_id=self._interval.interval_id)
            self._last_persist_at = self._clock()
            self._maintain_if_due()
        except (ResearchEvidenceStoreError, OSError):
            self._invalidate(IntervalValidity.INVALID_DISK, "persistence_failure")
            raise

    def _persist_classified(self, candidate: CanonicalResearchEvent) -> CanonicalResearchEvent:
        last_source_time, _, _ = self._store.watermark(candidate.source_id)
        existing = self._store.existing_digest(candidate.evidence_id)
        reconnect_pending = self._reconnect_pending.get(candidate.source_id, False)
        sequenced = bool(candidate.provenance.get("sequenced"))
        if sequenced and gap_detected(
            last_source_time=last_source_time,
            source_time=candidate.source_time,
            reconnect_pending=reconnect_pending,
            policy=self._policy,
        ):
            gap = self._control_event(
                EvidenceClassification.GAP,
                source_id=candidate.source_id,
                reason="source_time_gap",
            )
            self._store.persist_event(gap, interval_id=self._interval.interval_id)
            self._invalidate(IntervalValidity.INVALID_GAP, "source_time_gap")
        classified = classify_observation(
            candidate,
            existing_digest=existing,
            last_source_time=last_source_time,
            queue_depth=0,
            policy=self._policy,
            reconnect_pending=reconnect_pending,
        )
        self._store.persist_event(classified, interval_id=self._interval.interval_id)
        self._last_persist_at = self._clock()
        self._maintain_if_due()
        if classified.classification is EvidenceClassification.ACCEPTED:
            self._reconnect_pending[candidate.source_id] = False
        return classified

    def _maintain_if_due(self, *, force: bool = False) -> None:
        if not force and not self._store.maintenance_due:
            return
        try:
            result = self._store.maintain(now=self._clock())
        except ResearchEvidenceMaintenanceError as error:
            self._maintenance_status = "degraded"
            self._maintenance_stage = error.stage
            self._maintenance_error_code = error.sqlite_errorname
            self._maintenance_failures += 1
            if _maintenance_failure_is_fatal(error.sqlite_errorname) or (
                error.stage == "prune"
                and self._maintenance_failures >= MAX_CONSECUTIVE_PRUNE_FAILURES
            ):
                raise
            return
        self._maintenance_status = "degraded" if result.busy else "healthy"
        self._maintenance_stage = "checkpoint" if result.busy else None
        self._maintenance_error_code = "SQLITE_BUSY" if result.busy else None
        self._maintenance_failures = 0
        self._checkpoint_log_frames = result.log_frames
        self._checkpointed_frames = result.checkpointed_frames

    def _invalidate(self, validity: IntervalValidity, reason: str) -> None:
        if self._interval.validity in INVALID_INTERVAL_STATES:
            return
        self._window_failed = True
        self._interval = ResearchInterval(
            interval_id=self._interval.interval_id,
            started_at=self._interval.started_at,
            ended_at=self._interval.ended_at,
            validity=validity,
            reason=reason,
            code_sha=self._code_sha,
            configuration_digest=self._configuration_digest,
            policy_version=self._policy.policy_version,
            summary=self._interval.summary,
        )
        self._store.persist_interval(self._interval)

    def _new_open_interval(self) -> ResearchInterval:
        return ResearchInterval(
            interval_id=uuid4().hex,
            started_at=self._clock(),
            ended_at=None,
            validity=IntervalValidity.OPEN,
            reason="open",
            code_sha=self._code_sha,
            configuration_digest=self._configuration_digest,
            policy_version=self._policy.policy_version,
        )

    def _control_event(
        self,
        classification: EvidenceClassification,
        *,
        source_id: str,
        reason: str,
        event_kind: ObservationKind = ObservationKind.CONTROL,
    ) -> CanonicalResearchEvent:
        observed = self._clock()
        monotonic = self._monotonic_ns()
        identity: dict[str, object] = {
            "reason": reason,
            "run_id": self._run_id,
            "observed_time": observed.isoformat(),
        }
        provenance: dict[str, object] = {
            "code_sha": self._code_sha,
            "configuration_digest": self._configuration_digest,
            "policy_version": COLLECTOR_POLICY_VERSION,
            "reason": reason,
            "schema_version": RESEARCH_EVIDENCE_SCHEMA_VERSION,
        }
        return CanonicalResearchEvent(
            evidence_id=stable_evidence_id(source_id=source_id, identity_fields=identity),
            schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
            source_id=source_id,
            event_kind=event_kind,
            classification=classification,
            market_reference=None,
            outcome_reference=None,
            side=None,
            price=None,
            size=None,
            source_time=None,
            observed_time=observed,
            receive_monotonic_ns=monotonic,
            normalize_monotonic_ns=monotonic,
            attribution_status=AttributionStatus.NOT_APPLICABLE,
            leader_alias=None,
            confirmation=ConfirmationStatus.UNCONFIRMED,
            payload_digest=payload_digest(provenance),
            provenance=provenance,
            run_id=self._run_id,
        )


def _perf_ns() -> int:
    import time

    return time.perf_counter_ns()


def _maintenance_failure_is_fatal(error_name: str) -> bool:
    fatal_prefixes = (
        "SQLITE_CORRUPT",
        "SQLITE_FULL",
        "SQLITE_IOERR",
        "SQLITE_NOTADB",
        "SQLITE_READONLY",
    )
    return error_name.startswith(fatal_prefixes)
