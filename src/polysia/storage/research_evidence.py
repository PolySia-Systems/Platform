"""Isolated SQLite store for prospective research evidence.

Single writer. Not the Stage 4B financial database and not the latency sidecar.
No cross-database transactions.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import IO

from polysia.domain.research_evidence.collector import CollectorPolicy
from polysia.domain.research_evidence.models import (
    LEGACY_RESEARCH_EVIDENCE_SCHEMA_VERSION,
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    DecisionRecord,
    EvidenceClassification,
    IntervalValidity,
    ObservationKind,
    ResearchInterval,
)

Clock = Callable[[], datetime]

RESEARCH_EVIDENCE_SCHEMA_PATH = Path(__file__).with_name("research_evidence_schema.sql")
RESEARCH_EVIDENCE_FILENAME = "research-evidence.sqlite3"
WRITER_BUSY_TIMEOUT_MS = 5_000
WAL_CHECKPOINT_BYTES = 8 * 1024 * 1024
EXPERIMENT_WRITE_RESERVE_BYTES = 1024 * 1024


class ResearchEvidenceStoreError(RuntimeError):
    """Sanitized research-evidence persistence failure."""


class ResearchWriterLockError(ResearchEvidenceStoreError):
    """A second writer attempted to own the same research-evidence database."""


class ResearchEvidenceMaintenanceError(ResearchEvidenceStoreError):
    """A post-commit retention or checkpoint operation failed."""

    def __init__(self, stage: str, error: sqlite3.Error) -> None:
        super().__init__(f"research evidence {stage} maintenance failed")
        self.stage = stage
        self.sqlite_errorcode = getattr(error, "sqlite_errorcode", None)
        self.sqlite_errorname = getattr(error, "sqlite_errorname", "SQLITE_UNKNOWN")


class ResearchExperimentBudgetError(ResearchEvidenceStoreError):
    """The active experiment reached a declared time, event, or byte bound."""

    def __init__(self, limit: str) -> None:
        super().__init__(f"research experiment reached its {limit} limit")
        self.limit = limit


@dataclass(frozen=True, slots=True)
class ResearchExperiment:
    run_id: str
    started_at: datetime
    collection_ends_at: datetime
    max_events: int
    max_bytes: int
    status: str
    code_sha: str | None
    configuration_digest: str
    policy_version: str
    finalized_at: datetime | None = None
    bundle_path: str | None = None
    bundle_sha256: str | None = None
    event_count: int = 0


@dataclass(frozen=True, slots=True)
class WalCheckpointResult:
    """Sanitized outcome of a non-blocking WAL checkpoint attempt."""

    attempted: bool
    busy: bool
    log_frames: int
    checkpointed_frames: int


class ExclusiveWriterLock:
    """Smallest local exclusive lock. Rejects a second writer deterministically."""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path.with_name(f"{database_path.name}.lock")
        self._handle: IO[bytes] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")  # noqa: SIM115 — lock must outlive this method
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _lock_exclusive_nonblocking(handle)
        except OSError as error:
            handle.close()
            raise ResearchWriterLockError(
                "second writer rejected for research-evidence database"
            ) from error
        self._handle = handle
        _restrict_file_permissions(self._path)

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            _unlock_exclusive(handle)
        finally:
            handle.close()

    def __enter__(self) -> ExclusiveWriterLock:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.release()


class ResearchEvidenceStore:
    def __init__(
        self,
        path: str | Path,
        *,
        policy: CollectorPolicy | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._path = Path(path)
        self._policy = policy or CollectorPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._events_since_maintain = 0
        self._writer_lock = ExclusiveWriterLock(self._path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def maintenance_due(self) -> bool:
        return self._events_since_maintain >= 64

    def initialize(self) -> None:
        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.commit()
        finally:
            connection.close()
        _restrict_store_files(self._path)

    def acquire_writer(self) -> None:
        self._writer_lock.acquire()

    def release_writer(self) -> None:
        self._writer_lock.release()

    def persist_interval(self, interval: ResearchInterval) -> None:
        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO research_intervals ("
                "interval_id, started_at_utc, ended_at_utc, validity, reason, "
                "code_sha, configuration_digest, policy_version, summary_json"
                ") VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(interval_id) DO UPDATE SET "
                "ended_at_utc=excluded.ended_at_utc, "
                "validity=excluded.validity, "
                "reason=excluded.reason, "
                "summary_json=excluded.summary_json",
                (
                    interval.interval_id,
                    _utc_text(interval.started_at),
                    None if interval.ended_at is None else _utc_text(interval.ended_at),
                    interval.validity.value,
                    interval.reason,
                    interval.code_sha,
                    interval.configuration_digest,
                    interval.policy_version,
                    None if interval.summary is None else json.dumps(
                        interval.summary, sort_keys=True, separators=(",", ":"), default=str
                    ),
                ),
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("research interval persist failed") from error
        finally:
            connection.close()

    def existing_digest(self, evidence_id: str) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT payload_digest FROM research_events WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return str(row[0])

    def watermark(self, source_id: str) -> tuple[datetime | None, str | None, int]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT last_source_time_utc, last_evidence_id, reconnect_count "
                "FROM research_watermarks WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None, None, 0
        source_time = None if row[0] is None else _parse_utc(str(row[0]))
        evidence_id = None if row[1] is None else str(row[1])
        return source_time, evidence_id, int(row[2])

    def persist_event(
        self,
        event: CanonicalResearchEvent,
        *,
        interval_id: str,
    ) -> EvidenceClassification:
        """Insert one event. Identical retries increment a duplicate counter."""

        if event.schema_version != RESEARCH_EVIDENCE_SCHEMA_VERSION:
            raise ResearchEvidenceStoreError("legacy research evidence is read-only")
        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.execute("BEGIN IMMEDIATE")
            classification = event.classification
            self._require_experiment_capacity_unlocked(
                connection,
                event.run_id,
                will_insert=classification is not EvidenceClassification.DUPLICATE,
            )
            inserted = False
            if classification is EvidenceClassification.DUPLICATE:
                connection.execute(
                    "INSERT INTO research_duplicate_counts("
                    "evidence_id, duplicate_count, updated_at_utc"
                    ") VALUES (?, 1, ?) "
                    "ON CONFLICT(evidence_id) DO UPDATE SET "
                    "duplicate_count = duplicate_count + 1, "
                    "updated_at_utc = excluded.updated_at_utc",
                    (event.evidence_id, _utc_text(event.observed_time)),
                )
            else:
                try:
                    connection.execute(
                        "INSERT INTO research_events ("
                        "evidence_id, schema_version, source_id, event_kind, classification, "
                        "market_reference, outcome_reference, side, price, size, "
                        "source_time_utc, observed_time_utc, receive_monotonic_ns, "
                        "normalize_monotonic_ns, attribution_status, leader_alias, "
                        "confirmation, payload_digest, source_event_id, provenance_json, "
                        "related_evidence_id, run_id, interval_id"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        _event_params(event, interval_id=interval_id),
                    )
                except sqlite3.IntegrityError:
                    connection.execute(
                        "INSERT INTO research_duplicate_counts("
                        "evidence_id, duplicate_count, updated_at_utc"
                        ") VALUES (?, 1, ?) "
                        "ON CONFLICT(evidence_id) DO UPDATE SET "
                        "duplicate_count = duplicate_count + 1, "
                        "updated_at_utc = excluded.updated_at_utc",
                        (event.evidence_id, _utc_text(event.observed_time)),
                    )
                    classification = EvidenceClassification.DUPLICATE
                else:
                    inserted = True
                    if (
                        event.classification is EvidenceClassification.ACCEPTED
                        and event.event_kind is not ObservationKind.CONTROL
                    ):
                        connection.execute(
                            "INSERT INTO research_watermarks ("
                            "source_id, last_source_time_utc, last_evidence_id, "
                            "last_observed_time_utc, reconnect_count"
                            ") VALUES (?,?,?,?,0) "
                            "ON CONFLICT(source_id) DO UPDATE SET "
                            "last_source_time_utc=excluded.last_source_time_utc, "
                            "last_evidence_id=excluded.last_evidence_id, "
                            "last_observed_time_utc=excluded.last_observed_time_utc",
                            (
                                event.source_id,
                                None
                                if event.source_time is None
                                else _utc_text(event.source_time),
                                event.evidence_id,
                                _utc_text(event.observed_time),
                            ),
                        )
            if inserted:
                connection.execute(
                    "UPDATE research_experiments SET event_count = event_count + 1 "
                    "WHERE run_id = ? AND status = 'ACTIVE'",
                    (event.run_id,),
                )
            connection.commit()
            classification_result = classification
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("research event persist failed") from error
        finally:
            connection.close()
        self._events_since_maintain += 1
        return classification_result

    def start_or_resume_experiment(
        self,
        *,
        requested_run_id: str,
        duration: timedelta,
        max_events: int,
        max_bytes: int,
        code_sha: str | None,
        configuration_digest: str,
    ) -> ResearchExperiment:
        if (
            duration.total_seconds() <= 0
            or max_events < 1
            or max_bytes < EXPERIMENT_WRITE_RESERVE_BYTES
        ):
            raise ValueError("experiment bounds must be positive")
        self.initialize()
        connection = self._connect()
        try:
            active_rows = connection.execute(
                "SELECT * FROM research_experiments WHERE status = 'ACTIVE' "
                "ORDER BY started_at_utc DESC"
            ).fetchall()
            if len(active_rows) > 1:
                raise ResearchEvidenceStoreError("multiple active research experiments")
            if active_rows:
                active = _experiment_from_row(active_rows[0])
                if (
                    active.configuration_digest != configuration_digest
                    or active.code_sha != code_sha
                ):
                    raise ResearchEvidenceStoreError(
                        "active research experiment code or configuration changed"
                    )
                return active
            started = self._clock()
            ends = started + duration
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO research_experiments ("
                "run_id, started_at_utc, collection_ends_at_utc, max_events, max_bytes, "
                "status, code_sha, configuration_digest, policy_version"
                ") VALUES (?,?,?,?,?,'ACTIVE',?,?,?)",
                (
                    requested_run_id,
                    _utc_text(started),
                    _utc_text(ends),
                    max_events,
                    max_bytes,
                    code_sha,
                    configuration_digest,
                    self._policy.policy_version,
                ),
            )
            connection.commit()
            return ResearchExperiment(
                run_id=requested_run_id,
                started_at=started,
                collection_ends_at=ends,
                max_events=max_events,
                max_bytes=max_bytes,
                status="ACTIVE",
                code_sha=code_sha,
                configuration_digest=configuration_digest,
                policy_version=self._policy.policy_version,
            )
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("research experiment persist failed") from error
        finally:
            connection.close()

    def load_experiment(self, run_id: str) -> ResearchExperiment | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM research_experiments WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _experiment_from_row(row)

    def experiment_event_count(self, run_id: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT event_count FROM research_experiments WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            connection.close()
        return 0 if row is None else int(row[0])

    def finalize_experiment_record(
        self,
        run_id: str,
        *,
        bundle_path: Path,
        bundle_sha256: str,
        finalized_at: datetime,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE research_experiments SET status='FINALIZED', finalized_at_utc=?, "
                "bundle_path=?, bundle_sha256=? WHERE run_id=? AND status='ACTIVE'",
                (
                    _utc_text(finalized_at),
                    str(bundle_path),
                    bundle_sha256,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchEvidenceStoreError("active research experiment not found")
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("research experiment finalization failed") from error
        finally:
            connection.close()

    def require_experiment_within_bounds(self, run_id: str) -> None:
        connection = self._connect()
        try:
            self._require_experiment_capacity_unlocked(connection, run_id)
        finally:
            connection.close()

    def record_reconnect(self, source_id: str, *, observed_at: datetime) -> int:
        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO research_watermarks ("
                "source_id, last_source_time_utc, last_evidence_id, "
                "last_observed_time_utc, reconnect_count"
                ") VALUES (?, NULL, NULL, ?, 1) "
                "ON CONFLICT(source_id) DO UPDATE SET "
                "reconnect_count = reconnect_count + 1, "
                "last_observed_time_utc = excluded.last_observed_time_utc",
                (source_id, _utc_text(observed_at)),
            )
            row = connection.execute(
                "SELECT reconnect_count FROM research_watermarks WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            connection.commit()
            return 0 if row is None else int(row[0])
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("research reconnect persist failed") from error
        finally:
            connection.close()

    def persist_decision(self, decision: DecisionRecord) -> None:
        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.execute("BEGIN IMMEDIATE")
            for evidence_id in decision.evidence_ids:
                row = connection.execute(
                    "SELECT evidence_id FROM research_events WHERE evidence_id = ?",
                    (evidence_id,),
                ).fetchone()
                if row is None:
                    raise ResearchEvidenceStoreError(
                        "decision evidence is missing; interval must be invalidated"
                    )
            connection.execute(
                "INSERT INTO research_decisions ("
                "decision_id, interval_id, observed_time_utc, policy_id, policy_version, "
                "decision, evidence_ids_json, code_sha, configuration_digest"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    decision.decision_id,
                    decision.interval_id,
                    _utc_text(decision.observed_time),
                    decision.policy_id,
                    decision.policy_version,
                    decision.decision,
                    json.dumps(list(decision.evidence_ids), separators=(",", ":")),
                    decision.code_sha,
                    decision.configuration_digest,
                ),
            )
            connection.commit()
        except ResearchEvidenceStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("research decision persist failed") from error
        finally:
            connection.close()

    def load_interval(self, interval_id: str) -> ResearchInterval | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM research_intervals WHERE interval_id = ?",
                (interval_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        ended = row["ended_at_utc"]
        return ResearchInterval(
            interval_id=str(row["interval_id"]),
            started_at=_parse_utc(str(row["started_at_utc"])),
            ended_at=None if ended is None else _parse_utc(str(ended)),
            validity=IntervalValidity(str(row["validity"])),
            reason=str(row["reason"]),
            code_sha=None if row["code_sha"] is None else str(row["code_sha"]),
            configuration_digest=None
            if row["configuration_digest"] is None
            else str(row["configuration_digest"]),
            policy_version=str(row["policy_version"]),
            summary=_summary_from_row(row),
        )

    def load_events(
        self,
        *,
        run_id: str | None = None,
        interval_id: str | None = None,
    ) -> tuple[CanonicalResearchEvent, ...]:
        connection = self._connect()
        try:
            if interval_id is not None:
                rows = connection.execute(
                    "SELECT * FROM research_events WHERE interval_id = ? "
                    "ORDER BY observed_time_utc, evidence_id",
                    (interval_id,),
                ).fetchall()
            elif run_id is None:
                rows = connection.execute(
                    "SELECT * FROM research_events ORDER BY observed_time_utc, evidence_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM research_events WHERE run_id = ? "
                    "ORDER BY observed_time_utc, evidence_id",
                    (run_id,),
                ).fetchall()
        finally:
            connection.close()
        return tuple(_event_from_row(row) for row in rows)

    def load_interval_for_run(self, run_id: str) -> ResearchInterval | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT interval_id FROM research_events WHERE run_id = ? "
                "ORDER BY observed_time_utc LIMIT 1",
                (run_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return self.load_interval(str(row[0]))

    def duplicate_count(self, evidence_id: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT duplicate_count FROM research_duplicate_counts WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        finally:
            connection.close()
        return 0 if row is None else int(row[0])

    def event_count(self) -> int:
        connection = self._connect()
        try:
            row = connection.execute("SELECT COUNT(*) FROM research_events").fetchone()
        finally:
            connection.close()
        return 0 if row is None else int(row[0])

    def invalidate_open_intervals(self, *, reason: str) -> int:
        """Close leftover OPEN windows as INVALID after restart."""

        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.execute("BEGIN IMMEDIATE")
            ended = _utc_text(self._clock())
            cursor = connection.execute(
                "UPDATE research_intervals SET validity = ?, reason = ?, ended_at_utc = ? "
                "WHERE validity = ? AND ended_at_utc IS NULL",
                (
                    IntervalValidity.INVALID_SHUTDOWN.value,
                    reason,
                    ended,
                    IntervalValidity.OPEN.value,
                ),
            )
            connection.commit()
            return int(cursor.rowcount)
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("open interval recovery failed") from error
        finally:
            connection.close()

    def latest_closed_interval(self) -> ResearchInterval | None:
        connection = self._connect(timeout_seconds=WRITER_BUSY_TIMEOUT_MS / 1000)
        try:
            row = connection.execute(
                "SELECT * FROM research_intervals WHERE ended_at_utc IS NOT NULL "
                "ORDER BY ended_at_utc DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return self.load_interval(str(row["interval_id"]))

    def snapshot(self, destination: Path) -> Path:
        """Consistent reader snapshot via the SQLite Backup API."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.snapshot-tmp")
        try:
            source = sqlite3.connect(
                _read_only_uri(self._path),
                uri=True,
                timeout=WRITER_BUSY_TIMEOUT_MS / 1000,
            )
            target = sqlite3.connect(str(temporary), timeout=WRITER_BUSY_TIMEOUT_MS / 1000)
            try:
                source.execute(f"PRAGMA busy_timeout = {WRITER_BUSY_TIMEOUT_MS}")
                target.execute(f"PRAGMA busy_timeout = {WRITER_BUSY_TIMEOUT_MS}")
                source.backup(target)
                if target.execute("PRAGMA foreign_key_check").fetchall():
                    raise ResearchEvidenceStoreError("snapshot foreign-key check failed")
            finally:
                target.close()
                source.close()
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        _restrict_file_permissions(destination)
        return destination

    def storage_file_stats(self) -> dict[str, int]:
        """File sizes only. Health must not scan event tables."""

        stats = {"database_bytes": _file_size(self._path)}
        stats["wal_bytes"] = _file_size(Path(f"{self._path}-wal"))
        stats["shm_bytes"] = _file_size(Path(f"{self._path}-shm"))
        stats["lock_bytes"] = _file_size(self._writer_lock.path)
        stats["total_bytes"] = (
            stats["database_bytes"] + stats["wal_bytes"] + stats["shm_bytes"]
        )
        return stats

    def verify_integrity(self) -> None:
        connection = self._connect(timeout_seconds=WRITER_BUSY_TIMEOUT_MS / 1000)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            if row is None or str(row[0]) != "ok":
                raise ResearchEvidenceStoreError("research evidence integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ResearchEvidenceStoreError("research evidence foreign-key check failed")
            version = connection.execute(
                "SELECT schema_version FROM research_evidence_metadata WHERE singleton = 1"
            ).fetchone()
            if version is None or str(version[0]) != RESEARCH_EVIDENCE_SCHEMA_VERSION:
                raise ResearchEvidenceStoreError("research evidence schema version mismatch")
        finally:
            connection.close()

    def maintain(self, *, now: datetime | None = None) -> WalCheckpointResult:
        """Prune in one transaction, then checkpoint outside every transaction."""

        observed = now or self._clock()
        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.execute("BEGIN IMMEDIATE")
            self._prune_unlocked(connection, now=observed)
            connection.execute(
                "DELETE FROM research_duplicate_counts WHERE evidence_id NOT IN ("
                "SELECT evidence_id FROM research_events"
                ")"
            )
            connection.commit()
            self._events_since_maintain = 0
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceMaintenanceError("prune", error) from error
        finally:
            connection.close()

        wal_path = Path(f"{self._path}-wal")
        if _file_size(wal_path) < WAL_CHECKPOINT_BYTES:
            return WalCheckpointResult(False, False, 0, 0)

        checkpoint = self._connect()
        try:
            row = checkpoint.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            if row is None:
                raise sqlite3.OperationalError("checkpoint returned no status")
            return WalCheckpointResult(
                attempted=True,
                busy=bool(row[0]),
                log_frames=int(row[1]),
                checkpointed_frames=int(row[2]),
            )
        except sqlite3.Error as error:
            raise ResearchEvidenceMaintenanceError("checkpoint", error) from error
        finally:
            checkpoint.close()

    def _prune_unlocked(self, connection: sqlite3.Connection, *, now: datetime) -> None:
        cutoff = now - self._policy.market_state_retention
        connection.execute(
            "DELETE FROM research_events WHERE event_kind = ? AND observed_time_utc < ? "
            "AND evidence_id NOT IN ("
            "SELECT json_each.value FROM research_decisions, json_each(evidence_ids_json)"
            ") AND run_id NOT IN ("
            "SELECT run_id FROM research_experiments WHERE status = 'ACTIVE'"
            ")",
            (ObservationKind.MARKET_STATE.value, _utc_text(cutoff)),
        )
        max_events = self._policy.max_persisted_events
        row = connection.execute("SELECT COUNT(*) FROM research_events").fetchone()
        count = 0 if row is None else int(row[0])
        if count <= max_events:
            return
        overflow = count - max_events
        connection.execute(
            "DELETE FROM research_events WHERE evidence_id IN ("
            "SELECT evidence_id FROM research_events "
            "WHERE event_kind = ? AND evidence_id NOT IN ("
            "SELECT json_each.value FROM research_decisions, json_each(evidence_ids_json)"
            ") AND run_id NOT IN ("
            "SELECT run_id FROM research_experiments WHERE status = 'ACTIVE'"
            ") ORDER BY observed_time_utc ASC LIMIT ?"
            ")",
            (ObservationKind.MARKET_STATE.value, overflow),
        )

    def _require_experiment_capacity_unlocked(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        will_insert: bool = True,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM research_experiments WHERE run_id = ? AND status = 'ACTIVE'",
            (run_id,),
        ).fetchone()
        if row is None:
            return
        experiment = _experiment_from_row(row)
        if self._clock() >= experiment.collection_ends_at:
            raise ResearchExperimentBudgetError("duration")
        if will_insert and experiment.event_count >= experiment.max_events:
            raise ResearchExperimentBudgetError("event")
        if will_insert and (
            self.storage_file_stats()["total_bytes"] + EXPERIMENT_WRITE_RESERVE_BYTES
            > experiment.max_bytes
        ):
            raise ResearchExperimentBudgetError("storage")

    def _connect(self, *, timeout_seconds: float | None = None) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        timeout = (
            WRITER_BUSY_TIMEOUT_MS / 1000 if timeout_seconds is None else timeout_seconds
        )
        connection = sqlite3.connect(self._path, timeout=timeout)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {WRITER_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection


def ensure_research_evidence_schema(
    connection: sqlite3.Connection,
    *,
    policy_version: str,
) -> None:
    script = RESEARCH_EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(script)
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(research_events)")
    }
    if "source_event_id" not in columns:
        connection.execute("ALTER TABLE research_events ADD COLUMN source_event_id TEXT")
    interval_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(research_intervals)")
    }
    if "summary_json" not in interval_columns:
        connection.execute("ALTER TABLE research_intervals ADD COLUMN summary_json TEXT")
    experiment_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(research_experiments)")
    }
    if "event_count" not in experiment_columns:
        connection.execute(
            "ALTER TABLE research_experiments ADD COLUMN event_count INTEGER NOT NULL DEFAULT 0"
        )
    connection.execute(
        "INSERT OR IGNORE INTO research_evidence_metadata ("
        "singleton, schema_version, policy_version, created_at_utc"
        ") VALUES (1, ?, ?, ?)",
        (
            RESEARCH_EVIDENCE_SCHEMA_VERSION,
            policy_version,
            datetime.now(UTC).isoformat(),
        ),
    )
    row = connection.execute(
        "SELECT schema_version FROM research_evidence_metadata WHERE singleton = 1"
    ).fetchone()
    if row is not None and str(row[0]) == LEGACY_RESEARCH_EVIDENCE_SCHEMA_VERSION:
        connection.execute(
            "UPDATE research_evidence_metadata SET schema_version = ? WHERE singleton = 1",
            (RESEARCH_EVIDENCE_SCHEMA_VERSION,),
        )
        row = (RESEARCH_EVIDENCE_SCHEMA_VERSION,)
    if row is None or str(row[0]) != RESEARCH_EVIDENCE_SCHEMA_VERSION:
        raise ResearchEvidenceStoreError("research evidence schema version mismatch")
    connection.commit()


