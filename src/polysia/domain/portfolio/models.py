from dataclasses import dataclass
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

