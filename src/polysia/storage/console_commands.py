"""Dedicated command queue; the web process never writes financial evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


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
