from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from polysia.domain.market import MarketDetails, MarketFeeSchedule
from polysia.execution.tiny_live_round_trip import calculate_fee_aware_exit_target
from polysia.strategies.btc_15m_favorite_take_profit import (
    Btc15mFavoriteTakeProfitStrategy,
)


@given(
    fill_price=st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("0.98"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    tick_size=st.sampled_from(
        [Decimal("0.001"), Decimal("0.01"), Decimal("0.1")]
    ),
    quantity=st.integers(min_value=1, max_value=20).map(Decimal),
    fee_rate=st.sampled_from(
        [Decimal("0"), Decimal("0.05"), Decimal("0.25")]
    ),
    fee_exponent=st.sampled_from([Decimal("0"), Decimal("1"), Decimal("2")]),
)
def test_fee_aware_exit_target_is_minimal_tick_or_safely_rejected(
    fill_price: Decimal,
    tick_size: Decimal,
    quantity: Decimal,
    fee_rate: Decimal,
    fee_exponent: Decimal,
) -> None:
    market = MarketDetails(
        id="property-market",
        fee_schedule=MarketFeeSchedule(
            enabled=fee_rate > 0,
            rate=fee_rate if fee_rate > 0 else None,
            exponent=fee_exponent if fee_rate > 0 else None,
            taker_only=True,
        ),
    )
    entry_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
        market,
        price=fill_price,
        size=quantity,
    )
    target = calculate_fee_aware_exit_target(
        market,
        entry_price=fill_price,
        quantity=quantity,
        entry_fee=entry_fee,
        tick_size=tick_size,
        minimum_order_size=Decimal("1"),
    )

    if not target.achievable:
        assert target.target_price is None or target.target_price < Decimal("1")
        return
    assert target.target_price is not None
    assert target.target_price % tick_size == 0
    assert target.target_price > fill_price
    assert target.target_price < Decimal("1")
    assert target.expected_net_exit_proceeds is not None
    assert target.expected_net_exit_proceeds >= target.required_net_exit_proceeds
    assert target.expected_net_return is not None
    assert target.expected_net_return >= Decimal("0.10")

    previous_tick = target.target_price - tick_size
    if previous_tick > 0:
        previous_fee = Btc15mFavoriteTakeProfitStrategy.expected_fee(
            market,
            price=previous_tick,
            size=quantity,
        )
        assert (previous_tick * quantity) - previous_fee < target.required_net_exit_proceeds
