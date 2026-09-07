"""Frozen Target Exposure v1 position-construction policy.

This isolates repeated accumulation. It does not change exits, fees,
settlement, wallet scoring, or Live/Risk/Execution authority. SignalArbiter
remains a leader-relative execution-advantage metric, not a probability or
expected-value Alpha model.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from polysia.domain.copytrading.continuous_shadow import ZERO

TARGET_EXPOSURE_POLICY_ID = "target-exposure-v1"
TARGET_EXPOSURE_POLICY_VERSION = "1"
TARGET_UNIT = "shares"
REENTRY_POLICY = "none"


class TargetExposureDecision(StrEnum):
    ADMIT = "ADMIT"
    SKIP_REPEAT_SIGNAL = "SKIP_REPEAT_SIGNAL"
    SKIP_REBALANCE = "SKIP_REBALANCE"
    SKIP_REENTRY = "SKIP_REENTRY"
    REJECT_CONFLICT = "REJECT_CONFLICT"
    REJECT_MARKET_CAP = "REJECT_MARKET_CAP"
    REJECT_INCOMPLETE = "REJECT_INCOMPLETE"
    REJECT_CASH = "REJECT_CASH"


@dataclass(frozen=True, slots=True)
class TargetExposurePolicy:
    """Complete frozen contract for the primary Current-Control comparison."""

    policy_id: str = TARGET_EXPOSURE_POLICY_ID
    policy_version: str = TARGET_EXPOSURE_POLICY_VERSION
    target_unit: str = TARGET_UNIT
    entry_budget: Decimal = Decimal("5")
    market_exposure_cap: Decimal = Decimal("100")
    reentry: str = REENTRY_POLICY
    cost_model_version: str = "polymarket-fee-depth-delay-v0.2"
    control_policy_version: str = "continuous-shadow-policy-v0.2"

    def __post_init__(self) -> None:
        if self.policy_id != TARGET_EXPOSURE_POLICY_ID:
            raise ValueError("Target Exposure v1 policy_id is frozen")
        if self.policy_version != TARGET_EXPOSURE_POLICY_VERSION:
            raise ValueError("Target Exposure v1 policy_version is frozen")
        if self.target_unit != TARGET_UNIT:
            raise ValueError("Target Exposure v1 target_unit is frozen to shares")
        if self.reentry != REENTRY_POLICY:
            raise ValueError("Target Exposure v1 forbids silent re-entry")
        if not self.entry_budget.is_finite() or self.entry_budget <= ZERO:
            raise ValueError("entry_budget must be finite and positive")
        if not self.market_exposure_cap.is_finite() or self.market_exposure_cap <= ZERO:
            raise ValueError("market_exposure_cap must be finite and positive")
        if self.entry_budget > self.market_exposure_cap:
            raise ValueError("entry_budget must not exceed market_exposure_cap")
        if not self.cost_model_version.strip() or not self.control_policy_version.strip():
            raise ValueError("frozen cost-model and control policy versions are required")

    def to_dict(self) -> dict[str, object]:
        return {
            "control_policy_version": self.control_policy_version,
            "cost_model_version": self.cost_model_version,
            "entry_budget": format(self.entry_budget, "f"),
            "market_exposure_cap": format(self.market_exposure_cap, "f"),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "reentry": self.reentry,
            "target_unit": self.target_unit,
        }


@dataclass(frozen=True, slots=True)
class EpisodeAdmission:
    decision: TargetExposureDecision
    target_quantity: Decimal
    notional: Decimal
    fee: Decimal
    executable_price: Decimal | None

    @property
    def accepted(self) -> bool:
        return self.decision is TargetExposureDecision.ADMIT


def establish_target_quantity(
    *,
    executable_price: Decimal,
    requested_quantity: Decimal,
    entry_budget: Decimal,
) -> Decimal:
    """Set target shares once from the first accepted executable price."""

    if executable_price <= ZERO or requested_quantity <= ZERO or entry_budget <= ZERO:
        return ZERO
    budget_shares = entry_budget / executable_price
    return requested_quantity if requested_quantity <= budget_shares else budget_shares


def decide_entry(
    policy: TargetExposurePolicy,
    *,
    episode_open: bool,
    episode_closed: bool,
    first_entry_price: Decimal | None,
    executable_price: Decimal | None,
    requested_quantity: Decimal | None,
    recorded_fee: Decimal | None,
    opposing_quantity: Decimal,
    market_exposure: Decimal,
    cash: Decimal,
) -> EpisodeAdmission:
    """Fail closed on incomplete, conflicting, or re-entry evidence.

    Additional wallet agreement is not an input. It must not increase notional.
    A later cheaper price does not raise target shares or spend unused budget.
    """

    rejected = EpisodeAdmission(
        TargetExposureDecision.REJECT_INCOMPLETE, ZERO, ZERO, ZERO, executable_price
    )
    if episode_closed:
        return EpisodeAdmission(
            TargetExposureDecision.SKIP_REENTRY, ZERO, ZERO, ZERO, executable_price
        )
    if episode_open:
        cheaper = (
            executable_price is not None
            and first_entry_price is not None
            and executable_price < first_entry_price
        )
        decision = (
            TargetExposureDecision.SKIP_REBALANCE
            if cheaper
            else TargetExposureDecision.SKIP_REPEAT_SIGNAL
        )
        return EpisodeAdmission(decision, ZERO, ZERO, ZERO, executable_price)
    if (
        executable_price is None
        or requested_quantity is None
        or recorded_fee is None
        or not executable_price.is_finite()
        or not requested_quantity.is_finite()
        or not recorded_fee.is_finite()
        or executable_price <= ZERO
        or requested_quantity <= ZERO
        or recorded_fee < ZERO
    ):
        return rejected
    if opposing_quantity > ZERO:
        return EpisodeAdmission(
            TargetExposureDecision.REJECT_CONFLICT, ZERO, ZERO, ZERO, executable_price
        )
    target_quantity = establish_target_quantity(
        executable_price=executable_price,
        requested_quantity=requested_quantity,
        entry_budget=policy.entry_budget,
    )
    if target_quantity <= ZERO:
        return rejected
    notional = target_quantity * executable_price
    if market_exposure + notional > policy.market_exposure_cap:
        return EpisodeAdmission(
            TargetExposureDecision.REJECT_MARKET_CAP,
            ZERO,
            ZERO,
            ZERO,
            executable_price,
        )
    fee_ratio = target_quantity / requested_quantity
    fee = recorded_fee * fee_ratio
    if cash < notional + fee:
        return EpisodeAdmission(
            TargetExposureDecision.REJECT_CASH, ZERO, ZERO, ZERO, executable_price
        )
    return EpisodeAdmission(
        TargetExposureDecision.ADMIT,
        target_quantity,
        notional,
        fee,
        executable_price,
    )


def scale_exit_quantity(*, held_quantity: Decimal, recorded_exit_quantity: Decimal) -> Decimal:
    """Never sell more than held or more than the recorded exit."""

    if held_quantity <= ZERO or recorded_exit_quantity <= ZERO:
        return ZERO
    return (
        held_quantity
        if held_quantity <= recorded_exit_quantity
        else recorded_exit_quantity
    )


__all__ = [
    "EpisodeAdmission",
    "REENTRY_POLICY",
    "TARGET_EXPOSURE_POLICY_ID",
    "TARGET_EXPOSURE_POLICY_VERSION",
    "TARGET_UNIT",
    "TargetExposureDecision",
    "TargetExposurePolicy",
    "decide_entry",
    "establish_target_quantity",
    "scale_exit_quantity",
]
