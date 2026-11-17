"""Narrow read projection for authenticated Console routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from polysia.domain.leaderboard import REFERENCES, Board
from polysia.monitoring.console_contract import (
    BenchmarkSummary,
    BenchmarkWallet,
    LeaderboardActivity,
    LeaderboardBenchmarks,
    LeaderboardComparison,
    LeaderboardPage,
    LeaderboardPoint,
    LeaderboardRow,
    LeaderboardWallet,
    Validity,
)
from polysia.storage.leaderboard import LeaderboardStore, digest, latest_attempt


def page(
    path: Path | None,
    board: Board,
    now: datetime,
    query: str,
    offset: int,
    generation: str | None,
) -> LeaderboardPage:
    if len(query) > 160 or not 0 <= offset <= 1_000_000:
        raise ValueError("invalid_leaderboard_query")
    result = LeaderboardPage(
        state="UNAVAILABLE",
        generation=None,
        fetched_at=None,
        attempted_at=None,
        source_health_at=None,
        outcome=None,
        reason=None,
        next_retry_at=None,
        refresh_in_progress=False,
        critically_stale=False,
        has_more_at_source=None,
        depth=board.depth,
        board_count=0,
        bank_count=0,
        total=0,
        offset=offset,
        items=[],
    )
    if path is None or not path.is_file():
        return result
    with LeaderboardStore(path).read() as db:
        attempt = latest_attempt(db, board)
        snapshot = latest_attempt(db, board, publishable=True)
        if snapshot is None and attempt is not None and attempt["outcome"] != "complete":
            snapshot = db.execute(
                """SELECT * FROM leaderboard_attempts WHERE board=? AND outcome='partial'
                ORDER BY id DESC LIMIT 1""",
                (board.key,),
            ).fetchone()
        bank_count = db.execute("SELECT count(*) FROM leaderboard_bank").fetchone()[0]
        health = db.execute("SELECT source_computed_at FROM leaderboard_health").fetchone()
        running = db.execute(
            "SELECT 1 FROM leaderboard_lease WHERE expires_at>?", (now.isoformat(),)
        ).fetchone()
        term = query.strip().lower()
        bank_version = None
        if term:
            bank_version = db.execute(
                "SELECT max(id) FROM leaderboard_attempts WHERE outcome='complete'"
            ).fetchone()[0]
        current_generation = (
            digest(
                [
                    board.key,
                    term,
                    snapshot["id"] if snapshot is not None else None,
                    bank_version,
                ]
            )
            if snapshot is not None or bank_version is not None
            else None
        )
        if generation is not None and generation != current_generation:
            raise LookupError("cursor_expired")
        patch = {
            "bank_count": bank_count,
            "source_health_at": health[0] if health else None,
            "refresh_in_progress": running is not None,
            "generation": current_generation,
        }
        if attempt is not None:
            interval = (
                timedelta(hours=6) if attempt["outcome"] == "complete" else timedelta(minutes=15)
            )
            patch.update(
                attempted_at=attempt["fetched_at"],
                outcome=attempt["outcome"],
                reason=attempt["reason"],
                next_retry_at=(
                    datetime.fromisoformat(attempt["fetched_at"]) + interval
                ).isoformat(),
            )
        state: Validity = "UNAVAILABLE"
        snapshot_id = -1
        previous_id = -1
        if snapshot is not None:
            snapshot_id = int(snapshot["id"])
            previous = db.execute(
                """SELECT id FROM leaderboard_attempts WHERE board=? AND id<? AND outcome='complete'
                ORDER BY id DESC LIMIT 1""",
                (board.key, snapshot_id),
            ).fetchone()
            if previous is not None:
                previous_id = int(previous["id"])
            age = now - datetime.fromisoformat(snapshot["fetched_at"])
            if snapshot["outcome"] == "partial":
                state = "PARTIAL"
            elif age >= timedelta(hours=12):
                state = "STALE"
            else:
                state = "AVAILABLE" if snapshot["row_count"] else "EMPTY"
            continuation = snapshot["continuation"]
            patch.update(
                fetched_at=snapshot["fetched_at"],
                has_more_at_source=bool(continuation) if continuation is not None else None,
                board_count=snapshot["row_count"],
                critically_stale=age >= timedelta(hours=48),
            )
        # Include retained identities when searching. The current board still owns rank and PnL.
        if term:
            matching = """FROM (
                SELECT wallet, name FROM leaderboard_bank
                UNION ALL
                SELECT r.wallet, r.name FROM leaderboard_rows r WHERE r.attempt_id=?
                AND NOT EXISTS (SELECT 1 FROM leaderboard_bank b WHERE b.wallet=r.wallet)
            ) b LEFT JOIN leaderboard_rows r ON r.wallet=b.wallet AND r.attempt_id=?
            WHERE instr(b.wallet, ?) > 0 OR instr(lower(COALESCE(r.name, b.name, '')), ?) > 0"""
            args = (snapshot_id, snapshot_id, term, term)
            total = db.execute("SELECT count(*) " + matching, args).fetchone()[0]
            rows = db.execute(
                "SELECT b.wallet, COALESCE(r.name, b.name) name, r.rank, r.pnl, r.volume "
                + matching
                + " ORDER BY r.ordinal IS NULL, r.ordinal, b.wallet LIMIT 50 OFFSET ?",
                (*args, offset),
            ).fetchall()
        else:
            total = snapshot["row_count"] if snapshot is not None else 0
            rows = db.execute(
                """SELECT wallet, name, rank, pnl, volume FROM leaderboard_rows
                WHERE attempt_id=? ORDER BY ordinal LIMIT 50 OFFSET ?""",
                (snapshot_id, offset),
            ).fetchall()
        previous_ranks = {}
        if rows and previous_id >= 0 and state != "PARTIAL":
            slots = ",".join("?" for _ in rows)
            previous_ranks = dict(
                db.execute(
                    "SELECT wallet, rank FROM leaderboard_rows WHERE attempt_id=? "
                    f"AND wallet IN ({slots})",
                    (previous_id, *(row["wallet"] for row in rows)),
                ).fetchall()
            )
        items = []
        for row in rows:
            old_rank = previous_ranks.get(row["wallet"])
            items.append(
                LeaderboardRow(
                    **dict(row),
                    rank_change=old_rank - row["rank"]
                    if old_rank is not None and row["rank"] is not None
                    else None,
                )
            )
        patch.update(state=state, total=total, items=items)
        return LeaderboardPage.model_validate({**result.model_dump(), **patch})


def wallet_detail(path: Path | None, board: Board, wallet: str) -> LeaderboardWallet:
    if path is None or not path.is_file():
        raise LookupError("wallet_missing")
    with LeaderboardStore(path).read() as db:
        bank = db.execute(
            "SELECT wallet, name, first_seen, last_seen FROM leaderboard_bank WHERE wallet=?",
            (wallet,),
        ).fetchone()
        if bank is None:
            raise LookupError("wallet_missing")
        history = db.execute(
            """SELECT a.fetched_at observed_at, r.rank, r.pnl, r.volume
            FROM leaderboard_rows r JOIN leaderboard_attempts a ON a.id=r.attempt_id
            WHERE r.wallet=? AND a.board=? AND a.outcome='complete'
            ORDER BY a.id DESC LIMIT 30""",
            (wallet, board.key),
        ).fetchall()
        activity = db.execute(
            "SELECT * FROM leaderboard_activity WHERE wallet=?", (wallet,)
        ).fetchone()
        observed = None
        if activity is not None:
            observed = LeaderboardActivity(
                since=datetime.fromtimestamp(activity["since"], UTC).isoformat(),
                through=datetime.fromtimestamp(activity["through"], UTC).isoformat(),
                latest=datetime.fromtimestamp(activity["latest"], UTC).isoformat()
                if activity["latest"] is not None
                else None,
                trades=activity["trades"],
                markets=activity["markets"],
                complete=bool(activity["complete"]),
            )
        return LeaderboardWallet(
            **dict(bank),
            activity=observed,
            history=[LeaderboardPoint(**dict(row)) for row in history],
        )


def benchmarks(path: Path | None, now: datetime) -> LeaderboardBenchmarks:
    kept = {}
    if path is not None and path.is_file():
        with LeaderboardStore(path).read() as db:
            for source in REFERENCES:
                row = db.execute(
                    """SELECT * FROM leaderboard_references WHERE source=?
                    ORDER BY captured_at DESC, id DESC LIMIT 1""",
                    (source,),
                ).fetchone()
                if row is not None:
                    kept[source] = row
    items = []
    for source in REFERENCES:
        row = kept.get(source)
        captured = cast(str, row["captured_at"]) if row else None
        items.append(
            BenchmarkSummary(
                source=source,
                capture_id=row["id"] if row else None,
                captured_at=captured,
                bank_frozen_at=row["bank_frozen_at"] if row else None,
                bank_count=row["bank_count"] if row else None,
                scope=row["scope"] if row else None,
                method=row["method"] if row else None,
                complete=bool(row["complete"]) if row else None,
                shared=row["overlap"] if row else None,
                denominator=row["denominator"] if row else None,
                older_than_week=captured is not None
                and now - datetime.fromisoformat(captured) >= timedelta(days=7),
            )
        )
    return LeaderboardBenchmarks(items=items)


def comparison(path: Path | None, identifier: int, offset: int) -> LeaderboardComparison:
    if identifier < 1 or not 0 <= offset <= 5000:
        raise ValueError("invalid_comparison_query")
    if path is None or not path.is_file():
        raise LookupError("capture_missing")
    with LeaderboardStore(path).read() as db:
        capture = db.execute(
            "SELECT denominator FROM leaderboard_references WHERE id=?", (identifier,)
        ).fetchone()
        if capture is None:
            raise LookupError("capture_missing")
        rows = db.execute(
            """SELECT wallet, shared FROM leaderboard_comparison WHERE capture_id=?
            ORDER BY shared, wallet LIMIT 50 OFFSET ?""",
            (identifier, offset),
        ).fetchall()
        return LeaderboardComparison(
            capture_id=identifier,
            offset=offset,
            total=capture["denominator"],
            items=[
                BenchmarkWallet(wallet=row["wallet"], shared=bool(row["shared"])) for row in rows
            ],
        )
