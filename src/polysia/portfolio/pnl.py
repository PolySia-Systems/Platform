from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polysia.portfolio.positions import PositionLedger

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PortfolioPnL:
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    gross_market_value: Decimal
    total_equity: Decimal


def calculate_unrealized_pnl(
    ledger: PositionLedger,
    mark_prices: dict[str, Decimal],
) -> Decimal:
    pnl = ZERO
    for token_id, position in ledger.positions.items():
        mark_price = mark_prices.get(token_id)
        if mark_price is None:
            continue
        pnl += (mark_price - position.avg_price) * position.size
    return pnl


def calculate_gross_market_value(
    ledger: PositionLedger,
    mark_prices: dict[str, Decimal],
) -> Decimal:
    value = ZERO
    for token_id, position in ledger.positions.items():
        mark_price = mark_prices.get(token_id)
        if mark_price is None:
            continue
        value += position.market_value(mark_price)
    return value


def calculate_portfolio_pnl(
    ledger: PositionLedger,
    mark_prices: dict[str, Decimal],
) -> PortfolioPnL:
    gross_market_value = calculate_gross_market_value(ledger, mark_prices)
    unrealized_pnl = calculate_unrealized_pnl(ledger, mark_prices)
    return PortfolioPnL(
        cash=ledger.cash,
        realized_pnl=ledger.realized_pnl,
        unrealized_pnl=unrealized_pnl,
        gross_market_value=gross_market_value,
        total_equity=ledger.cash + gross_market_value,
    )
