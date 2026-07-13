from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from polysia.storage.db import SQLiteDatabase, transaction

ReconciliationLevel = Literal["ready", "warning", "blocked"]
FeeStatus = Literal["confirmed", "unknown"]
Clock = Callable[[], datetime]

_TOLERANCE = Decimal("0.000001")
_OPEN_ORDER_STATES = frozenset({"ACTIVE", "LIVE", "OPEN"})
_FILLED_ORDER_STATES = frozenset({"FILLED", "MATCHED"})
_CANCELLED_ORDER_STATES = frozenset({"CANCELED", "CANCELLED", "EXPIRED"})
_REJECTED_ORDER_STATES = frozenset({"FAILED", "REJECTED"})
_RECONCILABLE_AUTHORIZATION_STATES = frozenset(
    {
        "ENTRY_FILLED_EXIT_OPEN",
        "ENTRY_FILLED_EXIT_PARTIAL",
        "COMPLETED_ROUND_TRIP",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class LiveRoundTripReconciliationError(RuntimeError):
    """Raised when persisted state cannot support trustworthy reconciliation."""


@dataclass(frozen=True, slots=True)
class ObservedExitOrder:
    order_id: str
    token_id: str
    side: str
    price: Decimal
    original_size: Decimal
    matched_size: Decimal
    status: str


@dataclass(frozen=True, slots=True)
class ObservedExitFill:
    fill_id: str
    order_id: str
    token_id: str
    side: str
    price: Decimal
    size: Decimal
    status: str
    liquidity_role: str
    occurred_at: datetime
    fee: Decimal | None = None
    fee_source: str | None = None

    @property
    def fee_status(self) -> FeeStatus:
        return "confirmed" if self.fee is not None else "unknown"


@dataclass(frozen=True, slots=True)
class LiveRoundTripVenueSnapshot:
    order: ObservedExitOrder | None
    fills: tuple[ObservedExitFill, ...]
    position_size: Decimal
    account_balances_readable: bool
    read_at: datetime
    order_absence_confirmed: bool = False


class LiveRoundTripVenueReader(Protocol):
    async def read_exit_state(
        self,
        *,
        order_id: str,
        token_id: str,
    ) -> LiveRoundTripVenueSnapshot:
        """Read one exit lifecycle without submitting, cancelling, or replacing."""


@dataclass(frozen=True, slots=True)
class LiveRoundTripReconciliationConfig:
    database_path: Path
    run_id: str
    authorization_id: str = "POLYSIA-LIVE-004"


@dataclass(frozen=True, slots=True)
class LiveRoundTripReconciliationReport:
    run_id: str
    authorization_id: str
    classification: str
    status: ReconciliationLevel
    observed_order_status: str | None
    confirmed_exit_size: Decimal
    expected_remaining_position: Decimal
    observed_position_size: Decimal
    weighted_average_exit_price: Decimal | None
    gross_exit_proceeds: Decimal
    allocated_entry_cost: Decimal
    exit_fee: Decimal | None
    fee_status: FeeStatus
    net_realized_pnl: Decimal | None
    fill_count: int
    new_fill_count: int
    new_ledger_event_count: int
    duplicate_fill_count: int
    observation_recorded: bool
    observation_id: str
    warnings: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    read_only_venue_statement: str = (
        "Venue access was read-only; no order submit, cancel, replace, or retry method exists "
        "on the reconciliation port."
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "allocated_entry_cost": str(self.allocated_entry_cost),
            "authorization_id": self.authorization_id,
            "blocking_reasons": list(self.blocking_reasons),
            "classification": self.classification,
            "confirmed_exit_size": str(self.confirmed_exit_size),
            "duplicate_fill_count": self.duplicate_fill_count,
            "exit_fee": None if self.exit_fee is None else str(self.exit_fee),
            "expected_remaining_position": str(self.expected_remaining_position),
            "fee_status": self.fee_status,
            "fill_count": self.fill_count,
            "gross_exit_proceeds": str(self.gross_exit_proceeds),
            "net_realized_pnl": (
                None if self.net_realized_pnl is None else str(self.net_realized_pnl)
            ),
            "new_fill_count": self.new_fill_count,
            "new_ledger_event_count": self.new_ledger_event_count,
            "observation_id": self.observation_id,
            "observation_recorded": self.observation_recorded,
            "observed_order_status": self.observed_order_status,
            "observed_position_size": str(self.observed_position_size),
            "read_only_venue_statement": self.read_only_venue_statement,
            "run_id": self.run_id,
            "status": self.status,
            "warnings": list(self.warnings),
            "weighted_average_exit_price": (
                None
                if self.weighted_average_exit_price is None
                else str(self.weighted_average_exit_price)
            ),
        }


@dataclass(frozen=True, slots=True)
class _InternalRoundTripState:
    run_id: str
    authorization_id: str
    authorization_state: str
    strategy_id: str
    market_id: str
    token_id: str
    entry_order_id: str
    exit_order_id: str
    exit_client_order_id: str
    entry_size: Decimal
    entry_price: Decimal
    entry_fee: Decimal | None
    exit_size: Decimal
    current_realized_pnl: Decimal
    persisted_exit_fills: tuple[ObservedExitFill, ...]


async def reconcile_live_round_trip(
    config: LiveRoundTripReconciliationConfig,
    *,
    venue_reader: LiveRoundTripVenueReader,
    clock: Clock = utc_now,
) -> LiveRoundTripReconciliationReport:
    """Reconcile one persisted live round trip against read-only venue state."""

    with SQLiteDatabase(config.database_path) as database:
        state = _load_internal_state(
            database.connection,
            run_id=config.run_id,
            authorization_id=config.authorization_id,
        )
        snapshot = await venue_reader.read_exit_state(
            order_id=state.exit_order_id,
            token_id=state.token_id,
        )
        report, observed_fills = _build_report(state, snapshot)
        persisted = _persist_report(
            database.connection,
            state=state,
            snapshot=snapshot,
            report=report,
            fills=observed_fills,
            persisted_at=clock(),
        )
    return replace(
        report,
        new_fill_count=persisted[0],
        new_ledger_event_count=persisted[1],
        observation_recorded=persisted[2],
    )


def _load_internal_state(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    authorization_id: str,
) -> _InternalRoundTripState:
    authorization = connection.execute(
        "SELECT * FROM live_entry_attempts WHERE authorization_id = ?",
        (authorization_id,),
    ).fetchone()
    if authorization is None or str(authorization["run_id"]) != run_id:
        raise LiveRoundTripReconciliationError(
            "the persistent authorization does not identify the requested run"
        )
    authorization_state = str(authorization["state"])
    if authorization_state not in _RECONCILABLE_AUTHORIZATION_STATES:
        raise LiveRoundTripReconciliationError(
            "the persistent authorization has not reached a reconcilable exit state"
        )

    checkpoints = {
        str(row["phase"]): row
        for row in connection.execute(
            "SELECT * FROM live_order_checkpoints WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    }
    required_phases = {
        "ENTRY_RESPONSE",
        "ENTRY_FILL_CONFIRMED",
        "ENTRY_POSITION_RECONCILED",
        "EXIT_RESPONSE",
    }
    missing = sorted(required_phases - checkpoints.keys())
    if missing:
        raise LiveRoundTripReconciliationError(
            f"required live checkpoints are missing: {', '.join(missing)}"
        )

    entry_order_id = _required_text(checkpoints["ENTRY_FILL_CONFIRMED"]["venue_order_id"])
    exit_order_id = _required_text(checkpoints["EXIT_RESPONSE"]["venue_order_id"])
    exit_client_order_id = _required_text(checkpoints["EXIT_RESPONSE"]["client_order_id"])
    entry_fill = connection.execute(
        "SELECT * FROM fills WHERE fill_id = ?",
        (f"{run_id}:entry",),
    ).fetchone()
    if entry_fill is None:
        raise LiveRoundTripReconciliationError("the confirmed entry fill is not persisted")
    exit_order = connection.execute(
        "SELECT * FROM orders WHERE order_id = ?",
        (exit_order_id,),
    ).fetchone()
    if exit_order is None:
        raise LiveRoundTripReconciliationError("the persisted exit order is missing")
    position = connection.execute(
        "SELECT * FROM positions WHERE token_id = ?",
        (str(entry_fill["token_id"]),),
    ).fetchone()
    if position is None:
        raise LiveRoundTripReconciliationError("the persisted entry position is missing")

    persisted_fills = tuple(
        _stored_fill_to_observation(row)
        for row in connection.execute(
            "SELECT * FROM fills WHERE fill_id LIKE ? ORDER BY created_at, fill_id",
            (f"{run_id}:exit:%",),
        ).fetchall()
    )
    return _InternalRoundTripState(
        run_id=run_id,
        authorization_id=authorization_id,
        authorization_state=authorization_state,
        strategy_id=str(authorization["strategy_id"]),
        market_id=str(authorization["market_id"]),
        token_id=str(entry_fill["token_id"]),
        entry_order_id=entry_order_id,
        exit_order_id=exit_order_id,
        exit_client_order_id=exit_client_order_id,
        entry_size=Decimal(str(entry_fill["size"])),
        entry_price=Decimal(str(entry_fill["price"])),
        entry_fee=(
            None if entry_fill["fee"] is None else Decimal(str(entry_fill["fee"]))
        ),
        exit_size=Decimal(str(exit_order["size"])),
        current_realized_pnl=Decimal(str(position["realized_pnl"])),
        persisted_exit_fills=persisted_fills,
    )


def _build_report(
    state: _InternalRoundTripState,
    snapshot: LiveRoundTripVenueSnapshot,
) -> tuple[LiveRoundTripReconciliationReport, tuple[ObservedExitFill, ...]]:
    warnings: list[str] = []
    blocking: list[str] = []
    merged, duplicate_count = _merge_fills(
        state.persisted_exit_fills,
        snapshot.fills,
        blocking=blocking,
    )
    valid_fills = tuple(
        sorted(
            (fill for fill in merged if fill.status.upper() == "CONFIRMED"),
            key=lambda fill: (fill.occurred_at, fill.fill_id),
        )
    )
    for fill in merged:
        if fill.status.upper() != "CONFIRMED":
            warnings.append(f"fill {fill.fill_id} is not confirmed and was not applied")
    _validate_fills(state, valid_fills, blocking=blocking)

    confirmed_size = sum((fill.size for fill in valid_fills), Decimal("0"))
    expected_remaining = max(Decimal("0"), state.entry_size - confirmed_size)
    if confirmed_size - state.entry_size > _TOLERANCE:
        blocking.append("confirmed exit fills exceed the confirmed entry position")
    if abs(snapshot.position_size - expected_remaining) > _TOLERANCE:
        blocking.append("venue position does not match confirmed exit fill evidence")
    if not snapshot.account_balances_readable:
        blocking.append("required authenticated balance reads did not complete")

    fully_filled = abs(confirmed_size - state.entry_size) <= _TOLERANCE
    order_status = snapshot.order.status.upper() if snapshot.order is not None else None
    if snapshot.order is None:
        if (
            snapshot.order_absence_confirmed
            and fully_filled
            and abs(snapshot.position_size) <= _TOLERANCE
        ):
            order_status = "TERMINAL_UNAVAILABLE"
            warnings.append(
                "terminal order detail is unavailable; confirmed fills and zero position "
                "prove closure"
            )
        else:
            blocking.append("the venue exit order could not be identified")
    else:
        _validate_order(state, snapshot.order, confirmed_size, blocking, warnings)

    classification, level = _classify(
        confirmed_size=confirmed_size,
        entry_size=state.entry_size,
        order_status=order_status,
        blocking=blocking,
        warnings=warnings,
    )
    gross_proceeds = sum((fill.price * fill.size for fill in valid_fills), Decimal("0"))
    weighted_average = (
        None if confirmed_size == 0 else gross_proceeds / confirmed_size
    )
    allocated_entry_fee = (
        None
        if state.entry_fee is None
        else state.entry_fee * confirmed_size / state.entry_size
    )
    allocated_entry_cost = (state.entry_price * confirmed_size) + (
        allocated_entry_fee or Decimal("0")
    )
    all_fees_known = all(fill.fee is not None for fill in valid_fills)
    exit_fee = (
        sum((fill.fee or Decimal("0") for fill in valid_fills), Decimal("0"))
        if all_fees_known
        else None
    )
    fee_status: FeeStatus = (
        "confirmed" if all_fees_known and state.entry_fee is not None else "unknown"
    )
    net_pnl = (
        gross_proceeds - allocated_entry_cost - exit_fee
        if fee_status == "confirmed" and exit_fee is not None
        else None
    )
    if confirmed_size > 0 and fee_status == "unknown":
        warnings.append("realized P&L remains unknown because confirmed fee data is incomplete")
        if level == "ready":
            level = "warning"

    observation_id = _observation_id(
        state=state,
        snapshot=snapshot,
        fills=valid_fills,
        classification=classification,
        status=level,
    )
    return (
        LiveRoundTripReconciliationReport(
            run_id=state.run_id,
            authorization_id=state.authorization_id,
            classification=classification,
            status=level,
            observed_order_status=order_status,
            confirmed_exit_size=confirmed_size,
            expected_remaining_position=expected_remaining,
            observed_position_size=snapshot.position_size,
            weighted_average_exit_price=weighted_average,
            gross_exit_proceeds=gross_proceeds,
            allocated_entry_cost=allocated_entry_cost,
            exit_fee=exit_fee,
            fee_status=fee_status,
            net_realized_pnl=net_pnl,
            fill_count=len(valid_fills),
            new_fill_count=0,
            new_ledger_event_count=0,
            duplicate_fill_count=duplicate_count,
            observation_recorded=False,
            observation_id=observation_id,
            warnings=tuple(dict.fromkeys(warnings)),
            blocking_reasons=tuple(dict.fromkeys(blocking)),
        ),
        valid_fills,
    )


def _merge_fills(
    persisted: tuple[ObservedExitFill, ...],
    observed: tuple[ObservedExitFill, ...],
    *,
    blocking: list[str],
) -> tuple[tuple[ObservedExitFill, ...], int]:
    by_id: dict[str, ObservedExitFill] = {}
    duplicate_count = 0
    for fill in (*persisted, *observed):
        existing = by_id.get(fill.fill_id)
        if existing is None:
            by_id[fill.fill_id] = fill
            continue
        duplicate_count += 1
        if _fill_identity(existing) != _fill_identity(fill):
            blocking.append(f"conflicting duplicate fill identifier: {fill.fill_id}")
            continue
        if existing.fee is None and fill.fee is not None:
            by_id[fill.fill_id] = fill
    return tuple(by_id.values()), duplicate_count


def _validate_fills(
    state: _InternalRoundTripState,
    fills: tuple[ObservedExitFill, ...],
    *,
    blocking: list[str],
) -> None:
    for fill in fills:
        if fill.order_id != state.exit_order_id:
            blocking.append(f"fill {fill.fill_id} does not belong to the persisted exit order")
        if fill.token_id != state.token_id:
            blocking.append(f"fill {fill.fill_id} does not belong to the persisted token")
        if fill.side.upper() != "SELL":
            blocking.append(f"fill {fill.fill_id} is not an exit sell")
        if fill.size <= 0:
            blocking.append(f"fill {fill.fill_id} has a non-positive quantity")
        if fill.price <= 0 or fill.price > 1:
            blocking.append(f"fill {fill.fill_id} has an invalid prediction-market price")


def _validate_order(
    state: _InternalRoundTripState,
    order: ObservedExitOrder,
    confirmed_size: Decimal,
    blocking: list[str],
    warnings: list[str],
) -> None:
    if order.order_id != state.exit_order_id:
        blocking.append("venue order identifier does not match the persisted exit")
    if order.token_id != state.token_id or order.side.upper() != "SELL":
        blocking.append("venue order token or side does not match the persisted exit")
    if abs(order.original_size - state.exit_size) > _TOLERANCE:
        blocking.append("venue exit quantity does not match the persisted exit quantity")
    if order.matched_size - confirmed_size > _TOLERANCE:
        blocking.append("venue order matched size exceeds confirmed trade evidence")
    elif confirmed_size - order.matched_size > _TOLERANCE:
        warnings.append("confirmed fill was observed before the venue order status caught up")


def _classify(
    *,
    confirmed_size: Decimal,
    entry_size: Decimal,
    order_status: str | None,
    blocking: list[str],
    warnings: list[str],
) -> tuple[str, ReconciliationLevel]:
    if blocking:
        return "RECONCILIATION_BLOCKED", "blocked"
    fully_filled = abs(confirmed_size - entry_size) <= _TOLERANCE
    partially_filled = confirmed_size > _TOLERANCE and not fully_filled
    if fully_filled:
        if order_status in _OPEN_ORDER_STATES:
            warnings.append("exit fill is complete but the venue order status is still open")
        elif order_status in _CANCELLED_ORDER_STATES | _REJECTED_ORDER_STATES:
            warnings.append("exit fully filled before the venue reported a terminal order state")
        return "COMPLETED_ROUND_TRIP", "warning" if warnings else "ready"
    if partially_filled:
        if order_status in _OPEN_ORDER_STATES:
            warnings.append("exit is partially filled and remains open")
            return "EXIT_PARTIALLY_FILLED_OPEN", "warning"
        if order_status in _CANCELLED_ORDER_STATES:
            blocking.append("partially filled exit is cancelled with an unprotected remainder")
        elif order_status in _REJECTED_ORDER_STATES:
            blocking.append("partially filled exit is rejected with an unprotected remainder")
        else:
            blocking.append("partially filled exit has an unexplained terminal state")
        return "RECONCILIATION_BLOCKED", "blocked"
    if order_status in _OPEN_ORDER_STATES:
        return "EXIT_OPEN", "ready"
    if order_status in _CANCELLED_ORDER_STATES:
        blocking.append("unfilled exit was cancelled outside the reconciliation workflow")
    elif order_status in _REJECTED_ORDER_STATES:
        blocking.append("the persisted exit is rejected")
    elif order_status in _FILLED_ORDER_STATES:
        blocking.append("venue reports a filled exit but no confirmed fills were returned")
    else:
        blocking.append("the exit order is neither open nor safely explained")
    return "RECONCILIATION_BLOCKED", "blocked"


def _persist_report(
    connection: sqlite3.Connection,
    *,
    state: _InternalRoundTripState,
    snapshot: LiveRoundTripVenueSnapshot,
    report: LiveRoundTripReconciliationReport,
    fills: tuple[ObservedExitFill, ...],
    persisted_at: datetime,
) -> tuple[int, int, bool]:
    payload_json = _persisted_report_json(
        report,
        snapshot=snapshot,
        new_fills=0,
        new_ledger=0,
        observation_recorded=False,
    )
    new_fills = 0
    new_ledger = 0
    with transaction(connection) as active:
        observation_cursor = active.execute(
            """
            INSERT OR IGNORE INTO live_round_trip_reconciliations (
                observation_id, run_id, authorization_id, classification,
                status, payload_json, observed_at, persisted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.observation_id,
                state.run_id,
                state.authorization_id,
                report.classification,
                report.status,
                payload_json,
                snapshot.read_at.isoformat(),
                persisted_at.isoformat(),
            ),
        )
        observation_recorded = observation_cursor.rowcount == 1
        if not observation_recorded:
            return 0, 0, False
        if report.status == "blocked":
            payload_json = _persisted_report_json(
                report,
                snapshot=snapshot,
                new_fills=0,
                new_ledger=0,
                observation_recorded=True,
            )
            active.execute(
                "UPDATE live_round_trip_reconciliations SET payload_json = ? "
                "WHERE observation_id = ?",
                (payload_json, report.observation_id),
            )
            return 0, 0, True

        for fill in fills:
            stored_fill_id = _stored_fill_id(state.run_id, fill.fill_id)
            fill_payload = {
                "fee_source": fill.fee_source,
                "fee_status": fill.fee_status,
                "liquidity_role": fill.liquidity_role,
                "status": fill.status,
                "venue_fill_id": fill.fill_id,
            }
            cursor = active.execute(
                """
                INSERT OR IGNORE INTO fills (
                    fill_id, order_id, token_id, side, price, size, fee,
                    liquidity_role, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored_fill_id,
                    state.exit_order_id,
                    state.token_id,
                    "SELL",
                    str(fill.price),
                    str(fill.size),
                    None if fill.fee is None else str(fill.fee),
                    fill.liquidity_role,
                    _json_dumps(fill_payload),
                    fill.occurred_at.isoformat(),
                ),
            )
            if cursor.rowcount == 1:
                new_fills += 1
            else:
                _verify_existing_fill(active, stored_fill_id, fill)
                if fill.fee is not None:
                    active.execute(
                        """
                        UPDATE fills
                        SET fee = COALESCE(fee, ?), payload_json = ?
                        WHERE fill_id = ?
                        """,
                        (str(fill.fee), _json_dumps(fill_payload), stored_fill_id),
                    )
            new_ledger += _insert_fill_ledger(active, state, fill, stored_fill_id)

        payload_json = _persisted_report_json(
            report,
            snapshot=snapshot,
            new_fills=new_fills,
            new_ledger=new_ledger,
            observation_recorded=True,
        )
        active.execute(
            "UPDATE live_round_trip_reconciliations SET payload_json = ? "
            "WHERE observation_id = ?",
            (payload_json, report.observation_id),
        )
        payload = _json_object(payload_json)

        order_row = active.execute(
            "SELECT payload_json FROM orders WHERE order_id = ?",
            (state.exit_order_id,),
        ).fetchone()
        order_payload = _json_object(order_row["payload_json"] if order_row else None)
        order_payload["post_exit_reconciliation"] = payload
        active.execute(
            "UPDATE orders SET status = ?, payload_json = ?, updated_at = ? WHERE order_id = ?",
            (
                _internal_order_status(report),
                _json_dumps(order_payload),
                persisted_at.isoformat(),
                state.exit_order_id,
            ),
        )

        position_row = active.execute(
            "SELECT payload_json FROM positions WHERE token_id = ?",
            (state.token_id,),
        ).fetchone()
        position_payload = _json_object(position_row["payload_json"] if position_row else None)
        position_payload["post_exit_reconciliation"] = payload
        realized_pnl = (
            state.current_realized_pnl
            if report.net_realized_pnl is None
            else report.net_realized_pnl
        )
        active.execute(
            """
            UPDATE positions
            SET size = ?, realized_pnl = ?, payload_json = ?, updated_at = ?
            WHERE token_id = ?
            """,
            (
                str(report.expected_remaining_position),
                str(realized_pnl),
                _json_dumps(position_payload),
                persisted_at.isoformat(),
                state.token_id,
            ),
        )
        active.execute(
            """
            INSERT INTO live_order_checkpoints (
                run_id, phase, client_order_id, venue_order_id, payload_json, persisted_at
            ) VALUES (?, 'POST_EXIT_RECONCILIATION', ?, ?, ?, ?)
            ON CONFLICT(run_id, phase) DO UPDATE SET
                client_order_id = excluded.client_order_id,
                venue_order_id = excluded.venue_order_id,
                payload_json = excluded.payload_json,
                persisted_at = excluded.persisted_at
            """,
            (
                state.run_id,
                state.exit_client_order_id,
                state.exit_order_id,
                payload_json,
                persisted_at.isoformat(),
            ),
        )
        active.execute(
            "UPDATE live_entry_attempts SET state = ?, updated_at = ? WHERE authorization_id = ?",
            (
                _authorization_state(report),
                persisted_at.isoformat(),
                state.authorization_id,
            ),
        )
    return new_fills, new_ledger, True


def _persisted_report_json(
    report: LiveRoundTripReconciliationReport,
    *,
    snapshot: LiveRoundTripVenueSnapshot,
    new_fills: int,
    new_ledger: int,
    observation_recorded: bool,
) -> str:
    persisted_report = replace(
        report,
        new_fill_count=new_fills,
        new_ledger_event_count=new_ledger,
        observation_recorded=observation_recorded,
    )
    payload = persisted_report.to_dict()
    payload["observed_at"] = snapshot.read_at.isoformat()
    return _json_dumps(payload)


def _insert_fill_ledger(
    connection: sqlite3.Connection,
    state: _InternalRoundTripState,
    fill: ObservedExitFill,
    stored_fill_id: str,
) -> int:
    inserted = 0
    common = (
        state.run_id,
        state.token_id,
        state.exit_order_id,
        stored_fill_id,
        fill.occurred_at.isoformat(),
    )
    position_event_id = f"{stored_fill_id}:position"
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO ledger_events (
            event_id, run_id, event_type, instrument_id, amount, currency,
            order_id, fill_id, payload_json, occurred_at
        ) VALUES (?, ?, 'LIVE_EXIT_POSITION_DECREASE', ?, ?, 'shares', ?, ?, ?, ?)
        """,
        (
            position_event_id,
            common[0],
            common[1],
            str(-fill.size),
            common[2],
            common[3],
            _json_dumps({"fee_status": fill.fee_status}),
            common[4],
        ),
    )
    inserted += int(cursor.rowcount == 1)
    if fill.fee is not None:
        collateral_event_id = f"{stored_fill_id}:collateral"
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO ledger_events (
                event_id, run_id, event_type, instrument_id, amount, currency,
                order_id, fill_id, payload_json, occurred_at
            ) VALUES (?, ?, 'LIVE_EXIT_COLLATERAL_INCREASE', ?, ?, 'collateral', ?, ?, ?, ?)
            """,
            (
                collateral_event_id,
                common[0],
                common[1],
                str((fill.price * fill.size) - fill.fee),
                common[2],
                common[3],
                _json_dumps({"fee_source": fill.fee_source, "fee_status": fill.fee_status}),
                common[4],
            ),
        )
        inserted += int(cursor.rowcount == 1)
    return inserted


def _verify_existing_fill(
    connection: sqlite3.Connection,
    stored_fill_id: str,
    observed: ObservedExitFill,
) -> None:
    row = connection.execute(
        "SELECT * FROM fills WHERE fill_id = ?",
        (stored_fill_id,),
    ).fetchone()
    if row is None:
        raise LiveRoundTripReconciliationError("idempotent fill lookup failed")
    existing = (
        str(row["order_id"]),
        str(row["token_id"]),
        str(row["side"]),
        Decimal(str(row["price"])),
        Decimal(str(row["size"])),
    )
    expected = (
        observed.order_id,
        observed.token_id,
        observed.side.upper(),
        observed.price,
        observed.size,
    )
    if existing != expected:
        raise LiveRoundTripReconciliationError("persisted fill conflicts with venue evidence")


def _stored_fill_to_observation(row: sqlite3.Row) -> ObservedExitFill:
    payload = _json_object(row["payload_json"])
    return ObservedExitFill(
        fill_id=str(payload.get("venue_fill_id") or row["fill_id"]),
        order_id=str(row["order_id"]),
        token_id=str(row["token_id"]),
        side=str(row["side"]),
        price=Decimal(str(row["price"])),
        size=Decimal(str(row["size"])),
        status=str(payload.get("status") or "CONFIRMED"),
        liquidity_role=str(payload.get("liquidity_role") or row["liquidity_role"] or "UNKNOWN"),
        occurred_at=_datetime(str(row["created_at"])),
        fee=None if row["fee"] is None else Decimal(str(row["fee"])),
        fee_source=(None if payload.get("fee_source") is None else str(payload["fee_source"])),
    )


def _fill_identity(fill: ObservedExitFill) -> tuple[object, ...]:
    return (
        fill.order_id,
        fill.token_id,
        fill.side.upper(),
        fill.price,
        fill.size,
        fill.status.upper(),
        fill.liquidity_role.upper(),
    )


def _observation_id(
    *,
    state: _InternalRoundTripState,
    snapshot: LiveRoundTripVenueSnapshot,
    fills: tuple[ObservedExitFill, ...],
    classification: str,
    status: str,
) -> str:
    canonical = {
        "classification": classification,
        "fills": [
            {
                "fee": None if fill.fee is None else str(fill.fee),
                "fill_id": fill.fill_id,
                "price": str(fill.price),
                "size": str(fill.size),
                "status": fill.status.upper(),
            }
            for fill in fills
        ],
        "order_status": None if snapshot.order is None else snapshot.order.status.upper(),
        "position_size": str(snapshot.position_size),
        "run_id": state.run_id,
        "status": status,
    }
    digest = hashlib.sha256(_json_dumps(canonical).encode("utf-8")).hexdigest()
    return f"{state.run_id}:reconciliation:{digest[:24]}"


def _stored_fill_id(run_id: str, venue_fill_id: str) -> str:
    digest = hashlib.sha256(venue_fill_id.encode("utf-8")).hexdigest()[:24]
    return f"{run_id}:exit:{digest}"


def _internal_order_status(report: LiveRoundTripReconciliationReport) -> str:
    if report.classification == "COMPLETED_ROUND_TRIP":
        return "FILLED"
    if report.confirmed_exit_size > 0:
        return "PARTIALLY_FILLED"
    return report.observed_order_status or "UNKNOWN"


def _authorization_state(report: LiveRoundTripReconciliationReport) -> str:
    return {
        "COMPLETED_ROUND_TRIP": "COMPLETED_ROUND_TRIP",
        "EXIT_PARTIALLY_FILLED_OPEN": "ENTRY_FILLED_EXIT_PARTIAL",
        "EXIT_OPEN": "ENTRY_FILLED_EXIT_OPEN",
    }.get(report.classification, "RECONCILIATION_REQUIRED")


def _required_text(value: object) -> str:
    if value is None or not str(value):
        raise LiveRoundTripReconciliationError("required persisted identifier is missing")
    return str(value)


def _json_object(value: object) -> dict[str, object]:
    if value is None:
        return {}
    parsed = json.loads(str(value))
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = [
    "LiveRoundTripReconciliationConfig",
    "LiveRoundTripReconciliationError",
    "LiveRoundTripReconciliationReport",
    "LiveRoundTripVenueReader",
    "LiveRoundTripVenueSnapshot",
    "ObservedExitFill",
    "ObservedExitOrder",
    "reconcile_live_round_trip",
]
