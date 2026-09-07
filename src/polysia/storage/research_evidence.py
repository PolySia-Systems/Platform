"""Isolated SQLite store for prospective research evidence.

Single writer. Not the Stage 4B financial database and not the latency sidecar.
No cross-database transactions.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from polysia.domain.research_evidence.collector import CollectorPolicy
from polysia.domain.research_evidence.models import (
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

RESEARCH_EVIDENCE_SCHEMA_PATH = Path(__file__).with_name("research_evidence_schema.sql")
RESEARCH_EVIDENCE_FILENAME = "research-evidence.sqlite3"


class ResearchEvidenceStoreError(RuntimeError):
    """Sanitized research-evidence persistence failure."""


class ResearchEvidenceStore:
    def __init__(self, path: str | Path, *, policy: CollectorPolicy | None = None) -> None:
        self._path = Path(path)
        self._policy = policy or CollectorPolicy()

    @property
    def path(self) -> Path:
        return self._path

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
                "code_sha, configuration_digest, policy_version"
                ") VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(interval_id) DO UPDATE SET "
                "ended_at_utc=excluded.ended_at_utc, "
                "validity=excluded.validity, "
                "reason=excluded.reason",
                (
                    interval.interval_id,
                    _utc_text(interval.started_at),
                    None if interval.ended_at is None else _utc_text(interval.ended_at),
                    interval.validity.value,
                    interval.reason,
                    interval.code_sha,
                    interval.configuration_digest,
                    interval.policy_version,
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

        connection = self._connect()
        try:
            ensure_research_evidence_schema(
                connection,
                policy_version=self._policy.policy_version,
            )
            connection.execute("BEGIN IMMEDIATE")
            classification = event.classification
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
                        "confirmation, payload_digest, provenance_json, related_evidence_id, "
                        "run_id, interval_id"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            self._prune_unlocked(connection, now=datetime.now(UTC))
            connection.commit()
            return classification
        except sqlite3.Error as error:
            connection.rollback()
            raise ResearchEvidenceStoreError("research event persist failed") from error
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
        )

    def load_events(self, *, run_id: str | None = None) -> tuple[CanonicalResearchEvent, ...]:
        connection = self._connect()
        try:
            if run_id is None:
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

    def _prune_unlocked(self, connection: sqlite3.Connection, *, now: datetime) -> None:
        cutoff = now - self._policy.market_state_retention
        connection.execute(
            "DELETE FROM research_events WHERE event_kind = ? AND observed_time_utc < ? "
            "AND evidence_id NOT IN ("
            "SELECT json_each.value FROM research_decisions, json_each(evidence_ids_json)"
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
            ") ORDER BY observed_time_utc ASC LIMIT ?"
            ")",
            (ObservationKind.MARKET_STATE.value, overflow),
        )

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def ensure_research_evidence_schema(
    connection: sqlite3.Connection,
    *,
    policy_version: str,
) -> None:
    script = RESEARCH_EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(script)
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
