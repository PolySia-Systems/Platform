from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polysia.bus.events import MarketDataEvent
from polysia.execution.intents import OrderIntent
from polysia.features.microstructure import calculate_microstructure_features
from polysia.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True, slots=True)
class StalePriceStrategyConfig:
    """Controls for the toy stale-price signal."""

    min_edge: Decimal = Decimal("0.02")
    order_size: Decimal = Decimal("1")
    confidence: Decimal = Decimal("0.50")

    def __post_init__(self) -> None:
        if self.min_edge <= Decimal("0"):
            raise ValueError("min_edge must be positive")
        if self.order_size <= Decimal("0"):
            raise ValueError("order_size must be positive")
        if self.confidence < Decimal("0") or self.confidence > Decimal("1"):
            raise ValueError("confidence must be within [0, 1]")


class StalePriceStrategy(BaseStrategy):
    """Toy strategy that emits intents from microprice-vs-mid dislocation."""

    def __init__(
        self,
        *,
        strategy_id: str = "stale-price",
        config: StalePriceStrategyConfig | None = None,
    ) -> None:
        super().__init__(strategy_id=strategy_id)
        self._config = config or StalePriceStrategyConfig()

    async def generate_intents(
        self,
        event: MarketDataEvent,
        context: StrategyContext,
    ) -> list[OrderIntent]:
        if context.orderbook is None:
            return []
        if context.orderbook.token_id != event.token_id:
            return []
        if event.event_type not in {"book", "price_change", "best_bid_ask"}:
            return []

        features = calculate_microstructure_features(context.orderbook)
        if (
            features.microprice_edge is None
            or features.best_bid is None
            or features.best_ask is None
        ):
            return []

        if features.microprice_edge >= self._config.min_edge:
            return [
                OrderIntent(
                    strategy_id=self.strategy_id,
                    token_id=event.token_id,
                    side="BUY",
                    price=features.best_ask,
                    size=self._config.order_size,
                    reason=(
                        "microprice above mid by "
                        f"{features.microprice_edge}; toy stale-price signal"
                    ),
                    confidence=self._config.confidence,
                )
            ]

        if features.microprice_edge <= -self._config.min_edge:
            return [
                OrderIntent(
                    strategy_id=self.strategy_id,
                    token_id=event.token_id,
                    side="SELL",
                    price=features.best_bid,
                    size=self._config.order_size,
                    reason=(
                        "microprice below mid by "
                        f"{features.microprice_edge}; toy stale-price signal"
                    ),
                    confidence=self._config.confidence,
                )
            ]

        return []
