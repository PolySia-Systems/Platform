from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    event_id: str
    event_type: str
    instrument_id: str | None
    amount: Decimal
    currency: str
    occurred_at: datetime
    order_id: str | None = None
    fill_id: str | None = None

