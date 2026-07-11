from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ReconciliationStatus(StrEnum):
    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"


class ReconciliationSeverity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


class ReconciliationEventType(StrEnum):
    MANUAL_ORDER_CANCEL_DETECTED = "MANUAL_ORDER_CANCEL_DETECTED"
    MANUAL_POSITION_CLOSE_DETECTED = "MANUAL_POSITION_CLOSE_DETECTED"
    UNEXPECTED_FILL_DETECTED = "UNEXPECTED_FILL_DETECTED"
    MISSING_OPEN_ORDER = "MISSING_OPEN_ORDER"
    UNEXPECTED_OPEN_ORDER = "UNEXPECTED_OPEN_ORDER"
    STALE_INTERNAL_STATE = "STALE_INTERNAL_STATE"
    ACCOUNT_READ_FAILURE = "ACCOUNT_READ_FAILURE"
    GEOBLOCK_CHECK_FAILURE = "GEOBLOCK_CHECK_FAILURE"
    LIVE_STATE_UNAVAILABLE = "LIVE_STATE_UNAVAILABLE"
    INTERNAL_EXTERNAL_COUNT_MISMATCH = "INTERNAL_EXTERNAL_COUNT_MISMATCH"
    UNKNOWN_EXTERNAL_ORDER = "UNKNOWN_EXTERNAL_ORDER"


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    order_id: str
    token_id: str | None = None
    status: str | None = None
    created_by_system: bool = True
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    token_id: str
    size: Decimal
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FillSnapshot:
    fill_id: str
    order_id: str | None = None
    token_id: str | None = None
    size: Decimal | None = None
    recorded_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class InternalExpectedState:
    open_orders: tuple[OrderSnapshot, ...] = ()
    positions: tuple[PositionSnapshot, ...] = ()
    last_known_order_states: tuple[OrderSnapshot, ...] = ()
    last_known_fills: tuple[FillSnapshot, ...] = ()
    last_successful_account_read_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActualAccountState:
    open_orders: tuple[OrderSnapshot, ...] = ()
    positions: tuple[PositionSnapshot, ...] = ()
    account_readable: bool = True
    open_orders_readable: bool = True
    positions_readable: bool = True
    geoblock_readable: bool | None = True
    geoblock_status: str | None = None
    account_error_type: str | None = None
    geoblock_error_type: str | None = None
    read_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationInput:
    internal: InternalExpectedState
    actual: ActualAccountState
    checked_at: datetime
    max_stale_age: timedelta = timedelta(minutes=5)
    live_mode: bool = False


@dataclass(frozen=True, slots=True)
class ReconciliationEvent:
    event_type: ReconciliationEventType
    severity: ReconciliationSeverity
    message: str
    detected_at: datetime
    manual_intervention: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "detected_at": self.detected_at.isoformat(),
            "event_type": self.event_type.value,
            "manual_intervention": self.manual_intervention,
            "message": self.message,
            "metadata": self.metadata,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: ReconciliationStatus
    manual_intervention_detected: bool
    detected_events: tuple[ReconciliationEvent, ...]
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    internal_open_order_count: int
    actual_open_order_count: int | None
    checked_at: datetime
    last_successful_account_read_at: datetime | None
    trading_should_pause: bool
    requires_manual_acknowledgement: bool
    safety_pause_activated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "actual_open_order_count": self.actual_open_order_count,
            "blocking_reasons": list(self.blocking_reasons),
            "checked_at": self.checked_at.isoformat(),
            "detected_events": [event.to_dict() for event in self.detected_events],
            "internal_open_order_count": self.internal_open_order_count,
            "last_successful_account_read_at": (
                None
                if self.last_successful_account_read_at is None
                else self.last_successful_account_read_at.isoformat()
            ),
            "manual_intervention_detected": self.manual_intervention_detected,
            "requires_manual_acknowledgement": self.requires_manual_acknowledgement,
            "safety_pause_activated": self.safety_pause_activated,
            "status": self.status.value,
            "trading_should_pause": self.trading_should_pause,
            "warnings": list(self.warnings),
        }
