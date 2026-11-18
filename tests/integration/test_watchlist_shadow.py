from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from polysia.application.ports.copytrading import LeaderTradeReadPage
from polysia.application.services.watchlist_shadow import tick
from polysia.domain.copytrading.models import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
)
from polysia.domain.market.models import MarketOrderBookSnapshot, OrderBookLevel
from polysia.monitoring.watchlist_report import detail, summary
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
    assert captured[-1] == ("watchlist-0", step, start + timedelta(seconds=duration))
    assert len(captured) == 2
    [(status, data)] = runs.for_owner("owner")
    assert status == "FINISHED"
    assert data["name"] == "Cohort"
    assert data["wallets"][first]["through"] == data["ends_at"]
    assert data["cutoff_at"] == data["ends_at"]
    assert data["end_reason"] == "time"
    assert summary(status, data).coverage == "covered"
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


def test_subset_history_and_direct_start(tmp_path):
    path = tmp_path / "watchlists.sqlite3"
    lists = WatchlistStore(path)
    item = "1" * 32
    wallets = [f"0x{i:040x}" for i in range(10)]
    lists.save("owner", item, "Ten wallets", wallets, 0)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    runs = WatchlistRuns(path)
    for index in range(21):
        key = f"{index:032x}"
        runs.start("owner", key, item, 1, 900, now, selection=wallets[:6])
        runs.start("owner", key, item, 1, 900, now, selection=wallets[:6][::-1])
        with pytest.raises(ValueError, match="shadow_request_id_conflict"):
            runs.start("owner", key, item, 1, 900, now, selection=wallets[1:7])
        runs.cancel("owner", key, now + timedelta(seconds=5))
    [(_, oldest)] = runs.for_owner("owner", offset=20)
    assert list(oldest["wallets"]) == wallets[:6]
    assert lists.lists("owner")[0]["wallets"] == wallets
    assert runs.for_owner("another owner", run_id=key) == []
    fresh = WatchlistRuns(tmp_path / "fresh.sqlite3")
    fresh.start("owner", key, None, None, 900, now, selection=wallets[:1])
    assert fresh.busy()
    assert summary(*fresh.for_owner("owner")[0]).equity is None


def test_marks_reconcile_without_post_cutoff_fills(tmp_path):
    runs = WatchlistRuns(tmp_path / "watchlists.sqlite3")
    now = datetime(2026, 11, 18, tzinfo=UTC)
    key = "1" * 32
    wallet = "0x" + "a" * 40
    runs.start("owner", key, None, None, 900, now, selection=[wallet])
    expiry = now + timedelta(seconds=900)
    step = expiry - timedelta(seconds=25)

    class Source:
        async def read_page(self, alias, *, start_at, end_at):
            token = "late" if end_at == expiry else "priced"
            event = LeaderTradeEvent(
                token, "test", alias, "market", token, LeaderTradeAction.BUY,
                LeaderPositionEffect.OPEN, Decimal("0.5"), Decimal("8"), end_at, end_at, None,
            )
            return LeaderTradeReadPage((event,), None, 1, 1, 0, 0)

    class Books:
        async def get_order_book(self, token):
            assert token == "priced"
            return MarketOrderBookSnapshot(
                token_id=token, timestamp=step, minimum_order_size=Decimal("1"),
                tick_size=Decimal("0.01"),
                asks=(OrderBookLevel(price=Decimal("0.5"), size=Decimal("8")),),
                bids=(OrderBookLevel(price=Decimal("0.6"), size=Decimal("8")),),
            )

    assert asyncio.run(tick(runs, lambda _: Source(), Books(), clock=lambda: step)) == "OBSERVED"
    assert asyncio.run(tick(
        runs, lambda _: Source(), Books(), clock=lambda: expiry + timedelta(seconds=1),
    )) == "FINISHED"
    status, data = runs.for_owner("owner")[0]
    report = summary(status, data)
    assert Decimal(report.equity or "0") == Decimal("100.624")
    assert Decimal(report.net_pnl or "0") == Decimal("0.624")
    assert report.realized == "0"
    assert report.wallets[0].open_positions == report.wallets[0].valued_positions == 1
    evidence = detail(status, data, wallet, 0)
    assert {event.reason for event in evidence.events} == {
        "current_book_shadow_fill", "observed_after_cutoff",
    }
    assert tuple(p.outcome for p in evidence.positions) == ("priced",)


def test_busy_cohort_bounds_lookups_and_keeps_independent_marks(tmp_path):
    runs = WatchlistRuns(tmp_path / "watchlists.sqlite3")
    start = datetime(2026, 11, 18, tzinfo=UTC)
    step = start + timedelta(seconds=60)
    wallets = [f"0x{i:040x}" for i in range(6)]
    key = "1" * 32
    runs.start("owner", key, None, None, 900, start, selection=wallets)
    lookups = []

    class Source:
        async def read_page(self, alias, *, start_at, end_at):
            events = tuple(
                LeaderTradeEvent(
                    f"{alias}-{i:03}", "test", alias, "market", "token",
                    LeaderTradeAction.BUY, LeaderPositionEffect.OPEN,
                    Decimal("0.5"), Decimal("1"), step, step, None,
                )
                for i in range(15)
            )
            return LeaderTradeReadPage(events, None, 15, 15, 0, 0)

    class Books:
        async def get_order_book(self, token):
            lookups.append(token)
            return MarketOrderBookSnapshot(
                token_id=token, timestamp=step, minimum_order_size=Decimal("1"),
                tick_size=Decimal("0.01"),
                asks=(OrderBookLevel(price=Decimal("0.5"), size=Decimal("1")),),
                bids=(OrderBookLevel(price=Decimal("0.6"), size=Decimal("1")),),
            )

    assert asyncio.run(tick(runs, lambda _: Source(), Books(), clock=lambda: step)) == "OBSERVED"
    runs.cancel("owner", key, step + timedelta(seconds=1))
    status, data = runs.for_owner("owner")[0]
    result = summary(status, data)
    assert len(lookups) == 72
    assert result.end_reason == "manual"
    assert result.coverage == "incomplete"
    assert result.equity is None
    assert Decimal(result.marked_pnl) == Decimal("0.468")
    for wallet in result.wallets:
        assert (wallet.fills, wallet.skipped, wallet.marked_positions, wallet.valued_positions) == (
            12, 3, 1, 0,
        )
        assert detail(status, data, wallet.address, 0).positions[0].marked_quantity == "1"
