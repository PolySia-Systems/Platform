"""SQLite storage for public observations, isolated from trading admission."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from polysia.domain.leaderboard import Activity, Board, Observation, ReferenceCapture

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leaderboard_lease (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leaderboard_attempts (
    id INTEGER PRIMARY KEY,
    board TEXT NOT NULL,
    started_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('complete', 'partial', 'failed')),
    reason TEXT,
    continuation INTEGER,
    row_count INTEGER NOT NULL,
    requests INTEGER NOT NULL,
    received_bytes INTEGER NOT NULL,
    digest TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS leaderboard_attempts_board
    ON leaderboard_attempts(board, id DESC);
CREATE TABLE IF NOT EXISTS leaderboard_rows (
    attempt_id INTEGER NOT NULL REFERENCES leaderboard_attempts(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    wallet TEXT NOT NULL,
    name TEXT,
    rank INTEGER NOT NULL,
    pnl TEXT NOT NULL,
    volume TEXT NOT NULL,
    PRIMARY KEY(attempt_id, ordinal),
    UNIQUE(attempt_id, wallet)
);
CREATE INDEX IF NOT EXISTS leaderboard_rows_wallet ON leaderboard_rows(wallet, attempt_id DESC);
CREATE TABLE IF NOT EXISTS leaderboard_bank (
    wallet TEXT PRIMARY KEY,
    name TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    first_board TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leaderboard_health (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    observed_at TEXT NOT NULL,
    source_computed_at TEXT
);
CREATE TABLE IF NOT EXISTS leaderboard_activity (
    wallet TEXT PRIMARY KEY REFERENCES leaderboard_bank(wallet),
    since INTEGER NOT NULL,
    through INTEGER NOT NULL,
    latest INTEGER,
    trades INTEGER NOT NULL,
    markets INTEGER NOT NULL,
    complete INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS leaderboard_references (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    scope TEXT NOT NULL,
    method TEXT NOT NULL,
    complete INTEGER NOT NULL,
    bank_frozen_at TEXT NOT NULL,
    bank_count INTEGER NOT NULL,
    bank_digest TEXT NOT NULL,
    overlap INTEGER NOT NULL,
    denominator INTEGER NOT NULL,
    digest TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS leaderboard_references_source
    ON leaderboard_references(source, captured_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS leaderboard_comparison (
    capture_id INTEGER NOT NULL REFERENCES leaderboard_references(id) ON DELETE CASCADE,
    wallet TEXT NOT NULL,
    shared INTEGER NOT NULL,
    PRIMARY KEY(capture_id, wallet)
);
"""


