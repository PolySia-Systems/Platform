from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from polymarket import PolymarketError, RequestRejectedError

from polysia.adapters.polymarket.secure import (
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
    sanitize_order_request,
)


class FakePaginator:
    def __init__(self, items: tuple[Any, ...]) -> None:
        self._items = items

    async def first_page(self) -> SimpleNamespace:
        return SimpleNamespace(items=self._items)

    async def _iter_items(self) -> Any:
        for item in self._items:
            yield item

    def iter_items(self) -> Any:
        return self._iter_items()


class FakeSecureClient:
    def __init__(self) -> None:
        self.closed = False
        self.wallet_type = "DEPOSIT_WALLET"
        self.get_order_kwargs: dict[str, Any] | None = None
        self.open_order_kwargs: dict[str, Any] | None = None
        self.cancel_order_kwargs: dict[str, Any] | None = None
        self.cancel_market_kwargs: dict[str, Any] | None = None
        self.limit_order_kwargs: dict[str, Any] | None = None
        self.market_order_kwargs: dict[str, Any] | None = None
        self.position_kwargs: dict[str, Any] | None = None
        self.trade_kwargs: dict[str, Any] | None = None

    def list_open_orders(self, **kwargs: Any) -> FakePaginator:
        self.open_order_kwargs = kwargs
        return FakePaginator((SimpleNamespace(id="order-1"),))

    async def get_order(self, **kwargs: Any) -> SimpleNamespace:
        self.get_order_kwargs = kwargs
        return SimpleNamespace(id="order-1", status="MATCHED")

    def list_positions(self, **kwargs: Any) -> FakePaginator:
        self.position_kwargs = kwargs
        return FakePaginator(
            (SimpleNamespace(token_id="token-1"), SimpleNamespace(token_id="token-2"))
        )

    def list_account_trades(self, **kwargs: Any) -> FakePaginator:
        self.trade_kwargs = kwargs
        return FakePaginator((SimpleNamespace(id="trade-1"), SimpleNamespace(id="trade-2")))

    async def cancel_order(self, **kwargs: Any) -> dict[str, str]:
        self.cancel_order_kwargs = kwargs
        return {"status": "cancelled"}

    async def cancel_market_orders(self, **kwargs: Any) -> dict[str, str]:
        self.cancel_market_kwargs = kwargs
        return {"status": "cancelled"}

    async def place_limit_order(self, **kwargs: Any) -> dict[str, str]:
        self.limit_order_kwargs = kwargs
        return {"status": "accepted"}

    async def place_market_order(self, **kwargs: Any) -> dict[str, str]:
        self.market_order_kwargs = kwargs
        return {"status": "accepted"}

    async def close(self) -> None:
        self.closed = True


class CapturingLogger:
    def __init__(self) -> None:
        self.warning_records: list[dict[str, Any]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        return None

    def warning(self, event: str, **kwargs: Any) -> None:
        self.warning_records.append({"event": event, **kwargs})


@pytest.mark.asyncio
async def test_connect_uses_funder_wallet_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSecureClient()
    captured: dict[str, str | None] = {}

    async def factory(*, private_key: str, wallet: str | None) -> FakeSecureClient:
        captured["private_key"] = private_key
        captured["wallet"] = wallet
        return client

    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "test-private-key")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunderwallet")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xlegacywallet")
    adapter = PolymarketSecureAdapter(client_factory=factory)

    await adapter.connect()
    await adapter.close()

    assert captured == {
        "private_key": "test-private-key",
        "wallet": "0xfunderwallet",
    }
    assert client.closed is True


@pytest.mark.asyncio
async def test_connect_falls_back_to_legacy_wallet_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSecureClient()
    captured: dict[str, str | None] = {}

    async def factory(*, private_key: str, wallet: str | None) -> FakeSecureClient:
        captured["private_key"] = private_key
        captured["wallet"] = wallet
        return client

    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "test-private-key")
    monkeypatch.delenv("POLYMARKET_FUNDER_ADDRESS", raising=False)
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xlegacywallet")
    adapter = PolymarketSecureAdapter(client_factory=factory)

    await adapter.connect()

    assert captured["wallet"] == "0xlegacywallet"
    assert adapter.identity().active_wallet_source == "legacy_wallet"


@pytest.mark.asyncio
async def test_identity_reports_sanitized_funder_and_signature_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSecureClient()

    async def factory(*, private_key: str, wallet: str | None) -> FakeSecureClient:
        return client

    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "test-private-key")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunderwallet")
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "3")
    adapter = PolymarketSecureAdapter(client_factory=factory)

    await adapter.connect()
    identity = adapter.identity().to_dict()

    assert identity["signer_configured"] is True
    assert identity["funder_configured"] is True
    assert identity["active_wallet_source"] == "funder"
    assert identity["wallet_type"] == "DEPOSIT_WALLET"
    assert identity["sdk_signature_type"] == 3
    assert identity["signature_type_matches_sdk"] is True
    assert "0xfunderwallet" not in str(identity)


@pytest.mark.asyncio
async def test_connect_requires_private_key_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def factory(*, private_key: str, wallet: str | None) -> FakeSecureClient:
        raise AssertionError("factory must not be called without private key")

    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    adapter = PolymarketSecureAdapter(client_factory=factory)

    with pytest.raises(PolymarketSecureAdapterError, match="POLYMARKET_PRIVATE_KEY"):
        await adapter.connect()


