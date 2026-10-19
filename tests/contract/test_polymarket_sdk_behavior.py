"""Consumed SDK behavior through its real models, pagination and HTTP transport."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from polymarket import AsyncPublicClient, AsyncSecureClient
from polymarket._internal.context import AsyncSecureClientContext
from polymarket.clients import async_secure as secure_module
from polymarket.clients.async_secure import _CREATE_TOKEN
from polymarket.pagination import AsyncPaginator, Page

from polysia.adapters.polymarket.public import PolymarketPublicAdapter
from polysia.adapters.polymarket.secure import PolymarketSecureAdapter, PolymarketSecureAdapterError
from polysia.application.ports.cancellation import OrderLookupStatus
from polysia.execution.verified_live_state import snapshot_from_account_reads

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
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(wire)),
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
            snapshot = snapshot_from_account_reads(
                positions=positions,
                open_orders=[],
                trades=[],
                token_id="102",
                market_id=CONDITION,
                account_source_id="fixture",
                observed_at=datetime.now(UTC),
                market_data_observed_at=datetime.now(UTC),
            )
            assert snapshot.current_position.value == Decimal("2.25")
            assert snapshot.current_market_position.value == Decimal("2.250001")


def use_wire(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler))
    )


@pytest.mark.asyncio
async def test_real_sdk_asset_models_map_decimal_books_and_batch_serialization(monkeypatch):
    book = {
        "market": CONDITION,
        "asset_id": "101",
        "timestamp": "1787284800000",
        "bids": [{"price": "0.400001", "size": "1.000001"}],
        "asks": [{"price": "0.6", "size": "2"}],
        "min_order_size": "1",
        "tick_size": "0.000001",
        "neg_risk": False,
        "hash": "fixture-book",
    }
    calls = []

    def wire(request):
        calls.append(request)
        if request.url.path == "/book":
            assert request.url.params["token_id"] == "101"
            return httpx.Response(200, json=book)
        assert request.method == "POST" and request.url.path == "/books"
        assert json.loads(request.content) == [{"token_id": "101"}]
        return httpx.Response(200, json=[book])

    use_wire(monkeypatch, wire)
    adapter = PolymarketPublicAdapter()
    single = await adapter.get_order_book("101")
    batch = await adapter.get_order_books(("101",))
    assert single == batch["101"]
    assert single.token_id == "101" and single.market_id == CONDITION
    assert single.best_bid.price == Decimal("0.400001")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_real_sdk_mixed_cancellation_balance_and_order_evidence(monkeypatch):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/polymarket_order_cancellation_v0_6.json").read_text()
    )
    token = payload["open_order"]["asset_id"]
    calls = []

    def wire(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/data/orders":
            assert request.url.params["asset_id"] == token
            return httpx.Response(
                200, json={"data": [payload["open_order"]], "next_cursor": "LTE="}
            )
        if request.url.path == "/data/order/0xorder123":
            return httpx.Response(200, json=payload["open_order"])
        if request.url.path == "/balance-allowance":
            assert request.url.params["token_id"] == token
            return httpx.Response(200, json={"balance": "1250000", "allowances": {WALLET: "1"}})
        if request.url.path == "/order":
            assert request.method == "DELETE"
            assert json.loads(request.content)["orderID"] == "0xorder123"
            return httpx.Response(200, json=payload["cancel_orders_response"])
        assert request.method == "DELETE" and request.url.path == "/cancel-market-orders"
        assert json.loads(request.content) == {"market": CONDITION, "asset_id": token}
        return httpx.Response(200, json=payload["cancel_orders_response"])

    use_wire(monkeypatch, wire)
    async with AsyncPublicClient() as public:
        adapter = PolymarketSecureAdapter()
        adapter._client = secure_reader(public)
        orders = await adapter.get_open_orders(token_id=token)
        assert orders[0].asset_id == token
        detail = await adapter.observe_order_detail(order_id="0xorder123")
        assert detail.status == OrderLookupStatus.FOUND
        assert detail.order.token_id == token
        assert detail.order.matched_size == Decimal("2.250000")
        balance = await adapter.get_balance_allowance(asset_type="CONDITIONAL", token_id=token)
        assert balance.balance == Decimal("1250000")
        canceled = await adapter.cancel_market_orders(market=CONDITION, token_id=token)
        assert tuple(canceled.canceled) == ("0xorder123",)
        finality = await adapter.cancel_order_for_finality(order_id="0xorder123")
        assert finality.canceled_order_ids == ("0xorder123",)
        assert "0xorder456" in canceled.not_canceled
        assert len(calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload", [(404, {"error": "not found"}), (200, {"unexpected": True})]
)
async def test_real_sdk_verified_404_is_distinct_from_unknown_detail(monkeypatch, status, payload):
    use_wire(monkeypatch, lambda request: httpx.Response(status, json=payload))
    async with AsyncPublicClient() as public:
        adapter = PolymarketSecureAdapter()
        adapter._client = secure_reader(public)
        if status == 404:
            assert (
                await adapter.observe_order_detail(order_id="fixture")
            ).status == OrderLookupStatus.NOT_FOUND
        else:
            with pytest.raises(PolymarketSecureAdapterError):
                await adapter.observe_order_detail(order_id="fixture")


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["repeated", "missing_cursor", "malformed_size", "negative_size"])
async def test_real_sdk_incomplete_position_walk_never_returns_partial_inventory(
    monkeypatch, fault
):
    calls = []

    def wire(request):
        calls.append(request)
        assert len(calls) <= 4
        size_fault = fault in {"malformed_size", "negative_size"}
        return httpx.Response(
            200,
            json={
                "data": [
                    position_wire(
                        "101", {"malformed_size": "NaN", "negative_size": "-1"}.get(fault, "1")
                    )
                ],
                "pagination": {
                    "has_more": not size_fault,
                    "next_cursor": None if size_fault or fault == "missing_cursor" else "same",
                },
            },
        )

    use_wire(monkeypatch, wire)
    async with AsyncPublicClient() as public:
        adapter = PolymarketSecureAdapter()
        adapter._client = secure_reader(public)
        with pytest.raises(PolymarketSecureAdapterError):
            await adapter.list_positions(size_threshold=0)
    assert len(calls) <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_real_sdk_create_keeps_wallet_and_auth_inputs_and_closes_failed_bootstrap(
    monkeypatch, fail
):
    calls = []

    class Bootstrap:
        async def _ensure_wallet_ready(self):
            if fail:
                raise RuntimeError("offline bootstrap failure")
            return self

        async def close(self):
            calls.append("closed")

    bootstrap = Bootstrap()

    async def create(cls, **kwargs):
        calls.append(kwargs)
        return bootstrap

    monkeypatch.setattr(AsyncSecureClient, "_create", classmethod(create))
    if fail:
        with pytest.raises(RuntimeError, match="offline bootstrap failure"):
            await AsyncSecureClient.create(private_key="offline-marker", wallet=WALLET)
        assert calls[-1] == "closed"
    else:
        assert (
            await AsyncSecureClient.create(private_key="offline-marker", wallet=WALLET) is bootstrap
        )
    assert calls[0]["private_key"] == "offline-marker"
    assert calls[0]["wallet"] == WALLET
    assert calls[0]["validate_credentials"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TAKER", "MAKER"])
@pytest.mark.parametrize("wrong_asset", [False, True])
async def test_real_sdk_account_trade_models_preserve_linked_fill_identity(
    monkeypatch, role, wrong_asset
):
    asset = "102" if wrong_asset else "101"
    trade = {
        "id": "fixture-trade",
        "market": CONDITION,
        "asset_id": asset,
        "owner": "fixture-owner",
        "maker_address": WALLET,
        "taker_order_id": "wanted" if role == "TAKER" else "another-order",
        "side": "BUY",
        "trader_side": role,
        "price": "0.42",
        "size": "3",
        "outcome": "Yes",
        "status": "CONFIRMED",
        "fee_rate_bps": "0",
        "bucket_index": 0,
        "match_time": "1787284800",
        "last_update": "1787284801",
        "maker_orders": []
        if role == "TAKER"
        else [
            {
                "order_id": "wanted",
                "asset_id": asset,
                "owner": "fixture-owner",
                "maker_address": WALLET,
                "side": "BUY",
                "price": "0.41",
                "matched_amount": "1.25",
                "outcome": "Yes",
                "fee_rate_bps": "0",
            }
        ],
    }

    def wire(request):
        assert request.url.path == "/data/trades"
        assert request.url.params["asset_id"] == "101"
        return httpx.Response(200, json={"data": [trade], "next_cursor": "LTE="})

    use_wire(monkeypatch, wire)
    async with AsyncPublicClient() as public:
        adapter = PolymarketSecureAdapter()
        adapter._client = secure_reader(public)
        if wrong_asset:
            with pytest.raises(PolymarketSecureAdapterError, match="malformed"):
                await adapter.observe_order_trades(order_id="wanted", token_id="101")
        else:
            (fill,) = await adapter.observe_order_trades(order_id="wanted", token_id="101")
            assert fill.token_id == "101" and fill.status == "CONFIRMED"
            assert fill.size == Decimal("3" if role == "TAKER" else "1.25")
            assert fill.price == Decimal("0.42" if role == "TAKER" else "0.41")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [Decimal("0"), Decimal("5.125")])
async def test_real_sdk_limit_preparation_validates_before_the_intercepted_signer(
    monkeypatch, size
):
    calls = []

    async def draft(context, params):
        calls.append(params)
        return "offline-draft"

    async def sign(self, value, *, post_only):
        assert value == "offline-draft" and post_only is True
        calls.append("signer-intercepted")
        return "offline-prepared-order"

    monkeypatch.setattr(secure_module, "prepare_limit_order_draft", draft)
    monkeypatch.setattr(AsyncSecureClient, "_sign_order", sign)

    def no_wire(request):
        raise AssertionError("order preparation must not make a network request")

    use_wire(monkeypatch, no_wire)
    async with AsyncPublicClient() as public:
        adapter = PolymarketSecureAdapter()
        adapter._client = secure_reader(public)
        if size == 0:
            with pytest.raises(PolymarketSecureAdapterError):
                await adapter.prepare_limit_order(
                    token_id="101", price=Decimal("0.42"), size=size, side="BUY", post_only=True
                )
            assert calls == []
        else:
            assert (
                await adapter.prepare_limit_order(
                    token_id="101", price=Decimal("0.42"), size=size, side="BUY", post_only=True
                )
                == "offline-prepared-order"
            )
            assert calls[0].asset_id == "101"
            assert calls[0].size == size and calls[0].price == Decimal("0.42")
            assert calls[-1] == "signer-intercepted"


@pytest.mark.asyncio
async def test_real_sdk_depth_limited_page_cannot_qualify_an_account(monkeypatch):
    async def fetch(cursor):
        return Page(items=(), has_more=True, next_cursor=None, limit_reached=True)

    use_wire(monkeypatch, lambda request: pytest.fail("unexpected HTTP"))
    async with AsyncPublicClient() as public:
        sdk = secure_reader(public)
        monkeypatch.setattr(sdk, "list_positions", lambda **kwargs: AsyncPaginator(fetch))
        adapter = PolymarketSecureAdapter()
        adapter._client = sdk
        with pytest.raises(PolymarketSecureAdapterError, match="depth limit"):
            await adapter.list_positions(size_threshold=0)


@pytest.mark.asyncio
async def test_adapter_closes_actual_sdk_transports_without_authenticated_setup(monkeypatch):
    use_wire(monkeypatch, lambda request: pytest.fail("unexpected HTTP"))
    async with AsyncPublicClient() as public:
        adapter = PolymarketSecureAdapter()
        adapter._client = secure_reader(public)
        await adapter.close()
        assert not adapter.is_connected
        assert all(
            getattr(public._ctx, service)._client.is_closed
            for service in ("gamma", "data", "rfq", "clob", "perps")
        )
