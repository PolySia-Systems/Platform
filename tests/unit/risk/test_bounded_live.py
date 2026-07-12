from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from polysia.config.settings import TradingMode
from polysia.execution.intents import OrderIntent
from polysia.portfolio.live_admission import (
    PortfolioAdmissionContext,
    SingleStrategyPortfolioAdmission,
)
from polysia.risk.bounded_live import BoundedLiveRiskContext, BoundedLiveRiskEngine
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits


def intent(*, price: str = "0.60", size: str = "1") -> OrderIntent:
    return OrderIntent(
        strategy_id="strategy",
        token_id="token-up",
        side="BUY",
        price=Decimal(price),
        size=Decimal(size),
        reason="bounded test",
        confidence=Decimal("1"),
    )


def portfolio_context(**updates: object) -> PortfolioAdmissionContext:
    values: dict[str, object] = {
        "available_balance": Decimal("1.00"),
        "reserved_balance": Decimal("0.25"),
        "existing_market_positions": 0,
        "conflicting_open_orders": 0,
        "current_market_exposure": Decimal("0"),
        "exit_path_available": True,
    }
    values.update(updates)
    return PortfolioAdmissionContext(**values)  # type: ignore[arg-type]


def bounded_context() -> BoundedLiveRiskContext:
    return BoundedLiveRiskContext(
        entry_attempt_count=0,
        selected_market_count=1,
        existing_position_count=0,
        available_balance=Decimal("1.00"),
        expected_fee=Decimal("0.01"),
        order_price_valid=True,
        order_size_valid=True,
        market_tradeable=True,
        geoblock_allowed=True,
        duplicate_free=True,
        exit_path_available=True,
        owner_authorized=True,
        account_identity_consistent=True,
        signer_funder_compatible=True,
        reconciliation_available=True,
        token_allowlisted=True,
    )


def risk_context() -> RiskContext:
    return RiskContext(
        trading_mode=TradingMode.LIVE,
        live_trading_enabled=True,
        market_data_age_ms=1,
    )


def risk_engine(*, kill_switch: KillSwitch | None = None) -> BoundedLiveRiskEngine:
    return BoundedLiveRiskEngine(
        RiskEngine(
            kill_switch=kill_switch,
            limits=RiskLimits(
                allow_live_trading=True,
                max_order_notional=Decimal("1"),
                max_position_per_token=Decimal("3"),
                max_position_per_market=Decimal("3"),
                max_open_orders=1,
            ),
        )
    )


def test_portfolio_admission_uses_already_available_balance_without_double_reservation() -> None:
    decision = SingleStrategyPortfolioAdmission().evaluate(
        intent(),
        portfolio_context(),
        expected_fee=Decimal("0.01"),
    )

    assert decision.admitted is True
    assert decision.reserved_entry_notional == Decimal("0.61")


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"existing_market_positions": 1}, "one-position"),
        ({"conflicting_open_orders": 1}, "conflicting"),
        ({"current_market_exposure": Decimal("0.1")}, "exposure"),
        ({"exit_path_available": False}, "exit path"),
        ({"available_balance": Decimal("0.60")}, "insufficient"),
    ],
)
def test_portfolio_admission_rejects_conflicts(
    updates: dict[str, object],
    reason: str,
) -> None:
    decision = SingleStrategyPortfolioAdmission().evaluate(
        intent(),
        portfolio_context(**updates),
        expected_fee=Decimal("0.01"),
    )
    assert decision.admitted is False
    assert reason in decision.reason


def test_independent_risk_approves_only_complete_bounded_context() -> None:
    decision = risk_engine().evaluate_entry(intent(), risk_context(), bounded_context())

    assert decision.approved is True
    assert decision.reason == "bounded live entry approved"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("entry_attempt_count", 1, "one-entry-attempt"),
        ("selected_market_count", 2, "exactly one selected market"),
        ("existing_position_count", 1, "one-position"),
        ("available_balance", Decimal("0.50"), "balance"),
        ("order_price_valid", False, "price"),
        ("order_size_valid", False, "size"),
        ("market_tradeable", False, "market state"),
        ("geoblock_allowed", False, "geoblock"),
        ("duplicate_free", False, "duplicate"),
        ("exit_path_available", False, "exit path"),
        ("owner_authorized", False, "authorization"),
        ("account_identity_consistent", False, "identity"),
        ("signer_funder_compatible", False, "signer"),
        ("reconciliation_available", False, "reconciliation"),
        ("token_allowlisted", False, "allowlisted"),
    ],
)
def test_bounded_risk_rejects_each_authorization_invariant(
    field: str,
    value: object,
    reason: str,
) -> None:
    context = replace(bounded_context(), **{field: value})
    decision = risk_engine().evaluate_entry(intent(), risk_context(), context)
    assert decision.approved is False
    assert reason in decision.reason


def test_risk_enforces_notional_and_kill_switch() -> None:
    above_cap = risk_engine().evaluate_entry(
        intent(price="0.60", size="2"),
        risk_context(),
        bounded_context(),
    )
    assert above_cap.approved is False
    assert "notional" in above_cap.reason

    kill_switch = KillSwitch()
    kill_switch.activate("operator emergency")
    killed = risk_engine(kill_switch=kill_switch).evaluate_entry(
        intent(),
        risk_context(),
        bounded_context(),
    )
    assert killed.approved is False
    assert "kill switch" in killed.reason
