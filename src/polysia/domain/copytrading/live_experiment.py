from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")

EXPECTED_CANDIDATE_COUNT = 102
ENTRY_OFFSET = Decimal("0.05")
TAKE_PROFIT_RETURN = Decimal("0.10")
MAXIMUM_ENTRY_DEBIT = Decimal("5.00")
MAXIMUM_ACCOUNT_BALANCE = Decimal("10.00")
MAXIMUM_TOTAL_ENTRY_ATTEMPTS = 3
MAXIMUM_COMPLETED_LIVE_CYCLES = 3
MAXIMUM_SIGNAL_AGE = timedelta(seconds=10)
MINIMUM_SECONDS_TO_END_AT_SIGNAL = 420
ENTRY_CANCEL_BEFORE_END_SECONDS = 315
NO_NEW_ENTRY_FINAL_SECONDS = 300
ENTRY_TTL = timedelta(seconds=90)
SDK_GTD_MINIMUM_BUFFER = timedelta(seconds=180)
SDK_GTD_CLOCK_SAFETY_BUFFER = timedelta(seconds=5)


class CopyExperimentState(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    BASELINING = "BASELINING"
    MONITORING = "MONITORING"
    ENTRY_SUBMITTING = "ENTRY_SUBMITTING"
    ENTRY_PENDING = "ENTRY_PENDING"
    POSITION_OPEN = "POSITION_OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    AWAITING_RESOLUTION = "AWAITING_RESOLUTION"
    REDEEMABLE = "REDEEMABLE"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"
    FAILED_SAFE = "FAILED_SAFE"


TERMINAL_STATES = frozenset(
    {
        CopyExperimentState.REDEEMABLE,
        CopyExperimentState.FINALIZED,
        CopyExperimentState.FAILED_SAFE,
    }
)


@dataclass(frozen=True, slots=True, repr=False)
class CandidateBank:
    """Protected leader bank whose public representation never contains addresses."""

    aliases_and_addresses: tuple[tuple[str, str], ...]
    source_digest: str
    raw_address_count: int

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(alias for alias, _ in self.aliases_and_addresses)

    def as_protected_mapping(self) -> dict[str, str]:
        return dict(self.aliases_and_addresses)

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "alias_count": len(self.aliases_and_addresses),
            "first_alias": self.aliases[0],
            "last_alias": self.aliases[-1],
            "raw_address_count": self.raw_address_count,
            "source_digest": self.source_digest,
            "unique_address_count": len(self.aliases_and_addresses),
        }


@dataclass(frozen=True, slots=True)
class EntryQuote:
    raw_price: Decimal
    price: Decimal
    quantity: Decimal
    expected_fee: Decimal
    maximum_debit: Decimal
    cancel_at: datetime
    venue_expiration: int


@dataclass(frozen=True, slots=True)
class CopyExperimentSnapshot:
    state: CopyExperimentState
    total_entry_attempts: int
    completed_live_cycles: int
    signal_acceptance_open: bool
    active_leader_alias: str | None = None
    active_event_id: str | None = None
    active_market_id: str | None = None
    active_market_slug: str | None = None
    active_token_id: str | None = None
    entry_order_id: str | None = None
    exit_order_id: str | None = None
    entry_price: Decimal | None = None
    entry_quantity: Decimal | None = None
    entry_fee: Decimal = Decimal("0")
    entry_cancel_at: datetime | None = None
    fill_price: Decimal | None = None
    position_size: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not 0 <= self.total_entry_attempts <= MAXIMUM_TOTAL_ENTRY_ATTEMPTS:
            raise ValueError("total entry attempts are outside the owner-authorized range")
        if not 0 <= self.completed_live_cycles <= MAXIMUM_COMPLETED_LIVE_CYCLES:
            raise ValueError("completed live cycles are outside the owner-authorized range")
        if self.position_size < 0:
            raise ValueError("position size must not be negative")
        if self.entry_fee < 0:
            raise ValueError("entry fee must not be negative")
        if self.entry_cancel_at is not None:
            _require_utc("entry_cancel_at", self.entry_cancel_at)
        if self.entry_price is not None and not Decimal("0") < self.entry_price < Decimal("1"):
            raise ValueError("entry price must be within (0, 1)")
        if self.entry_quantity is not None and self.entry_quantity <= 0:
            raise ValueError("entry quantity must be positive")
        if self.fill_price is not None and not Decimal("0") < self.fill_price < Decimal("1"):
            raise ValueError("fill price must be within (0, 1)")
        if self.entry_order_id is not None and self.position_size > 0:
            raise ValueError("a pending entry and follower position cannot coexist")
        if self.exit_order_id is not None and self.position_size <= 0:
            raise ValueError("an exit order requires a confirmed follower position")
        if self.state is CopyExperimentState.ENTRY_PENDING and self.entry_order_id is None:
            raise ValueError("ENTRY_PENDING requires an entry order")
        if self.state in {
            CopyExperimentState.POSITION_OPEN,
            CopyExperimentState.EXIT_PENDING,
            CopyExperimentState.AWAITING_RESOLUTION,
        } and self.position_size <= 0:
            raise ValueError(f"{self.state} requires a positive position")
        if self.state is CopyExperimentState.EXIT_PENDING and self.exit_order_id is None:
            raise ValueError("EXIT_PENDING requires an exit order")
        if (
            self.total_entry_attempts >= MAXIMUM_TOTAL_ENTRY_ATTEMPTS
            or self.completed_live_cycles >= MAXIMUM_COMPLETED_LIVE_CYCLES
        ) and self.signal_acceptance_open:
            raise ValueError("signal acceptance must close at an experiment limit")


