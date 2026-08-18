from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.bus.events import MarketDataEvent
from polysia.control.models import DesiredStateRevision, OperationalState
from polysia.control.shadow_runtime import STALE_PRICE_SHADOW_TARGET, ShadowIntentBoundary
from polysia.orderbook.book import LocalOrderBook
from polysia.strategies.base import StrategyContext
from polysia.strategies.stale_price import StalePriceStrategy, StalePriceStrategyConfig

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def fixed_clock() -> datetime:
    return NOW


@pytest.mark.asyncio
async def test_shadow_boundary_suppresses_only_new_strategy_intents_when_paused() -> None:
    strategy = StalePriceStrategy(
        config=StalePriceStrategyConfig(min_edge=Decimal("0.01"))
    )
    boundary = ShadowIntentBoundary(
        STALE_PRICE_SHADOW_TARGET,
        clock=fixed_clock,
        identifier_factory=lambda: "observation-1",
    )
    event, context = _event_and_context()

    running_intents = await boundary.on_market_event(strategy, event, context)
    observation = boundary.reconcile(_revision(OperationalState.PAUSED))
    paused_intents = await boundary.on_market_event(strategy, event, context)

    assert running_intents
    assert paused_intents == []
    assert observation.observed_state.value == "PAUSED"
    assert observation.desired_revision == 1
    assert observation.reconciliation_status.value == "SUCCESS"


def test_shadow_boundary_rejects_a_different_strategy_identity() -> None:
    with pytest.raises(ValueError, match="unsupported Shadow control target"):
        ShadowIntentBoundary(
            STALE_PRICE_SHADOW_TARGET.model_copy(update={"strategy_id": "other"})
        )


def _revision(state: OperationalState) -> DesiredStateRevision:
    return DesiredStateRevision(
        key=STALE_PRICE_SHADOW_TARGET,
        revision=1,
        previous_revision=0,
        desired_state=state,
        command_id="command-1",
        plan_id="plan-1",
        created_at=NOW,
    )


def _event_and_context() -> tuple[MarketDataEvent, StrategyContext]:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=(("0.49", "100"),),
        asks=(("0.52", "10"),),
    )
    event = MarketDataEvent(
        source="fixture",
        event_type="book",
        token_id="token-1",
        received_at=NOW,
        exchange_ts=None,
        payload={},
        raw_payload={},
    )
    return event, StrategyContext(orderbook=book, clock=fixed_clock)
