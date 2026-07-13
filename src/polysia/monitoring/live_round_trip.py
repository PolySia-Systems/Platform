from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol

from polysia.config.logging import get_logger
from polysia.reconciliation.live_round_trip import (
    LiveRoundTripReconciliationConfig,
    LiveRoundTripReconciliationError,
    LiveRoundTripReconciliationReport,
    LiveRoundTripVenueReader,
    LiveRoundTripVenueReadError,
    reconcile_live_round_trip,
)
from polysia.storage.db import SQLiteDatabase, transaction

AlertSeverity = Literal["INFO", "WARNING", "CRITICAL"]
MonitorStatus = Literal["ready", "warning", "blocked"]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]

_REQUIRED_CHECKPOINTS = frozenset(
    {"ENTRY_RESPONSE", "ENTRY_FILL_CONFIRMED", "ENTRY_POSITION_RECONCILED", "EXIT_RESPONSE"}
)
_LOGGER = get_logger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class LifecycleHealthSnapshot:
    checked_at: datetime
    server_time_readable: bool
    clock_drift_seconds: Decimal | None
    geoblock_status: str
    geoblocked: bool | None
    error_types: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "clock_drift_seconds": (
                None if self.clock_drift_seconds is None else str(self.clock_drift_seconds)
            ),
            "error_types": list(self.error_types),
            "geoblock_status": self.geoblock_status,
            "geoblocked": self.geoblocked,
            "server_time_readable": self.server_time_readable,
        }


class LifecycleHealthReader(Protocol):
    async def read_health(self) -> LifecycleHealthSnapshot:
        """Read public server time and geoblock state without mutating venue state."""


@dataclass(frozen=True, slots=True)
class LiveRoundTripMonitorConfig:
    database_path: Path
    run_id: str
    authorization_id: str = "POLYSIA-LIVE-004"
    stale_after: timedelta = timedelta(minutes=5)
    max_clock_drift_seconds: Decimal = Decimal("5")
    max_cycles: int = 1
    interval_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        if self.max_clock_drift_seconds <= 0:
            raise ValueError("max_clock_drift_seconds must be positive")
        if not 1 <= self.max_cycles <= 10:
            raise ValueError("max_cycles must be between 1 and 10")
        if self.interval_seconds < 30:
            raise ValueError("interval_seconds must be at least 30")


