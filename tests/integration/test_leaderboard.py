"""Lifecycle proofs from validated observations to protected projections."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
from typer.testing import CliRunner

from polysia.adapters.polymarket.leaderboard import PublicReads
from polysia.cli_commands.leaderboard import app
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


def test_changed_interval_survives_restart_and_agrees_with_console(storage):
    store, now, token = storage
    board = Board("polymarket", "month", "PNL")
    store.publish(observation(now, standing(1, 1)), token)
    store.set_refresh_interval(token, 30)
    reopened = LeaderboardStore(store.path)
    midnight = now + timedelta(minutes=30)
    assert not reopened.should_refresh(board, midnight - timedelta(seconds=1))
    assert reopened.should_refresh(board, midnight)
    actual = page(store.path, board, now, "", 0, None)
    assert actual.next_retry_at == midnight.isoformat()
    assert actual.items[0].wallet == standing(1, 1).wallet


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
    later = now + timedelta(days=1)
    store.publish(observation(later, original, other), token)
    old = benchmarks(store.path, now).items[1]
    assert (old.shared, old.denominator, old.bank_count) == (1, 2, 1)
    assert [row.shared for row in comparison(store.path, identifier, 0).items] == [False, True]
    assert store.import_reference(imported, now=later) == (identifier, False)
    assert benchmarks(store.path, later).items[1].shared == 1
    assert store.import_reference(replace(imported, captured_at=later), now=later)[1]
    assert benchmarks(store.path, later).items[1].shared == 2
    empty = replace(imported, source="PolyIntel", captured_at=now - timedelta(seconds=1))
    store.import_reference(empty, now=later)
    assert benchmarks(store.path, later).items[2].bank_count == 0


def test_provider_and_board_retry_deadlines_survive_restart_and_force(storage):
    store, now, token = storage
    board = Board("polymarket", "month", "PNL")
    other = Board("polymarket", "week", "PNL")
    until = now + timedelta(hours=2)
    store.publish(observation(now - timedelta(days=1), standing(1, 1)), token)
    store.publish(
        replace(
            observation(now), outcome="failed", reason="http_503", has_more=None, retry_at=until
        ),
        token,
    )
    reopened = LeaderboardStore(store.path)
    assert not reopened.should_refresh(board, now + timedelta(hours=1), force=True)
    custom_depth = replace(board, discovery_only=True, discovery_depth=2000)
    assert not reopened.should_refresh(custom_depth, now + timedelta(hours=1), force=True)
    assert reopened.should_refresh(other, now)
    store.defer_provider(token, until + timedelta(hours=1))
    store.defer_provider(token, until)
    store.release(token)
    for scope in (board, other):
        assert not reopened.should_refresh(scope, until, force=True)
        assert reopened.should_refresh(scope, until + timedelta(hours=1))
    retained = page(store.path, board, now, "", 0, None)
    assert retained.next_retry_at == (until + timedelta(hours=1)).isoformat()
    assert retained.items[0].wallet == standing(1, 1).wallet


def test_discovery_depth_keeps_visible_board_and_increases_searchable_bank(storage):
    store, now, token = storage
    board = Board("polymarket", "month", "PNL")
    deeper = replace(board, discovery_only=True)
    store.publish(observation(now, standing(1, 1)), token)
    original = page(store.path, board, now, "", 0, None)
    store.publish(observation(now, standing(1, 1), standing(2, 1002), board=deeper), token)
    kept = page(store.path, board, now, "", 0, original.generation)
    assert (board.depth, deeper.depth, kept.board_count, kept.bank_count) == (1000, 3000, 1, 2)
    assert page(store.path, board, now, "Trader 2", 0, None).items[0].rank is None
    assert store.should_refresh(board, now + timedelta(hours=6))
    assert not store.should_refresh(deeper, now + timedelta(hours=6))
    assert store.should_refresh(deeper, now + timedelta(days=1))


def test_custom_discovery_depth_keeps_history_and_counts_unique_new_wallets(tmp_path, monkeypatch):
    path = tmp_path / "bank.sqlite3"
    store = LeaderboardStore(path)
    store.initialize()
    now = datetime.now(UTC)
    token = store.acquire(now)
    visible = Board("polymarket", "month", "PNL")
    original = replace(visible, discovery_only=True)
    assert token
    store.publish(observation(now, standing(1, 1)), token)
    store.publish(observation(now - timedelta(days=2), standing(2, 1), board=original), token)
    store.release(token)
    earlier = page(path, visible, now, "", 0, None)
    requests = []

    def transport(**options):
        reads = PublicReads(**options)

        def open_page(request, **kwargs):
            query = parse_qs(urlsplit(request.full_url).query)
            offset = int(query.get("cursor", ["0"])[0])
            limit = int(query["limit"][0])
            requests.append(query["time_period"][0])
            rows = [
                {"user_id": f"0x{i:040x}", "rank": i, "pnl": "1.23", "volume": "100"}
                for i in range(offset + 1, offset + limit + 1)
            ]
            return BytesIO(
                json.dumps(
                    {
                        "data": rows,
                        "pagination": {"has_more": True, "next_cursor": str(offset + limit)},
                    }
                ).encode()
            )

        monkeypatch.setattr(reads, "_open", open_page)
        return reads

    monkeypatch.setattr("polysia.cli_commands.leaderboard.PublicReads", transport)
    args = ["refresh", "--database", str(path), "--discovery-only", "--max-requests", "26"]
    runner = CliRunner()
    result = runner.invoke(app, [*args, "--discovery-depth", "1250"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert (summary["requests"], summary["max_requests"], summary["wallets_added"]) == (
        26,
        26,
        1248,
    )
    assert requests == ["month"] * 13 + ["all"] * 13
    assert all(key.endswith(":1250") for key in summary["boards"])
    kept = page(path, visible, now, "", 0, earlier.generation)
    assert kept.items == earlier.items and kept.bank_count == 1250
    with store.read() as db:
        assert (
            db.execute(
                "SELECT row_count FROM leaderboard_attempts WHERE board=?", (original.key,)
            ).fetchone()[0]
            == 1
        )
    # A new depth shares the discovery cadence, including the minimum manual interval.
    repeat = runner.invoke(app, [*args, "--discovery-depth", "1200", "--force"])
    assert repeat.exit_code == 0
    assert json.loads(repeat.stdout)["requests"] == json.loads(repeat.stdout)["wallets_added"] == 0


@pytest.mark.parametrize(
    "options",
    [
        ["--discovery-depth", "2000"],
        ["--discovery-only", "--discovery-depth", "1000"],
        ["--discovery-only", "--discovery-depth", "5001"],
        ["--discovery-only", "--discovery-depth", "1250", "--max-requests", "25"],
        ["--max-requests", "31"],
        ["--max-requests", "101"],
    ],
)
def test_invalid_collection_policy_precedes_database_or_network_use(tmp_path, options):
    path = tmp_path / "unopened.sqlite3"
    result = CliRunner().invoke(app, ["refresh", "--database", str(path), *options])
    assert result.exit_code == 2
    assert not path.exists()


def test_refresh_cli_shares_provider_cooldown_across_discovery_and_visible_boards(
    tmp_path, monkeypatch
):
    def limited(request, **_):
        headers = Message()
        headers["Retry-After"] = "3600"
        raise HTTPError(request.full_url, 429, "limited", headers, BytesIO())

    def transport(**options):
        reads = PublicReads(**options)
        monkeypatch.setattr(reads, "_open", limited)
        return reads

    monkeypatch.setattr("polysia.cli_commands.leaderboard.PublicReads", transport)
    runner = CliRunner()
    args = ["refresh", "--database", str(tmp_path / "bank.sqlite3")]
    first = runner.invoke(app, [*args, "--discovery-only"])
    assert first.exit_code == 1
    assert json.loads(first.stdout)["requests"] == 1
    retry_at = json.loads(first.stdout)["provider_retry_at"]
    second = runner.invoke(app, [*args, "--force"])
    assert second.exit_code == 0
    assert json.loads(second.stdout) == {"status": "provider_deferred", "retry_at": retry_at}


def test_legacy_database_is_readable_before_and_after_upgrade(storage):
    store, now, token = storage
    wallet = standing(1, 1)
    store.publish(observation(now, wallet), token)
    board = Board("polymarket", "month", "PNL")
    capture = ReferenceCapture("Rivo", now, "Visible", "Public table", (wallet.wallet,), True)
    identifier, _ = store.import_reference(capture, now=now)
    with store._write() as db:
        db.execute("DROP TABLE leaderboard_retry")
        db.execute("ALTER TABLE leaderboard_references DROP COLUMN compared_at")
        db.execute(
            "UPDATE leaderboard_references SET digest='legacy-digest' WHERE id=?", (identifier,)
        )
    before = page(store.path, board, now, "", 0, None)
    assert before.board_count == 1 and benchmarks(store.path, now).items[1].shared == 1
    store.initialize()
    store.initialize()
    assert page(store.path, board, now, "", 0, None) == before
    assert store.import_reference(capture, now=now)[1]
    with store.read() as db:
        assert [
            tuple(r)
            for r in db.execute(
                "SELECT digest,compared_at FROM leaderboard_references WHERE id=?", (identifier,)
            )
        ] == [("legacy-digest", None)]


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
