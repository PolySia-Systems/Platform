"""Independent, single-host custody supervision and bounded checkpoint handshake.

Run this owner under a separate OS identity: read-only journal/witness/outbox,
write-only custody control for the worker. No signer or venue client is imported.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from polysia.control.scoped_operations import ScopedPreview
from polysia.control.service import ControlService
from polysia.deployment.financial_recovery import verify_recovery
from polysia.domain.financial_session import (
    SessionAuthorization,
    SessionBlocked,
    canonical_json,
    digest,
    utc,
)
from polysia.monitoring.session_incidents import SessionIncidents
from polysia.security.session_authority import SessionCustody
from polysia.storage.atomic_files import read_publication_bytes
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.financial_session import SessionRecoveryCheckpoint


def committed_checkpoint(path: Path, witness: Path) -> SessionRecoveryCheckpoint:
    if any(not item.is_file() or item.is_symlink() for item in (path, witness)):
        raise SessionBlocked("supervisor_financial_files_unavailable")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute(
            "ATTACH DATABASE ? AS witness", (witness.resolve().as_uri() + "?mode=ro",)
        )
        connection.execute("BEGIN")
        row = connection.execute("SELECT authority,sequence,state FROM session").fetchone()
        control = connection.execute(
            "SELECT fingerprint,sequence,state_digest FROM witness.authority"
        ).fetchone()
        if (
            row is None
            or control is None
            or (row[0], row[1], digest(json.loads(row[2]))) != control
        ):
            raise SessionBlocked("supervisor_committed_state_mismatch")
        return SessionRecoveryCheckpoint(*control)


@dataclass(frozen=True, slots=True)
class SupervisionPolicy:
    minimum_free_bytes: int
    backup_maximum_age_seconds: int
    handshake_timeout_seconds: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise SessionBlocked("positive_supervision_limits_required")


class SessionSupervisor:
    def __init__(
        self,
        authority: SessionAuthorization,
        custody: SessionCustody,
        *,
        journal: Path,
        witness: Path,
        outbox: Path,
        backup_receipt: Path,
        policy: SupervisionPolicy,
        clock: Callable[[], datetime],
        free_bytes: Callable[[Path], int] | None = None,
        commands: ConsoleCommandStore | None = None,
        incidents: SessionIncidents | None = None,
    ) -> None:
        self.authority, self.custody = authority, custody
        self.journal, self.witness, self.outbox = journal, witness, outbox
        self.backup_receipt, self.policy, self.clock = backup_receipt, policy, clock
        self.free_bytes = free_bytes or (lambda path: shutil.disk_usage(path).free)
        self._gap_started_at: datetime | None = None
        self.commands = commands
        self.incidents = incidents
        self._backup_identity: str | None = None

    def process_controls(self) -> None:
        if self.commands is None:
            return
        target = self.authority.run_id + ":stop"

        def execute(preview: ScopedPreview) -> dict:
            if preview.target != target or preview.operation != "session.stop":
                raise SessionBlocked("supervisor_control_scope_denied")
            self.custody.stop(self.authority.fingerprint, reason="scoped_operator_STOP")
            return {"effect": "OBSERVED", "stopped": True, "receipt": preview.fingerprint}

        for key in self.commands.pending_scoped(
            targets=frozenset({target}), operations=frozenset({"session.stop"})
        ):
            ControlService.execute_scoped(
                self.commands, idempotency_key=key, now=self.clock(), execute=execute
            )

    def inspect(self) -> SessionRecoveryCheckpoint:
        now = utc(self.clock())
        self.process_controls()
        try:
            checkpoint = committed_checkpoint(self.journal, self.witness)
            heartbeat = _small_json(self.outbox)
            worker_at = datetime.fromisoformat(heartbeat["worker_at"])
            if heartbeat["checkpoint"] != asdict(checkpoint):
                self._gap_started_at = self._gap_started_at or now
                if (now - self._gap_started_at).total_seconds() < (
                    self.policy.handshake_timeout_seconds
                ):
                    # A commit and its publication cannot be atomic across OS
                    # owners. During the bounded gap, do not refresh health or
                    # acknowledge a new sequence. Workers require exact ACKs.
                    return self.custody.recovery_checkpoint(self.authority)
                raise SessionBlocked("checkpoint_publication_gap")
            self._gap_started_at = None
            if (
                not 0
                <= (now - utc(worker_at)).total_seconds()
                <= (self.authority.supervision_timeout_seconds)
            ):
                raise SessionBlocked("worker_liveness_lost")
            if self.free_bytes(self.journal.parent) < self.policy.minimum_free_bytes:
                raise SessionBlocked("critical_storage_reserve_lost")
            backup = _small_json(self.backup_receipt)
            # This is protected commissioning evidence, never browser configuration.
            if (
                backup.get("authority_fingerprint") != self.authority.fingerprint
                or backup.get("mode") != "SEPARATE_FINANCIAL_RECOVERY"
                or backup.get("restore_verified") is not True
                or not isinstance(backup.get("artifact_sha256"), str)
                or len(backup["artifact_sha256"]) != 64
                or not 0
                <= (now - utc(datetime.fromisoformat(backup["observed_at"]))).total_seconds()
                <= self.policy.backup_maximum_age_seconds
            ):
                raise SessionBlocked("financial_backup_unprotected_or_stale")
            paths = [
                Path(item) for item in backup.get("artifacts", []) + backup.get("restored", [])
            ]
            backup_identity = digest(
                (
                    backup,
                    [
                        (path.stat().st_size, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
                        for path in paths
                    ],
                )
            )
            if backup_identity != self._backup_identity:
                verify_recovery(backup)
                if (
                    backup["checkpoint"]["authority_fingerprint"]
                    != checkpoint.authority_fingerprint
                    or backup["checkpoint"]["sequence"] > checkpoint.sequence
                    or (
                        backup["checkpoint"]["sequence"] == checkpoint.sequence
                        and backup["checkpoint"] != asdict(checkpoint)
                    )
                ):
                    raise SessionBlocked("financial_backup_generation_inapplicable")
                self._backup_identity = backup_identity
            self.custody.acknowledge(
                checkpoint,
                now=now,
                worker_at=worker_at,
                reason="supervisor_checks_passed",
                ready=True,
            )
            return checkpoint
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, SessionBlocked) as error:
            self.custody.stop(self.authority.fingerprint, reason="independent_supervision_failed")
            if self.incidents is not None:
                kind = (
                    "backup_unprotected"
                    if "backup" in str(error).lower()
                    else (
                        "critical_storage"
                        if "storage" in str(error).lower()
                        else "supervision_lost"
                    )
                )
                with suppress(OSError, sqlite3.Error):
                    self.incidents.record(
                        kind,
                        scope=self.authority.run_id,
                        reason_code="independent_supervision_failed",
                        next_action="Retain STOP; inspect protected supervisor, "
                        "storage and restore evidence",
                    )
            raise SessionBlocked("independent_supervision_failed") from error


class CheckpointPublisher:
    def __init__(
        self,
        authority: SessionAuthorization,
        custody: SessionCustody,
        outbox: Path,
        *,
        clock: Callable[[], datetime],
        timeout_seconds: int,
        monotonic: Callable[[], float] = time.monotonic,
        wait: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < timeout_seconds <= authority.supervision_timeout_seconds:
            raise SessionBlocked("bounded_checkpoint_handshake_required")
        self.authority, self.custody, self.outbox = authority, custody, outbox
        self.clock, self.timeout, self.monotonic, self.wait = (
            clock,
            timeout_seconds,
            monotonic,
            wait,
        )

    def publish(self, checkpoint: SessionRecoveryCheckpoint, *, acknowledge: bool = True) -> None:
        deadline = self.monotonic() + self.timeout
        if self.outbox.is_symlink():
            raise SessionBlocked("checkpoint_outbox_symlink_denied")
        self.outbox.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.outbox.with_suffix(".pending")
        payload = canonical_json({"checkpoint": asdict(checkpoint), "worker_at": self.clock()})
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        while True:
            try:
                temporary.replace(self.outbox)
                break
            except PermissionError:
                # Windows metadata/indexing handles can briefly deny replace
                # even when our reader shares delete. Retry only local publish,
                # within the original handshake budget, never financial I/O.
                if os.name != "nt" or self.monotonic() >= deadline:
                    raise
                self.wait(min(0.01, max(0, deadline - self.monotonic())))
        if os.name != "nt":
            descriptor = os.open(self.outbox.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if not acknowledge:
            return
        while self.monotonic() < deadline:
            row = self.custody.snapshot(self.authority.fingerprint)
            # STOP remains enforceable while commissioning publication is allowed.
            if row["revoked"]:
                raise SessionBlocked("receipt_revoked_during_checkpoint_handshake")
            if row["checkpoint"] == canonical_json(asdict(checkpoint)):
                return
            self.wait(min(0.05, max(0, deadline - self.monotonic())))
        raise SessionBlocked("checkpoint_acknowledgement_timeout")


def _small_json(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > 8192:
        raise SessionBlocked("protected_supervision_evidence_invalid")
    result = json.loads(read_publication_bytes(path, maximum_bytes=8192))
    if not isinstance(result, dict):
        raise SessionBlocked("protected_supervision_evidence_invalid")
    return result
