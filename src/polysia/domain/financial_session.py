"""Bounded session contracts. Discovery and configuration never grant authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from polysia.domain.orders.models import OrderIntent, OrderSide

ZERO = Decimal("0")


class SessionBlocked(RuntimeError):
    """Stable, non-sensitive reason for denying a session operation."""


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise SessionBlocked("clock_not_UTC")
    return value


def decimal_value(value: Decimal, *, minimum: Decimal = ZERO) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < minimum:
        raise SessionBlocked("invalid_financial_value")
    return value


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def canonical_json(value: object) -> str:
    def encode(item: object) -> object:
        if isinstance(item, Decimal):
            decimal_value(item, minimum=Decimal("-Infinity"))
            return str(item)
        if isinstance(item, datetime):
            return utc(item).isoformat()
        if isinstance(item, frozenset):
            return sorted(item)
        raise TypeError(f"unsupported contract value: {type(item).__name__}")

    return json.dumps(value, default=encode, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    release: str
    configuration: str
    policy: str
    account: str
    host: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in asdict(self).values()):
            raise SessionBlocked("missing_runtime_binding")


@dataclass(frozen=True, slots=True)
class InstrumentScope:
    market: str
    token: str
    collateral: str
    settlement_route: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in asdict(self).values()):
            raise SessionBlocked("missing_instrument_identity")


@dataclass(frozen=True, slots=True)
class SessionAuthorization:
    """All fields are required; an explicit false grant is an inert envelope.

    This is an authority *carrier*, not a signature verifier or approval issuer.
    The trusted composition root must verify the owner receipt before provision.
    No CLI or Console endpoint provisions these contracts.
    """

    version: int
    run_id: str
    owner_receipt: str
    granted: bool
    binding: RuntimeBinding
    starts_at: datetime
    expires_at: datetime
    protective_until: datetime
    wallets: frozenset[str]
    instruments: tuple[InstrumentScope, ...]
    strategy: str
    exit_policy: str
    max_order_all_in: Decimal
    max_open_exposure: Decimal
    max_turnover: Decimal
    max_total_loss: Decimal
    max_daily_loss: Decimal
    max_market_exposure: Decimal
    max_wallet_exposure: Decimal
    max_positions: int
    max_concurrent_orders: int
    max_attempts: int
    fee_rate: Decimal
    max_evidence_age_seconds: int
    supervision_timeout_seconds: int
    max_holding_seconds: int
    dust_shares: Decimal
    max_requests: int
    protective_request_reserve: int
    max_response_bytes: int
    max_storage_bytes: int
    max_source_cost: Decimal
    restart_policy: str
    protective_actions: frozenset[str]

    def __post_init__(self) -> None:
        if self.version != 1 or type(self.granted) is not bool:
            raise SessionBlocked("unsupported_authorization")
        if not all((self.run_id, self.owner_receipt, self.strategy, self.exit_policy)):
            raise SessionBlocked("incomplete_authorization")
        if not utc(self.starts_at) < utc(self.expires_at) <= utc(self.protective_until):
            raise SessionBlocked("invalid_authority_window")
        if (
            not isinstance(self.wallets, frozenset)
            or not isinstance(self.instruments, tuple)
            or not self.wallets
            or not self.instruments
        ):
            raise SessionBlocked("empty_authorized_scope")
        if len({item.token for item in self.instruments}) != len(self.instruments):
            raise SessionBlocked("ambiguous_token_mapping")
        for value in (
            self.max_order_all_in,
            self.max_open_exposure,
            self.max_turnover,
            self.max_total_loss,
            self.max_daily_loss,
            self.max_market_exposure,
            self.max_wallet_exposure,
        ):
            if decimal_value(value) <= ZERO:
                raise SessionBlocked("nonpositive_authority_limit")
        for limit in (
            self.max_positions,
            self.max_concurrent_orders,
            self.max_attempts,
            self.max_evidence_age_seconds,
            self.supervision_timeout_seconds,
            self.max_holding_seconds,
            self.max_requests,
            self.max_response_bytes,
            self.max_storage_bytes,
        ):
            if type(limit) is not int or limit <= 0:
                raise SessionBlocked("invalid_resource_limit")
        decimal_value(self.fee_rate)
        decimal_value(self.dust_shares)
        decimal_value(self.max_source_cost)
        if self.fee_rate >= 1 or not 0 <= self.protective_request_reserve < self.max_requests:
            raise SessionBlocked("invalid_fee_or_request_reserve")
        if self.restart_policy not in {"DENY", "RECONCILE"}:
            raise SessionBlocked("invalid_restart_policy")
        if not self.protective_actions <= {"CANCEL", "REDUCE"}:
            raise SessionBlocked("unsupported_protective_authority")

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))

    def assert_action(self, binding: RuntimeBinding, now: datetime, action: str) -> None:
        if not self.granted or binding != self.binding:
            raise SessionBlocked("authority_denied_or_binding_mismatch")
        if not self.starts_at <= utc(now):
            raise SessionBlocked("authority_not_started")
        if action == "ENTRY":
            if now >= self.expires_at:
                raise SessionBlocked("entry_authority_expired")
        elif action not in self.protective_actions or now >= self.protective_until:
            raise SessionBlocked("protective_action_not_authorized")


class SessionMode(StrEnum):
    RUNNING = "RUNNING"
    DRAIN = "DRAIN"
    STOP = "STOP"


class SessionOrderState(StrEnum):
    RESERVED = "RESERVED"
    UNCERTAIN_SUBMIT = "UNCERTAIN_SUBMIT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    FINALIZED = "FINALIZED"
    RECONCILIATION_BLOCKED = "RECONCILIATION_BLOCKED"


@dataclass(frozen=True, slots=True)
class SessionLimitRequest:
    """Exact quantity and price limits, canonicalized before Risk approval."""

    strategy_id: str
    token_id: str
    side: OrderSide
    price: Decimal
    shares: Decimal
    expiration: int
    post_only: bool

    def __post_init__(self) -> None:
        if (
            not self.strategy_id
            or not self.token_id
            or self.side not in {"BUY", "SELL"}
            or type(self.expiration) is not int
            or self.expiration <= 0
            or type(self.post_only) is not bool
        ):
            raise SessionBlocked("invalid_limit_request")
        if not 0 < decimal_value(self.price) < 1 or decimal_value(self.shares) <= 0:
            raise SessionBlocked("invalid_limit_economics")

    def as_intent(self) -> OrderIntent:
        return OrderIntent(
            self.strategy_id,
            self.token_id,
            self.side,
            self.price,
            self.shares,
            "exact bounded session limit",
            ZERO,
        )


@dataclass(frozen=True, slots=True)
class ApprovedSessionLimit:
    """Same immutable approval rule as ApprovedOrder, for a quantity-bound limit."""

    request: SessionLimitRequest
    risk_reason: str
    approved_at: datetime

    def __post_init__(self) -> None:
        utc(self.approved_at)
        if not self.risk_reason:
            raise SessionBlocked("missing_risk_approval_reason")


@dataclass(frozen=True, slots=True)
class SourceOccurrence:
    chain: str
    transaction: str
    occurrence: str | None
    wallet: str
    instrument: InstrumentScope
    side: OrderSide
    occurred_at: datetime
    observed_at: datetime
    ingested_at: datetime
    source: str
    source_key: str
    schema: str
    complete: bool
    finalized: bool
    leader_price: Decimal | None = None

    @property
    def identity(self) -> str:
        if not all((self.chain, self.transaction, self.occurrence, self.wallet)):
            raise SessionBlocked("ambiguous_occurrence_identity")
        return digest(
            (
                self.chain,
                self.transaction,
                self.occurrence,
                self.wallet,
            )
        )


@dataclass(frozen=True, slots=True)
class SessionOpportunity:
    event: SourceOccurrence
    strategy: str
    exit_policy: str
    price: Decimal
    shares: Decimal
    fair_price: Decimal | None
    uncertainty: Decimal | None
    cost_per_share: Decimal | None
    entry_depth: Decimal
    exit_depth: Decimal
    market_observed_at: datetime
    market_expires_at: datetime
    venue_eligible: bool
    leader_reduction: bool
    reason: str
    exit_trigger: str | None = None
    cohort_digest: str | None = None
    qualification_evidence_id: str | None = None

    @property
    def evidence_digest(self) -> str:
        return digest(asdict(self))

    def validate(self, authority: SessionAuthorization, *, now: datetime) -> Decimal:
        event = self.event
        _ = event.identity
        if event.side == "BUY" and not (self.cohort_digest and self.qualification_evidence_id):
            raise SessionBlocked("frozen_cohort_qualification_required")
        if event.wallet not in authority.wallets or event.instrument not in authority.instruments:
            raise SessionBlocked("opportunity_outside_scope")
        if self.strategy != authority.strategy or self.exit_policy != authority.exit_policy:
            raise SessionBlocked("strategy_or_exit_policy_mismatch")
        if (
            self.venue_eligible is not True
            or event.complete is not True
            or event.finalized is not True
            or not all((event.source, event.source_key, event.schema))
        ):
            raise SessionBlocked("venue_or_source_evidence_ineligible")
        if event.side not in {"BUY", "SELL"}:
            raise SessionBlocked("invalid_side")
        times = (event.occurred_at, event.observed_at, event.ingested_at, self.market_observed_at)
        if any(
            not 0 <= (utc(now) - utc(t)).total_seconds() <= authority.max_evidence_age_seconds
            for t in times
        ):
            raise SessionBlocked("stale_or_future_evidence")
        if not event.occurred_at <= event.observed_at <= event.ingested_at:
            raise SessionBlocked("invalid_source_time_order")
        if utc(self.market_expires_at) <= now:
            raise SessionBlocked("market_expired_requires_settlement_review")
        for value in (self.price, self.shares, self.entry_depth, self.exit_depth):
            decimal_value(value)
        if not ZERO < self.price < 1 or self.shares <= authority.dust_shares:
            raise SessionBlocked("invalid_size_price_or_dust")
        if min(self.entry_depth, self.exit_depth) < self.shares:
            raise SessionBlocked("insufficient_entry_or_exit_liquidity")
        if any(value is None for value in (self.fair_price, self.uncertainty, self.cost_per_share)):
            raise SessionBlocked("edge_or_cost_unknown")
        assert self.fair_price is not None
        assert self.uncertainty is not None
        assert self.cost_per_share is not None
        for value in (self.fair_price, self.uncertainty, self.cost_per_share):
            decimal_value(value)
        if self.fair_price > 1 or self.cost_per_share < self.price * authority.fee_rate:
            raise SessionBlocked("unbounded_edge_or_unpriced_fees")
        gross = (
            self.fair_price - self.price if event.side == "BUY" else self.price - self.fair_price
        )
        edge = gross - self.uncertainty - self.cost_per_share
        if event.side == "BUY" and edge <= ZERO:
            raise SessionBlocked("nonpositive_conservative_edge")
        holding_exit = (
            self.exit_trigger == "MAX_HOLDING"
            and authority.exit_policy == "leader-reduction-or-max-hold/v1"
        )
        if event.side == "SELL" and self.leader_reduction is not True and not holding_exit:
            raise SessionBlocked("exit_policy_requires_reduction_evidence")
        return edge


@dataclass(frozen=True, slots=True)
class AccountObservation:
    account: str
    observed_at: datetime
    cash: Decimal | None
    positions: tuple[tuple[str, Decimal], ...] | None
    open_order_ids: frozenset[str] | None
    cumulative_fees: Decimal | None
    complete: bool
    evidence_id: str

    def require_complete(self, account: str, *, now: datetime, max_age: int) -> None:
        if (
            self.account != account
            or self.complete is not True
            or not self.evidence_id
            or self.cash is None
            or self.positions is None
            or self.open_order_ids is None
            or self.cumulative_fees is None
        ):
            raise SessionBlocked("account_evidence_incomplete_or_mismatched")
        if not 0 <= (utc(now) - utc(self.observed_at)).total_seconds() <= max_age:
            raise SessionBlocked("account_evidence_stale_or_future")
        decimal_value(self.cash)
        decimal_value(self.cumulative_fees)
        if len(dict(self.positions)) != len(self.positions):
            raise SessionBlocked("duplicate_account_position")
        for _, quantity in self.positions:
            decimal_value(quantity)


@dataclass(frozen=True, slots=True)
class ConfirmedSessionFill:
    fill_id: str
    intent_id: str
    order_id: str
    token: str
    side: OrderSide
    price: Decimal
    shares: Decimal
    fee: Decimal
    confirmed_at: datetime

    def __post_init__(self) -> None:
        if not all((self.fill_id, self.intent_id, self.order_id, self.token)):
            raise SessionBlocked("missing_fill_identity")
        for value in (self.price, self.shares, self.fee):
            decimal_value(value)
        if self.side not in {"BUY", "SELL"} or not 0 < self.price <= 1 or self.shares <= 0:
            raise SessionBlocked("invalid_confirmed_fill")
        utc(self.confirmed_at)


@dataclass(frozen=True, slots=True)
class ExitAssessment:
    action: str
    shares: Decimal
    reason: str


def assess_exit(
    *,
    held_shares: Decimal,
    leader_reduction_fraction: Decimal | None,
    available_depth: Decimal | None,
    opened_at: datetime,
    now: datetime,
    market_expires_at: datetime,
    resolved: bool,
    authority: SessionAuthorization,
) -> ExitAssessment:
    """Pre-risk advice only; resolution never implies redemption authority."""
    decimal_value(held_shares)
    if held_shares == ZERO:
        return ExitAssessment("CLOSED", ZERO, "no_position")
    if resolved:
        return ExitAssessment("REDEEMABLE_REVIEW", ZERO, "separate_redemption_authority_required")
    if utc(now) >= utc(market_expires_at):
        return ExitAssessment("AWAIT_SETTLEMENT", ZERO, "market_expired_no_order_assumed")
    if held_shares <= authority.dust_shares:
        return ExitAssessment("DUST_INCIDENT", ZERO, "do_not_treat_dust_as_financial_closure")
    fraction = ZERO
    if leader_reduction_fraction is not None:
        fraction = decimal_value(leader_reduction_fraction)
        if fraction > 1:
            raise SessionBlocked("invalid_leader_reduction_fraction")
    elapsed = (utc(now) - utc(opened_at)).total_seconds()
    if elapsed < 0:
        raise SessionBlocked("position_clock_in_future")
    if elapsed >= authority.max_holding_seconds:
        fraction = Decimal("1")
    if fraction == ZERO:
        return ExitAssessment("HOLD", ZERO, "no_authorized_exit_trigger")
    if available_depth is None or decimal_value(available_depth) <= authority.dust_shares:
        return ExitAssessment("ILLIQUID_INCIDENT", ZERO, "exit_depth_unknown_or_insufficient")
    target = held_shares * fraction
    quantity = min(target, available_depth)
    if quantity <= authority.dust_shares:
        return ExitAssessment("DUST_INCIDENT", ZERO, "partial_exit_below_dust")
    return ExitAssessment(
        "REDUCE",
        quantity,
        "partial_depth" if quantity < target else "leader_reduction_or_holding_limit",
    )
