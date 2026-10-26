"""Bounded public inventory, never complete authenticated account evidence.

OPEN includes winners; LOST covers the separate losing-settlement view. CLOSED
is retained history. Archived rows are requested; inactive markets can still be
absent upstream. No time filter is used: rows without economics clocks matter.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from polysia.adapters.polymarket.data_api_v2 import (
    DATA_API_V2_POSITIONS_PATH,
    DataApiV2Transport,
    fetch_data_api_v2_window,
)
from polysia.application.ports.copytrading import LeaderReadPurpose


async def public_position_inventory(
    transport: DataApiV2Transport, wallet: str, *, closed: bool = False, limit: int = 500
) -> list[dict[str, Any]]:
    statuses = ("CLOSED",) if closed else ("OPEN", "REDEEMABLE_LOST")
    by_token: dict[tuple[str, str], dict[str, Any]] = {}
    for status in statuses:
        params: dict[str, str | int | bool] = {
            "user": wallet, "status": status, "limit": limit,
            "filter_type": "TOKENS", "filter_amount": 0,
        }
        if not closed:
            params["include_archived"] = True
        rows = await fetch_data_api_v2_window(
            transport, DATA_API_V2_POSITIONS_PATH, params,
            purpose=LeaderReadPurpose.BASELINE,
        )
        for row in rows:
            token, condition = row.get("asset"), row.get("conditionId")
            if not isinstance(token, str) or not token or not isinstance(condition, str):
                raise ValueError("position identity missing")
            try:
                size = Decimal(str(row["size"]))
            except (KeyError, InvalidOperation) as error:
                raise ValueError("position size missing or invalid") from error
            if not size.is_finite() or size < 0:
                raise ValueError("position size invalid")
            if row.get("status") not in ({"CLOSED"} if closed else {"OPEN", "REDEEMABLE"}):
                raise ValueError("position lifecycle missing or invalid")
            key = (condition, token)
            previous = by_token.get(key)
            if previous is not None and previous != row:
                raise ValueError("conflicting position inventory views")
            by_token[key] = row
    return list(by_token.values())
