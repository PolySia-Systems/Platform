"""Pure Paper risk-context construction from the execution ledger."""

from __future__ import annotations

from collections.abc import Iterable
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
    edge: Decimal | None = None,
) -> RiskContext:
    """Build a Paper RiskContext from ledger inventory and open paper orders.

    ``daily_pnl`` is sell-side realized inventory P&L. Fees stay on the ledger
    and in cash. Unrealized marks are not included.
    """

    position = ledger.get(token_id).size
    return RiskContext(
        trading_mode=TradingMode.PAPER,
        live_trading_enabled=False,
        current_position=position,
        current_market_position=position,
        daily_pnl=ledger.realized_pnl,
        open_orders_count=sum(
            1 for order in orders if order.status in OPEN_PAPER_ORDER_STATUSES
        ),
        market_data_age_ms=market_data_age_ms,
        edge=edge,
    )
