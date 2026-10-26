from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from polysia.adapters.polymarket.data_api_v2 import fetch_data_api_v2_window
from polysia.adapters.polymarket.position_inventory import public_position_inventory


class Inventory:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.conflict = False

    async def get_json(self, base: str, path: str, params: Any, **kwargs: Any) -> Any:
        self.calls.append(dict(params))
        assert path == "/v2/positions"
        row = {"token_id": "one", "condition_id": "market", "current_size": "0.000001",
               "status": "REDEEMABLE", "archived": True, "redeemable": True}
        if self.conflict and params["status"] == "REDEEMABLE_LOST":
            row["current_size"] = "0.000002"
        return {"data": [deepcopy(row)],
                "pagination": {"has_more": False, "next_cursor": None}}


@pytest.mark.asyncio
async def test_overlapping_settlement_views_deduplicate_and_preserve_dust_archive() -> None:
    transport = Inventory()
    rows = await public_position_inventory(transport, "wallet")
    assert len(rows) == 1
    assert rows[0]["size"] == "0.000001"
    assert rows[0]["archived"] is True
    assert [call["status"] for call in transport.calls] == ["OPEN", "REDEEMABLE_LOST"]
    assert all(call["filter_amount"] == 0 for call in transport.calls)
    assert all("start" not in call and "end" not in call for call in transport.calls)
    transport.conflict = True
    with pytest.raises(ValueError, match="conflicting"):
        await public_position_inventory(transport, "wallet")


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint", [{"offset": 50}, {"cursor": "old-v1-offset"}])
async def test_legacy_checkpoint_is_not_reinterpreted(checkpoint: dict[str, Any]) -> None:
    transport = Inventory()
    with pytest.raises(ValueError, match="explicit migration"):
        await fetch_data_api_v2_window(transport, "/v2/positions", checkpoint)
    assert transport.calls == []
