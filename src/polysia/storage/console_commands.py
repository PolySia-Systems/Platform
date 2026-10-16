"""Dedicated command queue; the web process never writes financial evidence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path


class ConsoleCommandStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS commands (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE, actor TEXT NOT NULL,
                    action TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
            """)

    def submit(
        self, *, subject: str, action: str, expected_revision: int, idempotency_key: str,
    ) -> dict[str, object]:
        if action not in {"stop", "drain", "resume", "export"}:
            raise ValueError("unsupported_command")
        if (type(expected_revision) is not int or expected_revision < 0
                or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", idempotency_key)):
            raise ValueError("invalid_command_identity")
        digest = hashlib.sha256(json.dumps({
            "actor": subject, "action": action, "expected_revision": expected_revision,
        }, sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(self._path, timeout=1) as connection:
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
                "INSERT INTO commands(idempotency_key,actor,action,digest,status) "
                "VALUES(?,?,?,?,'REQUESTED')", (idempotency_key, subject, action, digest),
            )
            return {"revision": row.lastrowid, "status": "REQUESTED"}

    def status(self) -> dict[str, object]:
        with sqlite3.connect(f"{self._path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT revision, action, status, created_at FROM commands "
                "ORDER BY revision DESC LIMIT 30"
            ).fetchall()
        return {"revision": rows[0][0] if rows else 0,
                "receipts": [dict(zip(("revision", "action", "status", "created_at"), row,
                                      strict=True)) for row in rows]}

    def pending(self) -> list[tuple[int, str]]:
        with sqlite3.connect(self._path) as connection:
            return [(int(row[0]), str(row[1])) for row in connection.execute(
                "SELECT revision, action FROM commands WHERE status='REQUESTED' "
                "ORDER BY revision LIMIT 30",
            )]

    def finish(self, revision: int, *, status: str) -> None:
        if status not in {"APPLIED", "BLOCKED", "FAILED"}:
            raise ValueError("invalid terminal receipt")
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "UPDATE commands SET status=? WHERE revision=? AND status='REQUESTED'",
                (status, revision),
            )
