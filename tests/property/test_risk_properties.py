from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from polysia.config.settings import TradingMode
from polysia.execution.intents import OrderIntent
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.limits import RiskLimits


@given(
    price_cents=st.integers(min_value=1, max_value=99),
    size=st.integers(min_value=1, max_value=100),
    cap_cents=st.integers(min_value=1, max_value=5_000),
)
def test_risk_never_approves_notional_above_cap(
    price_cents: int,
    size: int,
    cap_cents: int,
) -> None:
    price = Decimal(price_cents) / Decimal(100)
    cap = Decimal(cap_cents) / Decimal(100)
    intent = OrderIntent(
        strategy_id="property-test",
        token_id="instrument",
        side="BUY",
        price=price,
        size=Decimal(size),
        reason="property",
        confidence=Decimal("0.5"),
    )
    decision = RiskEngine(
        limits=RiskLimits(
            max_order_notional=cap,
            max_position_per_token=Decimal("1000"),
            max_position_per_market=Decimal("1000"),
        )
    ).evaluate(
        intent,
        RiskContext(trading_mode=TradingMode.PAPER),
    )

    if price * Decimal(size) > cap:
        assert decision.approved is False
