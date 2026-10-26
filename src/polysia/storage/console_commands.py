"""Dedicated command queue; the web process never writes financial evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.control.scoped_operations import ScopedPreview
from polysia.domain.financial_session import canonical_json, digest, utc


class ConsoleCommandStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS commands (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE, actor TEXT NOT NULL,
                    action TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS scoped_previews(
                    identity TEXT PRIMARY KEY, actor TEXT NOT NULL, target TEXT NOT NULL,
                    preview TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scoped_targets(
                    target TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS scoped_commands(
                    idempotency TEXT PRIMARY KEY,digest TEXT NOT NULL,preview TEXT NOT NULL,
                    target TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,
                    result TEXT,UNIQUE(target,revision));
                CREATE TABLE IF NOT EXISTS console_preview_bindings(
                    preview_id TEXT PRIMARY KEY,context TEXT NOT NULL,identity TEXT NOT NULL);
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(commands)")}
            for name in ("parameters", "result"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE commands ADD COLUMN {name} TEXT")

        if sys.platform != "win32" and self._path.stat().st_uid == os.geteuid():
            # Dedicated worker/web IDs share only the setgid control directory.
            # The web process cannot chmod a worker-owned file, nor needs to.
            self._path.chmod(0o660)

    def submit(
        self,
        *,
        subject: str,
        action: str,
        expected_revision: int,
        idempotency_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        if action not in {"stop", "drain", "resume", "export"}:
            raise ValueError("unsupported_command")
        if (
            type(expected_revision) is not int
            or expected_revision < 0
            or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", idempotency_key)
        ):
            raise ValueError("invalid_command_identity")
        payload: dict[str, Any] = {
            "actor": subject,
            "action": action,
            "expected_revision": expected_revision,
        }
        if parameters is not None and not isinstance(parameters, dict):
            raise ValueError("command_parameters_object_required")
        if parameters:
            if action != "export" or set(parameters) != {"start", "end"}:
                raise ValueError("unsupported_command_parameters")
            start, end = (datetime.fromisoformat(parameters[key]) for key in ("start", "end"))
            if start >= end or any(item.utcoffset() != timedelta(0) for item in (start, end)):
                raise ValueError("paired_increasing_UTC_bounds_required")
            payload["parameters"] = parameters
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT revision, digest, status FROM commands WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing[1] != digest:
                    raise ValueError("idempotency_conflict")
                return {"revision": existing[0], "status": existing[2]}
            revision = connection.execute(
                "SELECT COALESCE(MAX(revision),0) FROM commands",
            ).fetchone()[0]
            if revision != expected_revision:
                raise ValueError("revision_conflict")
            row = connection.execute(
                "INSERT INTO commands(idempotency_key,actor,action,digest,status,parameters) "
                "VALUES(?,?,?,?,'REQUESTED',?)",
                (idempotency_key, subject, action, digest, json.dumps(parameters or {})),
            )
            return {"revision": row.lastrowid, "status": "REQUESTED"}

    def status(self) -> dict[str, object]:
        with closing(
            sqlite3.connect(
                f"{self._path.resolve().as_uri()}?mode=ro",
                uri=True,
            )
        ) as connection:
            rows = connection.execute(
                "SELECT revision, action, status, created_at, result FROM commands "
                "ORDER BY revision DESC LIMIT 30"
            ).fetchall()
        return {
            "revision": rows[0][0] if rows else 0,
            "receipts": [
                dict(
                    zip(
                        ("revision", "action", "status", "created_at", "result"),
                        (*row[:4], json.loads(row[4]) if row[4] else None),
                        strict=True,
                    )
                )
                for row in rows
            ],
        }

    def block_superseded_resumes(self) -> None:
        """A later STOP fences all earlier resume work, including after restart."""
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "UPDATE commands SET status='BLOCKED', result=? "
                "WHERE action='resume' AND status='REQUESTED' AND revision < "
                "(SELECT COALESCE(MAX(revision),0) FROM commands WHERE action='stop')",
                (json.dumps({"reason": "superseded_by_stop"}),),
            )

    def reconcile_report_downloads(self, archive: Path) -> int:
        """On isolated restore, explicitly retire unrecoverable APPLIED claims."""
        changed = 0
        with closing(sqlite3.connect(self._path)) as connection, connection:
            rows = connection.execute(
                "SELECT revision,result FROM commands WHERE action='export' AND status='APPLIED'"
            ).fetchall()
            for revision, raw in rows:
                result = json.loads(raw) if raw else {}
                download = result.get("download", "")
                if (not isinstance(download, str)
                        or re.fullmatch(r"/reports/[a-f0-9]{64}\.json", download) is None
                        or not (archive / download.rsplit("/", 1)[-1]).is_file()):
                    connection.execute(
                        "UPDATE commands SET status='FAILED',result=? WHERE revision=?",
                        (json.dumps({"reason": "retained_report_unavailable_after_restore",
                                     "previous_result": result}), revision),
                    )
                    changed += 1
        return changed

    def pending(self, *, actions: tuple[str, ...] | None = None) -> list[tuple[int, str]]:
        condition = "" if actions is None else " AND action IN (" + ",".join(
            "?" for _ in actions
        ) + ")"
        with closing(sqlite3.connect(self._path)) as connection, connection:
            return [
                (int(row[0]), str(row[1]))
                for row in connection.execute(
                    "SELECT revision, action FROM commands WHERE status='REQUESTED' "
                    + condition + " ORDER BY CASE WHEN action='stop' THEN 0 ELSE 1 END, "
                    "revision LIMIT 30",
                    actions or (),
                )
            ]

    def parameters(self, revision: int) -> dict[str, Any]:
        with closing(sqlite3.connect(self._path)) as connection:
            row = connection.execute(
                "SELECT parameters FROM commands WHERE revision=?", (revision,)
            ).fetchone()
        return json.loads(row[0]) if row and row[0] else {}

    def finish(self, revision: int, *, status: str, result: dict[str, Any] | None = None) -> None:
        if status not in {"APPLIED", "BLOCKED", "FAILED"}:
            raise ValueError("invalid terminal receipt")
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "UPDATE commands SET status=?,result=? WHERE revision=? AND status='REQUESTED'",
                (status, json.dumps(result), revision),
            )

    def save_scoped_preview(self, preview: ScopedPreview) -> str:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO scoped_previews VALUES(?,?,?,?)",
                (
                    preview.fingerprint,
                    preview.actor,
                    preview.target,
                    canonical_json(asdict(preview)),
                ),
            )
        return preview.fingerprint

    def scoped_revision(self, target: str) -> int:
        with closing(sqlite3.connect(self._path)) as connection:
            row = connection.execute("SELECT revision FROM scoped_targets WHERE target=?",
                                     (target,)).fetchone()
        return 0 if row is None else int(row[0])

    def submit_scoped(
        self, *, subject: str, role: str, preview_id: str, expected_revision: int,
        idempotency_key: str, now: datetime, allowed_targets: frozenset[str],
    ) -> dict[str, Any]:
        if role != "operator" or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", idempotency_key):
            raise ValueError("trusted_scoped_operator_required")
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT preview FROM scoped_previews WHERE identity=?",
                                     (preview_id,)).fetchone()
            if row is None:
                raise ValueError("unknown_immutable_preview")
            preview = json.loads(row[0])
            if digest(preview) != preview_id:
                raise ValueError("immutable_preview_corrupted")
            if preview["actor"] != subject or preview["target"] not in allowed_targets:
                raise ValueError("preview_actor_or_target_denied")
            content_digest = digest((subject, preview_id, expected_revision))
            existing = connection.execute(
                "SELECT digest,status,result,revision FROM scoped_commands WHERE idempotency=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing[0] != content_digest:
                    raise ValueError("scoped_idempotency_conflict")
                return {"status": existing[1], "result": json.loads(existing[2])
                        if existing[2] else None, "revision": existing[3]}
            if (preview["expected_revision"] != expected_revision
                    or not datetime.fromisoformat(preview["created_at"]) <= utc(now)
                    < datetime.fromisoformat(preview["expires_at"])):
                raise ValueError("stale_or_expired_preview")
            current = connection.execute("SELECT revision FROM scoped_targets WHERE target=?",
                                         (preview["target"],)).fetchone()
            if (0 if current is None else current[0]) != expected_revision:
                raise ValueError("scoped_revision_conflict")
            revision = expected_revision + 1
            connection.execute("INSERT INTO scoped_commands VALUES(?,?,?,?,?,'REQUESTED',NULL)",
                (idempotency_key, content_digest, row[0], preview["target"], revision))
            connection.execute("INSERT INTO scoped_targets VALUES(?,?) ON CONFLICT(target) "
                "DO UPDATE SET revision=excluded.revision", (preview["target"], revision))
            return {"status": "REQUESTED", "revision": revision, "effect": "NOT_OBSERVED"}

    def claim_scoped(self, idempotency_key: str, *, now: datetime) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT preview,status,target,revision FROM scoped_commands WHERE idempotency=?",
                (idempotency_key,),
            ).fetchone()
            if row is None or row[1] != "REQUESTED":
                return None
            if connection.execute("SELECT 1 FROM scoped_commands WHERE target=? AND "
                "(status='CLAIMED' OR (status='REQUESTED' AND revision<?)) LIMIT 1",
                (row[2], row[3])).fetchone():
                return None
            preview = json.loads(row[0])
            status = "CLAIMED" if (datetime.fromisoformat(preview["created_at"]) <= utc(now)
                < datetime.fromisoformat(preview["expires_at"])) else "FAILED"
            connection.execute("UPDATE scoped_commands SET status=?,result=? WHERE idempotency=?",
                               (status, None if status == "CLAIMED" else canonical_json(
                                   {"effect": "NOT_OBSERVED", "reason": "preview_expired"}),
                                idempotency_key))
            return preview if status == "CLAIMED" else None

    def pending_scoped(self, *, targets: frozenset[str], operations: frozenset[str]) -> list[str]:
        if not targets or not operations:
            return []
        with closing(sqlite3.connect(self._path)) as connection:
            rows = connection.execute("SELECT idempotency FROM scoped_commands "
                "WHERE status='REQUESTED' AND target IN (" + ",".join("?" for _ in targets)
                + ") AND json_extract(preview,'$.operation') IN ("
                + ",".join("?" for _ in operations) + ") ORDER BY "
                "CASE json_extract(preview,'$.operation') WHEN 'session.stop' THEN 0 ELSE 1 END,"
                "rowid LIMIT 100", (*sorted(targets), *sorted(operations))).fetchall()
        return [row[0] for row in rows]

    def retire_scoped_claims(self, *, targets: frozenset[str]) -> None:
        """Exclusive owner startup fences uncertain effects; never retry them."""
        with closing(sqlite3.connect(self._path)) as connection, connection:
            for target in targets:
                connection.execute("UPDATE scoped_commands SET status='FAILED',result=? "
                    "WHERE target=? AND status='CLAIMED'", (canonical_json({
                        "effect": "UNKNOWN", "reason": "owner_restarted_after_claim"}), target))

    def finish_scoped(self, key: str, *, status: str, result: dict[str, Any]) -> None:
        if status not in {"APPLIED", "FAILED", "BLOCKED"}:
            raise ValueError("terminal_scoped_receipt_required")
        with closing(sqlite3.connect(self._path)) as connection, connection:
            changed = connection.execute("UPDATE scoped_commands SET status=?,result=? "
                "WHERE idempotency=? AND status='CLAIMED'",
                (status, canonical_json(result), key)).rowcount
            if changed != 1:
                raise ValueError("scoped_command_not_claimed")

    def scoped_status(self) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self._path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                "SELECT idempotency,target,revision,status,result FROM scoped_commands "
                "ORDER BY rowid DESC LIMIT 100")]

    def bind_console_preview(self, preview_id: str, *, context: str, identity: str) -> None:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO console_preview_bindings VALUES(?,?,?)",
                (preview_id, context, identity),
            )

    def console_preview(self, preview_id: str, *, context: str, identity: str) -> dict[str, Any]:
        with closing(sqlite3.connect(self._path, timeout=1)) as connection:
            row = connection.execute(
                "SELECT p.preview FROM scoped_previews p JOIN console_preview_bindings b "
                "ON b.preview_id=p.identity WHERE b.preview_id=? AND b.context=? AND b.identity=?",
                (preview_id, context, identity),
            ).fetchone()
        if row is None:
            raise ValueError("console_preview_binding_differs")
        return json.loads(row[0])

    def console_receipts(
        self,
        *,
        subject: str,
        targets: frozenset[str],
        key: str | None = None,
        before: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Exact recovery and bounded history, scoped to current actor and target policy."""
        if not targets:
            return []
        if not 1 <= limit <= 100 or (
            key is not None and re.fullmatch(r"[a-zA-Z0-9-]{16,80}", key) is None
        ):
            raise ValueError("invalid_receipt_query")
        conditions = [
            "json_extract(preview,'$.actor')=?",
            "target IN (" + ",".join("?" for _ in targets) + ")",
        ]
        values: list[Any] = [subject, *sorted(targets)]
        if key is not None:
            conditions.append("idempotency=?")
            values.append(key)
        if before is not None:
            if before < 1:
                raise ValueError("invalid_history_cursor")
            conditions.append("rowid<?")
            values.append(before)
        with closing(sqlite3.connect(self._path, timeout=1)) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT rowid,idempotency,preview,target,revision,status,result "
                    "FROM scoped_commands "
                    "WHERE " + " AND ".join(conditions) + " ORDER BY rowid DESC LIMIT ?",
                    (*values, limit),
                )
            ]
