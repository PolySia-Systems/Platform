from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from polysia.adapters.polymarket.data_api_v2 import IncompleteWalletWindowError
from polysia.adapters.polymarket.native_discovery import (
    discover_native_activity,
    revalidate_native_cohort,
)

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
WALLET = "0x" + "a" * 40


class Transport:
    def __init__(self, *, incomplete: bool = False, future: bool = False) -> None:
        self.incomplete, self.future = incomplete, future
        self.calls: list[dict[str, Any]] = []

    async def get_json(self, _base: str, path: str, params: Any, **_kwargs: Any) -> Any:
        self.calls.append(dict(params))
        row = {"proxy_wallet": WALLET, "timestamp": int(NOW.timestamp()) + (
            1 if self.future else -1), "price": "0.5", "size": "2", "side": "BUY"}
        if path.endswith("activity"):
            row["type"] = "TRADE"
        has_more = self.incomplete or path.endswith("trades")
        return {"data": [row], "pagination": {
            "next_cursor": "opaque" if has_more else None,
            "has_more": has_more,
        }}


@pytest.mark.asyncio
async def test_complete_native_activity_is_causal_and_deterministic() -> None:
    first = await discover_native_activity(Transport(), cutoff=NOW, cohort_limit=1)
    second = await discover_native_activity(Transport(), cutoff=NOW, cohort_limit=1)
    assert first == second
    assert first["source_rows"] == 1
    assert first["candidates"][0]["state"] == "ACTIVITY_CONFIRMED"
    assert first["candidates"][0]["execution_eligibility"].startswith("UNKNOWN")
    assert first["profile"] == "native-recent-activity/v1"
    assert first["seed_coverage"] == "FIRST_PAGE_SAMPLE_NOT_EXHAUSTIVE"
    assert first["seed_has_more"] is True


@pytest.mark.asyncio
async def test_incomplete_native_walk_cannot_publish_candidate_snapshot() -> None:
    transport = Transport(incomplete=True)
    with pytest.raises(IncompleteWalletWindowError, match="repeated_cursor"):
        await discover_native_activity(transport, cutoff=NOW, cohort_limit=1)
    assert transport.calls[0] == {"limit": 500, "taker_only": False}
    assert "cursor" not in transport.calls[1]
    assert transport.calls[2] == {**transport.calls[1], "cursor": "opaque"}


@pytest.mark.asyncio
async def test_future_activity_is_excluded_before_cohort_freeze() -> None:
    result = await discover_native_activity(Transport(future=True), cutoff=NOW, cohort_limit=1)
    assert result["candidates"] == []
    assert result["excluded"] == {"after_cutoff": 1}


@pytest.mark.asyncio
async def test_stale_seed_has_explicit_source_condition_and_no_wallet_requests() -> None:
    from datetime import timedelta

    transport = Transport()
    result = await discover_native_activity(
        transport, cutoff=NOW + timedelta(minutes=4), cohort_limit=1,
        lookback=timedelta(seconds=60),
    )
    assert result["source_condition"] == "DEGRADED_SOURCE_FRESHNESS"
    assert result["seed_newest_age_seconds"] == 241
    assert result["excluded"] == {"before_activity_window": 1}
    assert result["candidates"] == []
    assert len(transport.calls) == 1


class BoundaryTransport:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def get_json(self, _base: str, path: str, _params: Any, **_kwargs: Any) -> Any:
        seed = {"proxy_wallet": WALLET, "timestamp": int(NOW.timestamp()) - 1,
                "price": "0.5", "size": "2", "side": "BUY"}
        return {"data": self.rows if path.endswith("activity") else [seed],
                "pagination": {"has_more": False, "next_cursor": None}}


class UnavailableMarket:
    async def get_market_by_condition_id(self, _condition: str) -> Any:
        raise ValueError("offline_market_evidence_unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["discovery", "revalidation"])
@pytest.mark.parametrize("only_boundary", [False, True])
async def test_precise_activity_window_filters_floor_second_without_losing_coverage(
    route: str, only_boundary: bool,
) -> None:
    cutoff = NOW.replace(microsecond=500_000)
    lower = cutoff - timedelta(seconds=300)
    row = {"proxy_wallet": WALLET, "timestamp": int(lower.timestamp()),
           "price": "0.5", "size": "2", "side": "BUY", "type": "TRADE",
           "condition_id": "condition", "asset": "token"}
    rows = [row] if only_boundary else [row, {**row, "timestamp": int(NOW.timestamp()) - 1}]
    transport = BoundaryTransport(rows)
    if route == "discovery":
        result = await discover_native_activity(transport, cutoff=cutoff, cohort_limit=1)
    else:
        original = await discover_native_activity(Transport(), cutoff=NOW, cohort_limit=1)
        original["candidates"][0]["execution_eligibility"] = "ELIGIBLE_FOR_RESEARCH"
        result = await revalidate_native_cohort(
            original, transport, UnavailableMarket(), clock=lambda: cutoff,  # type: ignore[arg-type]
        )
    candidate = result["candidates"][0]
    assert candidate["complete_activity_rows"] == len(rows)
    assert candidate["window_filtered_rows"] == 1
    assert candidate["state"] == ("NO_COMPLETE_ACTIVITY" if only_boundary else "ACTIVITY_CONFIRMED")
    assert candidate["last_qualifying_activity"] == (
        None if only_boundary else (NOW - timedelta(seconds=1)).isoformat()
    )
    assert result["window_start"] == lower.isoformat()
    assert result["cutoff"] == cutoff.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [{"timestamp": "invalid"}, {"side": "INVALID"},
                                    {"timestamp": int(NOW.timestamp()) + 1},
                                    {"timestamp": int(NOW.timestamp()) - 301},
                                    {"proxy_wallet": "0x" + "b" * 40}])
async def test_precise_window_does_not_hide_invalid_in_scope_activity(
    invalid: dict[str, Any],
) -> None:
    row = {"proxy_wallet": WALLET, "timestamp": int(NOW.timestamp()) - 1,
           "price": "0.5", "size": "2", "side": "BUY", "type": "TRADE", **invalid}
    with pytest.raises(ValueError):
        await discover_native_activity(BoundaryTransport([row]), cutoff=NOW, cohort_limit=1)


@pytest.mark.asyncio
async def test_whole_second_activity_window_keeps_both_inclusive_boundaries() -> None:
    lower = NOW - timedelta(seconds=300)
    row = {"proxy_wallet": WALLET, "timestamp": int(lower.timestamp()),
           "price": "0.5", "size": "2", "side": "BUY", "type": "TRADE"}
    result = await discover_native_activity(
        BoundaryTransport([row, {**row, "timestamp": int(NOW.timestamp())}]),
        cutoff=NOW, cohort_limit=1,
    )
    candidate = result["candidates"][0]
    assert candidate["complete_activity_rows"] == 2
    assert candidate["window_filtered_rows"] == 0
    assert candidate["last_qualifying_activity"] == NOW.isoformat()
