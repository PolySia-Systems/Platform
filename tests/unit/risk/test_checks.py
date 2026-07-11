from __future__ import annotations

from decimal import Decimal

from polysia.config.settings import TradingMode
from polysia.execution.intents import OrderIntent
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits


def make_intent(*, side: str = "BUY", price: str = "0.50", size: str = "10") -> OrderIntent:
    return OrderIntent(
        strategy_id="strategy-1",
        token_id="token-1",
        side=side,  # type: ignore[arg-type]
        price=Decimal(price),
        size=Decimal(size),
        reason="test",
        confidence=Decimal("0.5"),
    )


def paper_context(**overrides: object) -> RiskContext:
    data = {
        "trading_mode": TradingMode.PAPER,
        "live_trading_enabled": False,
        "current_position": Decimal("0"),
        "current_market_position": Decimal("0"),
        "daily_pnl": Decimal("0"),
        "open_orders_count": 0,
        "market_data_age_ms": 0,
        "edge": Decimal("0.05"),
    }
    data.update(overrides)
    return RiskContext(**data)


def test_risk_engine_approves_valid_paper_intent() -> None:
    engine = RiskEngine(limits=RiskLimits(max_order_notional=Decimal("10")))

    decision = engine.evaluate(make_intent(price="0.50", size="10"), paper_context())

    assert decision.approved is True
    assert decision.reason == "approved"
    assert decision.adjusted_size == Decimal("10")


def test_risk_engine_blocks_data_only_mode_by_default() -> None:
    engine = RiskEngine()

    decision = engine.evaluate(make_intent(), RiskContext())

    assert decision.approved is False
    assert "DATA_ONLY" in decision.reason


def test_risk_engine_blocks_live_orders_unless_all_live_gates_are_open() -> None:
    intent = make_intent(price="0.50", size="1")

    disabled_flag = RiskEngine(limits=RiskLimits(allow_live_trading=True)).evaluate(
        intent,
        RiskContext(trading_mode=TradingMode.LIVE, live_trading_enabled=False),
    )
    disabled_limit = RiskEngine(limits=RiskLimits(allow_live_trading=False)).evaluate(
        intent,
        RiskContext(trading_mode=TradingMode.LIVE, live_trading_enabled=True),
    )
    approved = RiskEngine(limits=RiskLimits(allow_live_trading=True)).evaluate(
        intent,
        RiskContext(trading_mode=TradingMode.LIVE, live_trading_enabled=True),
    )

    assert disabled_flag.approved is False
    assert "LIVE_TRADING_ENABLED" in disabled_flag.reason
    assert disabled_limit.approved is False
    assert "do not allow live trading" in disabled_limit.reason
    assert approved.approved is True


def test_risk_engine_blocks_when_kill_switch_is_active() -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("operator stop")
    engine = RiskEngine(kill_switch=kill_switch)

    decision = engine.evaluate(make_intent(), paper_context())

    assert decision.approved is False
    assert "operator stop" in decision.reason


def test_risk_engine_blocks_order_notional_above_limit() -> None:
    engine = RiskEngine(limits=RiskLimits(max_order_notional=Decimal("4.99")))

    decision = engine.evaluate(make_intent(price="0.50", size="10"), paper_context())

    assert decision.approved is False
    assert "max_order_notional" in decision.reason


def test_risk_engine_blocks_token_position_after_trade_above_limit() -> None:
    engine = RiskEngine(limits=RiskLimits(max_position_per_token=Decimal("12")))

    decision = engine.evaluate(
        make_intent(size="10"),
        paper_context(current_position=Decimal("5")),
    )

    assert decision.approved is False
    assert "max_position_per_token" in decision.reason


def test_risk_engine_blocks_market_position_after_trade_above_limit() -> None:
    engine = RiskEngine(limits=RiskLimits(max_position_per_market=Decimal("12")))

    decision = engine.evaluate(
        make_intent(size="10"),
        paper_context(current_market_position=Decimal("5")),
    )

    assert decision.approved is False
    assert "max_position_per_market" in decision.reason


def test_risk_engine_blocks_daily_loss_breach() -> None:
    engine = RiskEngine(limits=RiskLimits(max_daily_loss=Decimal("10")))

    decision = engine.evaluate(make_intent(), paper_context(daily_pnl=Decimal("-10.01")))

    assert decision.approved is False
    assert "max_daily_loss" in decision.reason


def test_risk_engine_blocks_when_open_order_limit_reached() -> None:
    engine = RiskEngine(limits=RiskLimits(max_open_orders=2))

    decision = engine.evaluate(make_intent(), paper_context(open_orders_count=2))

    assert decision.approved is False
    assert "max_open_orders" in decision.reason


def test_risk_engine_blocks_stale_market_data() -> None:
    engine = RiskEngine(limits=RiskLimits(max_stale_data_age_ms=100))

    decision = engine.evaluate(make_intent(), paper_context(market_data_age_ms=101))

    assert decision.approved is False
    assert "max_stale_data_age_ms" in decision.reason


def test_risk_engine_blocks_missing_or_insufficient_edge_when_required() -> None:
    engine = RiskEngine(limits=RiskLimits(min_edge_required=Decimal("0.02")))

    missing_edge = engine.evaluate(make_intent(), paper_context(edge=None))
    small_edge = engine.evaluate(make_intent(), paper_context(edge=Decimal("0.01")))
    enough_negative_edge = engine.evaluate(make_intent(), paper_context(edge=Decimal("-0.03")))

    assert missing_edge.approved is False
    assert "edge is required" in missing_edge.reason
    assert small_edge.approved is False
    assert "min_edge_required" in small_edge.reason
    assert enough_negative_edge.approved is True
