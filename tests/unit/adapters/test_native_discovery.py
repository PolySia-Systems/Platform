from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from polysia.adapters.polymarket.data_api_v2 import IncompleteWalletWindowError
from polysia.adapters.polymarket.native_discovery import discover_native_activity

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
        return {"data": [row], "pagination": {
            "next_cursor": "opaque" if self.incomplete else None,
            "has_more": self.incomplete,
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


@pytest.mark.asyncio
async def test_incomplete_native_walk_cannot_publish_candidate_snapshot() -> None:
    transport = Transport(incomplete=True)
    with pytest.raises(IncompleteWalletWindowError, match="repeated_cursor"):
        await discover_native_activity(transport, cutoff=NOW, cohort_limit=1)
    assert "cursor" not in transport.calls[0]
    assert transport.calls[1] == {**transport.calls[0], "cursor": "opaque"}


@pytest.mark.asyncio
async def test_future_activity_is_excluded_before_cohort_freeze() -> None:
    result = await discover_native_activity(Transport(future=True), cutoff=NOW, cohort_limit=1)
    assert result["candidates"] == []
    assert result["excluded"] == {"invalid_or_out_of_window_trade": 1}
