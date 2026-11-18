"""Persist frozen cohorts and atomic forward-Shadow progress."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.domain.copytrading.watchlist_shadow import (
    MAX_DURATION,
    MAX_RUN_WALLETS,
    MAX_RUNS,
    MIN_DURATION,
    SHADOW_MODEL,
    STARTING_CASH,
)
from polysia.storage.watchlists import LIST_ID_PATTERN


class WatchlistRuns:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute(
                """CREATE TABLE IF NOT EXISTS watchlist_run (
                    owner TEXT NOT NULL, id TEXT NOT NULL, list_id TEXT NOT NULL,
                    list_revision INTEGER NOT NULL, duration INTEGER NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL,
                    snapshot TEXT NOT NULL, started_at TEXT NOT NULL,
                    PRIMARY KEY(owner,id)
                )"""
            )
            db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS watchlist_run_active
                    ON watchlist_run(status) WHERE status = 'RUNNING'"""
            )
        except sqlite3.Error:
            db.close()
            raise
        return db

    def start(
        self, owner: str, run_id: str, item: str, revision: int, duration: int, now: datetime
    ) -> None:
        if (
            not MIN_DURATION <= duration <= MAX_DURATION
            or not re.fullmatch(LIST_ID_PATTERN, run_id)
            or not re.fullmatch(LIST_ID_PATTERN, item)
        ):
            raise ValueError("shadow_request_invalid")
        if not self.path.is_file():
            raise ValueError("watchlist_missing")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """SELECT list_id,list_revision,duration FROM watchlist_run
                   WHERE owner=? AND id=?""",
                (owner, run_id),
            ).fetchone()
            if existing is not None:
                if existing != (item, revision, duration):
                    raise ValueError("shadow_request_id_conflict")
                return
            row = db.execute(
                """SELECT name,wallets FROM saved_watchlist
                   WHERE owner=? AND id=? AND revision=?""",
                (owner, item, revision),
            ).fetchone()
            if row is None:
                raise ValueError("watchlist_revision_changed")
            name, encoded = row
            wallets = json.loads(encoded)
            if not 1 <= len(wallets) <= MAX_RUN_WALLETS:
                raise ValueError("shadow_cohort_size")
            if db.execute("SELECT 1 FROM watchlist_run WHERE status='RUNNING'").fetchone():
                raise ValueError("shadow_busy")
            if db.execute(
                "SELECT count(*) FROM watchlist_run WHERE owner=?", (owner,)
            ).fetchone()[0] >= MAX_RUNS:
                raise ValueError("shadow_history_limit")
            started_at = now.isoformat()
            data = {
                "id": run_id, "name": name, "model": SHADOW_MODEL,
                "started_at": started_at,
                "ends_at": (now + timedelta(seconds=duration)).isoformat(),
                "finished_at": None, "started_cash_per_wallet": STARTING_CASH,
                "wallets": {
                    wallet: {
                        "through": started_at, "read_errors": 0, "observations": 0,
                        "cash": STARTING_CASH, "realized": "0", "fees": "0", "slippage": "0",
                        "events": {}, "positions": {},
                    }
                    for wallet in wallets
                },
            }
            db.execute(
                "INSERT INTO watchlist_run VALUES (?,?,?,?,?,'RUNNING',0,?,?)",
                (owner, run_id, item, revision, duration, json.dumps(data), started_at),
            )

    def for_owner(self, owner: str) -> list[tuple[str, dict[str, Any]]]:
        if not self.path.is_file():
            return []
        with closing(self._connect()) as db:
            return [(status, json.loads(snapshot)) for status, snapshot in db.execute(
                """SELECT status,snapshot FROM watchlist_run
                   WHERE owner=? ORDER BY started_at DESC LIMIT ?""",
                (owner, MAX_RUNS),
            )]

    def active(self) -> tuple[str, str, int, dict[str, Any]] | None:
        if not self.path.is_file():
            return None
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT owner,id,revision,snapshot FROM watchlist_run WHERE status='RUNNING'"
            ).fetchone()
        return (row[0], row[1], row[2], json.loads(row[3])) if row is not None else None

    def apply(
        self, owner: str, run_id: str, revision: int, status: str, data: dict[str, Any]
    ) -> bool:
        with closing(self._connect()) as db, db:
            result = db.execute(
                """UPDATE watchlist_run SET snapshot=?,status=?,revision=revision+1
                   WHERE owner=? AND id=? AND revision=? AND status='RUNNING'""",
                (json.dumps(data), status, owner, run_id, revision),
            )
        return result.rowcount == 1

    def cancel(self, owner: str, run_id: str, now: datetime) -> None:
        if not self.path.is_file():
            return
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT snapshot FROM watchlist_run WHERE owner=? AND id=? AND status='RUNNING'",
                (owner, run_id),
            ).fetchone()
            if row is not None:
                data = json.loads(row[0])
                data["finished_at"] = now.isoformat()
                db.execute(
                    """UPDATE watchlist_run SET snapshot=?, status='CANCELLED', revision=revision+1
                       WHERE owner=? AND id=?""",
                    (json.dumps(data), owner, run_id),
                )
