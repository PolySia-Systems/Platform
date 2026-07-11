from __future__ import annotations

from decimal import Decimal

from polysia.reconciliation.models import (
    OrderSnapshot,
    PositionSnapshot,
    ReconciliationEvent,
    ReconciliationEventType,
    ReconciliationInput,
    ReconciliationSeverity,
)


def detect_reconciliation_events(
    reconciliation_input: ReconciliationInput,
) -> tuple[ReconciliationEvent, ...]:
    events: list[ReconciliationEvent] = []
    events.extend(_detect_account_read_failures(reconciliation_input))
    events.extend(_detect_geoblock_failures(reconciliation_input))
    events.extend(_detect_open_order_mismatches(reconciliation_input))
    events.extend(_detect_position_mismatches(reconciliation_input))
    events.extend(_detect_stale_internal_state(reconciliation_input))
    return tuple(events)


def _detect_open_order_mismatches(
    reconciliation_input: ReconciliationInput,
) -> tuple[ReconciliationEvent, ...]:
    checked_at = reconciliation_input.checked_at
    internal_orders = _orders_by_id(reconciliation_input.internal.open_orders)
    actual_orders = _orders_by_id(reconciliation_input.actual.open_orders)
    events: list[ReconciliationEvent] = []

    if reconciliation_input.actual.open_orders_readable and len(internal_orders) != len(
        actual_orders
    ):
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.INTERNAL_EXTERNAL_COUNT_MISMATCH,
                severity=ReconciliationSeverity.BLOCKING,
                message="Internal and external open order counts do not match.",
                detected_at=checked_at,
                metadata={
                    "actual_open_order_count": len(actual_orders),
                    "internal_open_order_count": len(internal_orders),
                },
            )
        )

    missing_count = len(set(internal_orders) - set(actual_orders))
    if missing_count:
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.MISSING_OPEN_ORDER,
                severity=ReconciliationSeverity.BLOCKING,
                message="An internally expected open order is missing externally.",
                detected_at=checked_at,
                manual_intervention=True,
                metadata={"missing_open_order_count": missing_count},
            )
        )
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.MANUAL_ORDER_CANCEL_DETECTED,
                severity=ReconciliationSeverity.BLOCKING,
                message="Manual order intervention is suspected.",
                detected_at=checked_at,
                manual_intervention=True,
                metadata={"suspected_manual_order_count": missing_count},
            )
        )

    unexpected_count = len(set(actual_orders) - set(internal_orders))
    if unexpected_count:
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.UNEXPECTED_OPEN_ORDER,
                severity=ReconciliationSeverity.BLOCKING,
                message="An external open order is not known by internal state.",
                detected_at=checked_at,
                manual_intervention=True,
                metadata={"unexpected_open_order_count": unexpected_count},
            )
        )
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.UNKNOWN_EXTERNAL_ORDER,
                severity=ReconciliationSeverity.BLOCKING,
                message="Unknown external order was detected.",
                detected_at=checked_at,
                manual_intervention=True,
                metadata={"unknown_external_order_count": unexpected_count},
            )
        )

    return tuple(events)


def _detect_position_mismatches(
    reconciliation_input: ReconciliationInput,
) -> tuple[ReconciliationEvent, ...]:
    if not reconciliation_input.actual.positions_readable:
        return ()

    checked_at = reconciliation_input.checked_at
    internal_positions = _positions_by_token(reconciliation_input.internal.positions)
    actual_positions = _positions_by_token(reconciliation_input.actual.positions)
    events: list[ReconciliationEvent] = []
    closed_count = 0
    unexpected_fill_count = 0

    for token_id, internal_size in internal_positions.items():
        actual_size = actual_positions.get(token_id, Decimal("0"))
        if internal_size != Decimal("0") and actual_size == Decimal("0"):
            closed_count += 1
        elif actual_size != internal_size:
            unexpected_fill_count += 1

    for token_id, actual_size in actual_positions.items():
        if token_id not in internal_positions and actual_size != Decimal("0"):
            unexpected_fill_count += 1

    if closed_count:
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.MANUAL_POSITION_CLOSE_DETECTED,
                severity=ReconciliationSeverity.BLOCKING,
                message="A position expected internally appears closed externally.",
                detected_at=checked_at,
                manual_intervention=True,
                metadata={"closed_position_count": closed_count},
            )
        )
    if unexpected_fill_count:
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.UNEXPECTED_FILL_DETECTED,
                severity=ReconciliationSeverity.BLOCKING,
                message="External position state differs from internal expected state.",
                detected_at=checked_at,
                manual_intervention=True,
                metadata={"unexpected_position_mismatch_count": unexpected_fill_count},
            )
        )

    return tuple(events)


def _detect_account_read_failures(
    reconciliation_input: ReconciliationInput,
) -> tuple[ReconciliationEvent, ...]:
    actual = reconciliation_input.actual
    if (
        actual.account_readable
        and actual.open_orders_readable
        and actual.positions_readable
    ):
        return ()

    severity = (
        ReconciliationSeverity.BLOCKING
        if reconciliation_input.live_mode
        else ReconciliationSeverity.WARNING
    )
    events = [
        ReconciliationEvent(
            event_type=ReconciliationEventType.LIVE_STATE_UNAVAILABLE,
            severity=severity,
            message="Live account state is unavailable for reconciliation.",
            detected_at=reconciliation_input.checked_at,
            metadata={"live_mode": reconciliation_input.live_mode},
        )
    ]
    if not actual.account_readable:
        events.append(
            ReconciliationEvent(
                event_type=ReconciliationEventType.ACCOUNT_READ_FAILURE,
                severity=severity,
                message="Account state could not be read.",
                detected_at=reconciliation_input.checked_at,
                metadata={"error_type": actual.account_error_type or "unavailable"},
            )
        )
    return tuple(events)


def _detect_geoblock_failures(
    reconciliation_input: ReconciliationInput,
) -> tuple[ReconciliationEvent, ...]:
    actual = reconciliation_input.actual
    if actual.geoblock_readable is not False:
        return ()
    return (
        ReconciliationEvent(
            event_type=ReconciliationEventType.GEOBLOCK_CHECK_FAILURE,
            severity=ReconciliationSeverity.BLOCKING,
            message="Geoblock or account eligibility status could not be verified.",
            detected_at=reconciliation_input.checked_at,
            metadata={"error_type": actual.geoblock_error_type or "unavailable"},
        ),
    )


def _detect_stale_internal_state(
    reconciliation_input: ReconciliationInput,
) -> tuple[ReconciliationEvent, ...]:
    updated_at = reconciliation_input.internal.updated_at
    if updated_at is None:
        return ()
    state_age = reconciliation_input.checked_at - updated_at
    if state_age <= reconciliation_input.max_stale_age:
        return ()
    return (
        ReconciliationEvent(
            event_type=ReconciliationEventType.STALE_INTERNAL_STATE,
            severity=ReconciliationSeverity.BLOCKING,
            message="Internal expected state is stale.",
            detected_at=reconciliation_input.checked_at,
            metadata={"state_age_seconds": int(state_age.total_seconds())},
        ),
    )


def _orders_by_id(orders: tuple[OrderSnapshot, ...]) -> dict[str, OrderSnapshot]:
    return {order.order_id: order for order in orders if order.order_id}


def _positions_by_token(positions: tuple[PositionSnapshot, ...]) -> dict[str, Decimal]:
    return {position.token_id: position.size for position in positions if position.token_id}
