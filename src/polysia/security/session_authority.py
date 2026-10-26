"""Small local Ed25519 receipt verifier. No issuance or browser provisioning API.

Trusted public keys are operator-installed configuration; the private issuer key
is never loaded by this package. Revocation and consumption live outside every
financial backup. OS identity/ACL separation is a commissioning prerequisite.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from polysia.domain.financial_session import (
    RuntimeBinding,
    SessionAuthorization,
    SessionBlocked,
    canonical_json,
    utc,
)
from polysia.storage.financial_session import SessionRecoveryCheckpoint


def receipt_message(authority: SessionAuthorization, *, key_id: str, receipt_id: str) -> bytes:
    body = asdict(authority)
    del body["owner_receipt"]
    return canonical_json(
        {
            "version": "session-owner-receipt/v1",
            "key_id": key_id,
            "receipt_id": receipt_id,
            "authorization": body,
        }
    ).encode()


@dataclass(frozen=True, slots=True)
class VerifiedSessionReceipt:
    receipt_id: str
    key_id: str
    fingerprint: str


class SessionReceiptVerifier:
    def __init__(self, keys: Mapping[str, bytes]) -> None:
        self._keys = {
            name: Ed25519PublicKey.from_public_bytes(value) for name, value in keys.items()
        }

    def verify(
        self,
        authority: SessionAuthorization,
        binding: RuntimeBinding,
        *,
        now: datetime,
        action: str = "ENTRY",
    ) -> VerifiedSessionReceipt:
        authority.assert_action(binding, utc(now), action)
        try:
            envelope = json.loads(authority.owner_receipt)
            if not isinstance(envelope, dict) or set(envelope) != {
                "key_id",
                "receipt_id",
                "signature",
            }:
                raise ValueError("receipt shape")
            key_id, receipt_id = envelope["key_id"], envelope["receipt_id"]
            if not isinstance(receipt_id, str) or not 16 <= len(receipt_id) <= 128:
                raise ValueError("receipt identity")
            signature = base64.b64decode(envelope["signature"], validate=True)
            self._keys[key_id].verify(
                signature, receipt_message(authority, key_id=key_id, receipt_id=receipt_id)
            )
        except (ValueError, TypeError, KeyError, InvalidSignature) as error:
            raise SessionBlocked("owner_receipt_untrusted") from error
        return VerifiedSessionReceipt(receipt_id, key_id, authority.fingerprint)


class SessionCustody:
    """Supervisor-owned consumed receipts, revocations, STOP and exact checkpoints.

    Workers receive a read-only mount/ACL. Only the independent supervisor calls
    mutators. This database must not be co-restored with journal/witness backups.
    A claim is never refunded, including after failed provisioning.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        if self.path.is_symlink():
            raise SessionBlocked("custody_symlink_denied")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self._connect(write=True)) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS grants(
                    receipt TEXT PRIMARY KEY, key_id TEXT NOT NULL,
                    fingerprint TEXT UNIQUE NOT NULL,
                    run_id TEXT UNIQUE NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                    stopped INTEGER NOT NULL DEFAULT 1, reason TEXT NOT NULL,
                    stop_reason TEXT NOT NULL DEFAULT 'commissioning_stop',
                    supervised_at TEXT, worker_at TEXT, sequence INTEGER, checkpoint TEXT);
                CREATE TABLE IF NOT EXISTS revoked_keys(key_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS revoked_receipts(receipt_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS custody_events(
                    sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, evidence TEXT NOT NULL);
            """)

    def claim(self, receipt: VerifiedSessionReceipt, authority: SessionAuthorization) -> None:
        if receipt.fingerprint != authority.fingerprint:
            raise SessionBlocked("verified_receipt_binding_changed")
        try:
            with closing(self._connect(write=True)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                if (
                    connection.execute(
                        "SELECT 1 FROM revoked_keys WHERE key_id=?", (receipt.key_id,)
                    ).fetchone()
                    or connection.execute(
                        "SELECT 1 FROM revoked_receipts WHERE receipt_id=?", (receipt.receipt_id,)
                    ).fetchone()
                ):
                    raise SessionBlocked("owner_key_or_receipt_revoked")
                connection.execute(
                    "INSERT INTO grants(receipt,key_id,fingerprint,run_id,reason) "
                    "VALUES(?,?,?,?,?)",
                    (
                        receipt.receipt_id,
                        receipt.key_id,
                        receipt.fingerprint,
                        authority.run_id,
                        "commissioning_stop",
                    ),
                )
                self._event(connection, "CLAIMED", {"receipt": receipt.receipt_id})
        except sqlite3.IntegrityError as error:
            raise SessionBlocked("receipt_replayed_or_run_already_claimed") from error

    def revoke(self, *, receipt_id: str | None = None, key_id: str | None = None) -> None:
        if (receipt_id is None) == (key_id is None):
            raise SessionBlocked("exact_revocation_target_required")
        with closing(self._connect(write=True)) as connection, connection:
            if key_id is not None:
                connection.execute("INSERT OR IGNORE INTO revoked_keys VALUES(?)", (key_id,))
                connection.execute(
                    "UPDATE grants SET revoked=1,stopped=1 WHERE key_id=?", (key_id,)
                )
            else:
                connection.execute(
                    "INSERT OR IGNORE INTO revoked_receipts VALUES(?)", (receipt_id,)
                )
                connection.execute(
                    "UPDATE grants SET revoked=1,stopped=1 WHERE receipt=?", (receipt_id,)
                )
            self._event(connection, "REVOKED", {"receipt": receipt_id, "key": key_id})

    def stop(self, fingerprint: str, *, reason: str) -> None:
        with closing(self._connect(write=True)) as connection, connection:
            changed = connection.execute(
                "UPDATE grants SET stopped=1,reason=?,stop_reason=? WHERE fingerprint=?",
                (reason, reason, fingerprint),
            ).rowcount
            if changed != 1:
                raise SessionBlocked("unknown_grant_for_STOP")
            self._event(connection, "STOP", {"fingerprint": fingerprint, "reason": reason})

    def acknowledge(
        self,
        checkpoint: SessionRecoveryCheckpoint,
        *,
        now: datetime,
        worker_at: datetime,
        reason: str,
        ready: bool,
    ) -> None:
        """Supervisor only: acknowledge an independently checked committed state.

        Healthy liveness never clears a durable STOP. A stopped receipt needs a
        distinct explicit trusted release after commissioning/recovery checks.
        """
        with closing(self._connect(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT sequence,checkpoint FROM grants WHERE fingerprint=?",
                (checkpoint.authority_fingerprint,),
            ).fetchone()
            if row is None or (row[0] is not None and checkpoint.sequence < row[0]):
                raise SessionBlocked("checkpoint_rollback_or_unknown_grant")
            encoded = canonical_json(asdict(checkpoint))
            if row[0] == checkpoint.sequence and row[1] != encoded:
                raise SessionBlocked("checkpoint_fork")
            connection.execute(
                "UPDATE grants SET sequence=?,checkpoint=?,supervised_at=?,worker_at=?,"
                "reason=?,stopped=CASE WHEN ? THEN stopped ELSE 1 END WHERE fingerprint=?",
                (
                    checkpoint.sequence,
                    encoded,
                    utc(now).isoformat(),
                    utc(worker_at).isoformat(),
                    reason,
                    ready,
                    checkpoint.authority_fingerprint,
                ),
            )
            # Keep current health on the grant row. Idle supervision must not
            # append 20 identical checkpoint events per second indefinitely.
            # Distinct financial generations retain their durable ACK history.
            if row[0] != checkpoint.sequence or row[1] != encoded:
                self._event(
                    connection,
                    "CHECKPOINT_ACK",
                    {"checkpoint": asdict(checkpoint), "ready": ready, "at": now, "reason": reason},
                )

    def release_stop(self, fingerprint: str, *, expected: SessionRecoveryCheckpoint) -> None:
        """Privileged supervisor commissioning operation, absent from browser/worker APIs."""
        with closing(self._connect(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT checkpoint,revoked,reason,stop_reason FROM grants WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
            if (
                row is None
                or row[1]
                or row[3] != "commissioning_stop"
                or row[2] != "supervisor_checks_passed"
                or row[0] != canonical_json(asdict(expected))
            ):
                raise SessionBlocked("stop_release_requires_exact_healthy_checkpoint")
            connection.execute("UPDATE grants SET stopped=0 WHERE fingerprint=?", (fingerprint,))
            self._event(connection, "STOP_RELEASE", {"checkpoint": asdict(expected)})

    def snapshot(self, fingerprint: str) -> dict[str, object]:
        with closing(self._connect(write=False)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM grants WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
        if row is None:
            raise SessionBlocked("authority_not_in_independent_custody")
        return dict(row)

    def require_current(
        self,
        authority: SessionAuthorization,
        *,
        now: datetime,
        checkpoint: SessionRecoveryCheckpoint | None = None,
    ) -> dict[str, object]:
        row = self.snapshot(authority.fingerprint)
        if row["revoked"] or row["stopped"]:
            raise SessionBlocked("independent_stop_or_revocation")
        timestamp = row["supervised_at"]
        if (
            not isinstance(timestamp, str)
            or not 0
            <= (utc(now) - datetime.fromisoformat(timestamp)).total_seconds()
            <= authority.supervision_timeout_seconds
        ):
            raise SessionBlocked("independent_supervisor_unavailable")
        if checkpoint is not None and row["checkpoint"] != canonical_json(asdict(checkpoint)):
            raise SessionBlocked("checkpoint_not_independently_retained")
        return row

    def recovery_checkpoint(self, authority: SessionAuthorization) -> SessionRecoveryCheckpoint:
        row = self.snapshot(authority.fingerprint)
        raw = row["checkpoint"]
        if not isinstance(raw, str):
            raise SessionBlocked("independent_recovery_proof_unavailable")
        return SessionRecoveryCheckpoint(**json.loads(raw))

    def _connect(self, *, write: bool) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise SessionBlocked("custody_symlink_denied")
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + ("?mode=rwc" if write else "?mode=ro"),
            uri=True,
            timeout=1,
        )
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _event(connection: sqlite3.Connection, kind: str, evidence: object) -> None:
        connection.execute(
            "INSERT INTO custody_events(kind,evidence) VALUES(?,?)",
            (kind, canonical_json(evidence)),
        )
