"""Consumed SDK behavior through its real models, pagination and HTTP transport."""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from polymarket import AsyncPublicClient, AsyncSecureClient
from polymarket._internal.context import AsyncSecureClientContext
from polymarket.clients.async_secure import _CREATE_TOKEN

from polysia.adapters.polymarket.secure import PolymarketSecureAdapter

WALLET = "0x" + "a" * 40
CONDITION = "0x" + "b" * 64


def position_wire(token: str, size: str, **changes: object) -> dict[str, object]:
    return {
        "proxy_wallet": WALLET,
        "token_id": token,
        "condition_id": CONDITION,
        "current_size": size,
        "avg_price": "0.40",
        "entry_cost_usdc": "40",
        "entry_fees_usdc": "0.10",
        "total_cost_usdc": "40.10",
        "current_price": "0",
        "current_value": "0",
        "total_size": "100",
        "realized_pnl": "0",
        "unrealized_pnl": "-40",
        "total_pnl": "-40",
        "percent_pnl": "-100",
        "percent_realized_pnl": "0",
        "status": "OPEN",
        "redeemable": False,
        "mergeable": False,
        "negative_risk": False,
        "archived": False,
        "verified": True,
        "end_date": "2020-01-01",
        **changes,
    }


def secure_reader(public: AsyncPublicClient) -> AsyncSecureClient:
    """Use actual SDK client/context with no key, auth setup, signer or RPC."""
    values = {field.name: getattr(public._ctx, field.name) for field in fields(public._ctx)}
    values.pop("environment_config")
    context = AsyncSecureClientContext(
        **values,
        wallet=WALLET,
        signer=SimpleNamespace(address=WALLET),
        credentials=None,
        secure_clob=public._ctx.clob,
        wallet_type="EOA",
        signer_type="EOA",
        relayer=public._ctx.clob,
        combos=public._ctx.clob,
        builder_gateway=public._ctx.clob,
        api_key=None,
        rpc=None,
        order_metadata=None,
    )
    return AsyncSecureClient(ctx=context, _create_token=_CREATE_TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", [None, 0, Decimal("1.25")])
async def test_actual_sdk_positions_preserve_current_inventory_and_complete_cursor_walk(
    monkeypatch: pytest.MonkeyPatch, threshold: Decimal | int | None
) -> None:
    requests = []
    rows = [
        position_wire("101", "0.000001"),
        position_wire("102", "2.25", status="REDEEMABLE", redeemable=True, archived=True),
        position_wire("103", "0"),
        position_wire("104", "0", status="CLOSED"),
    ]

    def wire(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/positions"
        params = dict(request.url.params)
        assert params["user"].lower() == WALLET
        assert params["condition_id"] == CONDITION
        assert params["include_archived"] == "true"
        assert params["filter_type"] == "TOKENS" and params["filter_amount"] == "0"
        assert "sizeThreshold" not in params and "market" not in params
        requests.append(params)
        second = params.get("cursor") == "opaque-second-page"
        return httpx.Response(
            200,
            json={
                "data": rows[2:] if second else rows[:2],
                "pagination": {
                    "has_more": not second,
                    "next_cursor": None if second else "opaque-second-page",
                },
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(wire))
    )
    async with AsyncPublicClient() as public:
        adapter = PolymarketSecureAdapter()
        adapter._client = secure_reader(public)
        positions = await adapter.list_positions(market=(CONDITION,), size_threshold=threshold)
        assert len(requests) == 2
        assert requests[0] == {k: v for k, v in requests[1].items() if k != "cursor"}
        assert [(p.token_id, p.size) for p in positions] == (
            [("102", Decimal("2.25"))]
            if threshold
            else [(str(101 + i), Decimal(row["current_size"])) for i, row in enumerate(rows)]
        )
        assert positions[0].avg_price == Decimal("0.40")
        assert positions[0].cur_price == 0
        assert all(p.size != Decimal("100") for p in positions)
        if not threshold:
            assert positions[1].redeemable is True
            assert positions[-1].size == 0
