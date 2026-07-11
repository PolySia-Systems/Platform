from datetime import UTC, datetime
from decimal import Decimal

from polysia.bus.events import MarketDataEvent
from polysia.execution.intents import OrderIntent
from polysia.strategies.base import BaseStrategy
from polysia.strategies.passive_market_maker import (
    PassiveMarketMakerConfig,
    PassiveMarketMakerStrategy,
)
from polysia.strategies.stale_price import StalePriceStrategy, StalePriceStrategyConfig


def build_research_strategy(
    *,
    strategy: str,
    order_size: Decimal,
    min_edge: Decimal,
) -> BaseStrategy:
    if strategy == "stale-price":
        return StalePriceStrategy(
            config=StalePriceStrategyConfig(min_edge=min_edge, order_size=order_size)
        )
    if strategy == "passive-market-maker":
        return PassiveMarketMakerStrategy(
            config=PassiveMarketMakerConfig(
                quote_size=order_size,
                min_spread=min_edge,
            )
        )
    raise ValueError("supported strategies: stale-price, passive-market-maker")


def local_market_event(token_id: str) -> MarketDataEvent:
    return MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id=token_id,
        received_at=datetime.now(UTC),
        exchange_ts=None,
        payload={},
        raw_payload={},
    )


def intent_to_dict(intent: object) -> dict[str, object]:
    if not isinstance(intent, OrderIntent):
        raise TypeError("expected OrderIntent")
    return {
        "confidence": str(intent.confidence),
        "price": str(intent.price),
        "reason": intent.reason,
        "side": intent.side,
        "size": str(intent.size),
        "strategy_id": intent.strategy_id,
        "token_id": intent.token_id,
    }
