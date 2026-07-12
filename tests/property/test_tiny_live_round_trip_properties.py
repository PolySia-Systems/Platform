from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from polysia.execution.tiny_live_round_trip import normalize_exit_target


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
)
def test_normalized_exit_target_is_tick_aligned_or_safely_rejected(
    fill_price: Decimal,
    tick_size: Decimal,
) -> None:
    target = normalize_exit_target(fill_price, tick_size=tick_size)

    if target is None:
        raw = fill_price * Decimal("1.10")
        assert raw >= Decimal("1") - tick_size or fill_price <= 0
        return
    assert target % tick_size == 0
    assert target > fill_price
    assert target <= Decimal("1") - tick_size
    assert target >= fill_price * Decimal("1.10")
