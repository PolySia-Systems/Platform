"""Strategy interfaces and implementations."""

from polysia.strategies.btc_15m_favorite_take_profit import (
    Btc15mFavoriteTakeProfitStrategy,
    FavoriteTakeProfitConfig,
)
from polysia.strategies.passive_market_maker import (
    PassiveMarketMakerConfig,
    PassiveMarketMakerStrategy,
)
from polysia.strategies.registry import StrategyRegistry, StrategyRegistryError
from polysia.strategies.stale_price import StalePriceStrategy, StalePriceStrategyConfig

__all__ = [
    "Btc15mFavoriteTakeProfitStrategy",
    "FavoriteTakeProfitConfig",
    "PassiveMarketMakerConfig",
    "PassiveMarketMakerStrategy",
    "StalePriceStrategy",
    "StalePriceStrategyConfig",
    "StrategyRegistry",
    "StrategyRegistryError",
]
