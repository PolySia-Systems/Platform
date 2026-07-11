from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from polysia.domain.clock import FixedClock
from polysia.domain.market import MarketOutcomeSummary, MarketSummary, Venue, VenueCapabilityProfile
from polysia.domain.orders import ApprovedOrderIntent, OrderIntent


def test_market_summary_is_venue_neutral_and_immutable() -> None:
    market = MarketSummary(
        id="canonical-market",
        question="Will the test pass?",
        outcomes=(MarketOutcomeSummary(label="Yes", price=Decimal("0.6")),),
    )

    assert market.id == "canonical-market"
    with pytest.raises(ValidationError):
        market.question = "changed"  # type: ignore[misc]


def test_capability_profile_keeps_venue_specific_behavior_explicit() -> None:
    profile = VenueCapabilityProfile(
        venue=Venue(id="example", display_name="Example Venue"),
        supported_order_types=("LIMIT", "MARKET"),
        supports_market_data_stream=True,
        supports_authenticated_reads=True,
        supports_order_cancellation=True,
        supports_live_execution=False,
        requires_geoblock_check=True,
    )

    assert profile.venue.id == "example"
    assert profile.requires_geoblock_check is True


def test_order_intent_validation_and_naive_clock_normalization() -> None:
    intent = OrderIntent(
        strategy_id="strategy",
        token_id="instrument",
        side="BUY",
        price=Decimal("0.4"),
        size=Decimal("2"),
        reason="test",
        confidence=Decimal("0.7"),
    )
    approved = ApprovedOrderIntent(
        intent=intent,
        approved_size=Decimal("1"),
        risk_reason="within limits",
        approved_at=datetime(2026, 7, 11),
    )

    assert approved.approved_at.tzinfo is UTC
    with pytest.raises(ValueError, match="price"):
        OrderIntent(
            strategy_id="strategy",
            token_id="instrument",
            side="BUY",
            price=Decimal("1.1"),
            size=Decimal("1"),
            reason="invalid",
            confidence=Decimal("0.5"),
        )


def test_fixed_clock_is_deterministic_and_timezone_aware() -> None:
    clock = FixedClock(datetime(2026, 7, 11, 12, 30))

    assert clock.now() == clock.now()
    assert clock.now().tzinfo is UTC

