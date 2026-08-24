from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
)
from polysia.domain.copytrading.dynamic_shadow import (
    DynamicShadowConfig,
    DynamicShadowMode,
    ShadowBookLevel,
    ShadowEvaluationStatus,
    ShadowQuoteEvidence,
    evaluate_shadow_events,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _event(
    event_id: str,
    action: LeaderTradeAction,
    price: str,
    *,
    second: int,
    size: str = "10",
) -> LeaderTradeEvent:
    executed_at = NOW + timedelta(seconds=second)
    return LeaderTradeEvent(
        event_id=event_id,
        source_id="polymarket:data-api",
        leader_id="wallet-id",
        market_reference="condition-1",
        outcome_reference="token-1",
        trade_action=action,
        position_effect=LeaderPositionEffect.UNKNOWN,
        executed_price=Decimal(price),
        executed_size=Decimal(size),
        executed_at=executed_at,
        observed_at=executed_at + timedelta(seconds=2),
        external_evidence_reference="sha256:evidence",
    )


def test_historical_cost_model_records_fee_slippage_delay_liquidity_and_pnl() -> None:
    events = (
        _event("buy", LeaderTradeAction.BUY, "0.40", second=0),
        _event("sell", LeaderTradeAction.SELL, "0.60", second=10),
    )
    evaluations, summary = evaluate_shadow_events(
        "wallet-id",
        events,
        mode=DynamicShadowMode.HISTORICAL,
        config=DynamicShadowConfig(maximum_notional=Decimal("10")),
        quotes={},
        evaluated_at=NOW + timedelta(minutes=1),
    )

    assert [item.status for item in evaluations] == [
        ShadowEvaluationStatus.SIMULATED,
        ShadowEvaluationStatus.SIMULATED,
    ]
    assert evaluations[0].follower_price == Decimal("0.404")
    assert evaluations[1].follower_price == Decimal("0.594")
    assert evaluations[0].delay_ms == 2_000
    assert evaluations[0].available_liquidity == Decimal("100")
    assert summary.fees == Decimal("0.1996")
    assert summary.slippage == Decimal("0.100")
    assert summary.realized_pnl == Decimal("1.7004")
    assert summary.open_notional == Decimal("0")


def test_forward_shadow_walks_current_order_book_depth() -> None:
    event = _event("buy", LeaderTradeAction.BUY, "0.40", second=0, size="5")
    quote = ShadowQuoteEvidence(
        token_id="token-1",
        observed_at=event.observed_at,
        bids=(ShadowBookLevel(price=Decimal("0.39"), size=Decimal("5")),),
        asks=(
            ShadowBookLevel(price=Decimal("0.41"), size=Decimal("2")),
            ShadowBookLevel(price=Decimal("0.42"), size=Decimal("3")),
        ),
    )

    evaluations, summary = evaluate_shadow_events(
        "wallet-id",
        (event,),
        mode=DynamicShadowMode.FORWARD,
        config=DynamicShadowConfig(fee_bps=Decimal("0")),
        quotes={event.event_id: quote},
        evaluated_at=event.observed_at,
    )

    assert evaluations[0].status is ShadowEvaluationStatus.SIMULATED
    assert evaluations[0].filled_size == Decimal("5")
    assert evaluations[0].follower_price == Decimal("0.416")
    assert evaluations[0].available_liquidity == Decimal("5")
    assert evaluations[0].quote_source == "polymarket-current-book"
    assert summary.slippage == Decimal("0.080")


def test_forward_missing_book_and_sell_without_position_fail_unknown() -> None:
    buy = _event("buy", LeaderTradeAction.BUY, "0.40", second=0)
    sell = _event("sell", LeaderTradeAction.SELL, "0.60", second=1)

    buy_rows, _ = evaluate_shadow_events(
        "wallet-id",
        (buy,),
        mode=DynamicShadowMode.FORWARD,
        config=DynamicShadowConfig(),
        quotes={buy.event_id: None},
        evaluated_at=buy.observed_at,
    )
    sell_rows, _ = evaluate_shadow_events(
        "wallet-id",
        (sell,),
        mode=DynamicShadowMode.HISTORICAL,
        config=DynamicShadowConfig(),
        quotes={},
        evaluated_at=sell.observed_at,
    )

    assert buy_rows[0].status is ShadowEvaluationStatus.UNKNOWN
    assert buy_rows[0].reason == "current_order_book_unavailable"
    assert sell_rows[0].status is ShadowEvaluationStatus.UNKNOWN
    assert sell_rows[0].reason == "no_shadow_position_to_sell"


def test_cost_parameters_are_part_of_the_processing_version() -> None:
    default = DynamicShadowConfig()
    changed = DynamicShadowConfig(fee_bps=Decimal("250"))

    assert default.effective_cost_model_version != changed.effective_cost_model_version
    assert default.effective_cost_model_version.startswith(default.cost_model_version + "+")