@dataclass(frozen=True, slots=True)
class LifecycleAlert:
    alert_id: str
    code: str
    severity: AlertSeverity
    correlation_id: str
    run_id: str
    authorization_id: str
    order_reference: str | None
    message: str
    operator_action: str
    observed_at: datetime
    recorded: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "alert_id": self.alert_id,
            "authorization_id": self.authorization_id,
            "code": self.code,
            "correlation_id": self.correlation_id,
            "message": self.message,
            "observed_at": self.observed_at.isoformat(),
            "operator_action": self.operator_action,
            "order_reference": self.order_reference,
            "recorded": self.recorded,
            "run_id": self.run_id,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class LiveRoundTripMonitorCycle:
    cycle_number: int
    observed_at: datetime
    status: MonitorStatus
    health: LifecycleHealthSnapshot
    reconciliation: LiveRoundTripReconciliationReport | None
    alerts: tuple[LifecycleAlert, ...]
    new_alert_count: int
    duplicate_alert_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "alerts": [alert.to_dict() for alert in self.alerts],
            "cycle_number": self.cycle_number,
            "duplicate_alert_count": self.duplicate_alert_count,
            "health": self.health.to_dict(),
            "new_alert_count": self.new_alert_count,
            "observed_at": self.observed_at.isoformat(),
            "reconciliation": (
                None if self.reconciliation is None else self.reconciliation.to_dict()
            ),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class LiveRoundTripMonitorReport:
    run_id: str
    authorization_id: str
    status: MonitorStatus
    cycles: tuple[LiveRoundTripMonitorCycle, ...]
    new_alert_count: int
    duplicate_alert_count: int
    read_only_statement: str = (
        "Lifecycle monitoring uses read-only venue ports and cannot submit, cancel, replace, "
        "or retry an order."
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "cycles": [cycle.to_dict() for cycle in self.cycles],
            "duplicate_alert_count": self.duplicate_alert_count,
            "new_alert_count": self.new_alert_count,
            "read_only_statement": self.read_only_statement,
            "run_id": self.run_id,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class _MonitorContext:
    exit_order_id: str
    order_reference: str
    token_id: str
    exit_created_at: datetime


@dataclass(frozen=True, slots=True)
class _IntegritySnapshot:
    exit_fill_size: Decimal
    latest_exit_fill_at: datetime | None
    position_size: Decimal
    ledger_matches: bool


async def monitor_live_round_trip(
    config: LiveRoundTripMonitorConfig,
    *,
    venue_reader: LiveRoundTripVenueReader,
    health_reader: LifecycleHealthReader,
    clock: Clock = utc_now,
    sleep: Sleeper = asyncio.sleep,
) -> LiveRoundTripMonitorReport:
    """Run a bounded read-only lifecycle monitor and persist idempotent alerts."""

    cycles: list[LiveRoundTripMonitorCycle] = []
    for cycle_number in range(1, config.max_cycles + 1):
        cycles.append(
            await _monitor_cycle(
                config,
                cycle_number=cycle_number,
                venue_reader=venue_reader,
                health_reader=health_reader,
                clock=clock,
            )
        )
        if cycle_number < config.max_cycles:
            await sleep(config.interval_seconds)

    return LiveRoundTripMonitorReport(
        run_id=config.run_id,
        authorization_id=config.authorization_id,
        status=_status(alert for cycle in cycles for alert in cycle.alerts),
        cycles=tuple(cycles),
        new_alert_count=sum(cycle.new_alert_count for cycle in cycles),
        duplicate_alert_count=sum(cycle.duplicate_alert_count for cycle in cycles),
    )


async def _monitor_cycle(
    config: LiveRoundTripMonitorConfig,
    *,
    cycle_number: int,
    venue_reader: LiveRoundTripVenueReader,
    health_reader: LifecycleHealthReader,
    clock: Clock,
) -> LiveRoundTripMonitorCycle:
    observed_at = _as_utc(clock())
    health = await _safe_health_read(health_reader, observed_at)
    alerts = _health_alerts(config, health, observed_at)
    reconciliation: LiveRoundTripReconciliationReport | None = None

    try:
        context = _load_context(config)
    except LiveRoundTripReconciliationError as error:
        alerts.extend(_context_error_alerts(config, error, observed_at))
        context = None
    except (OSError, sqlite3.DatabaseError, ValueError):
        alerts.append(
            _alert(
                config,
                code="CORRUPT_CHECKPOINT",
                severity="CRITICAL",
                state_key="context-unreadable",
                observed_at=observed_at,
                message="Persisted lifecycle context could not be read safely.",
                operator_action="Inspect or restore the database before any live action.",
            )
        )
        context = None

    if context is not None:
        try:
            reconciliation = await reconcile_live_round_trip(
                LiveRoundTripReconciliationConfig(
                    database_path=config.database_path,
                    run_id=config.run_id,
                    authorization_id=config.authorization_id,
                ),
                venue_reader=venue_reader,
                clock=clock,
            )
        except LiveRoundTripVenueReadError:
            alerts.extend(
                (
                    _alert(
                        config,
                        code="AUTHENTICATION_READ_FAILED",
                        severity="CRITICAL",
                        state_key="authenticated-read-failed",
                        observed_at=observed_at,
                        context=context,
                        message="Required authenticated account reads failed.",
                        operator_action=(
                            "Restore authenticated read access, then run monitoring again."
                        ),
                    ),
                    _alert(
                        config,
                        code="API_DEGRADED",
                        severity="WARNING",
                        state_key="authenticated-api-read-failed",
                        observed_at=observed_at,
                        context=context,
                        message="The venue API did not return complete lifecycle evidence.",
                        operator_action=(
                            "Check venue availability and do not mutate the open lifecycle."
                        ),
                    ),
                )
            )
        except LiveRoundTripReconciliationError as error:
            alerts.extend(_context_error_alerts(config, error, observed_at, context=context))
        except (OSError, sqlite3.DatabaseError, ValueError):
            alerts.append(
                _alert(
                    config,
                    code="CORRUPT_CHECKPOINT",
                    severity="CRITICAL",
                    state_key="database-or-checkpoint-invalid",
                    observed_at=observed_at,
                    context=context,
                    message="Persisted lifecycle state could not be read safely.",
                    operator_action="Restore or inspect the database before any live action.",
                )
            )
        except Exception:  # noqa: BLE001 - monitoring must fail closed on unknown state
            alerts.extend(
                (
                    _alert(
                        config,
                        code="UNEXPECTED_VENUE_STATE",
                        severity="CRITICAL",
                        state_key="unexpected-monitor-failure",
                        observed_at=observed_at,
                        context=context,
                        message="An unexpected lifecycle state prevented safe classification.",
                        operator_action=(
                            "Preserve evidence and perform manual read-only reconciliation."
                        ),
                    ),
                    _alert(
                        config,
                        code="RECONCILIATION_FAILED",
                        severity="CRITICAL",
                        state_key="unexpected-monitor-failure",
                        observed_at=observed_at,
                        context=context,
                        message="Lifecycle reconciliation did not complete.",
                        operator_action="Do not place another order until reconciliation succeeds.",
                    ),
                )
            )
        else:
            alerts.extend(_reconciliation_alerts(config, context, reconciliation, observed_at))

    persisted = _persist_alerts(config.database_path, alerts)
    for alert in persisted:
        if alert.recorded:
            _log_alert(alert)
    return LiveRoundTripMonitorCycle(
        cycle_number=cycle_number,
        observed_at=observed_at,
        status=_status(persisted),
        health=health,
        reconciliation=reconciliation,
        alerts=persisted,
        new_alert_count=sum(alert.recorded for alert in persisted),
        duplicate_alert_count=sum(not alert.recorded for alert in persisted),
    )


async def _safe_health_read(
    reader: LifecycleHealthReader,
    observed_at: datetime,
) -> LifecycleHealthSnapshot:
    try:
        return await reader.read_health()
    except Exception as error:  # noqa: BLE001 - sanitized degraded health result
        return LifecycleHealthSnapshot(
            checked_at=observed_at,
            server_time_readable=False,
            clock_drift_seconds=None,
            geoblock_status="error",
            geoblocked=None,
            error_types=(type(error).__name__,),
        )


def _health_alerts(
    config: LiveRoundTripMonitorConfig,
    health: LifecycleHealthSnapshot,
    observed_at: datetime,
) -> list[LifecycleAlert]:
    alerts: list[LifecycleAlert] = []
    if not health.server_time_readable or health.geoblock_status in {"error", "unavailable"}:
        alerts.append(
            _alert(
                config,
                code="API_DEGRADED",
                severity="WARNING",
                state_key="|".join(health.error_types) or "public-health-unavailable",
                observed_at=observed_at,
                message="One or more public venue health reads are unavailable.",
                operator_action="Verify venue connectivity before relying on lifecycle timing.",
            )
        )
    if health.geoblocked is True or health.geoblock_status == "blocked":
        alerts.append(
            _alert(
                config,
                code="GEOBLOCKED",
                severity="CRITICAL",
                state_key="geoblocked",
                observed_at=observed_at,
                message="The venue geoblock endpoint reports trading is blocked.",
                operator_action="Keep all trading mutations disabled.",
            )
        )
    drift = health.clock_drift_seconds
    if drift is not None and abs(drift) > config.max_clock_drift_seconds:
        alerts.append(
            _alert(
                config,
                code="CLOCK_DRIFT",
                severity="CRITICAL",
                state_key="clock-drift-exceeded",
                observed_at=observed_at,
                message="Local clock drift exceeds the approved monitoring threshold.",
                operator_action="Synchronize Windows time and rerun the read-only monitor.",
            )
        )
    return alerts


def _reconciliation_alerts(
    config: LiveRoundTripMonitorConfig,
    context: _MonitorContext,
    report: LiveRoundTripReconciliationReport,
    observed_at: datetime,
) -> list[LifecycleAlert]:
    alerts: list[LifecycleAlert] = []
    state_key = report.observation_id
    age = max(timedelta(0), observed_at - context.exit_created_at)

    if report.classification == "EXIT_OPEN":
        alerts.append(
            _alert(
                config,
                code="EXIT_ORDER_OPEN",
                severity="INFO",
                state_key=state_key,
                observed_at=observed_at,
                context=context,
                message="The exit order remains open with no confirmed exit fill.",
                operator_action="Continue scheduled read-only monitoring.",
            )
        )
        if age >= config.stale_after:
            alerts.append(
                _alert(
                    config,
                    code="EXIT_ORDER_STALE",
                    severity="WARNING",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message="The open exit order has exceeded the stale-order threshold.",
                    operator_action=(
                        "Review liquidity and reconcile; do not create a replacement order."
                    ),
                )
            )
    elif report.classification == "EXIT_PARTIALLY_FILLED_OPEN":
        alerts.extend(
            (
                _alert(
                    config,
                    code="EXIT_ORDER_OPEN",
                    severity="INFO",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message="The exit order remains open after a confirmed partial fill.",
                    operator_action="Continue scheduled read-only monitoring.",
                ),
                _alert(
                    config,
                    code="EXIT_PARTIALLY_FILLED",
                    severity="WARNING",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message=(
                        "The exit is partially filled and the confirmed remainder is still open."
                    ),
                    operator_action=(
                        "Monitor the remaining confirmed position without adding exposure."
                    ),
                ),
            )
        )
        if age >= config.stale_after:
            alerts.append(
                _alert(
                    config,
                    code="EXIT_ORDER_STALE",
                    severity="WARNING",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message="The partially filled exit remains open beyond the stale threshold.",
                    operator_action=(
                        "Review the confirmed remainder; do not create a replacement order."
                    ),
                )
            )
    elif report.classification == "COMPLETED_ROUND_TRIP":
        alerts.append(
            _alert(
                config,
                code="ROUND_TRIP_CLOSED",
                severity="INFO",
                state_key=state_key,
                observed_at=observed_at,
                context=context,
                message="The round trip is fully closed and the confirmed venue position is zero.",
                operator_action="Retain the reconciliation evidence for phase reporting.",
            )
        )

    try:
        integrity = _load_integrity(config, context)
    except (InvalidOperation, OSError, sqlite3.DatabaseError, ValueError):
        alerts.append(
            _alert(
                config,
                code="CORRUPT_CHECKPOINT",
                severity="CRITICAL",
                state_key=f"{state_key}:integrity-unreadable",
                observed_at=observed_at,
                context=context,
                message="Internal lifecycle integrity records could not be read safely.",
                operator_action="Inspect or restore persistence before any live action.",
            )
        )
        integrity = None

    if integrity is not None:
        if abs(integrity.exit_fill_size - report.confirmed_exit_size) > Decimal("0.000001"):
            alerts.append(
                _alert(
                    config,
                    code="FILL_MISMATCH",
                    severity="CRITICAL",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message="Persisted exit fills do not match confirmed reconciliation evidence.",
                    operator_action="Stop mutation and inspect fill identity and persistence.",
                )
            )
        if abs(integrity.position_size - report.observed_position_size) > Decimal("0.000001"):
            alerts.append(
                _alert(
                    config,
                    code="POSITION_MISMATCH",
                    severity="CRITICAL",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message="Internal and venue-confirmed positions do not match.",
                    operator_action="Keep Risk paused and perform manual reconciliation.",
                )
            )
        if not integrity.ledger_matches:
            alerts.append(
                _alert(
                    config,
                    code="LEDGER_MISMATCH",
                    severity="CRITICAL",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message="Exit fills and expected ledger events do not match.",
                    operator_action="Repair accounting evidence before phase closure.",
                )
            )
        if (
            integrity.latest_exit_fill_at is not None
            and integrity.latest_exit_fill_at - context.exit_created_at >= config.stale_after
        ):
            alerts.append(
                _alert(
                    config,
                    code="EXIT_FILLED_LATE",
                    severity="WARNING",
                    state_key=state_key,
                    observed_at=observed_at,
                    context=context,
                    message="A confirmed exit fill arrived after the stale-order threshold.",
                    operator_action="Confirm closure and retain the delayed-fill evidence.",
                )
            )

    if report.duplicate_fill_count:
        alerts.append(
            _alert(
                config,
                code="DUPLICATE_EVENT",
                severity="INFO",
                state_key=state_key,
                observed_at=observed_at,
                context=context,
                message="Duplicate fill evidence was recognized and ignored idempotently.",
                operator_action="No action is required unless duplicate evidence conflicts.",
            )
        )
    if report.status == "blocked":
        alerts.append(
            _alert(
                config,
                code="RECONCILIATION_FAILED",
                severity="CRITICAL",
                state_key=state_key,
                observed_at=observed_at,
                context=context,
                message="Lifecycle reconciliation is blocked by inconsistent evidence.",
                operator_action="Do not mutate the lifecycle; investigate the reported mismatch.",
            )
        )
        alerts.extend(_blocking_reason_alerts(config, context, report, observed_at))
    return alerts


def _blocking_reason_alerts(
    config: LiveRoundTripMonitorConfig,
    context: _MonitorContext,
    report: LiveRoundTripReconciliationReport,
    observed_at: datetime,
) -> list[LifecycleAlert]:
    text = " ".join(report.blocking_reasons).lower()
    alerts: list[LifecycleAlert] = []
    for needle, code, message in (
        ("position", "POSITION_MISMATCH", "Venue and internal position evidence conflict."),
        ("fill", "FILL_MISMATCH", "Venue and internal fill evidence conflict."),
        ("order", "UNEXPECTED_VENUE_STATE", "The venue order state is not safely explained."),
    ):
        if needle in text:
            alerts.append(
                _alert(
                    config,
                    code=code,
                    severity="CRITICAL",
                    state_key=report.observation_id,
                    observed_at=observed_at,
                    context=context,
                    message=message,
                    operator_action=(
                        "Preserve evidence and perform manual read-only reconciliation."
                    ),
                )
            )
    return alerts


def _context_error_alerts(
    config: LiveRoundTripMonitorConfig,
    error: LiveRoundTripReconciliationError,
    observed_at: datetime,
    *,
    context: _MonitorContext | None = None,
) -> list[LifecycleAlert]:
    detail = str(error).lower()
    if "missing" in detail or "does not identify" in detail:
        code = "MISSING_CHECKPOINT"
        message = "Required persistent lifecycle state is missing."
    elif "invalid" in detail or "corrupt" in detail or "required persisted identifier" in detail:
        code = "CORRUPT_CHECKPOINT"
        message = "Persistent lifecycle state is invalid or corrupt."
    else:
        code = "RECONCILIATION_FAILED"
        message = "Persistent lifecycle state cannot support safe reconciliation."
    return [
        _alert(
            config,
            code=code,
            severity="CRITICAL",
            state_key=code.lower(),
            observed_at=observed_at,
            context=context,
            message=message,
            operator_action="Inspect or restore the checkpoint before any live action.",
        )
    ]


def _load_context(config: LiveRoundTripMonitorConfig) -> _MonitorContext:
    with SQLiteDatabase(config.database_path) as database:
        connection = database.connection
        authorization = connection.execute(
            "SELECT run_id FROM live_entry_attempts WHERE authorization_id = ?",
            (config.authorization_id,),
        ).fetchone()
        if authorization is None or str(authorization["run_id"]) != config.run_id:
            raise LiveRoundTripReconciliationError(
                "the persistent authorization does not identify the requested run"
            )
        rows = connection.execute(
            "SELECT * FROM live_order_checkpoints WHERE run_id = ?",
            (config.run_id,),
        ).fetchall()
        by_phase = {str(row["phase"]): row for row in rows}
        missing = sorted(_REQUIRED_CHECKPOINTS - by_phase.keys())
        if missing:
            raise LiveRoundTripReconciliationError(
                f"required live checkpoints are missing: {', '.join(missing)}"
            )
        for row in by_phase.values():
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, Mapping):
                raise LiveRoundTripReconciliationError("checkpoint payload is corrupt")
        exit_checkpoint = by_phase["EXIT_RESPONSE"]
        exit_order_id = str(exit_checkpoint["venue_order_id"] or "")
        if not exit_order_id:
            raise LiveRoundTripReconciliationError("required persisted identifier is missing")
        order = connection.execute(
            "SELECT token_id, created_at FROM orders WHERE order_id = ?",
            (exit_order_id,),
        ).fetchone()
        if order is None:
            raise LiveRoundTripReconciliationError("the persisted exit order is missing")
        return _MonitorContext(
            exit_order_id=exit_order_id,
            order_reference=_safe_reference(exit_order_id),
            token_id=str(order["token_id"]),
            exit_created_at=_parse_datetime(str(order["created_at"])),
        )