def digest(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


class LeaderboardStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            yield db

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE")
            yield db

    def initialize(self) -> None:
        with self._write() as db:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            if any(not row["name"].startswith("leaderboard_") for row in tables):
                raise ValueError("separate_leaderboard_database_required")
            # Keep creation atomic. executescript implicitly commits pending transactions.
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)

    def acquire(self, now: datetime) -> str | None:
        token = uuid4().hex
        with self._write() as db:
            result = db.execute(
                """INSERT INTO leaderboard_lease VALUES (1, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET token=excluded.token,
                expires_at=excluded.expires_at WHERE leaderboard_lease.expires_at <= ?""",
                (token, (now + timedelta(minutes=12)).isoformat(), now.isoformat()),
            )
            return token if result.rowcount else None

    @staticmethod
    def _require_lease(db: sqlite3.Connection, token: str) -> None:
        if not db.execute(
            "SELECT 1 FROM leaderboard_lease WHERE token=? AND expires_at>?",
            (token, datetime.now(UTC).isoformat()),
        ).fetchone():
            raise ValueError("refresh_lease_lost")

    def release(self, token: str) -> None:
        with self._write() as db:
            db.execute("DELETE FROM leaderboard_lease WHERE token=?", (token,))

    def should_refresh(self, board: Board, now: datetime, *, force: bool = False) -> bool:
        with self.read() as db:
            last = latest_attempt(db, board)
        if last is None:
            return True
        interval = timedelta(minutes=15)
        if last["outcome"] == "complete" and not force:
            interval = timedelta(hours=6)
        return now - datetime.fromisoformat(last["fetched_at"]) >= interval

    def publish(self, item: Observation, token: str) -> None:
        if item.outcome == "complete" and (
            item.has_more is None or item.has_more and len(item.rows) != item.board.depth
        ):
            raise ValueError("invalid_complete_observation")
        if len(item.rows) > item.board.depth or item.outcome == "failed" and item.rows:
            raise ValueError("invalid_observation_size")
        source = item.board.key
        fetched = item.fetched_at.isoformat()
        mapped = [(r.wallet, r.name, r.rank, str(r.pnl), str(r.volume)) for r in item.rows]
        with self._write() as db:
            self._require_lease(db, token)
            record_id = db.execute(
                """INSERT INTO leaderboard_attempts
                (board, started_at, fetched_at, outcome, reason, continuation, row_count,
                 requests, received_bytes, digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source,
                    item.started_at.isoformat(),
                    fetched,
                    item.outcome,
                    item.reason,
                    item.has_more,
                    len(mapped),
                    item.request_count,
                    item.byte_count,
                    digest([source, item.outcome, item.has_more, mapped]),
                ),
            ).lastrowid
            db.executemany(
                "INSERT INTO leaderboard_rows VALUES (?, ?, ?, ?, ?, ?, ?)",
                ((record_id, index, *row) for index, row in enumerate(mapped, 1)),
            )
            if item.outcome == "complete":
                db.executemany(
                    """INSERT INTO leaderboard_bank VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(wallet) DO UPDATE SET
                    name=COALESCE(excluded.name, leaderboard_bank.name),
                    last_seen=excluded.last_seen
                    WHERE excluded.last_seen >= leaderboard_bank.last_seen""",
                    ((wallet, name, fetched, fetched, source) for wallet, name, *_ in mapped),
                )

    def health(self, observed: datetime, computed: datetime | None, token: str) -> None:
        with self._write() as db:
            self._require_lease(db, token)
            db.execute(
                "INSERT OR REPLACE INTO leaderboard_health VALUES (1, ?, ?)",
                (observed.isoformat(), computed.isoformat() if computed else None),
            )

    def activities(self, items: Sequence[Activity], token: str) -> None:
        with self._write() as db:
            self._require_lease(db, token)
            db.executemany(
                """INSERT INTO leaderboard_activity VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet) DO UPDATE SET since=excluded.since, through=excluded.through,
                    latest=excluded.latest, trades=excluded.trades, markets=excluded.markets,
                    complete=excluded.complete
                WHERE excluded.through >= leaderboard_activity.through
                AND (excluded.complete OR NOT leaderboard_activity.complete)""",
                (
                    (
                        r.wallet,
                        r.since,
                        r.through,
                        r.latest,
                        r.trade_count,
                        r.market_count,
                        r.complete,
                    )
                    for r in items
                ),
            )

    def import_reference(self, capture: ReferenceCapture, *, now: datetime) -> tuple[int, bool]:
        # Lock the bank generation only for this short, local comparison.
        with self._write() as db:
            bank = {str(row[0]) for row in db.execute("SELECT wallet FROM leaderboard_bank")}
            reference = sorted(set(capture.wallets))
            bank_hash = digest(sorted(bank))
            capture_hash = digest(
                [
                    capture.source,
                    capture.captured_at.isoformat(),
                    capture.scope,
                    capture.method,
                    capture.complete,
                    reference,
                    bank_hash,
                ]
            )
            result = db.execute(
                """INSERT INTO leaderboard_references
                (source, captured_at, scope, method, complete, bank_frozen_at, bank_count,
                 bank_digest, overlap, denominator, digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(digest) DO NOTHING""",
                (
                    capture.source,
                    capture.captured_at.isoformat(),
                    capture.scope,
                    capture.method,
                    capture.complete,
                    now.isoformat(),
                    len(bank),
                    bank_hash,
                    len(bank.intersection(reference)),
                    len(reference),
                    capture_hash,
                ),
            )
            if result.rowcount:
                assert result.lastrowid is not None
                identifier = result.lastrowid
                db.executemany(
                    "INSERT INTO leaderboard_comparison VALUES (?, ?, ?)",
                    ((identifier, wallet, wallet in bank) for wallet in reference),
                )
                return identifier, True
            existing = db.execute(
                "SELECT id FROM leaderboard_references WHERE digest=?", (capture_hash,)
            ).fetchone()
            assert existing is not None
            return int(existing["id"]), False

    def prune(self, now: datetime, token: str) -> int:
        """Keep current evidence and one complete snapshot per board/day for a year."""
        with self._write() as db:
            self._require_lease(db, token)
            return db.execute(
                """DELETE FROM leaderboard_attempts WHERE id NOT IN (
                    SELECT max(id) FROM leaderboard_attempts GROUP BY board, outcome
                ) AND (
                    fetched_at < ? OR (fetched_at < ? AND (
                        outcome != 'complete' OR id NOT IN (
                            SELECT max(id) FROM leaderboard_attempts WHERE outcome='complete'
                            GROUP BY board, substr(fetched_at,1,10)
                        )
                    ))
                )""",
                ((now - timedelta(days=365)).isoformat(), (now - timedelta(days=30)).isoformat()),
            ).rowcount


def latest_attempt(
    db: sqlite3.Connection, board: Board, *, publishable: bool = False
) -> sqlite3.Row | None:
    condition = "AND outcome='complete'" if publishable else ""
    return db.execute(
        f"SELECT * FROM leaderboard_attempts WHERE board=? {condition} ORDER BY id DESC LIMIT 1",
        (board.key,),
    ).fetchone()
