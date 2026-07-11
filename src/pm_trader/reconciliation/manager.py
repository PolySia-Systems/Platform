from __future__ import annotations

from pm_trader.reconciliation.detectors import detect_reconciliation_events
from pm_trader.reconciliation.models import (
    ReconciliationEvent,
    ReconciliationInput,
    ReconciliationResult,
    ReconciliationSeverity,
    ReconciliationStatus,
)
from pm_trader.reconciliation.safety_pause import SafetyPause


class ReconciliationManager:
    """Read-only reconciliation coordinator for manual-intervention detection."""

    def __init__(self, *, safety_pause: SafetyPause | None = None) -> None:
        self._safety_pause = safety_pause

    def reconcile(self, reconciliation_input: ReconciliationInput) -> ReconciliationResult:
        events = detect_reconciliation_events(reconciliation_input)
        manual_intervention_detected = any(event.manual_intervention for event in events)
        blocking_reasons = tuple(
            event.message
            for event in events
            if _is_blocking(event, live_mode=reconciliation_input.live_mode)
        )
        warnings = tuple(
            event.message
            for event in events
            if not _is_blocking(event, live_mode=reconciliation_input.live_mode)
        )
        status = _status_from_events(blocking_reasons, warnings)
        trading_should_pause = status == ReconciliationStatus.BLOCKED
        requires_manual_acknowledgement = manual_intervention_detected or trading_should_pause
        safety_pause_activated = False

        if trading_should_pause and self._safety_pause is not None:
            self._safety_pause.activate(
                "reconciliation blocked: manual intervention or account mismatch detected"
            )
            safety_pause_activated = True

        actual_open_order_count: int | None
        if reconciliation_input.actual.open_orders_readable:
            actual_open_order_count = len(reconciliation_input.actual.open_orders)
        else:
            actual_open_order_count = None

        return ReconciliationResult(
            actual_open_order_count=actual_open_order_count,
            blocking_reasons=blocking_reasons,
            checked_at=reconciliation_input.checked_at,
            detected_events=events,
            internal_open_order_count=len(reconciliation_input.internal.open_orders),
            last_successful_account_read_at=(
                reconciliation_input.internal.last_successful_account_read_at
            ),
            manual_intervention_detected=manual_intervention_detected,
            requires_manual_acknowledgement=requires_manual_acknowledgement,
            safety_pause_activated=safety_pause_activated,
            status=status,
            trading_should_pause=trading_should_pause,
            warnings=warnings,
        )


def _is_blocking(event: ReconciliationEvent, *, live_mode: bool) -> bool:
    if event.severity == ReconciliationSeverity.BLOCKING:
        return True
    return live_mode and event.severity == ReconciliationSeverity.WARNING


def _status_from_events(
    blocking_reasons: tuple[str, ...],
    warnings: tuple[str, ...],
) -> ReconciliationStatus:
    if blocking_reasons:
        return ReconciliationStatus.BLOCKED
    if warnings:
        return ReconciliationStatus.WARNING
    return ReconciliationStatus.READY
