from __future__ import annotations

from importlib.metadata import version

from polymarket import AsyncPublicClient, AsyncSecureClient


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
        "list_account_trades",
        "list_open_orders",
        "list_positions",
        "place_limit_order",
        "place_market_order",
    }

    assert required <= set(dir(AsyncSecureClient))