def default_research_evidence_path(data_directory: Path) -> Path:
    return data_directory / RESEARCH_EVIDENCE_FILENAME


def _event_params(event: CanonicalResearchEvent, *, interval_id: str) -> tuple[object, ...]:
    return (
        event.evidence_id,
        event.schema_version,
        event.source_id,
        event.event_kind.value,
        event.classification.value,
        event.market_reference,
        event.outcome_reference,
        event.side,
        None if event.price is None else format(event.price, "f"),
        None if event.size is None else format(event.size, "f"),
        None if event.source_time is None else _utc_text(event.source_time),
        _utc_text(event.observed_time),
        event.receive_monotonic_ns,
        event.normalize_monotonic_ns,
        event.attribution_status.value,
        event.leader_alias,
        event.confirmation.value,
        event.payload_digest,
        event.source_event_id,
        json.dumps(event.provenance, sort_keys=True, separators=(",", ":"), default=str),
        event.related_evidence_id,
        event.run_id,
        interval_id,
    )


def _event_from_row(row: Mapping[str, object]) -> CanonicalResearchEvent:
    price = row["price"]
    size = row["size"]
    source_time = row["source_time_utc"]
    provenance_raw = row["provenance_json"]
    provenance = json.loads(str(provenance_raw))
    if not isinstance(provenance, dict):
        raise ResearchEvidenceStoreError("stored provenance is invalid")
    return CanonicalResearchEvent(
        evidence_id=str(row["evidence_id"]),
        schema_version=str(row["schema_version"]),
        source_id=str(row["source_id"]),
        event_kind=ObservationKind(str(row["event_kind"])),
        classification=EvidenceClassification(str(row["classification"])),
        market_reference=None if row["market_reference"] is None else str(row["market_reference"]),
        outcome_reference=None
        if row["outcome_reference"] is None
        else str(row["outcome_reference"]),
        side=None if row["side"] is None else str(row["side"]),
        price=None if price is None else Decimal(str(price)),
        size=None if size is None else Decimal(str(size)),
        source_time=None if source_time is None else _parse_utc(str(source_time)),
        observed_time=_parse_utc(str(row["observed_time_utc"])),
        receive_monotonic_ns=int(str(row["receive_monotonic_ns"])),
        normalize_monotonic_ns=int(str(row["normalize_monotonic_ns"])),
        attribution_status=AttributionStatus(str(row["attribution_status"])),
        leader_alias=None if row["leader_alias"] is None else str(row["leader_alias"]),
        confirmation=ConfirmationStatus(str(row["confirmation"])),
        payload_digest=str(row["payload_digest"]),
        provenance=provenance,
        source_event_id=None
        if row["source_event_id"] is None
        else str(row["source_event_id"]),
        related_evidence_id=None
        if row["related_evidence_id"] is None
        else str(row["related_evidence_id"]),
        run_id=str(row["run_id"]),
    )


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResearchEvidenceStoreError("persisted times must be timezone-aware UTC")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _summary_from_row(row: Mapping[str, object]) -> dict[str, object] | None:
    try:
        raw = row["summary_json"]
    except (KeyError, IndexError):
        return None
    if raw is None:
        return None
    parsed = json.loads(str(raw))
    if not isinstance(parsed, dict):
        raise ResearchEvidenceStoreError("stored interval summary is invalid")
    return parsed


