"""Operator-side public collection and bounded reference intake."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from polysia.adapters.polymarket.leaderboard import (
    WALLET,
    PublicReads,
    board_observation,
    source_health,
    wallet_activity,
)
from polysia.domain.leaderboard import CATEGORIES, RANKINGS, REFERENCES, Board, ReferenceCapture
from polysia.storage.leaderboard import LeaderboardStore

app = typer.Typer(help="Collect public ranking evidence independently of trading.")
Database = Annotated[Path, typer.Option("--database", dir_okay=False)]


@app.command("refresh")
def refresh(database: Database, force: bool = False) -> None:
    """Refresh due public boards and bounded wallet details."""
    store = LeaderboardStore(database)
    now = datetime.now(UTC)
    token = None
    results: dict[str, str] = {}
    reads = PublicReads()
    enriched = 0
    try:
        store.initialize()
        token = store.acquire(now)
        if token is None:
            typer.echo('{"status":"refresh_in_progress"}')
            return
        boards = [
            Board("polymarket", period, ranking)
            for period in ("month", "all", "week", "day")
            for ranking in RANKINGS
        ]
        boards.extend(
            Board("polymarket", "month", ranking, category)
            for category in CATEGORIES[1:]
            for ranking in RANKINGS
        )
        shortlist: set[str] = set()
        for board in boards:
            if not store.should_refresh(board, now, force=force):
                continue
            item = board_observation(board, reads)
            store.publish(item, token)
            results[board.key] = item.outcome if item.reason is None else item.reason
            if item.outcome == "complete" and board == Board("polymarket", "month", "PNL"):
                shortlist.update(row.wallet for row in item.rows[:12])
        if results:
            computed = source_health(reads)
            store.health(datetime.now(UTC), computed, token)
        through = int(now.timestamp())
        since = int((now - timedelta(days=7)).timestamp())
        for wallet in sorted(shortlist):
            activity = wallet_activity(wallet, reads, since, through)
            if activity.complete or activity.trade_count:
                store.activities((activity,), token)
                enriched += 1
        if results:
            store.prune(datetime.now(UTC), token)
    except OSError, ValueError, sqlite3.DatabaseError:
        typer.echo('{"status":"leaderboard_store_or_lease_unavailable"}', err=True)
        raise typer.Exit(1) from None
    finally:
        if token is not None:
            try:
                store.release(token)
            except sqlite3.DatabaseError:
                # A crashed/locked database cannot have its lease stolen before expiry.
                typer.echo('{"status":"lease_release_failed"}', err=True)
    typer.echo(
        json.dumps(
            {
                "boards": results,
                "requests": reads.requests,
                "received_bytes": reads.bytes,
                "enriched_wallets": enriched,
            }
        )
    )
    if results and not all(result == "complete" for result in results.values()):
        raise typer.Exit(1)


@app.command("import-reference")
def import_reference(
    database: Database,
    capture_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Compare a dated reference capture with the existing independent bank."""
    store = LeaderboardStore(database)
    try:
        with capture_file.open("rb") as source:
            raw = source.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("capture_too_large")
        capture = parse_reference(json.loads(raw), now=datetime.now(UTC))
        store.initialize()
        identifier, inserted = store.import_reference(capture, now=datetime.now(UTC))
    except OSError, ValueError, sqlite3.DatabaseError, TypeError:
        typer.echo('{"status":"reference_import_failed"}', err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps({"comparison": identifier, "created": inserted}))


def parse_reference(payload: object, *, now: datetime) -> ReferenceCapture:
    fields = {"source", "captured_at", "scope", "method", "wallets", "complete"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("invalid_reference_shape")
    source, captured, scope, method, wallets, complete = (
        payload[k] for k in ("source", "captured_at", "scope", "method", "wallets", "complete")
    )
    if (
        source not in REFERENCES
        or not isinstance(captured, str)
        or not isinstance(scope, str)
        or not 0 < len(scope.strip()) <= 300
        or len(scope) > 300
        or not isinstance(method, str)
        or not 0 < len(method.strip()) <= 100
        or len(method) > 100
        or type(complete) is not bool
        or not isinstance(wallets, list)
        or len(wallets) > 5000
        or any(not isinstance(wallet, str) or not WALLET.fullmatch(wallet) for wallet in wallets)
    ):
        raise ValueError("invalid_reference_fields")
    timestamp = datetime.fromisoformat(captured)
    if timestamp.tzinfo is None or timestamp > now:
        raise ValueError("invalid_capture_time")
    normalized = tuple(wallet.lower() for wallet in wallets)
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate_reference_wallets")
    return ReferenceCapture(source, timestamp.astimezone(UTC), scope, method, normalized, complete)
