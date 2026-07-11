from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from polysia.bus.events import MarketDataEvent
from polysia.config.logging import get_logger
from polysia.domain.market import MarketSummary
from polysia.execution.intents import OrderIntent
from polysia.orderbook.book import LocalOrderBook

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Read-only data made available to strategies."""

    orderbook: LocalOrderBook | None = None
    latest_market: MarketSummary | None = None
    positions: Mapping[str, Decimal] = field(default_factory=dict)
    risk_limits: Mapping[str, Decimal | bool | int | str] = field(default_factory=dict)
    clock: Clock = utc_now


class BaseStrategy(ABC):
    """Template method base class that audits every generated intent."""

    def __init__(self, *, strategy_id: str, logger: Any | None = None) -> None:
        if not strategy_id:
            raise ValueError("strategy_id must not be empty")
        self.strategy_id = strategy_id
        self._logger = logger or get_logger(self.__class__.__name__)

    async def on_market_event(
        self,
        event: MarketDataEvent,
        context: StrategyContext,
    ) -> list[OrderIntent]:
        """Consume one market event and return pre-risk order intents."""
        intents = await self.generate_intents(event, context)
        for intent in intents:
            self.audit_intent(intent=intent, event=event, context=context)
        return intents

    @abstractmethod
    async def generate_intents(
        self,
        event: MarketDataEvent,
        context: StrategyContext,
    ) -> list[OrderIntent]:
        """Generate zero or more pre-risk intents."""

    def audit_intent(
        self,
        *,
        intent: OrderIntent,
        event: MarketDataEvent,
        context: StrategyContext,
    ) -> None:
        self._logger.info(
            "strategy_order_intent",
            confidence=str(intent.confidence),
            event_type=event.event_type,
            price=str(intent.price),
            reason=intent.reason,
            side=intent.side,
            size=str(intent.size),
            strategy_id=intent.strategy_id,
            token_id=intent.token_id,
            timestamp=context.clock().isoformat(),
        )
