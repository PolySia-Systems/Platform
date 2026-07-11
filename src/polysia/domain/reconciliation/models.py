from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReconciliationSnapshot:
    venue_id: str
    captured_at: datetime
    open_order_count: int
    position_count: int


@dataclass(frozen=True, slots=True)
class ReconciliationDiscrepancy:
    discrepancy_id: str
    discrepancy_type: str
    message: str
    detected_at: datetime
    blocking: bool