def _experiment_from_row(row: Mapping[str, object]) -> ResearchExperiment:
    finalized = row["finalized_at_utc"]
    return ResearchExperiment(
        run_id=str(row["run_id"]),
        started_at=_parse_utc(str(row["started_at_utc"])),
        collection_ends_at=_parse_utc(str(row["collection_ends_at_utc"])),
        max_events=int(str(row["max_events"])),
        max_bytes=int(str(row["max_bytes"])),
        status=str(row["status"]),
        code_sha=None if row["code_sha"] is None else str(row["code_sha"]),
        configuration_digest=str(row["configuration_digest"]),
        policy_version=str(row["policy_version"]),
        finalized_at=None if finalized is None else _parse_utc(str(finalized)),
        bundle_path=None if row["bundle_path"] is None else str(row["bundle_path"]),
        bundle_sha256=None
        if row["bundle_sha256"] is None
        else str(row["bundle_sha256"]),
        event_count=int(str(row["event_count"])),
    )


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _restrict_file_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def _restrict_store_files(database: Path) -> None:
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if path.exists():
            _restrict_file_permissions(path)


def _lock_exclusive_nonblocking(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined,unused-ignore]
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined,unused-ignore]


def _unlock_exclusive(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined,unused-ignore]
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined,unused-ignore]
