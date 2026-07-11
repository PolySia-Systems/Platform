from __future__ import annotations

from decimal import Decimal

import pytest

from polysia.risk.limits import RiskLimits


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_order_notional", Decimal("0")),
        ("max_position_per_token", Decimal("-1")),
        ("max_position_per_market", Decimal("-1")),
        ("max_daily_loss", Decimal("-1")),
        ("max_open_orders", -1),
        ("min_edge_required", Decimal("-0.01")),
        ("max_stale_data_age_ms", -1),
    ],
)
def test_risk_limits_reject_invalid_values(field_name: str, value: object) -> None:
    with pytest.raises(ValueError, match=field_name):
        RiskLimits(**{field_name: value})
