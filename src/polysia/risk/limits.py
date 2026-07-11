from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Pre-trade risk limits used before any broker sees an order intent."""

    max_order_notional: Decimal = Decimal("10")
    max_position_per_token: Decimal = Decimal("100")
    max_position_per_market: Decimal = Decimal("250")
    max_daily_loss: Decimal = Decimal("50")
    max_open_orders: int = 20
    min_edge_required: Decimal = Decimal("0")
    max_stale_data_age_ms: int = 5_000
    allow_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.max_order_notional <= Decimal("0"):
            raise ValueError("max_order_notional must be positive")
        if self.max_position_per_token < Decimal("0"):
            raise ValueError("max_position_per_token must not be negative")
        if self.max_position_per_market < Decimal("0"):
            raise ValueError("max_position_per_market must not be negative")
        if self.max_daily_loss < Decimal("0"):
            raise ValueError("max_daily_loss must not be negative")
        if self.max_open_orders < 0:
            raise ValueError("max_open_orders must not be negative")
        if self.min_edge_required < Decimal("0"):
            raise ValueError("min_edge_required must not be negative")
        if self.max_stale_data_age_ms < 0:
            raise ValueError("max_stale_data_age_ms must not be negative")
