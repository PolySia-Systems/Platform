from __future__ import annotations

from decimal import Decimal

from polysia.portfolio.pnl import calculate_portfolio_pnl, calculate_unrealized_pnl
from polysia.portfolio.positions import Position, PositionLedger


def test_calculate_unrealized_pnl_uses_available_marks_only() -> None:
    ledger = PositionLedger(
        cash=Decimal("10"),
        positions={
            "token-1": Position(token_id="token-1", size=Decimal("10"), avg_price=Decimal("0.40")),
            "token-2": Position(token_id="token-2", size=Decimal("5"), avg_price=Decimal("0.20")),
        },
        realized_pnl=Decimal("1"),
    )

    assert calculate_unrealized_pnl(ledger, {"token-1": Decimal("0.50")}) == Decimal("1.00")


def test_calculate_portfolio_pnl_returns_equity_components() -> None:
    ledger = PositionLedger(
        cash=Decimal("95"),
        positions={
            "token-1": Position(token_id="token-1", size=Decimal("10"), avg_price=Decimal("0.40")),
        },
        realized_pnl=Decimal("1"),
    )

    pnl = calculate_portfolio_pnl(ledger, {"token-1": Decimal("0.50")})

    assert pnl.cash == Decimal("95")
    assert pnl.gross_market_value == Decimal("5.00")
    assert pnl.realized_pnl == Decimal("1")
    assert pnl.unrealized_pnl == Decimal("1.00")
    assert pnl.total_equity == Decimal("100.00")
