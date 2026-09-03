from __future__ import annotations

import inspect
import json
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

import pytest
from polymarket import (
    AcceptedOrder,
    AsyncPublicClient,
    AsyncSecureClient,
    BalanceAllowance,
    OrderBook,
    UserInputError,
)
from polymarket.models.clob.account import ClobTrade, MakerOrder, OpenOrder
from polymarket.models.clob.cancel import CancelOrdersResponse
from polymarket.models.gamma.market import FeeSchedule, MarketState, MarketTrading

FIXTURE = Path(__file__).with_name("fixtures") / "polymarket_order_cancellation_v0_6.json"


def test_pinned_polymarket_sdk_version() -> None:
    assert version("polymarket-client") == "0.7.1"


def test_public_sdk_methods_used_by_adapter_exist() -> None:
    required = {
        "get_market",
        "list_activity",
        "list_closed_positions",
        "list_markets",
        "list_positions",
        "list_trades",
        "search",
        "subscribe",
    }

    assert required <= set(dir(AsyncPublicClient))


def test_secure_sdk_methods_used_by_adapter_exist() -> None:
    required = {
        "cancel_market_orders",
        "cancel_order",
        "create",
        "create_limit_order",
        "get_balance_allowance",
        "get_market",
        "get_order_book",
        "get_order",
        "list_account_trades",
        "list_open_orders",
        "list_positions",
        "place_limit_order",
        "place_market_order",
        "post_order",
    }

    assert required <= set(dir(AsyncSecureClient))


def test_secure_sdk_creation_preserves_signer_and_funder_inputs() -> None:
    create_parameters = inspect.signature(AsyncSecureClient.create).parameters

    assert {"private_key", "wallet"} <= set(create_parameters)


def test_round_trip_sdk_models_preserve_required_contract_fields() -> None:
    assert {
        "asks",
        "bids",
        "condition_id",
        "market",
        "min_order_size",
        "tick_size",
        "timestamp",
        "token_id",
    } <= set(OrderBook.model_fields)
    assert {"allowances", "balance"} <= set(BalanceAllowance.model_fields)
    assert {"making_amount", "ok", "order_id", "status", "taking_amount"} <= set(
        AcceptedOrder.model_fields
    )
    assert {
        "fee_rate_bps",
        "maker_orders",
        "price",
        "size",
        "status",
        "taker_order_id",
    } <= set(ClobTrade.model_fields)
    assert {
        "fee_rate_bps",
        "matched_amount",
        "order_id",
        "price",
        "side",
        "token_id",
    } <= set(MakerOrder.model_fields)
    assert {
        "id",
        "original_size",
        "price",
        "side",
        "size_matched",
        "status",
        "token_id",
    } <= set(OpenOrder.model_fields)
    assert {"exponent", "rate", "rebate_rate", "taker_only"} <= set(
        FeeSchedule.model_fields
    )
    assert {
        "fee_schedule",
        "fees_enabled",
        "minimum_order_size",
        "minimum_tick_size",
    } <= set(MarketTrading.model_fields)
    assert {
        "accepting_orders",
        "active",
        "archived",
        "closed",
        "enable_order_book",
        "end_date",
    } <= set(MarketState.model_fields)


def test_open_order_wire_fixture_preserves_aliases_decimals_and_identifiers() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["open_order"]

    order = OpenOrder.model_validate(payload)

    assert order.id == "0xorder123"
    assert str(order.condition_id) == payload["market"]
    assert str(order.market) == payload["market"]
    assert str(order.token_id) == payload["asset_id"]
    assert order.maker_address == payload["maker_address"]
    assert order.price == Decimal("0.420000")
    assert order.original_size == Decimal("10.500000")
    assert order.size_matched == Decimal("2.250000")
    assert order.associate_trades == ("trade-1",)
    assert order.expires_at is None
    assert order.created_at.tzinfo is not None


def test_cancel_orders_response_fixture_preserves_mixed_results() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["cancel_orders_response"]

    response = CancelOrdersResponse.model_validate(payload)

    assert tuple(str(order_id) for order_id in response.canceled) == ("0xorder123",)
    assert {str(order_id): reason for order_id, reason in response.not_canceled.items()} == {
        "0xorder456": "order is already matched"
    }


def test_round_trip_order_methods_preserve_bounded_parameters() -> None:
    market_parameters = inspect.signature(AsyncSecureClient.place_market_order).parameters
    limit_parameters = inspect.signature(AsyncSecureClient.place_limit_order).parameters
    create_limit_parameters = inspect.signature(
        AsyncSecureClient.create_limit_order
    ).parameters
    post_parameters = inspect.signature(AsyncSecureClient.post_order).parameters

    assert {"amount", "max_price", "max_spend", "order_type", "side", "token_id"} <= set(
        market_parameters
    )
    assert {"post_only", "price", "side", "size", "token_id"} <= set(
        limit_parameters
    )
    assert {"post_only", "price", "side", "size", "token_id"} <= set(
        create_limit_parameters
    )
    assert "signed_order" in post_parameters


def test_pinned_sdk_gtd_minimum_buffer_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polymarket._internal.actions.orders import limit

    monkeypatch.setattr(limit.time, "time", lambda: 1_000)

    with pytest.raises(UserInputError, match="at least 180 seconds"):
        limit.validate_limit_order_params(
            token_id="1",
            price=Decimal("0.50"),
            size=Decimal("5"),
            side="BUY",
            post_only=True,
            expiration=1_179,
        )

    params = limit.validate_limit_order_params(
        token_id="1",
        price=Decimal("0.50"),
        size=Decimal("5"),
        side="BUY",
        post_only=True,
        expiration=1_185,
    )
    assert params.expiration == 1_185
