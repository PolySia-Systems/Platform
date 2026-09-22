from decimal import Decimal

import pytest

from polysia.portfolio.positions import Position, PositionLedger


def test_settle_resolution_pays_winner_and_books_inventory_pnl() -> None:
    ledger = PositionLedger(cash=Decimal("10"), fees=Decimal("0.25"))
    ledger.positions["yes"] = Position(
        token_id="yes",
        size=Decimal("4"),
        avg_price=Decimal("0.40"),
    )

    realized = ledger.settle_resolution("yes", Decimal("1"))

    assert realized == Decimal("2.40")
    assert ledger.cash == Decimal("14")
    assert ledger.realized_pnl == Decimal("2.40")
    assert ledger.fees == Decimal("0.25")
    assert "yes" not in ledger.positions


def test_settle_resolution_closes_loser_without_extra_cash() -> None:
    ledger = PositionLedger(cash=Decimal("6"), fees=Decimal("0.10"))
    ledger.positions["no"] = Position(
        token_id="no",
        size=Decimal("4"),
        avg_price=Decimal("0.40"),
    )

    realized = ledger.settle_resolution("no", Decimal("0"))

    assert realized == Decimal("-1.60")
    assert ledger.cash == Decimal("6")
    assert ledger.realized_pnl == Decimal("-1.60")
    assert ledger.fees == Decimal("0.10")
    assert "no" not in ledger.positions


def test_settle_resolution_is_idempotent_and_rejects_non_binary_prices() -> None:
    ledger = PositionLedger(cash=Decimal("6"))
    ledger.positions["yes"] = Position(
        token_id="yes",
        size=Decimal("1"),
        avg_price=Decimal("0.20"),
    )
    ledger.settle_resolution("yes", Decimal("1"))
    cash = ledger.cash
    realized = ledger.realized_pnl

    assert ledger.settle_resolution("yes", Decimal("1")) is None
    assert ledger.cash == cash
    assert ledger.realized_pnl == realized
    with pytest.raises(ValueError, match="0 or 1"):
        ledger.settle_resolution("yes", Decimal("0.5"))
