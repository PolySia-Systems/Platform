"""Lifecycle proofs from validated observations to protected projections."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.domain.leaderboard import Board, Observation, ReferenceCapture, Standing
from polysia.monitoring.console import ConsoleApplication
from polysia.monitoring.leaderboard import benchmarks, comparison, page, wallet_detail
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.leaderboard import LeaderboardStore


def standing(index, rank):
    return Standing(f"0x{index:040x}", f"Trader {index}", rank, Decimal("1.000056"), Decimal(20))


def observation(when, *rows, board=None):
    return Observation(
        board or Board("polymarket", "month", "PNL"),
        rows,
        when,
        when,
        "complete",
        None,
        False,
        1,
        123,
    )


@pytest.fixture
def storage(tmp_path):
    store = LeaderboardStore(tmp_path / "leaderboard.sqlite3")
    store.initialize()
    now = datetime.now(UTC)
    token = store.acquire(now)
    assert token
    return store, now, token


def test_partial_restart_and_window_isolation(storage):
    store, now, token = storage
    board = Board("polymarket", "month", "PNL")
    accepted = observation(now - timedelta(hours=18), standing(1, 1))
    store.publish(accepted, token)
    first = page(store.path, board, now, "", 0, None)
    assert first.state == "STALE"
    partial = replace(
        observation(now, standing(2, 1)), outcome="partial", reason="http_500", has_more=None
    )
    store.publish(partial, token)
    reopened = LeaderboardStore(store.path)
    assert reopened.acquire(now) is None
    actual = page(reopened.path, board, now, "", 0, first.generation)
    assert actual.items == first.items
    assert actual.fetched_at == first.fetched_at
    assert actual.outcome == "partial" and actual.next_retry_at
    week = Board("polymarket", "week", "PNL")
    assert page(store.path, week, now, "", 0, None).state == "UNAVAILABLE"
    store.publish(replace(partial, board=week), token)
    cold = page(store.path, week, now, "", 0, None)
    assert cold.state == "PARTIAL" and cold.items[0].wallet == standing(2, 1).wallet
    assert cold.bank_count == 1
    assert not reopened.should_refresh(board, now + timedelta(minutes=14), force=True)
    assert reopened.should_refresh(board, now + timedelta(minutes=15))
    with pytest.raises(LookupError, match="cursor_expired"):
        page(store.path, week, now, "", 50, first.generation)


def test_failed_write_rolls_back_generation_and_discovery(storage):
    store, now, token = storage
    good = observation(now, standing(1, 1))
    store.publish(good, token)
    with store._write() as db:
        db.execute("""CREATE TRIGGER fail_board BEFORE INSERT ON leaderboard_rows
                      BEGIN SELECT raise(ABORT, 'simulated disk failure'); END""")
    with pytest.raises(sqlite3.DatabaseError, match="simulated disk failure"):
        store.publish(observation(now, standing(2, 1)), token)
    kept = page(store.path, good.board, now, "", 0, None)
    assert kept.bank_count == 1
    assert len(kept.items) == 1 and kept.items[0].wallet == good.rows[0].wallet
    with store.read() as db:
        assert db.execute("SELECT count(*) FROM leaderboard_attempts").fetchone()[0] == 1


def test_benchmark_is_frozen_and_does_not_write_bank(storage):
    store, now, token = storage
    original, other = standing(1, 1), standing(2, 1)
    store.publish(observation(now, original), token)
    imported = ReferenceCapture(
        "Rivo", now, "Visible 2", "Observed page", (original.wallet, other.wallet), True
    )
    identifier, created = store.import_reference(imported, now=now)
    assert created
    assert store.import_reference(imported, now=now) == (identifier, False)
    assert page(store.path, Board("polymarket", "month", "PNL"), now, "", 0, None).bank_count == 1
    store.publish(observation(now, original, other), token)
    old = benchmarks(store.path, now).items[1]
    assert (old.shared, old.denominator, old.bank_count) == (1, 2, 1)
    assert [row.shared for row in comparison(store.path, identifier, 0).items] == [False, True]
    assert store.import_reference(imported, now=now)[1]
    assert benchmarks(store.path, now).items[1].shared == 2


def test_bank_search_pagination_is_bound_to_the_independent_generation(storage):
    store, now, token = storage
    board = Board("polymarket", "month", "PNL")
    store.publish(observation(now, standing(1, 1)), token)
    current = page(store.path, board, now, "trader", 0, None)
    assert current.generation and current.total == 1
    other = Board("polymarket", "day", "PNL")
    store.publish(observation(now, standing(2, 1), board=other), token)
    with pytest.raises(LookupError, match="cursor_expired"):
        page(store.path, board, now, "trader", 50, current.generation)
    assert page(store.path, board, now, "trader", 0, None).total == 2


def test_history_valid_empty_and_retention(storage):
    store, now, token = storage
    old, recent = standing(1, 5), standing(1, 2)
    prior_date = now - timedelta(days=60)
    store.publish(observation(prior_date - timedelta(minutes=1), old), token)
    store.publish(observation(prior_date, old), token)
    store.publish(observation(now, recent), token)
    board = Board("polymarket", "month", "PNL")
    assert page(store.path, board, now, "", 0, None).items[0].rank_change == 3
    assert store.prune(now, token) == 1
    store.publish(observation(now), token)
    current = page(store.path, board, now, "", 0, None)
    assert current.state == "EMPTY" and current.generation is not None
    search = page(store.path, board, now, "Trader 1", 0, None)
    assert len(search.items) == 1 and search.items[0].pnl is None
    detail = wallet_detail(store.path, board, old.wallet)
    assert [item.rank for item in detail.history] == [2, 5]
    assert detail.activity is None


def test_expired_lease_cannot_publish_after_takeover(storage):
    store, now, token = storage
    replacement = store.acquire(now + timedelta(minutes=13))
    assert replacement and replacement != token
    store.release(token)
    with pytest.raises(ValueError, match="refresh_lease_lost"):
        store.publish(observation(now, standing(1, 1)), token)
    store.publish(observation(now, standing(2, 1)), replacement)


def test_console_routes_protect_identity_and_isolate_example(storage, tmp_path):
    store, now, token = storage
    row = standing(123, 1)
    store.publish(observation(now, row), token)

    def verify(value):
        if value != "fixture-reader":
            raise ValueError("unauthenticated")
        return "fixture-reader", "reader"

    app = ConsoleApplication(
        tmp_path / "publication.json",
        origin="https://fixture.invalid",
        verify=verify,
        commands=ConsoleCommandStore(tmp_path / "commands.sqlite3"),
        csrf_secret=b"fixture-key-for-leaderboard-test" * 2,
        leaderboard_database=store.path,
    )

    def request(identity, query=""):
        status = []
        body = b"".join(
            app(
                {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": "/api/console/v1/leaderboard",
                    "HTTP_HOST": "fixture.invalid",
                    "HTTP_CF_ACCESS_JWT_ASSERTION": identity,
                    "QUERY_STRING": query,
                },
                lambda line, headers: status.append(int(line.split()[0])),
            )
        )
        return status[0], json.loads(body)

    assert request("unknown")[0] == 403
    status, data = request("fixture-reader")
    assert status == 200 and data["items"][0]["wallet"] == row.wallet
    assert request("fixture-reader", "example=1")[1]["items"] == []


def test_collector_rejects_existing_non_leaderboard_database(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE legacy_identity (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO legacy_identity VALUES (42)")
    with pytest.raises(ValueError, match="separate_leaderboard_database_required"):
        LeaderboardStore(path).initialize()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id FROM legacy_identity").fetchall() == [(42,)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("legacy_identity",)
        ]
