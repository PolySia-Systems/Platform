from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.bus.events import MarketDataEvent
from polysia.config.settings import TradingMode
from polysia.execution.intents import ApprovedOrderIntent
from polysia.execution.order_state import OrderStatus
from polysia.execution.paper_broker import PaperBroker
from polysia.orderbook.builder import BookBuilder
from polysia.portfolio.positions import PositionLedger
from polysia.reconciliation.manager import ReconciliationManager
from polysia.reconciliation.models import (
    ActualAccountState,
    InternalExpectedState,
    PositionSnapshot,
    ReconciliationInput,
    ReconciliationStatus,
)
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.limits import RiskLimits
from polysia.strategies.base import StrategyContext
from polysia.strategies.stale_price import StalePriceStrategy, StalePriceStrategyConfig

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_market_event_to_reconciliation_paper_vertical_slice() -> None:
    event = MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id="instrument",
        received_at=NOW,
        exchange_ts=NOW,
        payload={
            "bids": [{"price": "0.49", "size": "100"}],
            "asks": [{"price": "0.52", "size": "10"}],
        },
        raw_payload={},
    )
    book = BookBuilder().apply(event)
    strategy = StalePriceStrategy(
        config=StalePriceStrategyConfig(
            min_edge=Decimal("0.01"),
            order_size=Decimal("2"),
            confidence=Decimal("0.6"),
        )
    )

    intents = await strategy.on_market_event(event, StrategyContext(orderbook=book))
    assert len(intents) == 1
    intent = intents[0]

    decision = RiskEngine(
        limits=RiskLimits(
            max_order_notional=Decimal("10"),
            max_position_per_token=Decimal("10"),
            max_position_per_market=Decimal("10"),
        )
    ).evaluate(intent, RiskContext(trading_mode=TradingMode.PAPER))
    assert decision.approved is True

    approved = ApprovedOrderIntent(
        intent=intent,
        approved_size=decision.adjusted_size or intent.size,
        risk_reason=decision.reason,
        approved_at=NOW,
    )
    ledger = PositionLedger(cash=Decimal("10"))
    order = PaperBroker(ledger=ledger, clock=lambda: NOW).submit_limit_order(approved, book)

    assert order.status == OrderStatus.FILLED
    assert ledger.get("instrument").size == Decimal("2")
    assert ledger.cash == Decimal("8.96")

    position = PositionSnapshot(token_id="instrument", size=Decimal("2"), updated_at=NOW)
    result = ReconciliationManager().reconcile(
        ReconciliationInput(
            internal=InternalExpectedState(
                positions=(position,),
                last_successful_account_read_at=NOW,
                updated_at=NOW,
            ),
            actual=ActualAccountState(positions=(position,), read_at=NOW),
            checked_at=NOW,
        )
    )

    assert result.status == ReconciliationStatus.READY
    assert result.trading_should_pause is False
