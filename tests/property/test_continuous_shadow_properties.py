from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from polysia.domain.copytrading import LeaderTradeAction
from polysia.domain.copytrading.continuous_shadow import walk_order_book
from polysia.domain.market import MarketOrderBookSnapshot, OrderBookLevel


@given(
    first=st.integers(min_value=1, max_value=100),
    second=st.integers(min_value=1, max_value=100),
    available=st.integers(min_value=1, max_value=100),
)
def test_repeated_walks_never_consume_more_than_recorded_book_liquidity(
    first: int,
    second: int,
    available: int,
) -> None:
    book = MarketOrderBookSnapshot(
        token_id="token",
        timestamp=datetime(2026, 8, 25, tzinfo=UTC),
        asks=(
            OrderBookLevel(price=Decimal("0.50"), size=Decimal(available)),
        ),
        minimum_order_size=Decimal("1"),
        tick_size=Decimal("0.01"),
    )
    consumed: dict[Decimal, Decimal] = {}
    first_walk = walk_order_book(
        book,
        action=LeaderTradeAction.BUY,
        requested_size=Decimal(first),
        already_consumed=consumed,
    )
    for price, size in first_walk.consumed:
        consumed[price] = consumed.get(price, Decimal("0")) + size
    second_walk = walk_order_book(
        book,
        action=LeaderTradeAction.BUY,
        requested_size=Decimal(second),
        already_consumed=consumed,
    )

    assert first_walk.filled_size + second_walk.filled_size <= Decimal(available)
    assert first_walk.gross_notional >= 0
    assert second_walk.gross_notional >= 0
