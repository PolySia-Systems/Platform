from __future__ import annotations

from decimal import Decimal

import pytest

from pm_trader.execution.intents import OrderIntent


def test_order_intent_accepts_valid_decimal_values() -> None:
    intent = OrderIntent(
        strategy_id="strategy-1",
        token_id="token-1",
        side="BUY",
        price=Decimal("0.51"),
        size=Decimal("10"),
        reason="test",
        confidence=Decimal("0.75"),
    )

    assert intent.price == Decimal("0.51")
    assert intent.size == Decimal("10")


@pytest.mark.parametrize(
    ("price", "size", "confidence", "message"),
    [
        (Decimal("1.01"), Decimal("1"), Decimal("0.5"), "price"),
        (Decimal("0.50"), Decimal("0"), Decimal("0.5"), "size"),
        (Decimal("0.50"), Decimal("1"), Decimal("1.1"), "confidence"),
    ],
)
def test_order_intent_rejects_invalid_values(
    price: Decimal,
    size: Decimal,
    confidence: Decimal,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        OrderIntent(
            strategy_id="strategy-1",
            token_id="token-1",
            side="BUY",
            price=price,
            size=size,
            reason="test",
            confidence=confidence,
        )
