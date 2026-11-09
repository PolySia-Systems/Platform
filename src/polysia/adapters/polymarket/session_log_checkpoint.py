"""Durable, account-scoped finalized log evidence for the bounded RPC reader."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from polysia.domain.financial_session import SessionBlocked, canonical_json, digest


class FinalizedLogCheckpoint:
    MAX_BYTES = 64 * 1024**2

    def __init__(self, path: Path, scope: str) -> None:
        self.path, self.scope = path, scope

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise SessionBlocked("RPC_checkpoint_symlink_denied")
        if not self.path.exists():
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        if self.path.stat().st_size > self.MAX_BYTES:
            raise SessionBlocked("RPC_checkpoint_storage_bound_exceeded")
        return sqlite3.connect(self.path, timeout=1)

    def get(self, key: str) -> Any:
        if not self.path.exists():
            return None
        with closing(self._connect()) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'evidence'").fetchone() is None:
                return None
            row = db.execute(
                "SELECT body, fingerprint FROM evidence WHERE scope = ? AND key = ?",
                (self.scope, key),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        if digest(value) != row[1]:
            raise SessionBlocked("RPC_checkpoint_digest_mismatch")
        return value

    def advance(self, key: str, previous: Any, value: Any) -> None:
        with closing(self._connect()) as db, db:
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(f"PRAGMA max_page_count = {self.MAX_BYTES // page_size}")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS evidence (scope TEXT, key TEXT, body TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, PRIMARY KEY (scope, key))"
            )
            row = db.execute(
                "SELECT fingerprint FROM evidence WHERE scope = ? AND key = ?", (self.scope, key)
            ).fetchone()
            if (row[0] if row else None) != (digest(previous) if previous is not None else None):
                raise SessionBlocked("RPC_checkpoint_concurrent_writer")
            db.execute(
                "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?)",
                (self.scope, key, canonical_json(value), digest(value)),
            )
