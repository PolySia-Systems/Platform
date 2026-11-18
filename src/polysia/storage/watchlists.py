"""Independent owner-scoped lists. Rank refresh and experimental state are separate."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict

MAX_LISTS = 16
MAX_WALLETS = 32
MAX_NAME = 80
WALLET_PATTERN = r"^0x[0-9a-f]{40}$"
LIST_ID_PATTERN = r"^[0-9a-f]{32}$"


class SavedWatchlist(TypedDict):
    id: str
    name: str
    wallets: list[str]
    revision: int


class WatchlistStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute(
                """CREATE TABLE IF NOT EXISTS saved_watchlist (
                    owner TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
                    wallets TEXT NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(owner,id)
                )"""
            )
        except sqlite3.Error:
            db.close()
            raise
        return db

    def lists(self, owner: str) -> list[SavedWatchlist]:
        if not self.path.is_file():
            return []
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT id, name, wallets, revision FROM saved_watchlist
                WHERE owner=? ORDER BY name COLLATE NOCASE,id LIMIT ?""",
                (owner, MAX_LISTS),
            ).fetchall()
        return [
            SavedWatchlist(id=item, name=name, wallets=json.loads(wallets), revision=rev)
            for item, name, wallets, rev in rows
        ]

    def save(
        self, owner: str, item: str, name: str, wallets: list[str], expected_revision: int
    ) -> None:
        name = name.strip()
        addresses = sorted({wallet.strip().lower() for wallet in wallets})
        if (
            re.fullmatch(LIST_ID_PATTERN, item) is None
            or not name.isprintable()
            or not 1 <= len(name) <= MAX_NAME
            or not 0 <= len(addresses) <= MAX_WALLETS
            or any(not re.fullmatch(WALLET_PATTERN, address) for address in addresses)
            or expected_revision < 0
        ):
            raise ValueError("watchlist_invalid")
        encoded = json.dumps(addresses)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT name, wallets, revision FROM saved_watchlist WHERE owner=? AND id=?",
                (owner, item),
            ).fetchone()
            if row is None:
                count = db.execute(
                    "SELECT count(*) FROM saved_watchlist WHERE owner=?", (owner,)
                ).fetchone()[0]
                if expected_revision or count >= MAX_LISTS:
                    raise ValueError("watchlist_creation_conflict")
                db.execute(
                    "INSERT INTO saved_watchlist VALUES (?,?,?,?,1)",
                    (owner, item, name, encoded),
                )
            elif row == (name, encoded, expected_revision + 1):
                return  # The exact previous request already committed.
            elif row[2] == expected_revision:
                db.execute(
                    """UPDATE saved_watchlist SET name=?,wallets=?,revision=revision+1
                    WHERE owner=? AND id=?""",
                    (name, encoded, owner, item),
                )
            else:
                raise ValueError("watchlist_revision_changed")

    def delete(self, owner: str, item: str, expected_revision: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM saved_watchlist WHERE owner=? AND id=?", (owner, item)
            ).fetchone()
            if row is None:
                return
            if row[0] != expected_revision:
                raise ValueError("watchlist_revision_changed")
            db.execute("DELETE FROM saved_watchlist WHERE owner=? AND id=?", (owner, item))
