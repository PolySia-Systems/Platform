from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.execution.intents import OrderIntent
from pm_trader.execution.live_broker import LiveBroker, LiveBrokerError
from pm_trader.risk.checks import RiskContext, RiskEngine
from pm_trader.risk.kill_switch import KillSwitch
from pm_trader.risk.limits import RiskLimits


class FakeLiveAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.cancel_order_calls: list[dict[str, Any]] = []
        self.cancel_market_calls: list[dict[str, Any]] = []
        self.limit_orders: list[dict[str, Any]] = []
        self.market_orders: list[dict[str, Any]] = []
        self.open_order_calls: list[dict[str, Any]] = []
        self.open_orders: list[Any] = []
        self.limit_order_response: Any = {"status": "accepted", "ok": True}

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def get_open_orders(self, **kwargs: Any) -> list[Any]:
        self.open_order_calls.append(kwargs)
        return self.open_orders

    async def cancel_order(self, **kwargs: Any) -> dict[str, tuple[str, ...] | dict[str, str]]:
        self.cancel_order_calls.append(kwargs)
        return {"canceled": (kwargs["order_id"],), "not_canceled": {}}

    async def cancel_market_orders(
        self,
        **kwargs: Any,
    ) -> dict[str, tuple[str, ...] | dict[str, str]]:
        self.cancel_market_calls.append(kwargs)
        return {"canceled": ("order-1",), "not_canceled": {}}

    async def place_limit_order(self, **kwargs: Any) -> Any:
        self.limit_orders.append(kwargs)
        return self.limit_order_response

    async def place_market_order(self, **kwargs: Any) -> dict[str, str]:
        self.market_orders.append(kwargs)
        return {"status": "accepted"}


class FakeGeoblockCheck:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls = 0

    async def assert_allowed(self) -> object:
        self.calls += 1
        if not self.allowed:
            from pm_trader.adapters.geoblock import PreLiveOrderGeoblockError

            raise PreLiveOrderGeoblockError("blocked")
        return object()


def make_intent(*, price: str = "0.50", size: str = "5") -> OrderIntent:
    return OrderIntent(
        strategy_id="strategy-1",
        token_id="token-1",
        side="BUY",
        price=Decimal(price),
        size=Decimal(size),
        reason="unit test",
        confidence=Decimal("0.80"),
    )


def live_settings(*, enabled: bool = True) -> AppSettings:
    return AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=enabled,
    )


def live_risk_engine(*, kill_switch: KillSwitch | None = None) -> RiskEngine:
    return RiskEngine(
        limits=RiskLimits(
            max_order_notional=Decimal("100"),
            max_position_per_token=Decimal("100"),
            max_position_per_market=Decimal("100"),
            allow_live_trading=True,
        ),
        kill_switch=kill_switch,
    )


@pytest.mark.asyncio
async def test_live_broker_blocks_by_default_settings() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=AppSettings(),
    )

    with pytest.raises(LiveBrokerError, match="TRADING_MODE=LIVE"):
        await broker.place_limit_order(
            make_intent(),
            RiskContext(),
            i_understand_this_places_real_orders=True,
        )

    assert adapter.limit_orders == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_live_broker_blocks_without_live_enabled_flag() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(enabled=False),
    )

    with pytest.raises(LiveBrokerError, match="LIVE_TRADING_ENABLED=true"):
        await broker.place_limit_order(
            make_intent(),
            RiskContext(),
            i_understand_this_places_real_orders=True,
        )

    assert adapter.limit_orders == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_live_broker_blocks_without_explicit_confirmation() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
    )

    with pytest.raises(LiveBrokerError, match="i-understand-this-places-real-orders"):
        await broker.place_limit_order(
            make_intent(),
            RiskContext(),
            i_understand_this_places_real_orders=False,
        )

    assert adapter.limit_orders == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_live_broker_blocks_when_kill_switch_is_active() -> None:
    adapter = FakeLiveAdapter()
    kill_switch = KillSwitch()
    kill_switch.activate("manual stop")
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(kill_switch=kill_switch),
        settings=live_settings(),
    )

    with pytest.raises(LiveBrokerError, match="kill switch"):
        await broker.place_limit_order(
            make_intent(),
            RiskContext(),
            i_understand_this_places_real_orders=True,
        )

    assert adapter.limit_orders == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_live_broker_blocks_when_risk_engine_denies_order() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=RiskEngine(limits=RiskLimits(allow_live_trading=True)),
        settings=live_settings(),
    )

    with pytest.raises(LiveBrokerError, match="risk engine blocked"):
        await broker.place_limit_order(
            make_intent(price="0.99", size="100"),
            RiskContext(),
            i_understand_this_places_real_orders=True,
        )

    assert adapter.limit_orders == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_dry_run_returns_sanitized_request_without_submitting() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
    )

    result = await broker.place_limit_order(
        make_intent(),
        RiskContext(),
        i_understand_this_places_real_orders=True,
        dry_run=True,
        post_only=True,
    )

    assert result.submitted is False
    assert result.dry_run is True
    assert result.request == {
        "action": "place_limit_order",
        "token_id": "token-1",
        "side": "BUY",
        "price": "0.50",
        "size": "5",
        "post_only": True,
    }
    assert "private" not in str(result.request).lower()
    assert "signed" not in str(result.request).lower()
    assert adapter.limit_orders == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_actual_live_submit_requires_token_allowlist() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
    )

    with pytest.raises(LiveBrokerError, match="POLYMARKET_LIVE_TOKEN_ALLOWLIST"):
        await broker.place_limit_order(
            make_intent(),
            RiskContext(),
            i_understand_this_places_real_orders=True,
            dry_run=False,
        )

    assert adapter.limit_orders == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_live_submit_requires_all_gates_and_uses_adapter() -> None:
    adapter = FakeLiveAdapter()
    geoblock = FakeGeoblockCheck()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
        allowed_token_ids=("token-1",),
        geoblock_check=geoblock,  # type: ignore[arg-type]
    )

    result = await broker.place_limit_order(
        make_intent(),
        RiskContext(),
        i_understand_this_places_real_orders=True,
        dry_run=False,
    )

    assert result.submitted is True
    assert result.dry_run is False
    assert result.response == {"status": "accepted", "ok": True}
    assert geoblock.calls == 1
    assert adapter.connected is True
    assert adapter.limit_orders == [
        {
            "token_id": "token-1",
            "side": "BUY",
            "price": Decimal("0.50"),
            "size": Decimal("5"),
            "post_only": False,
            "expiration": None,
            "builder_code": None,
        }
    ]


