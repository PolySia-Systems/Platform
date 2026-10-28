"""Immutable small policy presets, shared pre-risk advice for Shadow and actual orders."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from polysia.domain.copytrading.models import LeaderTradeAction
from polysia.domain.financial_session import SessionBlocked, decimal_value, digest, utc

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ShadowPositionAction:
    position_id: str
    policy_digest: str
    trigger: str
    leader_id: str
    market_reference: str
    outcome_reference: str
    executed_price: Decimal
    executed_size: Decimal
    executed_at: datetime
    observed_at: datetime
    position_revision: str = "initial"
    source_id: str = "shadow-position-policy"
    trade_action: LeaderTradeAction = LeaderTradeAction.SELL

    @property
    def event_id(self) -> str:
        return digest(
            (
                "shadow-position-action/v1",
                self.position_id,
                self.policy_digest,
                self.trigger,
                self.position_revision,
            )
        )

    @property
    def external_evidence_reference(self) -> str:
        return "position-policy:" + self.position_id


@dataclass(frozen=True, slots=True)
class CopyPolicy:
    version: str
    sizing: Literal["FIXED_DEBIT", "CAPITAL_PROPORTIONAL"]
    fixed_debit: Decimal
    capital_fraction: Decimal
    exit_preset: Literal["MIRROR", "NET_TAKE_PROFIT", "HYBRID"]
    net_take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    maximum_holding_seconds: int | None = None
    reentry: bool = False
    quantity_quantum: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        if not self.version or self.sizing not in {"FIXED_DEBIT", "CAPITAL_PROPORTIONAL"}:
            raise SessionBlocked("unsupported_copy_policy")
        if self.exit_preset not in {"MIRROR", "NET_TAKE_PROFIT", "HYBRID"}:
            raise SessionBlocked("unsupported_exit_preset")
        if (
            decimal_value(self.fixed_debit) <= 0
            or not 0 < decimal_value(self.capital_fraction) <= 1
        ):
            raise SessionBlocked("invalid_policy_size")
        if type(self.reentry) is not bool:
            raise SessionBlocked("explicit_reentry_policy_required")
        if not 0 < decimal_value(self.quantity_quantum) <= 1:
            raise SessionBlocked("bounded_quantity_quantum_required")
        if self.exit_preset != "MIRROR" and self.net_take_profit is None:
            raise SessionBlocked("net_take_profit_threshold_required")
        if self.exit_preset == "MIRROR" and self.net_take_profit is not None:
            raise SessionBlocked("mirror_policy_has_no_profit_trigger")
        for value in (self.net_take_profit, self.stop_loss):
            if value is not None and decimal_value(value) <= 0:
                raise SessionBlocked("positive_exit_threshold_required")
        if (self.stop_loss is not None or self.maximum_holding_seconds is not None) and (
            self.exit_preset != "HYBRID"
        ):
            raise SessionBlocked("optional_stop_time_requires_hybrid_preset")
        if self.maximum_holding_seconds is not None and (
            type(self.maximum_holding_seconds) is not int or self.maximum_holding_seconds <= 0
        ):
            raise SessionBlocked("invalid_holding_limit")

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))

    def entry_size(
        self,
        *,
        cash: Decimal,
        reserved_debit: Decimal,
        price: Decimal,
        fee_per_share: Decimal,
        share_quantum: Decimal,
        minimum_shares: Decimal,
        depth: Decimal,
        entered_before: bool,
    ) -> Decimal:
        for value in (
            cash,
            reserved_debit,
            price,
            fee_per_share,
            share_quantum,
            minimum_shares,
            depth,
        ):
            decimal_value(value)
        if not 0 < price < 1 or share_quantum <= 0 or minimum_shares <= 0:
            raise SessionBlocked("market_size_rules_unknown")
        if entered_before and not self.reentry:
            return ZERO
        available = max(ZERO, cash - reserved_debit)
        budget = min(
            available,
            self.fixed_debit if self.sizing == "FIXED_DEBIT" else available * self.capital_fraction,
        )
        raw = min(depth, budget / (price + fee_per_share))
        size = (raw / share_quantum).to_integral_value(rounding=ROUND_DOWN) * share_quantum
        return size if size >= minimum_shares else ZERO

    def exit_decision(
        self,
        *,
        held: Decimal,
        reserved_sell: Decimal,
        cost_basis: Decimal,
        bid: Decimal,
        exit_fee_per_share: Decimal,
        entry_fees: Decimal,
        opened_at: datetime,
        now: datetime,
        leader_before: Decimal | None,
        leader_reduction: Decimal | None,
        share_quantum: Decimal,
    ) -> tuple[str, Decimal]:
        for value in (
            held,
            reserved_sell,
            cost_basis,
            bid,
            exit_fee_per_share,
            entry_fees,
            share_quantum,
        ):
            decimal_value(value)
        if share_quantum <= 0 or not 0 < bid < 1 or utc(now) < utc(opened_at):
            raise SessionBlocked("invalid_position_trigger_evidence")
        available = (max(ZERO, held - reserved_sell) / share_quantum).to_integral_value(
            rounding=ROUND_DOWN
        ) * share_quantum
        if not held or not available:
            return "HOLD", ZERO
        # Fixed precedence: stop, time, net profit, leader reduction. STOP and
        # independent Risk still govern the eventual attempted order.
        net = held * (bid - exit_fee_per_share) - cost_basis - entry_fees
        if self.stop_loss is not None and net <= -self.stop_loss:
            return "STOP_LOSS", available
        if (
            self.maximum_holding_seconds is not None
            and (now - opened_at).total_seconds() >= self.maximum_holding_seconds
        ):
            return "MAX_HOLDING", available
        if self.net_take_profit is not None and net >= self.net_take_profit:
            return "NET_TAKE_PROFIT", available
        if self.exit_preset in {"MIRROR", "HYBRID"} and leader_reduction is not None:
            if (
                leader_before is None
                or decimal_value(leader_before) <= 0
                or decimal_value(leader_reduction) > leader_before
            ):
                raise SessionBlocked("evidenced_leader_baseline_required")
            target = min(available, held * leader_reduction / leader_before)
            quantity = (target / share_quantum).to_integral_value(rounding=ROUND_DOWN)
            return "LEADER_REDUCTION", quantity * share_quantum
        return "HOLD", ZERO
