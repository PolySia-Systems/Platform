"""Pure Paper risk-context construction from the execution ledger."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from polysia.config.settings import TradingMode
from polysia.execution.order_state import OrderStatus, PaperOrder
from polysia.portfolio.positions import PositionLedger
from polysia.risk.checks import RiskContext

OPEN_PAPER_ORDER_STATUSES = {
    OrderStatus.NEW,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
}


def paper_risk_context(
    *,
    ledger: PositionLedger,
    token_id: str,
    orders: Iterable[PaperOrder],
    market_data_age_ms: int,
    as_of: datetime,
    edge: Decimal | None = None,
) -> RiskContext:
    """Build a Paper RiskContext from ledger inventory and open paper orders.

    ``daily_pnl`` is UTC-day gross realized inventory P&L less fees incurred
    on that day. Unrealized marks remain outside the Risk loss comparison.
    """

    position = ledger.get(token_id).size
    return RiskContext(
        trading_mode=TradingMode.PAPER,
        live_trading_enabled=False,
        current_position=position,
        current_market_position=position,
        daily_pnl=ledger.daily_net_pnl(as_of),
        open_orders_count=sum(
            1 for order in orders if order.status in OPEN_PAPER_ORDER_STATUSES
        ),
        market_data_age_ms=market_data_age_ms,
        edge=edge,
    )