@pytest.mark.asyncio
async def test_live_submit_rejected_response_raises() -> None:
    adapter = FakeLiveAdapter()
    adapter.limit_order_response = {
        "ok": False,
        "code": "not_enough_balance",
        "message": "not enough balance",
    }
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
        allowed_token_ids=("token-1",),
        geoblock_check=FakeGeoblockCheck(),  # type: ignore[arg-type]
    )

    with pytest.raises(LiveBrokerError, match="Polymarket rejected live order"):
        await broker.place_limit_order(
            make_intent(),
            RiskContext(),
            i_understand_this_places_real_orders=True,
            dry_run=False,
        )

    assert adapter.connected is True
    assert len(adapter.limit_orders) == 1


@pytest.mark.asyncio
async def test_live_submit_aborts_when_geoblock_blocks() -> None:
    adapter = FakeLiveAdapter()
    geoblock = FakeGeoblockCheck(allowed=False)
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
        allowed_token_ids=("token-1",),
        geoblock_check=geoblock,  # type: ignore[arg-type]
    )

    with pytest.raises(LiveBrokerError, match="blocked"):
        await broker.place_limit_order(
            make_intent(),
            RiskContext(),
            i_understand_this_places_real_orders=True,
            dry_run=False,
        )

    assert geoblock.calls == 1
    assert adapter.connected is False
    assert adapter.limit_orders == []


@pytest.mark.asyncio
async def test_market_order_dry_run_defaults_to_approved_shares() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
    )

    result = await broker.place_market_order(
        make_intent(size="2"),
        RiskContext(),
        i_understand_this_places_real_orders=True,
    )

    assert result.request == {
        "action": "place_market_order",
        "token_id": "token-1",
        "side": "BUY",
        "shares": "2",
        "order_type": "FAK",
    }
    assert adapter.market_orders == []


@pytest.mark.asyncio
async def test_live_open_orders_requires_live_mode_by_default() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=AppSettings(),
    )

    with pytest.raises(LiveBrokerError, match="TRADING_MODE=LIVE"):
        await broker.get_open_orders(i_understand_this_uses_live_account=True)

    assert adapter.open_order_calls == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_live_open_orders_connects_with_explicit_account_ack() -> None:
    adapter = FakeLiveAdapter()
    adapter.open_orders = [{"id": "order-1"}]
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(enabled=False),
    )

    result = await broker.get_open_orders(
        token_id="token-1",
        i_understand_this_uses_live_account=True,
    )

    assert result.response == [{"id": "order-1"}]
    assert result.request == {
        "action": "get_open_orders",
        "token_id": "token-1",
    }
    assert adapter.connected is True
    assert adapter.open_order_calls == [
        {"token_id": "token-1", "order_id": None, "market": None}
    ]


@pytest.mark.asyncio
async def test_live_cancel_order_dry_run_does_not_connect() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
    )

    result = await broker.cancel_order(
        order_id="order-1",
        i_understand_this_modifies_live_orders=True,
    )

    assert result.submitted is False
    assert result.dry_run is True
    assert result.request == {
        "action": "cancel_order",
        "order_id": "order-1",
    }
    assert adapter.cancel_order_calls == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_live_cancel_market_actual_requires_allowlisted_token() -> None:
    adapter = FakeLiveAdapter()
    broker = LiveBroker(
        adapter=adapter,  # type: ignore[arg-type]
        risk_engine=live_risk_engine(),
        settings=live_settings(),
        allowed_token_ids=("token-allowed",),
    )

    with pytest.raises(LiveBrokerError, match="not in the live allowlist"):
        await broker.cancel_market_orders(
            token_id="token-blocked",
            dry_run=False,
            i_understand_this_modifies_live_orders=True,
        )

    assert adapter.cancel_market_calls == []
    assert adapter.connected is False