def _load_integrity(
    config: LiveRoundTripMonitorConfig,
    context: _MonitorContext,
) -> _IntegritySnapshot:
    with SQLiteDatabase(config.database_path) as database:
        connection = database.connection
        fills = connection.execute(
            "SELECT fill_id, size, fee, created_at FROM fills "
            "WHERE order_id = ? AND fill_id LIKE ? ORDER BY created_at, fill_id",
            (context.exit_order_id, f"{config.run_id}:exit:%"),
        ).fetchall()
        exit_fill_size = sum((Decimal(str(row["size"])) for row in fills), Decimal("0"))
        latest_fill = None if not fills else _parse_datetime(str(fills[-1]["created_at"]))
        position = connection.execute(
            "SELECT size FROM positions WHERE token_id = ?",
            (context.token_id,),
        ).fetchone()
        if position is None:
            raise ValueError("position is missing")
        ledger_matches = True
        for fill in fills:
            expected_types = {"LIVE_EXIT_POSITION_DECREASE"}
            if fill["fee"] is not None:
                expected_types.add("LIVE_EXIT_COLLATERAL_INCREASE")
            actual_types = {
                str(row["event_type"])
                for row in connection.execute(
                    "SELECT event_type FROM ledger_events WHERE run_id = ? AND fill_id = ?",
                    (config.run_id, str(fill["fill_id"])),
                ).fetchall()
            }
            if actual_types != expected_types:
                ledger_matches = False
        return _IntegritySnapshot(
            exit_fill_size=exit_fill_size,
            latest_exit_fill_at=latest_fill,
            position_size=Decimal(str(position["size"])),
            ledger_matches=ledger_matches,
        )


