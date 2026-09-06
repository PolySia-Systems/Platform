from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.execution.canonical_order import (
    CanonicalOrderError,
    assert_exact_approved_request,
    bind_approved_order,
    canonicalize_market_order,
    risk_intent_from_canonical,
)
from polysia.execution.intents import OrderIntent


def buy_intent(*, size: str = "2") -> OrderIntent:
    return OrderIntent(
        strategy_id="s",
        token_id="token-1",
        side="BUY",
        price=Decimal("0.50"),
        size=Decimal(size),
        reason="test",
        confidence=Decimal("1"),
    )


def sell_intent(*, size: str = "1") -> OrderIntent:
    return OrderIntent(
        strategy_id="s",
        token_id="token-1",
        side="SELL",
        price=Decimal("0.40"),
        size=Decimal(size),
        reason="test",
        confidence=Decimal("1"),
    )


def test_buy_canonical_uses_spend_and_max_price() -> None:
    request = canonicalize_market_order(
        buy_intent(),
        amount=Decimal("1.00"),
        max_price=Decimal("0.50"),
    )

    assert request.amount == Decimal("1.00")
    assert request.shares is None
    assert request.max_price == Decimal("0.50")
    assert risk_intent_from_canonical(buy_intent(), request).size == Decimal("2")


def test_sell_canonical_uses_shares_and_min_price() -> None:
    request = canonicalize_market_order(
        sell_intent(),
        shares=Decimal("1"),
        min_price=Decimal("0.40"),
    )

    assert request.shares == Decimal("1")
    assert request.amount is None
    assert request.min_price == Decimal("0.40")


def test_invalid_side_parameter_combinations() -> None:
    with pytest.raises(CanonicalOrderError, match="forbids shares"):
        canonicalize_market_order(
            buy_intent(),
            shares=Decimal("1"),
            max_price=Decimal("0.50"),
        )
    with pytest.raises(CanonicalOrderError, match="forbids amount"):
        canonicalize_market_order(
            sell_intent(),
            amount=Decimal("1"),
            min_price=Decimal("0.40"),
        )


def test_risk_adjusted_exposure_is_frozen_on_approved_order() -> None:
    request = canonicalize_market_order(
        buy_intent(size="4"),
        amount=Decimal("2.00"),
        max_price=Decimal("0.50"),
    )
    approved = bind_approved_order(
        request,
        adjusted_size=Decimal("2"),
        risk_reason="reduced",
        approved_at=datetime.now(UTC),
    )

    assert approved.approved_exposure == Decimal("2")
    assert approved.request.amount == Decimal("1.00")
    with pytest.raises(CanonicalOrderError, match="exactly match"):
        assert_exact_approved_request(approved, request)
