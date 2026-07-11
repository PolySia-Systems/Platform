from __future__ import annotations

import asyncio
import json
import re
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from polysia.adapters.polymarket.geoblock import GeoblockStatus, PreLiveOrderGeoblockCheck
from polysia.adapters.polymarket.secure import (
    BalanceAssetType,
    MarketOrderType,
    OrderSide,
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.config.settings import AppSettings, TradingMode
from polysia.execution.intents import OrderIntent
from polysia.reconciliation.manager import ReconciliationManager
from polysia.reconciliation.models import (
    ActualAccountState,
    InternalExpectedState,
    OrderSnapshot,
    PositionSnapshot,
    ReconciliationInput,
    ReconciliationResult,
    ReconciliationStatus,
)
from polysia.reconciliation.safety_pause import KillSwitchSafetyPause
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits

ManualInterventionSide = Literal["BUY", "SELL"]
ManualInterventionOutcome = Literal["YES", "NO"]
ManualInterventionOrderType = Literal["FAK", "FOK"]
ManualInterventionFinalResult = Literal[
    "DRY_RUN_READY",
    "BLOCKED",
    "LIVE_ORDER_SUBMITTED_AWAITING_OPERATOR",
    "MANUAL_INTERVENTION_DETECTED",
    "NO_MANUAL_INTERVENTION_DETECTED",
    "LIVE_ORDER_ERROR",
]
ReportFormat = Literal["json", "markdown"]
Clock = Callable[[], datetime]
GitReader = Callable[[Path, tuple[str, ...]], str]
Sleeper = Callable[[float], Awaitable[None]]

MAX_MANUAL_INTERVENTION_NOTIONAL = Decimal("1.00")

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
_LONG_TOKEN_RE = re.compile(r"\b[0-9]{30,}\b")


def utc_now() -> datetime:
    return datetime.now(UTC)


class ManualInterventionLiveTestError(RuntimeError):
    """Raised when the manual-intervention live test must fail closed."""


class ManualInterventionAdapter(Protocol):
    @property
    def is_connected(self) -> bool:
        """Whether the authenticated adapter is connected."""

    async def connect(self) -> None:
        """Connect to authenticated APIs."""

    async def close(self) -> None:
        """Close authenticated resources."""

    def identity(self) -> Any:
        """Return sanitized signer/funder diagnostics."""

    async def get_balance_allowance(
        self,
        *,
        asset_type: BalanceAssetType,
        token_id: str | None = None,
    ) -> Any:
        """Read balance and approval metadata."""

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        """Read open orders only."""

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        """Read positions only."""

    async def place_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | None = None,
        shares: Decimal | None = None,
        max_spend: Decimal | None = None,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> Any:
        """Submit one tiny market order."""


class ManualInterventionGeoblockCheck(Protocol):
    async def check(self) -> GeoblockStatus:
        """Return sanitized geoblock status."""


@dataclass(frozen=True, slots=True)
class ManualInterventionLiveTestConfig:
    settings: AppSettings
    output_dir: Path
    token_id: str
    side: ManualInterventionSide
    outcome: ManualInterventionOutcome
    max_notional: Decimal
    order_type: ManualInterventionOrderType
    market_slug: str
    condition_id: str | None = None
    dry_run: bool = True
    acknowledgement: bool = False
    manual_intervention_acknowledgement: bool = False
    require_clean_git: bool = False
    poll_attempts: int = 30
    poll_interval_seconds: float = 2.0
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class ManualInterventionLiveTestReport:
    timestamp: datetime
    dry_run: bool
    final_result: ManualInterventionFinalResult
    selected_market_slug: str
    selected_token_configured: bool
    token_allowlisted: bool
    side: ManualInterventionSide
    outcome: ManualInterventionOutcome
    max_notional: str
    order_type: ManualInterventionOrderType
    order_submitted: bool
    live_attempt_count: int
    submitted_order_state: dict[str, object]
    operator_instruction: str
    poll_attempts_completed: int
    detection_latency_seconds: int | None
    manual_intervention_detected: bool
    reconciliation_status: str | None
    reconciliation_event_types: tuple[str, ...]
    trading_should_pause: bool
    requires_manual_acknowledgement: bool
    safety_pause_activated: bool
    no_retry_statement: str
    no_cancel_statement: str
    no_strategy_statement: str
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "blocking_reasons": list(self.blocking_reasons),
            "detection_latency_seconds": self.detection_latency_seconds,
            "dry_run": self.dry_run,
            "final_result": self.final_result,
            "live_attempt_count": self.live_attempt_count,
            "manual_intervention_detected": self.manual_intervention_detected,
            "max_notional": self.max_notional,
            "no_cancel_statement": self.no_cancel_statement,
            "no_retry_statement": self.no_retry_statement,
            "no_strategy_statement": self.no_strategy_statement,
            "operator_instruction": self.operator_instruction,
            "order_submitted": self.order_submitted,
            "order_type": self.order_type,
            "outcome": self.outcome,
            "poll_attempts_completed": self.poll_attempts_completed,
            "reconciliation_event_types": list(self.reconciliation_event_types),
            "reconciliation_status": self.reconciliation_status,
            "requires_manual_acknowledgement": self.requires_manual_acknowledgement,
            "safety_pause_activated": self.safety_pause_activated,
            "selected_market_slug": self.selected_market_slug,
            "selected_token_configured": self.selected_token_configured,
            "side": self.side,
            "submitted_order_state": self.submitted_order_state,
            "timestamp": self.timestamp.isoformat(),
            "token_allowlisted": self.token_allowlisted,
            "trading_should_pause": self.trading_should_pause,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class ManualInterventionOrderPlan:
    risk_price: Decimal
    risk_size: Decimal
    amount: Decimal | None
    shares: Decimal | None


class OneManualInterventionOrderAttempt:
    """Enforces the one-live-order-attempt invariant."""

    def __init__(self) -> None:
        self.count = 0

    async def submit_once(
        self,
        adapter: ManualInterventionAdapter,
        *,
        token_id: str,
        side: ManualInterventionSide,
        plan: ManualInterventionOrderPlan,
        order_type: ManualInterventionOrderType,
    ) -> Any:
        if self.count >= 1:
            raise ManualInterventionLiveTestError("one live order attempt invariant violated.")
        self.count += 1
        return await adapter.place_market_order(
            token_id=token_id,
            side=cast(OrderSide, side),
            amount=plan.amount,
            shares=plan.shares,
            order_type=cast(MarketOrderType, order_type),
        )


async def run_manual_intervention_live_test(
    config: ManualInterventionLiveTestConfig,
    *,
    adapter: ManualInterventionAdapter | None = None,
    geoblock_check: ManualInterventionGeoblockCheck | None = None,
    risk_engine: RiskEngine | None = None,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    git_reader: GitReader | None = None,
    sleeper: Sleeper = asyncio.sleep,
) -> ManualInterventionLiveTestReport:
    """Run a guarded manual-intervention live test or dry-run preview."""

    active_adapter = adapter or PolymarketSecureAdapter()
    active_geoblock = geoblock_check or PreLiveOrderGeoblockCheck()
    active_kill_switch = kill_switch or KillSwitch()
    active_risk_engine = risk_engine or _manual_intervention_risk_engine(
        config.settings,
        active_kill_switch,
    )
    attempt_guard = OneManualInterventionOrderAttempt()
    blocking = list(_static_blocking_reasons(config, active_kill_switch, git_reader=git_reader))
    warnings: list[str] = []
    submitted_order_state: dict[str, object] = {"status": "not_submitted"}
    reconciliation_result: ReconciliationResult | None = None
    poll_attempts_completed = 0
    submitted_at: datetime | None = None
    detection_latency_seconds: int | None = None
    final_result: ManualInterventionFinalResult = "BLOCKED"

    try:
        if blocking:
            raise ManualInterventionLiveTestError("static gates blocked")
        plan = _build_order_plan(config)

        if config.dry_run:
            final_result = "DRY_RUN_READY"
        else:
            if not active_adapter.is_connected:
                await active_adapter.connect()
            _assert_identity_ready(active_adapter.identity())
            _assert_balance_allowance_ready(
                await active_adapter.get_balance_allowance(
                    asset_type="COLLATERAL",
                    token_id=None,
                )
            )
            status = await active_geoblock.check()
            _assert_geoblock_allows(status)
            open_orders_count = len(await active_adapter.get_open_orders(token_id=config.token_id))
            risk_decision = active_risk_engine.evaluate(
                OrderIntent(
                    strategy_id="operator-manual-intervention-live-test",
                    token_id=config.token_id,
                    side=config.side,
                    price=plan.risk_price,
                    size=plan.risk_size,
                    reason="manual intervention live connectivity test",
                    confidence=Decimal("1"),
                ),
                RiskContext(
                    trading_mode=TradingMode.LIVE,
                    live_trading_enabled=config.settings.live_trading_enabled,
                    current_position=Decimal("0"),
                    current_market_position=Decimal("0"),
                    daily_pnl=Decimal("0"),
                    open_orders_count=open_orders_count,
                    market_data_age_ms=0,
                ),
            )
            if not risk_decision.approved:
                raise ManualInterventionLiveTestError(
                    f"risk engine blocked order: {risk_decision.reason}"
                )

            response = await attempt_guard.submit_once(
                active_adapter,
                token_id=config.token_id,
                side=config.side,
                plan=plan,
                order_type=config.order_type,
            )
            submitted_at = clock()
            response_payload = _model_or_mapping_to_dict(response)
            submitted_order_state = _safe_submitted_order_state(response_payload)
            final_result = "LIVE_ORDER_SUBMITTED_AWAITING_OPERATOR"
            internal = _internal_state_from_submit(config, response_payload, submitted_at)
            reconciliation_result, poll_attempts_completed = await _poll_reconciliation(
                adapter=active_adapter,
                config=config,
                internal=internal,
                kill_switch=active_kill_switch,
                clock=clock,
                sleeper=sleeper,
            )
            if reconciliation_result.manual_intervention_detected:
                final_result = "MANUAL_INTERVENTION_DETECTED"
                detection_latency_seconds = int(
                    (reconciliation_result.checked_at - submitted_at).total_seconds()
                )
            elif reconciliation_result.status == ReconciliationStatus.BLOCKED:
                final_result = "BLOCKED"
            else:
                final_result = "NO_MANUAL_INTERVENTION_DETECTED"
                warnings.append("Manual intervention was not detected within the polling window.")
    except (
        ManualInterventionLiveTestError,
        PolymarketSecureAdapterError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        if str(error) != "static gates blocked":
            blocking.append(str(error))
        if attempt_guard.count > 0:
            final_result = "LIVE_ORDER_ERROR"
    finally:
        await active_adapter.close()

    report = ManualInterventionLiveTestReport(
        timestamp=clock(),
        dry_run=config.dry_run,
        final_result=final_result,
        selected_market_slug=config.market_slug,
        selected_token_configured=bool(config.token_id),
        token_allowlisted=config.token_id in config.settings.polymarket_live_token_allowlist,
        side=config.side,
        outcome=config.outcome,
        max_notional=str(config.max_notional),
        order_type=config.order_type,
        order_submitted=attempt_guard.count > 0,
        live_attempt_count=attempt_guard.count,
        submitted_order_state=submitted_order_state,
        operator_instruction=(
            "After the one tiny order is submitted, manually cancel the open order "
            "or close the resulting position from the Polymarket website. The system "
            "will only run read-only reconciliation polling."
        ),
        poll_attempts_completed=poll_attempts_completed,
        detection_latency_seconds=detection_latency_seconds,
        manual_intervention_detected=(
            reconciliation_result.manual_intervention_detected
            if reconciliation_result is not None
            else False
        ),
        reconciliation_status=(
            reconciliation_result.status.value if reconciliation_result is not None else None
        ),
        reconciliation_event_types=(
            tuple(event.event_type.value for event in reconciliation_result.detected_events)
            if reconciliation_result is not None
            else ()
        ),
        trading_should_pause=(
            reconciliation_result.trading_should_pause
            if reconciliation_result is not None
            else False
        ),
        requires_manual_acknowledgement=(
            reconciliation_result.requires_manual_acknowledgement
            if reconciliation_result is not None
            else False
        ),
        safety_pause_activated=(
            reconciliation_result.safety_pause_activated
            if reconciliation_result is not None
            else False
        ),
        no_retry_statement="No retry is available; exactly one live order attempt maximum.",
        no_cancel_statement="No automatic cancel is available in this command.",
        no_strategy_statement="No strategy loop, repeated trading, or market making is used.",
        blocking_reasons=tuple(blocking),
        warnings=tuple(warnings),
    )
    return write_manual_intervention_live_test_reports(config.settings, report, config.output_dir)


def write_manual_intervention_live_test_reports(
    settings: AppSettings,
    report: ManualInterventionLiveTestReport,
    output_dir: Path,
) -> ManualInterventionLiveTestReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    final_report = report
    if _unsafe_rendered_values(settings, report):
        final_report = replace(
            report,
            blocking_reasons=(
                *report.blocking_reasons,
                "Generated manual-intervention report contained sensitive values.",
            ),
            final_result="BLOCKED",
            trading_should_pause=True,
            requires_manual_acknowledgement=True,
        )
    for report_format in ("json", "markdown"):
        path = output_dir / manual_intervention_live_test_filename(report_format)
        path.write_text(
            f"{render_manual_intervention_live_test(final_report, report_format)}\n",
            encoding="utf-8",
        )
    return final_report


def render_manual_intervention_live_test(
    report: ManualInterventionLiveTestReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return render_manual_intervention_live_test_markdown(report)


def render_manual_intervention_live_test_markdown(
    report: ManualInterventionLiveTestReport,
) -> str:
    blockers = "\n".join(f"- {reason}" for reason in report.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    events = "\n".join(f"- {event}" for event in report.reconciliation_event_types) or "- None"
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Controlled Manual Intervention Live Test",
            "",
            f"- Final result: {report.final_result}",
            f"- Dry run: {report.dry_run}",
            f"- Order submitted: {report.order_submitted}",
            f"- Live attempt count: {report.live_attempt_count}",
            f"- Side/outcome: {report.side} {report.outcome}",
            f"- Order type: {report.order_type}",
            f"- Max notional: {report.max_notional}",
            f"- Token allowlisted: {report.token_allowlisted}",
            f"- Manual intervention detected: {report.manual_intervention_detected}",
            f"- Detection latency seconds: {report.detection_latency_seconds}",
            f"- Reconciliation status: {report.reconciliation_status}",
            f"- Trading should pause: {report.trading_should_pause}",
            f"- Requires manual acknowledgement: {report.requires_manual_acknowledgement}",
            f"- Safety pause activated: {report.safety_pause_activated}",
            "",
            "## Operator Instruction",
            "",
            f"- {report.operator_instruction}",
            "",
            "## Submitted Order State",
            "",
            f"- {report.submitted_order_state}",
            "",
            "## Reconciliation Events",
            "",
            events,
            "",
            "## Safety Statements",
            "",
            f"- {report.no_retry_statement}",
            f"- {report.no_cancel_statement}",
            f"- {report.no_strategy_statement}",
            "",
            "## Blocking Reasons",
            "",
            blockers,
            "",
            "## Warnings",
            "",
            warnings,
            "",
        )
    )


def manual_intervention_live_test_filename(report_format: ReportFormat) -> str:
    return {
        "json": "manual-intervention-live-test.json",
        "markdown": "manual-intervention-live-test.md",
    }[report_format]


def _static_blocking_reasons(
    config: ManualInterventionLiveTestConfig,
    kill_switch: KillSwitch,
    *,
    git_reader: GitReader | None,
) -> tuple[str, ...]:
    blocking: list[str] = []
    if not config.token_id.strip():
        blocking.append("A selected token is required.")
    if not _is_btc_updown_5m_slug(config.market_slug):
        blocking.append("Manual intervention live test is restricted to BTC Up/Down 5m.")
    if config.side != "BUY":
        blocking.append("Manual intervention live test supports BUY only in this phase.")
    if config.order_type not in {"FAK", "FOK"}:
        blocking.append("Only FAK or FOK orders are allowed.")
    if config.max_notional <= 0:
        blocking.append("max_notional must be positive.")
    if config.max_notional > MAX_MANUAL_INTERVENTION_NOTIONAL:
        blocking.append("max_notional above 1.00 is rejected.")
    if config.poll_attempts < 1:
        blocking.append("poll_attempts must be at least 1.")
    if config.poll_interval_seconds < 0:
        blocking.append("poll_interval_seconds must not be negative.")
    if not config.settings.polymarket_live_token_allowlist:
        blocking.append("POLYMARKET_LIVE_TOKEN_ALLOWLIST is required.")
    if config.token_id not in config.settings.polymarket_live_token_allowlist:
        blocking.append("Selected token is not allowlisted.")
    if config.dry_run:
        return tuple(blocking)
    if config.settings.trading_mode != TradingMode.LIVE:
        blocking.append("Real manual-intervention test requires TRADING_MODE=LIVE.")
    if not config.settings.live_trading_enabled:
        blocking.append("Real manual-intervention test requires LIVE_TRADING_ENABLED=true.")
    if not config.acknowledgement:
        blocking.append("Real submit requires --i-understand-this-places-one-real-order.")
    if not config.manual_intervention_acknowledgement:
        blocking.append("Real test requires --i-will-manually-cancel-or-close.")
    if config.settings.polymarket_private_key is None:
        blocking.append("Real submit requires POLYMARKET_PRIVATE_KEY.")
    if not config.settings.polymarket_funder_address:
        blocking.append("Real submit requires POLYMARKET_FUNDER_ADDRESS.")
    if kill_switch.is_active():
        reason = kill_switch.reason or "kill switch active"
        blocking.append(f"Kill switch is active: {reason}")
    if config.require_clean_git and _git_status(config.project_root, git_reader=git_reader).strip():
        blocking.append("Repository has uncommitted changes.")
    return tuple(blocking)


async def _poll_reconciliation(
    *,
    adapter: ManualInterventionAdapter,
    config: ManualInterventionLiveTestConfig,
    internal: InternalExpectedState,
    kill_switch: KillSwitch,
    clock: Clock,
    sleeper: Sleeper,
) -> tuple[ReconciliationResult, int]:
    manager = ReconciliationManager(safety_pause=KillSwitchSafetyPause(kill_switch))
    last_result: ReconciliationResult | None = None
    for attempt in range(1, config.poll_attempts + 1):
        checked_at = clock()
        actual = await _read_actual_state(adapter, config=config, checked_at=checked_at)
        result = manager.reconcile(
            ReconciliationInput(
                actual=actual,
                checked_at=checked_at,
                internal=internal,
                live_mode=True,
            )
        )
        last_result = result
        if result.manual_intervention_detected:
            return result, attempt
        if attempt < config.poll_attempts:
            await sleeper(config.poll_interval_seconds)
    if last_result is None:
        raise ManualInterventionLiveTestError("Reconciliation polling did not run.")
    return last_result, config.poll_attempts


async def _read_actual_state(
    adapter: ManualInterventionAdapter,
    *,
    config: ManualInterventionLiveTestConfig,
    checked_at: datetime,
) -> ActualAccountState:
    try:
        open_orders = _order_snapshots_from_external(
            await adapter.get_open_orders(token_id=config.token_id)
        )
        positions = _position_snapshots_from_external(
            await adapter.list_positions(
                market=(config.condition_id,) if config.condition_id else None,
                size_threshold=0,
            )
        )
    except PolymarketSecureAdapterError as error:
        return ActualAccountState(
            account_error_type=type(error).__name__,
            account_readable=False,
            open_orders_readable=False,
            positions_readable=False,
            read_at=checked_at,
        )
    return ActualAccountState(
        account_readable=True,
        open_orders=open_orders,
        open_orders_readable=True,
        positions=positions,
        positions_readable=True,
        read_at=checked_at,
    )


def _internal_state_from_submit(
    config: ManualInterventionLiveTestConfig,
    response_payload: dict[str, object],
    submitted_at: datetime,
) -> InternalExpectedState:
    order_id = _submitted_order_id(response_payload)
    filled_size = _filled_size(response_payload)
    status = _response_status(response_payload)
    if filled_size is not None and filled_size > 0:
        return InternalExpectedState(
            last_successful_account_read_at=submitted_at,
            positions=(
                PositionSnapshot(
                    token_id=config.token_id,
                    size=filled_size,
                    updated_at=submitted_at,
                ),
            ),
            updated_at=submitted_at,
        )
    return InternalExpectedState(
        last_successful_account_read_at=submitted_at,
        open_orders=(
            OrderSnapshot(
                order_id=order_id or "submitted-order",
                status=status,
                token_id=config.token_id,
                updated_at=submitted_at,
            ),
        ),
        updated_at=submitted_at,
    )


def _safe_submitted_order_state(response_payload: dict[str, object]) -> dict[str, object]:
    return {
        "filled_size": _safe_decimal_str(_filled_size(response_payload)),
        "order_id": _redacted_presence(_submitted_order_id(response_payload), "order_id"),
        "response_status": _response_status(response_payload),
    }


def _build_order_plan(
    config: ManualInterventionLiveTestConfig,
) -> ManualInterventionOrderPlan:
    risk_price = Decimal("1")
    risk_size = config.max_notional
    return ManualInterventionOrderPlan(
        amount=config.max_notional,
        risk_price=risk_price,
        risk_size=risk_size,
        shares=None,
    )


def _manual_intervention_risk_engine(
    settings: AppSettings,
    kill_switch: KillSwitch,
) -> RiskEngine:
    return RiskEngine(
        kill_switch=kill_switch,
        limits=RiskLimits(
            allow_live_trading=True,
            max_open_orders=settings.polymarket_live_max_open_orders,
            max_order_notional=min(
                settings.polymarket_live_max_order_notional,
                MAX_MANUAL_INTERVENTION_NOTIONAL,
            ),
            max_position_per_market=settings.polymarket_live_max_order_size,
            max_position_per_token=settings.polymarket_live_max_order_size,
        ),
    )


def _assert_geoblock_allows(status: GeoblockStatus) -> None:
    if status.status == "allowed" and status.blocked is False:
        return
    if status.status == "blocked" or status.blocked is True:
        raise ManualInterventionLiveTestError("Polymarket geoblock returned blocked=true.")
    raise ManualInterventionLiveTestError("Polymarket geoblock check failed closed.")


def _assert_identity_ready(identity: Any) -> None:
    payload = _model_or_mapping_to_dict(identity)
    if payload.get("signer_configured") is not True:
        raise ManualInterventionLiveTestError("signer is not configured.")
    if payload.get("funder_configured") is not True:
        raise ManualInterventionLiveTestError("funder is not configured.")


def _assert_balance_allowance_ready(balance_allowance: Any) -> None:
    payload = _model_or_mapping_to_dict(balance_allowance)
    balance = _decimal_or_none(payload.get("balance"))
    allowances = payload.get("allowances")
    if balance is None or balance <= 0:
        raise ManualInterventionLiveTestError("balance is missing or zero.")
    if not isinstance(allowances, dict):
        raise ManualInterventionLiveTestError("approval allowance is not readable.")
    if not any((_decimal_or_none(value) or Decimal("0")) > 0 for value in allowances.values()):
        raise ManualInterventionLiveTestError("approval allowance is missing or zero.")


def _order_snapshots_from_external(orders: list[Any]) -> tuple[OrderSnapshot, ...]:
    snapshots: list[OrderSnapshot] = []
    for index, order in enumerate(orders):
        order_id = _optional_text(_read_field(order, "id") or _read_field(order, "order_id"))
        snapshots.append(
            OrderSnapshot(
                order_id=order_id or f"external-order-{index}",
                status=_optional_text(_read_field(order, "status")),
                token_id=_optional_text(_read_field(order, "token_id")),
                created_by_system=False,
            )
        )
    return tuple(snapshots)


def _position_snapshots_from_external(
    positions: list[Any],
) -> tuple[PositionSnapshot, ...]:
    snapshots: list[PositionSnapshot] = []
    for index, position in enumerate(positions):
        token_id = _optional_text(_read_field(position, "token_id"))
        snapshots.append(
            PositionSnapshot(
                token_id=token_id or f"external-position-{index}",
                size=_decimal_or_none(_read_field(position, "size")) or Decimal("0"),
            )
        )
    return tuple(snapshots)


def _submitted_order_id(response_payload: dict[str, object]) -> str | None:
    return _optional_text(
        response_payload.get("order_id")
        or response_payload.get("id")
        or response_payload.get("orderID")
    )


def _response_status(response_payload: dict[str, object]) -> str | None:
    return _optional_text(response_payload.get("status"))


def _filled_size(response_payload: dict[str, object]) -> Decimal | None:
    for key in ("filled_size", "takingAmount", "taking_amount", "size_matched"):
        value = _decimal_or_none(response_payload.get(key))
        if value is not None:
            return value
    status = (_response_status(response_payload) or "").lower()
    if status in {"matched", "filled"}:
        return _decimal_or_none(response_payload.get("size"))
    return None


def _unsafe_rendered_values(
    settings: AppSettings,
    report: ManualInterventionLiveTestReport,
) -> tuple[str, ...]:
    rendered = render_manual_intervention_live_test(
        report,
        "json",
    ) + render_manual_intervention_live_test(report, "markdown")
    unsafe: list[str] = []
    for value in _sensitive_values(settings):
        if value in rendered:
            unsafe.append(value)
    if _TX_HASH_RE.search(rendered):
        unsafe.append("transaction_hash")
    if _ADDRESS_RE.search(rendered):
        unsafe.append("wallet_address")
    if _LONG_TOKEN_RE.search(rendered):
        unsafe.append("token_id")
    return tuple(unsafe)


def _sensitive_values(settings: AppSettings) -> tuple[str, ...]:
    values: list[str] = []
    if settings.polymarket_private_key is not None:
        values.append(settings.polymarket_private_key.get_secret_value())
    values.extend(
        value
        for value in (
            settings.polymarket_wallet_address,
            settings.polymarket_funder_address,
            *settings.polymarket_live_token_allowlist,
        )
        if value
    )
    return tuple(value for value in values if len(value) >= 4)


def _model_or_mapping_to_dict(source: object) -> dict[str, object]:
    if hasattr(source, "to_dict"):
        return dict(source.to_dict())
    if hasattr(source, "model_dump"):
        return dict(source.model_dump(mode="python"))
    if isinstance(source, dict):
        return dict(source)
    return {
        field_name: getattr(source, field_name)
        for field_name in dir(source)
        if not field_name.startswith("_") and not callable(getattr(source, field_name))
    }


def _read_field(source: Any, field_name: str) -> object:
    if source is None:
        return None
    if hasattr(source, "model_dump"):
        return source.model_dump(mode="python").get(field_name)
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_decimal_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _redacted_presence(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    return f"<redacted-{label}-present>"


def _is_btc_updown_5m_slug(market_slug: str) -> bool:
    normalized = market_slug.lower().replace("_", "-")
    return "btc" in normalized and "5m" in normalized and (
        "updown" in normalized or ("up" in normalized and "down" in normalized)
    )


def _git_status(project_root: Path, *, git_reader: GitReader | None) -> str:
    if git_reader is not None:
        return git_reader(project_root.resolve(), ("git", "status", "--short"))
    result = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        cwd=project_root.resolve(),
        text=True,
        timeout=5,
    )
    return result.stdout


__all__ = [
    "ManualInterventionLiveTestConfig",
    "ManualInterventionLiveTestError",
    "ManualInterventionLiveTestReport",
    "manual_intervention_live_test_filename",
    "render_manual_intervention_live_test",
    "render_manual_intervention_live_test_markdown",
    "run_manual_intervention_live_test",
    "write_manual_intervention_live_test_reports",
]
