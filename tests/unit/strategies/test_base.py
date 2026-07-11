from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.bus.events import MarketDataEvent
from polysia.execution.intents import OrderIntent
from polysia.strategies.base import BaseStrategy, StrategyContext


class FakeLogger:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.records.append({"event": event, **kwargs})


class IntentStrategy(BaseStrategy):
    async def generate_intents(
        self,
        event: MarketDataEvent,
        context: StrategyContext,
    ) -> list[OrderIntent]:
        return [
            OrderIntent(
                strategy_id=self.strategy_id,
                token_id=event.token_id,
                side="BUY",
                price=Decimal("0.51"),
                size=Decimal("1"),
                reason="unit test",
                confidence=Decimal("0.5"),
            )
        ]


def make_event() -> MarketDataEvent:
    return MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id="token-1",
        received_at=datetime.now(UTC),
        exchange_ts=None,
        payload={},
        raw_payload={},
    )


@pytest.mark.asyncio
async def test_base_strategy_audits_every_generated_intent() -> None:
    logger = FakeLogger()
    strategy = IntentStrategy(strategy_id="strategy-1", logger=logger)
    context = StrategyContext(clock=lambda: datetime(2026, 1, 1, tzinfo=UTC))

    intents = await strategy.on_market_event(make_event(), context)

    assert len(intents) == 1
    assert logger.records == [
        {
            "confidence": "0.5",
            "event": "strategy_order_intent",
            "event_type": "book",
            "price": "0.51",
            "reason": "unit test",
            "side": "BUY",
            "size": "1",
            "strategy_id": "strategy-1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "token_id": "token-1",
        }
    ]
