"""One bounded public Data API v2 cursor reader for wallet-attributed feeds."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from polysia.application.ports.copytrading import LeaderReadPurpose

DATA_API_BASE_URL = "https://data-api.polymarket.com"
DATA_API_V2_TRADES_PATH = "/v2/trades"
DATA_API_V2_ACTIVITY_PATH = "/v2/activity"


class DataApiV2Transport(Protocol):
    async def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> Any: ...


class IncompleteWalletWindowError(ValueError):
    """The bounded cursor walk cannot establish complete available-page coverage."""


def data_api_v2_rows(payload: object) -> list[dict[str, Any]]:
    """Require the official envelope and adapt snake-case rows at the boundary."""

    if not isinstance(payload, Mapping):
        raise TypeError("Data API v2 response is not an object")
    if "data" not in payload or payload["data"] is None:
        raise TypeError("Data API v2 feed data is missing")
    data = payload["data"]
    if not isinstance(data, list) or any(not isinstance(row, Mapping) for row in data):
        raise TypeError("Data API v2 data is not a list of objects")
    rows: list[dict[str, Any]] = []
    aliases = {
        "condition_id": "conditionId",
        "event_slug": "eventSlug",
        "outcome_index": "outcomeIndex",
        "proxy_wallet": "proxyWallet",
        "token_id": "asset",
        "transaction_hash": "transactionHash",
        "usdc_size": "usdcSize",
    }
    for row in data:
        adapted = dict(row)
        for current, legacy in aliases.items():
            if current in row:
                adapted[legacy] = row[current]
        rows.append(adapted)
    return rows


async def fetch_data_api_v2_window(
    transport: DataApiV2Transport,
    path: str,
    params: Mapping[str, str | int | bool],
    *,
    purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    max_pages: int = 20,
    max_requests: int = 20,
    max_elapsed_seconds: float = 30.0,
    monotonic: Callable[[], float] = time.monotonic,
    deadline_monotonic: float | None = None,
    on_page: Callable[[list[dict[str, Any]]], None] | None = None,
) -> list[dict[str, Any]]:
    """Return a complete available-page walk or raise without publishing rows.

    The cursor carries the seek anchor, while every request retains the same
    frozen filters. Completion says nothing about upstream publication delay.
    """

    if path not in {DATA_API_V2_TRADES_PATH, DATA_API_V2_ACTIVITY_PATH}:
        raise ValueError("unsupported Data API v2 feed")
    if max_pages <= 0 or max_requests <= 0 or max_elapsed_seconds <= 0:
        raise ValueError("Data API v2 walk budgets must be positive")
    deadline = monotonic() + max_elapsed_seconds
    if deadline_monotonic is not None:
        deadline = min(deadline, deadline_monotonic)
    rows: list[dict[str, Any]] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None
    page_count = 0
    request_count = 0
    while True:
        if page_count >= max_pages or request_count >= max_requests:
            raise IncompleteWalletWindowError("page_or_request_budget_exhausted")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise IncompleteWalletWindowError("time_budget_exhausted")
        request_params = dict(params)
        if cursor is not None:
            request_params["cursor"] = cursor
        request_count += 1
        try:
            payload = await asyncio.wait_for(
                transport.get_json(DATA_API_BASE_URL, path, request_params, purpose=purpose),
                timeout=remaining,
            )
        except TimeoutError as error:
            raise IncompleteWalletWindowError("time_budget_exhausted") from error
        if monotonic() >= deadline:
            raise IncompleteWalletWindowError("time_budget_exhausted")
        page_rows = data_api_v2_rows(payload)
        assert isinstance(payload, Mapping)
        pagination = payload.get("pagination")
        if not isinstance(pagination, Mapping):
            raise TypeError("Data API v2 pagination is missing")
        has_more = pagination.get("has_more")
        next_cursor = pagination.get("next_cursor")
        if not isinstance(has_more, bool) or not (
            next_cursor is None or isinstance(next_cursor, str) and next_cursor
        ):
            raise TypeError("Data API v2 pagination is malformed")
        if has_more != (next_cursor is not None):
            raise TypeError("Data API v2 pagination is inconsistent")
        page_count += 1
        if on_page is not None:
            on_page(page_rows)
            if monotonic() >= deadline:
                raise IncompleteWalletWindowError("time_budget_exhausted")
        rows.extend(page_rows)
        if next_cursor is None:
            return rows
        if next_cursor in seen_cursors:
            raise IncompleteWalletWindowError("repeated_cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
