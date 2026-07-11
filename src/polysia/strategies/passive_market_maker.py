from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polysia.bus.events import MarketDataEvent
from polysia.execution.intents import OrderIntent
from polysia.strategies.base import BaseStrategy, StrategyContext

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PassiveMarketMakerConfig:
    """Research-only passive quoting controls."""

    quote_size: Decimal = Decimal("1")
    min_spread: Decimal = Decimal("0.02")
    max_inventory: Decimal = Decimal("10")
    confidence: Decimal = Decimal("0.40")
    allow_short: bool = False

    def __post_init__(self) -> None:
        if self.quote_size <= ZERO:
            raise ValueError("quote_size must be positive")
        if self.min_spread <= ZERO:
            raise ValueError("min_spread must be positive")
        if self.max_inventory < ZERO:
            raise ValueError("max_inventory must not be negative")
        if self.confidence < ZERO or self.confidence > Decimal("1"):
            raise ValueError("confidence must be within [0, 1]")


class PassiveMarketMakerStrategy(BaseStrategy):
    """Research strategy that joins top of book without crossing the spread."""

    def __init__(
        self,
        *,
        strategy_id: str = "passive-market-maker",
        config: PassiveMarketMakerConfig | None = None,
    ) -> None:
        super().__init__(strategy_id=strategy_id)
        self._config = config or PassiveMarketMakerConfig()

    async def generate_intents(
        self,
        event: MarketDataEvent,
        context: StrategyContext,
    ) -> list[OrderIntent]:
        book = context.orderbook
        if book is None or book.token_id != event.token_id:
            return []
        if event.event_type not in {"book", "price_change", "best_bid_ask"}:
            return []
        if book.best_bid is None or book.best_ask is None or book.spread is None:
            return []
        if book.spread < self._config.min_spread:
            return []

        current_position = context.positions.get(event.token_id, ZERO)
        intents: list[OrderIntent] = []

        buy_size = min(
            self._config.quote_size,
            self._config.max_inventory - current_position,
        )
        if buy_size > ZERO:
            intents.append(
                OrderIntent(
                    strategy_id=self.strategy_id,
                    token_id=event.token_id,
                    side="BUY",
                    price=book.best_bid,
                    size=buy_size,
                    reason=(
                        "passive market maker joins best bid; "
                        f"spread {book.spread} >= {self._config.min_spread}"
                    ),
                    confidence=self._config.confidence,
                )
            )

        sell_size = self._sell_size(current_position)
        if sell_size > ZERO:
            intents.append(
                OrderIntent(
                    strategy_id=self.strategy_id,
                    token_id=event.token_id,
                    side="SELL",
                    price=book.best_ask,
                    size=sell_size,
                    reason=(
                        "passive market maker joins best ask; "
                        f"spread {book.spread} >= {self._config.min_spread}"
                    ),
                    confidence=self._config.confidence,
                )
            )

        return intents

    def _sell_size(self, current_position: Decimal) -> Decimal:
        if self._config.allow_short:
            return min(
                self._config.quote_size,
                self._config.max_inventory + current_position,
            )
        return min(self._config.quote_size, current_position)