@pytest.mark.asyncio
async def test_authenticated_methods_call_connected_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSecureClient()

    async def factory(*, private_key: str, wallet: str | None) -> FakeSecureClient:
        return client

    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "test-private-key")
    adapter = PolymarketSecureAdapter(client_factory=factory)
    await adapter.connect()

    orders = await adapter.get_open_orders(token_id="token-1", market="market-1")
    order = await adapter.get_order(order_id="order-1")
    positions = await adapter.list_positions(size_threshold=0)
    trades = await adapter.list_account_trades(token_id="token-1", market="market-1")
    cancel_response = await adapter.cancel_order(order_id="order-1")
    cancel_market_response = await adapter.cancel_market_orders(token_id="token-1")
    limit_response = await adapter.place_limit_order(
        token_id="token-1",
        side="BUY",
        price=Decimal("0.50"),
        size=Decimal("5"),
        post_only=True,
    )
    market_response = await adapter.place_market_order(
        token_id="token-1",
        side="SELL",
        shares=Decimal("3"),
    )

    assert [order.id for order in orders] == ["order-1"]
    assert order.status == "MATCHED"
    assert [position.token_id for position in positions] == ["token-1", "token-2"]
    assert [trade.id for trade in trades] == ["trade-1", "trade-2"]
    assert cancel_response == {"status": "cancelled"}
    assert cancel_market_response == {"status": "cancelled"}
    assert limit_response == {"status": "accepted"}
    assert market_response == {"status": "accepted"}
    assert client.open_order_kwargs == {
        "token_id": "token-1",
        "id": None,
        "market": "market-1",
    }
    assert client.get_order_kwargs == {"order_id": "order-1"}
    assert client.position_kwargs == {"market": None, "size_threshold": 0}
    assert client.trade_kwargs == {"token_id": "token-1", "market": "market-1"}
    assert client.cancel_order_kwargs == {"order_id": "order-1"}
    assert client.cancel_market_kwargs == {"market": None, "token_id": "token-1"}
    assert client.limit_order_kwargs == {
        "token_id": "token-1",
        "side": "BUY",
        "price": Decimal("0.50"),
        "size": Decimal("5"),
        "post_only": True,
        "expiration": None,
        "builder_code": None,
    }
    assert client.market_order_kwargs == {
        "token_id": "token-1",
        "side": "SELL",
        "amount": None,
        "shares": Decimal("3"),
        "max_spend": None,
        "max_price": None,
        "min_price": None,
        "order_type": "FAK",
        "builder_code": None,
    }


@pytest.mark.asyncio
async def test_get_order_maps_venue_not_found_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingOrderClient(FakeSecureClient):
        async def get_order(self, **kwargs: Any) -> SimpleNamespace:
            raise RequestRejectedError("not found", status=404)

    client = MissingOrderClient()

    async def factory(*, private_key: str, wallet: str | None) -> MissingOrderClient:
        return client

    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "test-private-key")
    adapter = PolymarketSecureAdapter(client_factory=factory)
    await adapter.connect()

    assert await adapter.get_order(order_id="missing-order") is None


def test_sanitize_order_request_redacts_sensitive_values() -> None:
    request = sanitize_order_request(
        "place_limit_order",
        token_id="token-1",
        price=Decimal("0.51"),
        private_key="should-not-leak",
        funder_address="0xfundersecret",
        wallet_address="0xsecret",
        signed_payload={"danger": True},
    )

    assert request == {
        "action": "place_limit_order",
        "token_id": "token-1",
        "price": "0.51",
        "funder_address": "<redacted>",
        "private_key": "<redacted>",
        "wallet_address": "<redacted>",
        "signed_payload": "<redacted>",
    }
    assert "should-not-leak" not in str(request)
    assert "0xfundersecret" not in str(request)
    assert "0xsecret" not in str(request)


@pytest.mark.asyncio
async def test_sdk_error_logging_does_not_include_error_text_or_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient(FakeSecureClient):
        async def place_limit_order(self, **kwargs: Any) -> dict[str, str]:
            raise PolymarketError("signed payload should-not-leak")

    async def factory(*, private_key: str, wallet: str | None) -> FailingClient:
        return FailingClient()

    logger = CapturingLogger()
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "test-private-key")
    adapter = PolymarketSecureAdapter(client_factory=factory, logger=logger)
    await adapter.connect()

    with pytest.raises(PolymarketSecureAdapterError):
        await adapter.place_limit_order(
            token_id="token-1",
            side="BUY",
            price=Decimal("0.50"),
            size=Decimal("5"),
        )

    assert logger.warning_records == [
        {
            "event": "polymarket_secure_sdk_error",
            "operation": "place_limit_order",
            "error_type": "PolymarketError",
            "action": "place_limit_order",
            "token_id": "token-1",
            "side": "BUY",
            "price": "0.50",
            "size": "5",
            "post_only": False,
        }
    ]
    assert "should-not-leak" not in str(logger.warning_records)
    assert "test-private-key" not in str(logger.warning_records)
