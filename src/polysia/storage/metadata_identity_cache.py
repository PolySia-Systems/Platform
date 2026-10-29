"""Disposable bounded identity cache; never stores mutable market authority."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class MetadataIdentityCache:
    VERSION = "polymarket-identity/v1"
    MAX_ENTRIES = 1024
    MAX_BYTES = 2_097_152
    TTL = timedelta(hours=3)

    def __init__(self, path: Path) -> None:
        self.path = path
        self.counts = {"hits": 0, "misses": 0, "invalid": 0, "errors": 0}

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise OSError("disposable cache symlink denied")
        connection = sqlite3.connect(self.path, timeout=0.05)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS identity_cache (scope TEXT PRIMARY KEY,"
            "version TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL,"
            "digest TEXT NOT NULL)"
        )
        return connection

    def get(self, scope: str, *, now: datetime) -> dict[str, Any] | None:
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT version,observed_at,payload,digest FROM identity_cache WHERE scope=?",
                    (scope,),
                ).fetchone()
                if row is not None:
                    age = now - datetime.fromisoformat(row[1])
                    if (
                        row[0] == self.VERSION
                        and timedelta(0) <= age < self.TTL
                        and len(row[2].encode()) <= 4096
                        and hashlib.sha256(row[2].encode()).hexdigest() == row[3]
                    ):
                        value = json.loads(row[2])
                        if isinstance(value, dict):
                            self.counts["hits"] += 1
                            return value
                    self.counts["invalid"] += 1
                    connection.execute("DELETE FROM identity_cache WHERE scope=?", (scope,))
        except OSError, ValueError, TypeError, sqlite3.Error:
            self.counts["errors"] += 1
        self.counts["misses"] += 1
        return None

    def put(self, scope: str, payload: dict[str, Any], *, observed_at: datetime) -> None:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(raw.encode()) > 4096:
            return
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR REPLACE INTO identity_cache VALUES(?,?,?,?,?)",
                    (
                        scope,
                        self.VERSION,
                        observed_at.isoformat(),
                        raw,
                        hashlib.sha256(raw.encode()).hexdigest(),
                    ),
                )
                connection.execute(
                    "DELETE FROM identity_cache WHERE observed_at<?",
                    ((observed_at - self.TTL).isoformat(),),
                )
                # A fixed payload bound also bounds file growth; SQLite reuses free pages.
                connection.execute(
                    "DELETE FROM identity_cache WHERE scope NOT IN "
                    "(SELECT scope FROM identity_cache ORDER BY observed_at DESC,scope LIMIT ?)",
                    (min(self.MAX_ENTRIES, self.MAX_BYTES // 4096),),
                )
        except OSError, ValueError, sqlite3.Error:
            self.counts["errors"] += 1

    def evict(self, scope: str) -> None:
        self.counts["invalid"] += 1
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("DELETE FROM identity_cache WHERE scope=?", (scope,))
        except OSError, sqlite3.Error:
            self.counts["errors"] += 1
