from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    OrderBookLevel,
)
from polysia.strategies.btc_15m_favorite_take_profit import (
    Btc15mFavoriteTakeProfitStrategy,
    FavoriteTakeProfitConfig,
)

NOW = datetime(2026, 7, 11, 12, tzinfo=UTC)


def market(*, fee_enabled: bool = False) -> MarketDetails:
    return MarketDetails(
        id="market-1",
        slug="btc-updown-15m-123",
        question="Bitcoin Up or Down?",
        active=True,
        closed=False,
        accepting_orders=True,
        end_date=NOW + timedelta(minutes=10),
        condition_id="condition-1",
        enable_order_book=True,
        archived=False,
        outcomes=(
            MarketOutcomeSummary(label="Up", token_id="token-up"),
            MarketOutcomeSummary(label="Down", token_id="token-down"),
        ),
        fee_schedule=MarketFeeSchedule(
            enabled=fee_enabled,
            rate=Decimal("0.25") if fee_enabled else None,
            exponent=Decimal("1") if fee_enabled else None,
            taker_only=True,
        ),
    )


def book(
    token_id: str,
    *,
    bid: str,
    ask: str,
    ask_size: str = "25",
    minimum: str = "1",
    timestamp: datetime = NOW,
) -> MarketOrderBookSnapshot:
    return MarketOrderBookSnapshot(
        token_id=token_id,
        timestamp=timestamp,
        bids=(OrderBookLevel(price=Decimal(bid), size=Decimal("5")),),
        asks=(OrderBookLevel(price=Decimal(ask), size=Decimal(ask_size)),),
        minimum_order_size=Decimal(minimum),
        tick_size=Decimal("0.01"),
    )


def normal_books() -> tuple[MarketOrderBookSnapshot, ...]:
    return (
        book("token-up", bid="0.58", ask="0.60"),
        book("token-down", bid="0.38", ask="0.40"),
    )


def test_selects_current_executable_favorite_and_emits_intent() -> None:
    strategy = Btc15mFavoriteTakeProfitStrategy()

    decision = strategy.decide(market(), normal_books(), now=NOW)
    intent = decision.to_intent()

    assert decision.status == "TRADE"
    assert decision.selected_label == "Up"
    assert decision.entry_price == Decimal("0.60")
    assert decision.entry_size == Decimal("16.666666")
    assert intent.token_id == "token-up"
    assert intent.strategy_id == "btc-15m-favorite-take-profit"


def test_fee_aware_size_keeps_total_spend_within_ten() -> None:
    strategy = Btc15mFavoriteTakeProfitStrategy()
    active_market = market(fee_enabled=True)

    decision = strategy.decide(active_market, normal_books(), now=NOW)
    assert decision.status == "TRADE"
    assert decision.entry_size is not None
    assert decision.entry_price is not None
    expected_fee = strategy.expected_fee(
        active_market,
        price=decision.entry_price,
        size=decision.entry_size,
    )
    assert decision.entry_notional is not None
    assert decision.entry_notional + expected_fee <= Decimal("10.00")


@pytest.mark.parametrize(
    ("books", "reason"),
    [
        (
            (
                book("token-up", bid="0.53", ask="0.55"),
                book("token-down", bid="0.50", ask="0.55"),
            ),
            "tied",
        ),
        (
            (
                book(
                    "token-up",
                    bid="0.58",
                    ask="0.60",
                    timestamp=NOW - timedelta(seconds=6),
                ),
                book("token-down", bid="0.38", ask="0.40"),
            ),
            "stale",
        ),
        (
            (
                book(
                    "token-up",
                    bid="0.58",
                    ask="0.60",
                    timestamp=NOW + timedelta(seconds=4),
                ),
                book("token-down", bid="0.38", ask="0.40"),
            ),
            "ahead of the system clock",
        ),
        (
            (
                book("token-up", bid="0.58", ask="0.60", ask_size="1"),
                book("token-down", bid="0.38", ask="0.40"),
            ),
            "liquidity",
        ),
        (
            (
                book("token-up", bid="0.58", ask="0.60", minimum="20"),
                book("token-down", bid="0.38", ask="0.40"),
            ),
            "minimum order",
        ),
    ],
)
def test_rejects_unsafe_or_ambiguous_quotes(
    books: tuple[MarketOrderBookSnapshot, ...],
    reason: str,
) -> None:
    decision = Btc15mFavoriteTakeProfitStrategy().decide(market(), books, now=NOW)

    assert decision.status == "NO_TRADE"
    assert reason in decision.reason
    with pytest.raises(ValueError, match="cannot create"):
        decision.to_intent()


def test_rejects_ambiguous_token_mapping() -> None:
    duplicate = book("token-up", bid="0.38", ask="0.40")

    decision = Btc15mFavoriteTakeProfitStrategy().decide(
        market(),
        (normal_books()[0], duplicate),
        now=NOW,
    )

    assert decision.status == "NO_TRADE"
    assert "distinct token ids" in decision.reason


def test_accepts_bounded_venue_clock_lead() -> None:
    books = (
        book(
            "token-up",
            bid="0.58",
            ask="0.60",
            timestamp=NOW + timedelta(seconds=2),
        ),
        book("token-down", bid="0.38", ask="0.40"),
    )

    decision = Btc15mFavoriteTakeProfitStrategy().decide(market(), books, now=NOW)

    assert decision.status == "TRADE"


def test_configuration_never_allows_more_than_ten_collateral_units() -> None:
    with pytest.raises(ValueError, match="10.00"):
        FavoriteTakeProfitConfig(maximum_entry_notional=Decimal("10.01"))


def test_configuration_caps_future_clock_skew() -> None:
    with pytest.raises(ValueError, match="3000"):
        FavoriteTakeProfitConfig(maximum_future_clock_skew_ms=3_001)
