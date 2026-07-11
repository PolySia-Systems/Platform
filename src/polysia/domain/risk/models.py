from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class RiskRejectionReason(StrEnum):
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_MARKET_STATE = "INVALID_MARKET_STATE"
    STALE_DATA = "STALE_DATA"
    CONFIGURATION_BLOCKED = "CONFIGURATION_BLOCKED"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    approved_size: Decimal
    reason: str
    rejection_reason: RiskRejectionReason | None = None