def load_candidate_bank(text: str) -> CandidateBank:
    """Extract, normalize, and deduplicate the exact protected candidate bank."""

    raw_addresses = [
        line.strip()
        for line in text.splitlines()
        if _WALLET_PATTERN.fullmatch(line.strip())
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for address in raw_addresses:
        normalized = address.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    if len(unique) != EXPECTED_CANDIDATE_COUNT:
        raise ValueError(
            f"protected candidate bank must contain exactly {EXPECTED_CANDIDATE_COUNT} "
            f"unique valid addresses; found {len(unique)}"
        )
    aliases_and_addresses = tuple(
        (f"candidate-{index:03d}", address)
        for index, address in enumerate(unique, start=1)
    )
    digest = hashlib.sha256("\n".join(unique).encode()).hexdigest()
    return CandidateBank(
        aliases_and_addresses=aliases_and_addresses,
        source_digest=f"sha256:{digest}",
        raw_address_count=len(raw_addresses),
    )


def calculate_entry_quote(
    *,
    leader_fill_price: Decimal,
    minimum_order_size: Decimal,
    tick_size: Decimal,
    best_ask: Decimal,
    expected_fee: Decimal,
    now: datetime,
    market_end: datetime,
) -> EntryQuote:
    """Build the only permitted post-only GTD entry quote."""

    _require_utc("now", now)
    _require_utc("market_end", market_end)
    if not Decimal("0") < leader_fill_price < Decimal("1"):
        raise ValueError("leader fill price must be within (0, 1)")
    if minimum_order_size <= 0:
        raise ValueError("minimum order size must be positive")
    if not Decimal("0") < tick_size < Decimal("1"):
        raise ValueError("tick size must be within (0, 1)")
    if not Decimal("0") < best_ask <= Decimal("1"):
        raise ValueError("best ask must be within (0, 1]")
    if expected_fee < 0:
        raise ValueError("expected fee must not be negative")
    remaining = (market_end - now).total_seconds()
    if remaining < MINIMUM_SECONDS_TO_END_AT_SIGNAL:
        raise ValueError("fewer than seven minutes remain before market end")

    raw_price = leader_fill_price * (Decimal("1") - ENTRY_OFFSET)
    price = round_down_to_tick(raw_price, tick_size)
    if price <= 0:
        raise ValueError("entry offset rounds below the venue price range")
    if price >= best_ask:
        raise ValueError("entry would cross the spread and violate post-only behavior")

    maximum_debit = (price * minimum_order_size) + expected_fee
    if maximum_debit > MAXIMUM_ENTRY_DEBIT:
        raise ValueError("minimum valid order exceeds the 5.00 USD entry-debit cap")

    cancel_at = min(
        now + ENTRY_TTL,
        market_end - timedelta(seconds=ENTRY_CANCEL_BEFORE_END_SECONDS),
    )
    if cancel_at <= now:
        raise ValueError("entry cancellation deadline is not safely representable")
    venue_expires_at = now + SDK_GTD_MINIMUM_BUFFER + SDK_GTD_CLOCK_SAFETY_BUFFER
    final_entry_cutoff = market_end - timedelta(
        seconds=ENTRY_CANCEL_BEFORE_END_SECONDS
    )
    if venue_expires_at > final_entry_cutoff:
        raise ValueError(
            "SDK GTD backstop cannot expire before the final entry cutoff"
        )
    venue_expiration = int(venue_expires_at.timestamp())
    return EntryQuote(
        raw_price=raw_price,
        price=price,
        quantity=minimum_order_size,
        expected_fee=expected_fee,
        maximum_debit=maximum_debit,
        cancel_at=cancel_at,
        venue_expiration=venue_expiration,
    )


def calculate_take_profit_price(
    average_fill_price: Decimal,
    *,
    tick_size: Decimal,
) -> Decimal:
    if not Decimal("0") < average_fill_price < Decimal("1"):
        raise ValueError("average fill price must be within (0, 1)")
    if not Decimal("0") < tick_size < Decimal("1"):
        raise ValueError("tick size must be within (0, 1)")
    target = round_up_to_tick(
        average_fill_price * (Decimal("1") + TAKE_PROFIT_RETURN),
        tick_size,
    )
    maximum_price = Decimal("1") - tick_size
    if target > maximum_price:
        raise ValueError("10% take-profit target exceeds the highest valid sell price")
    return target


def calculate_realized_pnl(
    *,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    entry_fee: Decimal,
    exit_fee: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return gross and fee-adjusted PnL for one long outcome-token cycle."""

    if not Decimal("0") <= entry_price <= Decimal("1"):
        raise ValueError("entry price must be within [0, 1]")
    if not Decimal("0") <= exit_price <= Decimal("1"):
        raise ValueError("exit price must be within [0, 1]")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if entry_fee < 0 or exit_fee < 0:
        raise ValueError("fees must not be negative")
    gross = (exit_price - entry_price) * quantity
    return gross, gross - entry_fee - exit_fee


def signal_is_fresh(
    *,
    executed_at: datetime,
    observed_at: datetime,
    market_end: datetime,
) -> bool:
    for name, value in (
        ("executed_at", executed_at),
        ("observed_at", observed_at),
        ("market_end", market_end),
    ):
        _require_utc(name, value)
    age = observed_at - executed_at
    return (
        timedelta(0) <= age <= MAXIMUM_SIGNAL_AGE
        and (market_end - observed_at).total_seconds() >= MINIMUM_SECONDS_TO_END_AT_SIGNAL
    )


def round_down_to_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    if tick_size <= 0:
        raise ValueError("tick size must be positive")
    return (value / tick_size).to_integral_value(rounding=ROUND_FLOOR) * tick_size


def round_up_to_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    if tick_size <= 0:
        raise ValueError("tick size must be positive")
    return (value / tick_size).to_integral_value(rounding=ROUND_CEILING) * tick_size


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = [
    "CandidateBank",
    "CopyExperimentSnapshot",
    "CopyExperimentState",
    "ENTRY_CANCEL_BEFORE_END_SECONDS",
    "ENTRY_OFFSET",
    "ENTRY_TTL",
    "EntryQuote",
    "EXPECTED_CANDIDATE_COUNT",
    "MAXIMUM_ACCOUNT_BALANCE",
    "MAXIMUM_COMPLETED_LIVE_CYCLES",
    "MAXIMUM_ENTRY_DEBIT",
    "MAXIMUM_SIGNAL_AGE",
    "MAXIMUM_TOTAL_ENTRY_ATTEMPTS",
    "MINIMUM_SECONDS_TO_END_AT_SIGNAL",
    "NO_NEW_ENTRY_FINAL_SECONDS",
    "TAKE_PROFIT_RETURN",
    "TERMINAL_STATES",
    "calculate_entry_quote",
    "calculate_realized_pnl",
    "calculate_take_profit_price",
    "load_candidate_bank",
    "round_down_to_tick",
    "round_up_to_tick",
    "signal_is_fresh",
]