def _alert(
    config: LiveRoundTripMonitorConfig,
    *,
    code: str,
    severity: AlertSeverity,
    state_key: str,
    observed_at: datetime,
    message: str,
    operator_action: str,
    context: _MonitorContext | None = None,
) -> LifecycleAlert:
    canonical = json.dumps(
        {
            "authorization_id": config.authorization_id,
            "code": code,
            "run_id": config.run_id,
            "state_key": state_key,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return LifecycleAlert(
        alert_id=f"{config.run_id}:alert:{digest}",
        code=code,
        severity=severity,
        correlation_id=f"{config.run_id}:{code.lower()}",
        run_id=config.run_id,
        authorization_id=config.authorization_id,
        order_reference=None if context is None else context.order_reference,
        message=message,
        operator_action=operator_action,
        observed_at=observed_at,
    )


def _persist_alerts(path: Path, alerts: list[LifecycleAlert]) -> tuple[LifecycleAlert, ...]:
    persisted: list[LifecycleAlert] = []
    with SQLiteDatabase(path) as database, transaction(database.connection) as connection:
        for alert in alerts:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO live_lifecycle_alerts (
                    alert_id, run_id, authorization_id, alert_code, severity,
                    correlation_id, order_reference, message, operator_action,
                    observed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.alert_id,
                    alert.run_id,
                    alert.authorization_id,
                    alert.code,
                    alert.severity,
                    alert.correlation_id,
                    alert.order_reference,
                    alert.message,
                    alert.operator_action,
                    alert.observed_at.isoformat(),
                    utc_now().isoformat(),
                ),
            )
            persisted.append(replace(alert, recorded=cursor.rowcount == 1))
    return tuple(persisted)


def _log_alert(alert: LifecycleAlert) -> None:
    fields = {
        "alert_code": alert.code,
        "authorization_id": alert.authorization_id,
        "correlation_id": alert.correlation_id,
        "order_reference": alert.order_reference,
        "run_id": alert.run_id,
        "severity": alert.severity,
    }
    if alert.severity == "CRITICAL":
        _LOGGER.critical("live_round_trip_alert", **fields)
    elif alert.severity == "WARNING":
        _LOGGER.warning("live_round_trip_alert", **fields)
    else:
        _LOGGER.info("live_round_trip_alert", **fields)


def _status(alerts: Iterable[LifecycleAlert]) -> MonitorStatus:
    severities = {alert.severity for alert in alerts}
    if "CRITICAL" in severities:
        return "blocked"
    if "WARNING" in severities:
        return "warning"
    return "ready"


def render_live_round_trip_monitor(
    report: LiveRoundTripMonitorReport,
    report_format: Literal["json", "markdown"],
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    lines = [
        "# PolySia Live Round-Trip Monitor",
        "",
        f"- Status: {report.status}",
        f"- Run: {report.run_id}",
        f"- Authorization: {report.authorization_id}",
        f"- New alerts: {report.new_alert_count}",
        f"- Duplicate alerts ignored: {report.duplicate_alert_count}",
        "",
        "## Alerts",
        "",
    ]
    alerts = [alert for cycle in report.cycles for alert in cycle.alerts]
    lines.extend(
        f"- [{alert.severity}] `{alert.code}` — {alert.message} Action: {alert.operator_action}"
        for alert in alerts
    )
    if not alerts:
        lines.append("- None")
    lines.extend(("", "## Safety", "", report.read_only_statement, ""))
    return "\n".join(lines)


def write_live_round_trip_monitor_reports(
    report: LiveRoundTripMonitorReport,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "live-round-trip-monitor.json",
        "markdown": output_dir / "live-round-trip-monitor.md",
    }
    for report_format, path in paths.items():
        path.write_text(
            f"{render_live_round_trip_monitor(report, report_format)}\n",  # type: ignore[arg-type]
            encoding="utf-8",
        )
    return paths


def _safe_reference(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "LifecycleAlert",
    "LifecycleHealthReader",
    "LifecycleHealthSnapshot",
    "LiveRoundTripMonitorConfig",
    "LiveRoundTripMonitorCycle",
    "LiveRoundTripMonitorReport",
    "monitor_live_round_trip",
    "render_live_round_trip_monitor",
    "write_live_round_trip_monitor_reports",
]
