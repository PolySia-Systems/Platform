"""Frozen public envelopes and transport fault behavior."""

from collections import deque
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from polysia.adapters.polymarket.leaderboard import (
    PublicReads,
    ReadFailure,
    board_observation,
    wallet_activity,
)
from polysia.domain.leaderboard import Board


def row(i, rank):
    return {
        "rank": rank,
        "user_id": f"0x{i:040x}",
        "pnl": "890.1234567890123456789",
        "volume": "10",
    }


def response(rows, cursor=None):
    return {"data": rows, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}}


def supply(monkeypatch, reads, *responses):
    remaining = deque(responses)
    calls = []

    def get(path, params):
        calls.append((path, dict(params)))
        item = remaining.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(reads, "get", get)
    return calls


def test_snapshot_preserves_ties_and_exact_values(monkeypatch):
    reads = PublicReads()
    calls = supply(
        monkeypatch, reads, response([row(2, 1), row(1, 1)], "next"), response([row(3, 3)])
    )
    item = board_observation(Board("polymarket", "month", "PNL"), reads)
    assert item.outcome == "complete"
    assert item.has_more is False
    assert [r.wallet for r in item.rows] == [f"0x{i:040x}" for i in (1, 2, 3)]
    assert [r.rank for r in item.rows] == [1, 1, 3]
    assert str(item.rows[0].pnl) == "890.1234567890123456789"
    assert item.rows[0].name is None
    assert calls[1] == (calls[0][0], {**calls[0][1], "cursor": "next"})


@pytest.mark.parametrize(
    "second, reason",
    [
        (ReadFailure("network_unavailable"), "network_unavailable"),
        (response([row(5, 3)], "next"), "invalid_page_or_repeated_cursor"),
        (response([row(1, 1)]), "duplicate_wallet"),
        (response([row(5, 0)]), "invalid_rank"),
    ],
)
def test_bad_later_page_preserves_only_valid_prefix(monkeypatch, second, reason):
    reads = PublicReads()
    supply(monkeypatch, reads, response([row(1, 1)], "next"), second)
    item = board_observation(Board("polymarket", "month", "PNL"), reads)
    assert (item.outcome, item.reason, len(item.rows)) == ("partial", reason, 1)
    assert item.has_more is None


def test_bounded_top_n_and_valid_empty(monkeypatch):
    reads = PublicReads()
    supply(monkeypatch, reads, response([row(i, i) for i in range(1, 101)], "more"), response([]))
    bounded = board_observation(Board("polymarket", "day", "PNL"), reads)
    empty = board_observation(Board("polymarket", "week", "VOLUME"), reads)
    assert len(bounded.rows) == 100 and bounded.has_more
    assert empty.outcome == "complete" and empty.rows == () and empty.has_more is False


@pytest.mark.parametrize("failure", [429, 500, "timeout", "connection"])
def test_transport_retries_and_caps_attempts(monkeypatch, failure):
    pauses = []
    reads = PublicReads(max_requests=3, sleep=pauses.append)

    def fail(request, **_):
        if failure == "timeout":
            raise TimeoutError
        if failure == "connection":
            raise URLError("offline")
        raise HTTPError(request.full_url, failure, "failed", Message(), BytesIO())

    monkeypatch.setattr(reads, "_open", fail)
    with pytest.raises(ReadFailure, match="network_unavailable|http_429|http_500"):
        reads.get("/v2/leaderboard", {})
    assert reads.requests == 3
    assert len(pauses) == 2 and pauses[0] < pauses[1]


def test_invalid_schema_and_rate_hint_do_not_loop(monkeypatch):
    reads = PublicReads(sleep=lambda _: pytest.fail("Must defer this long wait"))
    headers = Message()
    headers["Retry-After"] = "180"

    def limited(request, **_):
        raise HTTPError(request.full_url, 429, "limited", headers, BytesIO())

    monkeypatch.setattr(reads, "_open", limited)
    with pytest.raises(ReadFailure, match="http_429"):
        reads.get("/v2/leaderboard", {})
    with pytest.raises(ReadFailure, match="http_429"):
        reads.get("/v2/status", {})
    assert reads.requests == 1
    supply(monkeypatch, reads, {"error": "invalid"})
    item = board_observation(Board("polymarket", "month", "PNL"), reads)
    assert item.outcome == "failed" and item.reason == "invalid_data_envelope"


def test_activity_counts_only_frozen_identity_and_window(monkeypatch):
    wallet = row(1, 1)["user_id"]
    reads = PublicReads()
    event = {"proxy_wallet": wallet, "condition_id": "one", "timestamp": 20}
    supply(
        monkeypatch,
        reads,
        response([event, {**event, "timestamp": 21}], "next"),
        response([{**event, "timestamp": 40}]),
    )
    activity = wallet_activity(wallet, reads, 10, 30)
    assert (activity.trade_count, activity.market_count, activity.latest) == (2, 1, 21)
    assert activity.complete is False
