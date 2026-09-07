from __future__ import annotations

from decimal import Decimal

import pytest

from polysia.domain.copytrading.target_exposure import (
    TARGET_EXPOSURE_POLICY_ID,
    TARGET_UNIT,
    TargetExposureDecision,
    TargetExposurePolicy,
    decide_entry,
    establish_target_quantity,
)

POLICY = TargetExposurePolicy()


def test_frozen_policy_identity() -> None:
    assert POLICY.policy_id == TARGET_EXPOSURE_POLICY_ID
    assert POLICY.target_unit == TARGET_UNIT
    assert POLICY.reentry == "none"
    with pytest.raises(ValueError):
        TargetExposurePolicy(policy_id="other")


def test_target_shares_are_set_once_from_first_price() -> None:
    quantity = establish_target_quantity(
        executable_price=Decimal("0.50"),
        requested_quantity=Decimal("20"),
        entry_budget=Decimal("5"),
    )
    assert quantity == Decimal("10")


def test_repeated_signal_and_price_decline_do_not_add_notional() -> None:
    first = decide_entry(
        POLICY,
        episode_open=False,
        episode_closed=False,
        first_entry_price=None,
        executable_price=Decimal("0.50"),
        requested_quantity=Decimal("10"),
        recorded_fee=Decimal("0.02"),
        opposing_quantity=Decimal("0"),
        market_exposure=Decimal("0"),
        cash=Decimal("1000"),
    )
    repeat = decide_entry(
        POLICY,
        episode_open=True,
        episode_closed=False,
        first_entry_price=Decimal("0.50"),
        executable_price=Decimal("0.50"),
        requested_quantity=Decimal("10"),
        recorded_fee=Decimal("0.02"),
        opposing_quantity=Decimal("0"),
        market_exposure=Decimal("5"),
        cash=Decimal("994"),
    )
    cheaper = decide_entry(
        POLICY,
        episode_open=True,
        episode_closed=False,
        first_entry_price=Decimal("0.50"),
        executable_price=Decimal("0.20"),
        requested_quantity=Decimal("10"),
        recorded_fee=Decimal("0.02"),
        opposing_quantity=Decimal("0"),
        market_exposure=Decimal("5"),
        cash=Decimal("994"),
    )

    assert first.accepted
    assert first.target_quantity == Decimal("10")
    assert first.notional == Decimal("5.00")
    assert repeat.decision is TargetExposureDecision.SKIP_REPEAT_SIGNAL
    assert cheaper.decision is TargetExposureDecision.SKIP_REBALANCE
    assert repeat.notional == Decimal("0")
    assert cheaper.notional == Decimal("0")


def test_conflict_incomplete_and_reentry_fail_closed() -> None:
    conflict = decide_entry(
        POLICY,
        episode_open=False,
        episode_closed=False,
        first_entry_price=None,
        executable_price=Decimal("0.40"),
        requested_quantity=Decimal("5"),
        recorded_fee=Decimal("0.01"),
        opposing_quantity=Decimal("8"),
        market_exposure=Decimal("3"),
        cash=Decimal("1000"),
    )
    incomplete = decide_entry(
        POLICY,
        episode_open=False,
        episode_closed=False,
        first_entry_price=None,
        executable_price=None,
        requested_quantity=Decimal("5"),
        recorded_fee=Decimal("0.01"),
        opposing_quantity=Decimal("0"),
        market_exposure=Decimal("0"),
        cash=Decimal("1000"),
    )
    reentry = decide_entry(
        POLICY,
        episode_open=False,
        episode_closed=True,
        first_entry_price=Decimal("0.40"),
        executable_price=Decimal("0.40"),
        requested_quantity=Decimal("5"),
        recorded_fee=Decimal("0.01"),
        opposing_quantity=Decimal("0"),
        market_exposure=Decimal("0"),
        cash=Decimal("1000"),
    )
    cap = decide_entry(
        POLICY,
        episode_open=False,
        episode_closed=False,
        first_entry_price=None,
        executable_price=Decimal("0.50"),
        requested_quantity=Decimal("10"),
        recorded_fee=Decimal("0"),
        opposing_quantity=Decimal("0"),
        market_exposure=Decimal("96"),
        cash=Decimal("1000"),
    )

    assert conflict.decision is TargetExposureDecision.REJECT_CONFLICT
    assert incomplete.decision is TargetExposureDecision.REJECT_INCOMPLETE
    assert reentry.decision is TargetExposureDecision.SKIP_REENTRY
    assert cap.decision is TargetExposureDecision.REJECT_MARKET_CAP
