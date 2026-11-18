from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from polysia.application.ports.copytrading import LeaderTradeReadPage
from polysia.application.services.watchlist_shadow import tick
from polysia.storage.watchlist_runs import WatchlistRuns
from polysia.storage.watchlists import WatchlistStore


@pytest.mark.parametrize("duration", [7_200, 259_200, 345_600])
def test_expiry_is_durable_and_the_cohort_does_not_follow_list_edits(tmp_path, duration):
    database = tmp_path / "watchlists.sqlite3"
    lists = WatchlistStore(database)
    item, run_id = "1" * 32, "2" * 32
    first, second = "0x" + "a" * 40, "0x" + "b" * 40
    lists.save("owner", item, "Cohort", [first], 0)
    start = datetime(2026, 11, 18, tzinfo=UTC)
    WatchlistRuns(database).start("owner", run_id, item, 1, duration, start)
    lists.save("owner", item, "Changed", [second], 1)
    runs = WatchlistRuns(database)
    runs.start("owner", run_id, item, 1, duration, start)
    assert runs.for_owner("reader") == []
    captured = []

    class PublicSource:
        async def read_page(self, alias, *, start_at, end_at):
            captured.append((alias, start_at, end_at))
            return LeaderTradeReadPage((), None, 0, 0, 0, 0)

    def source_factory(aliases):
        assert aliases == {"watchlist-0": first}
        return PublicSource()

    step = start + timedelta(minutes=5)
    assert asyncio.run(
        tick(runs, source_factory, SimpleNamespace(), clock=lambda: step)
    ) == "OBSERVED"
    assert captured == [("watchlist-0", start, step)]
    end = start + timedelta(seconds=duration + 20)
    assert asyncio.run(
        tick(WatchlistRuns(database), source_factory, SimpleNamespace(), clock=lambda: end)
    ) == "FINISHED"
    assert len(captured) == 1
    [(status, data)] = runs.for_owner("owner")
    assert status == "FINISHED"
    assert data["name"] == "Cohort"
    assert data["wallets"][first]["through"] == step.isoformat()
    assert not data["wallets"][first]["events"]


def test_cancellation_wins_over_a_stale_background_checkpoint(tmp_path):
    path = tmp_path / "watchlists.sqlite3"
    item, run_id = "1" * 32, "2" * 32
    WatchlistStore(path).save("owner", item, "Cohort", ["0x" + "a" * 40], 0)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    runs = WatchlistRuns(path)
    runs.start("owner", run_id, item, 1, 7200, now)
    active = runs.active()
    assert active is not None
    actor, key, revision, snapshot = active
    runs.cancel("owner", run_id, now + timedelta(seconds=1))
    assert not runs.apply(actor, key, revision, "RUNNING", snapshot)
    assert runs.active() is None
    assert runs.for_owner("owner")[0][0] == "CANCELLED"
