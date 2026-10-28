"""Single-host financial journal with a separately retained rollback witness.

Both SQLite files use rollback journals so ATTACH participates in one atomic
super-journal commit. Restoring the financial file alone cannot refund authority.
The active trusted witness directory must never be restored with financial
backups. Isolated witness copies may verify backup integrity; they are never
installed as active custody or used to reissue consumed authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from polysia.domain.financial_session import (
    AccountObservation,
    SessionAuthorization,
    SessionBlocked,
    canonical_json,
    digest,
)
from polysia.storage.research_evidence import ExclusiveWriterLock


@dataclass(frozen=True, slots=True)
class SessionRecoveryCheckpoint:
    authority_fingerprint: str
    sequence: int
    state_digest: str


class FinancialSessionJournal:
    """No implicit initialize/migrate/restore, no automatic authority rollover.

    All financial writers for an account must use the same protected witness
    root. The lock is held across network awaits, not only SQL transactions.
    This is local process fencing, not distributed exactly-once delivery.
    """

    def __init__(self, path: Path, witness_root: Path, authority: SessionAuthorization) -> None:
        self.path = path.resolve()
        root = witness_root.resolve()
        if self.path.is_relative_to(root) or root.is_relative_to(self.path.parent):
            raise SessionBlocked("witness_must_be_separate_from_financial_backup")
        self.witness = root / (digest(authority.binding.account) + ".sqlite3")
        self.authority = authority
        self._lock = ExclusiveWriterLock(self.witness, rejected_message="account_writer_busy")
        self._connection: sqlite3.Connection | None = None
        self._fence: int | None = None
        self.after_commit: Callable[[SessionRecoveryCheckpoint], None] | None = None
        self._publication_failed = False

    def provision(self, opening: AccountObservation) -> None:
        """Explicit trusted-owner bootstrap; never called by a worker or Console.

        Existing inventory/orders require an assessed migration and are refused.
        Neither an existing witness nor an existing journal may be overwritten.
        """
        opening.require_complete(
            self.authority.binding.account,
            now=opening.observed_at,
            max_age=self.authority.max_evidence_age_seconds,
        )
        self.authority.assert_action(self.authority.binding, opening.observed_at, "ENTRY")
        if opening.positions or opening.open_order_ids:
            raise SessionBlocked("nonempty_account_requires_assessed_migration")
        self._lock.acquire()
        try:
            if self.path.exists() or self.witness.exists():
                raise SessionBlocked("existing_authority_must_not_be_reinitialized")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.witness.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents a failed bootstrap from being mistaken
            # for a fresh authority. Partial files remain visibly blocked.
            self.path.touch(exist_ok=False)
            self.witness.touch(exist_ok=False)
            for path in (self.path, self.witness):
                if os.name != "nt":
                    path.chmod(0o600)
            state = {
                "version": 1,
                "run_id": self.authority.run_id,
                "authorization": asdict(self.authority),
                "mode": "STOP",
                "opening": asdict(opening),
                "orders": {},
                "fills": [],
                "quarantined_fills": [],
                "quarantined_finality": [],
                "decisions": {},
                "attempts": 0,
                "turnover": "0",
                "requests": 0,
                "source_cost": "0",
                "response_bytes": 0,
                "supervised_at": None,
                "reconciled_at": None,
                "reconciliation_ok": False,
                "incidents": [],
                "equity": [],
                "checkpoints": {},
            }
            encoded = canonical_json(state)
            with closing(self._connect()) as connection, connection:
                connection.executescript(
                    "CREATE TABLE session(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                    "authority TEXT NOT NULL, sequence INTEGER NOT NULL, state TEXT NOT NULL);"
                    "CREATE TABLE journal(sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
                    "payload TEXT NOT NULL);"
                    "CREATE TABLE network_evidence(request_id TEXT PRIMARY KEY, "
                    "body BLOB NOT NULL,sha256 TEXT NOT NULL);"
                    "CREATE TABLE witness.authority(singleton INTEGER PRIMARY KEY "
                    "CHECK(singleton=1), fingerprint TEXT NOT NULL, sequence INTEGER NOT NULL, "
                    "state_digest TEXT NOT NULL, fence INTEGER NOT NULL, opens INTEGER NOT NULL);"
                )
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO session VALUES(1,?,0,?)",
                    (self.authority.fingerprint, encoded),
                )
                connection.execute(
                    "INSERT INTO witness.authority VALUES(1,?,0,?,0,0)",
                    (self.authority.fingerprint, digest(state)),
                )
        finally:
            self._lock.release()

    def open(
        self,
        *,
        checkpoint: SessionRecoveryCheckpoint | None = None,
    ) -> FinancialSessionJournal:
        if self._connection is not None:
            raise SessionBlocked("writer_already_open")
        if not self.path.is_file() or not self.witness.is_file():
            raise SessionBlocked("financial_state_or_authority_lost_no_automatic_bootstrap")
        if self.path.is_symlink() or self.witness.is_symlink():
            raise SessionBlocked("financial_state_symlink_denied")
        self._lock.acquire()
        try:
            connection = self._connect()
            self._connection = connection
            connection.execute("BEGIN IMMEDIATE")
            self._verified_state(connection)
            if self.authority.version == 2 and connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='network_evidence'"
            ).fetchone() is None:
                raise SessionBlocked("composed_financial_schema_missing_no_implicit_migration")
            row = connection.execute("SELECT * FROM witness.authority").fetchone()
            if row["opens"] and self.authority.restart_policy != "RECONCILE":
                raise SessionBlocked("restart_not_authorized")
            if row["opens"]:
                if checkpoint is None:
                    raise SessionBlocked("explicit_recovery_checkpoint_required")
                if checkpoint != SessionRecoveryCheckpoint(
                    row["fingerprint"],
                    row["sequence"],
                    row["state_digest"],
                ):
                    raise SessionBlocked("recovery_checkpoint_mismatch_no_budget_reset")
            self._fence = int(row["fence"]) + 1
            connection.execute("UPDATE witness.authority SET fence=?,opens=opens+1", (self._fence,))
            connection.commit()
            # Reopening always requires fresh supervision and account reconciliation.
            self.mutate("WRITER_OPEN", {"fence": self._fence}, self._invalidate_recovery)
            return self
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _invalidate_recovery(state: dict[str, Any]) -> None:
        state["reconciliation_ok"] = False
        state["supervised_at"] = None

    def close(self) -> None:
        connection, self._connection = self._connection, None
        self._fence = None
        try:
            if connection is not None:
                connection.close()
        finally:
            self._lock.release()

    def __enter__(self) -> FinancialSessionJournal:
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    def read(self) -> dict[str, Any]:
        return self._verified_state(self._require_open())

    def checkpoint(self) -> SessionRecoveryCheckpoint:
        """Publish to independent recovery control, outside all financial backups.

        A worker must not construct its own receipt from restored files. Restoring
        both files and external recovery control is outside local fencing.
        """
        connection = self._require_open()
        self._verified_state(connection)
        row = connection.execute("SELECT * FROM witness.authority").fetchone()
        return SessionRecoveryCheckpoint(row["fingerprint"], row["sequence"], row["state_digest"])

    def retain_response(self, request_id: str, body: bytes) -> None:
        fingerprint = hashlib.sha256(body).hexdigest()

        def update(state: dict[str, Any]) -> None:
            connection = self._require_open()
            existing = connection.execute("SELECT sha256 FROM network_evidence WHERE request_id=?",
                                          (request_id,)).fetchone()
            if existing is not None and existing[0] != fingerprint:
                raise SessionBlocked("conflicting_retained_response")
            connection.execute("INSERT OR IGNORE INTO network_evidence VALUES(?,?,?)",
                               (request_id, body, fingerprint))
            state["wire"][request_id]["evidence_sha256"] = fingerprint
        self.mutate("RETAINED_NETWORK_EVIDENCE", {"request": request_id, "bytes": len(body),
                                                 "sha256": fingerprint}, update)

    def read_response(self, request_id: str) -> bytes:
        state = self.read()
        row = (
            self._require_open()
            .execute("SELECT body,sha256 FROM network_evidence WHERE request_id=?", (request_id,))
            .fetchone()
        )
        if (row is None or hashlib.sha256(row[0]).hexdigest() != row[1]
                or state["wire"][request_id].get("evidence_sha256") != row[1]):
            raise SessionBlocked("retained_network_evidence_integrity_failed")
        return bytes(row[0])

    def mutate(self, kind: str, payload: object, change: Callable[[dict[str, Any]], None]) -> None:
        if self._publication_failed:
            raise SessionBlocked("checkpoint_publication_failed_requires_cold_recovery")
        connection = self._require_open()
        try:
            connection.execute("BEGIN IMMEDIATE")
            state = self._verified_state(connection)
            change(state)
            encoded = canonical_json(state)
            # Keep room for incident/reconciliation records before a full disk.
            current_size = sum(p.stat().st_size for p in (self.path, self.witness))
            low_priority = (
                kind
                in {
                    "REQUEST_RESERVED",
                    "DECISION_OBSERVED",
                    "DECISION_PHASE",
                    "ATTEMPT_AND_RESERVATION",
                    "WIRE_REQUEST",
                }
                and state.get("resource_class") == "ENTRY"
            )
            storage_limit = self.authority.max_storage_bytes - (
                self.authority.protective_storage_reserve if low_priority else 0)
            allocated_pages = sum(connection.execute(f"PRAGMA {schema}.page_count").fetchone()[0]
                                  * connection.execute(f"PRAGMA {schema}.page_size").fetchone()[0]
                                  for schema in ("main", "witness"))
            if (max(current_size, allocated_pages) * 2 + len(encoded.encode()) * 2
                    + 65536) > storage_limit:
                raise SessionBlocked("financial_storage_budget_exhausted")
            sequence = connection.execute("SELECT sequence FROM session").fetchone()[0] + 1
            connection.execute("UPDATE session SET sequence=?,state=?", (sequence, encoded))
            connection.execute(
                "INSERT INTO journal VALUES(?,?,?)", (sequence, kind, canonical_json(payload))
            )
            connection.execute(
                "UPDATE witness.authority SET sequence=?,state_digest=? WHERE fence=?",
                (sequence, digest(state), self._fence),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        # The financial commit is irreversible here. Publication failure cannot
        # roll it back, refund authority, or let this worker generate recovery proof.
        if self.after_commit is not None:
            try:
                self.after_commit(self.checkpoint())
            except BaseException:
                self._publication_failed = True
                raise

    def _require_open(self) -> sqlite3.Connection:
        if self._connection is None or self._fence is None:
            raise SessionBlocked("account_writer_not_held")
        return self._connection

    def _verified_state(self, connection: sqlite3.Connection) -> dict[str, Any]:
        session = connection.execute("SELECT * FROM session WHERE singleton=1").fetchone()
        witness = connection.execute("SELECT * FROM witness.authority WHERE singleton=1").fetchone()
        if (
            session is None
            or witness is None
            or session["authority"] != self.authority.fingerprint
            or witness["fingerprint"] != self.authority.fingerprint
            or session["sequence"] != witness["sequence"]
        ):
            raise SessionBlocked("authority_or_rollback_witness_mismatch")
        state: dict[str, Any] = json.loads(session["state"])
        if digest(state) != witness["state_digest"] or state.get("version") != 1:
            raise SessionBlocked("financial_state_integrity_mismatch")
        if self._fence is not None and self._fence != witness["fence"]:
            raise SessionBlocked("stale_account_writer_fence")
        return state

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=1)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute(
                "ATTACH DATABASE ? AS witness", (self.witness.as_uri() + "?mode=rw",)
            )
            connection.execute("PRAGMA witness.synchronous=FULL")
            connection.execute("PRAGMA witness.journal_mode=DELETE")
            for schema in ("main", "witness"):
                page_size = connection.execute(f"PRAGMA {schema}.page_size").fetchone()[0]
                # Reserve two permanent files, their worst-case rollback journals
                # and super-journal overhead inside the approved disk budget.
                pages = (self.authority.max_storage_bytes - 65536) // (4 * page_size)
                current = connection.execute(f"PRAGMA {schema}.page_count").fetchone()[0]
                if pages < max(4, current):
                    raise SessionBlocked("financial_storage_budget_exhausted")
                connection.execute(f"PRAGMA {schema}.max_page_count={pages}")
                if connection.execute(f"PRAGMA {schema}.quick_check").fetchone()[0] != "ok":
                    raise SessionBlocked("financial_store_integrity_failed")
            return connection
        except BaseException:
            connection.close()
            raise


class SessionCancellationCheckpoints:
    """Adapt the existing cancellation finality gate to the same financial writer."""

    def __init__(self, journal: FinancialSessionJournal) -> None:
        self.journal = journal

    def get(self, *, run_id: str, phase: str) -> dict[str, object] | None:
        self._run(run_id)
        return self.journal.read()["checkpoints"].get(phase)

    def insert_if_absent(
        self,
        *,
        run_id: str,
        phase: str,
        client_order_id: str,
        venue_order_id: str | None,
        payload: Mapping[str, Any],
        persisted_at: datetime,
    ) -> bool:
        self._run(run_id)
        inserted = False

        def update(state: dict[str, Any]) -> None:
            nonlocal inserted
            if phase not in state["checkpoints"]:
                state["checkpoints"][phase] = {"payload": dict(payload)}
                inserted = True

        self.journal.mutate("CANCELLATION_CHECKPOINT", {"phase": phase, "at": persisted_at}, update)
        return inserted

    def upsert(
        self,
        *,
        run_id: str,
        phase: str,
        client_order_id: str,
        venue_order_id: str | None,
        payload: Mapping[str, Any],
        persisted_at: datetime,
    ) -> None:
        self._run(run_id)

        def update(state: dict[str, Any]) -> None:
            state["checkpoints"][phase] = {"payload": dict(payload)}

        self.journal.mutate("CANCELLATION_CHECKPOINT", {"phase": phase, "at": persisted_at}, update)

    def _run(self, run_id: str) -> None:
        if run_id != self.journal.authority.run_id:
            raise SessionBlocked("cancellation_run_mismatch")
