from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polysia.execution.intents import OrderIntent
from polysia.risk.checks import RiskContext, RiskDecision, RiskEngine

MAXIMUM_AUTHORIZED_ENTRY_NOTIONAL = Decimal("10.00")


@dataclass(frozen=True, slots=True)
class BoundedLiveRiskContext:
    entry_attempt_count: int
    selected_market_count: int
    existing_position_count: int
    available_balance: Decimal
    expected_fee: Decimal
    order_price_valid: bool
    order_size_valid: bool
    market_tradeable: bool
    geoblock_allowed: bool
    duplicate_free: bool
    exit_path_available: bool
    owner_authorized: bool
    account_identity_consistent: bool
    signer_funder_compatible: bool
    reconciliation_available: bool
    token_allowlisted: bool


class BoundedLiveRiskEngine:
    """Independent final Risk authority for the one authorized live entry."""

    def __init__(self, base: RiskEngine) -> None:
        self._base = base

    @property
    def base(self) -> RiskEngine:
        return self._base

    def evaluate_entry(
        self,
        intent: OrderIntent,
        risk_context: RiskContext,
        bounded: BoundedLiveRiskContext,
    ) -> RiskDecision:
        base_decision = self._base.evaluate(intent, risk_context)
        if not base_decision.approved:
            return base_decision

        notional = intent.price * intent.size
        checks: tuple[tuple[bool, str], ...] = (
            (
                notional <= MAXIMUM_AUTHORIZED_ENTRY_NOTIONAL,
                "entry notional exceeds owner-authorized 10.00 cap",
            ),
            (
                notional + bounded.expected_fee
                <= MAXIMUM_AUTHORIZED_ENTRY_NOTIONAL,
                "entry notional plus expected fee exceeds owner-authorized 10.00 cap",
            ),
            (bounded.entry_attempt_count == 0, "one-entry-attempt limit reached"),
            (bounded.selected_market_count == 1, "exactly one selected market is required"),
            (bounded.existing_position_count == 0, "one-position limit reached"),
            (bounded.expected_fee >= 0, "expected fee is invalid"),
            (
                bounded.available_balance >= notional + bounded.expected_fee,
                "available balance is insufficient for notional and expected fee",
            ),
            (bounded.order_price_valid, "order price is invalid for venue rules"),
            (bounded.order_size_valid, "order size is invalid for venue rules"),
            (bounded.market_tradeable, "market state is not tradeable"),
            (bounded.geoblock_allowed, "geoblock does not authorize entry"),
            (bounded.duplicate_free, "duplicate or conflicting order state detected"),
            (bounded.exit_path_available, "compliant exit path is unavailable"),
            (bounded.owner_authorized, "owner authorization scope is absent"),
            (
                bounded.account_identity_consistent,
                "account identity is inconsistent or unreadable",
            ),
            (
                bounded.signer_funder_compatible,
                "signer, funder, wallet, or signature type is incompatible",
            ),
            (
                bounded.reconciliation_available,
                "read-only reconciliation is unavailable",
            ),
            (bounded.token_allowlisted, "selected token is not allowlisted"),
        )
        for passed, reason in checks:
            if not passed:
                return RiskDecision(approved=False, reason=reason)
        return RiskDecision(
            approved=True,
            reason="bounded live entry approved",
            adjusted_size=base_decision.adjusted_size or intent.size,
        )


__all__ = [
    "BoundedLiveRiskContext",
    "BoundedLiveRiskEngine",
    "MAXIMUM_AUTHORIZED_ENTRY_NOTIONAL",
]
