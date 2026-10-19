from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Position:
    instrument_id: str
    size: Decimal
    average_price: Decimal
    realized_pnl: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class CashBalance:
    currency: str
    available: Decimal
    reserved: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class AccountPosition:
    """Observed current inventory, independent from a venue's historical volume."""

    token_id: str
    condition_id: str
    size: Decimal
    avg_price: Decimal | None
    current_value: Decimal | None
    cur_price: Decimal | None
    outcome: str | None
    redeemable: bool | None
    mergeable: bool | None
    end_date: date | None

