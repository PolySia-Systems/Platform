from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polysia.execution.intents import OrderIntent


@dataclass(frozen=True, slots=True)
class PortfolioAdmissionContext:
    available_balance: Decimal
    reserved_balance: Decimal
    existing_market_positions: int
    conflicting_open_orders: int
    current_market_exposure: Decimal
    maximum_positions: int = 1
    maximum_markets: int = 1
    exit_path_available: bool = False


@dataclass(frozen=True, slots=True)
class PortfolioAdmissionDecision:
    admitted: bool
    reason: str
    reserved_entry_notional: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, object]:
        return {
            "admitted": self.admitted,
            "reason": self.reason,
            "reserved_entry_notional": str(self.reserved_entry_notional),
        }


class SingleStrategyPortfolioAdmission:
    """Bounded pre-risk admission; not a generalized capital allocator."""

    def evaluate(
        self,
        intent: OrderIntent,
        context: PortfolioAdmissionContext,
        *,
        expected_fee: Decimal,
    ) -> PortfolioAdmissionDecision:
        notional = intent.price * intent.size
        required = notional + expected_fee
        if expected_fee < 0:
            return PortfolioAdmissionDecision(False, "expected fee must not be negative")
        if context.available_balance < 0 or context.reserved_balance < 0:
            return PortfolioAdmissionDecision(False, "account balance state is invalid")
        if context.existing_market_positions >= context.maximum_positions:
            return PortfolioAdmissionDecision(False, "one-position limit reached")
        if context.current_market_exposure != 0:
            return PortfolioAdmissionDecision(False, "existing market exposure blocks entry")
        if context.conflicting_open_orders > 0:
            return PortfolioAdmissionDecision(False, "conflicting open order blocks entry")
        if not context.exit_path_available:
            return PortfolioAdmissionDecision(False, "compliant exit path is unavailable")
        if context.available_balance < required:
            return PortfolioAdmissionDecision(
                False,
                "available balance after reservations is insufficient",
            )
        return PortfolioAdmissionDecision(
            True,
            "single-strategy bounded admission approved",
            reserved_entry_notional=required,
        )


__all__ = [
    "PortfolioAdmissionContext",
    "PortfolioAdmissionDecision",
    "SingleStrategyPortfolioAdmission",
]
