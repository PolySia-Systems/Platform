from __future__ import annotations

import inspect
from importlib.metadata import version

from polymarket import (
    AcceptedOrder,
    AsyncPublicClient,
    AsyncSecureClient,
    BalanceAllowance,
    OrderBook,
)
from polymarket.models.clob.account import ClobTrade, MakerOrder, OpenOrder
from polymarket.models.gamma.market import FeeSchedule, MarketState, MarketTrading


def test_pinned_polymarket_sdk_version() -> None:
    assert version("polymarket-client") == "0.1.0b11"


def test_public_sdk_methods_used_by_adapter_exist() -> None:
    required = {"get_market", "list_markets", "search", "subscribe"}

    assert required <= set(dir(AsyncPublicClient))


def test_secure_sdk_methods_used_by_adapter_exist() -> None:
    required = {
        "cancel_market_orders",
        "cancel_order",
        "create",
        "get_balance_allowance",
        "get_market",
        "get_order_book",
        "get_order",
        "list_account_trades",
        "list_open_orders",
        "list_positions",
        "place_limit_order",
        "place_market_order",
    }

    assert required <= set(dir(AsyncSecureClient))


def test_round_trip_sdk_models_preserve_required_contract_fields() -> None:
    assert {
        "asks",
        "bids",
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


def test_round_trip_order_methods_preserve_bounded_parameters() -> None:
    market_parameters = inspect.signature(AsyncSecureClient.place_market_order).parameters
    limit_parameters = inspect.signature(AsyncSecureClient.place_limit_order).parameters

    assert {"amount", "max_price", "max_spend", "order_type", "side", "token_id"} <= set(
        market_parameters
    )
    assert {"post_only", "price", "side", "size", "token_id"} <= set(
        limit_parameters
    )
