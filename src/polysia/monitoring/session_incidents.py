"""Deduplicated protected local incidents; optional delivery requires its own authority."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from polysia.domain.financial_session import SessionBlocked, digest, utc

KINDS = frozenset(
    {
        "financial_ambiguity",
        "supervision_lost",
        "experiment_stopped",
        "critical_storage",
        "backup_unprotected",
    }
)


class IncidentSink(Protocol):
    def deliver(self, payload: dict[str, Any]) -> str: ...


class SessionIncidents:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime],
        minimum_interval: timedelta = timedelta(minutes=5),
    ) -> None:
        if minimum_interval <= timedelta(0):
            raise ValueError("positive incident rate limit required")
        self.path, self.clock, self.interval = path, clock, minimum_interval

    def initialize(self) -> None:
        if self.path.is_symlink():
            raise SessionBlocked("incident_store_symlink_denied")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS incidents("
                "identity TEXT PRIMARY KEY,kind TEXT,scope TEXT,reason TEXT,next_action TEXT,"
                "first_at TEXT,last_at TEXT,count INTEGER,delivery_state TEXT,"
                "last_attempt TEXT,delivery_receipt TEXT)"
            )
        self.path.chmod(0o600)

    def record(self, kind: str, *, scope: str, reason_code: str, next_action: str) -> str:
        if kind not in KINDS or not scope or not reason_code or not next_action:
            raise ValueError("allowlisted actionable incident required")
        identity = digest((kind, scope, reason_code))
        now = utc(self.clock()).isoformat()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO incidents VALUES(?,?,?,?,?,?,?,1,'LOCAL_ONLY',NULL,NULL)"
                " ON CONFLICT(identity) DO UPDATE SET last_at=excluded.last_at,count=count+1",
                (identity, kind, scope, reason_code, next_action, now, now),
            )
        return identity

    def deliver(
        self, identity: str, sink: IncidentSink, *, destination_authorized: bool = False
    ) -> str:
        if destination_authorized is not True:
            raise SessionBlocked("separate_notification_delivery_authority_required")
        now = utc(self.clock())
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM incidents WHERE identity=?", (identity,)
            ).fetchone()
            if row is None:
                raise ValueError("unknown incident")
            if (
                row["last_attempt"] is not None
                and now - datetime.fromisoformat(row["last_attempt"]) < self.interval
            ):
                return "RATE_LIMITED"
            # Durable claim precedes sink I/O. Crashes leave UNKNOWN delivery and
            # cannot immediately cause a second notification on restart.
            connection.execute(
                "UPDATE incidents SET last_attempt=?,delivery_state='UNKNOWN' WHERE identity=?",
                (now.isoformat(), identity),
            )
            payload = dict(row)
        try:
            receipt = sink.deliver(payload)
            if not isinstance(receipt, str) or not receipt:
                raise ValueError("sink receipt missing")
            status = "DELIVERED"
        except Exception:
            receipt, status = None, "FAILED"
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "UPDATE incidents SET delivery_state=?,delivery_receipt=? WHERE identity=?",
                (status, json.dumps(receipt), identity),
            )
        return status

    def projection(self) -> list[dict[str, Any]]:
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM incidents ORDER BY last_at DESC LIMIT 100"
                )
            ]
