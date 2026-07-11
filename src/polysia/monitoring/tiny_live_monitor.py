from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol

from polysia.adapters.polymarket.geoblock import GeoblockStatus, PreLiveOrderGeoblockCheck
from polysia.adapters.polymarket.secure import (
    FUNDER_ADDRESS_ENV,
    PRIVATE_KEY_ENV,
    SIGNATURE_TYPE_ENV,
    WALLET_ADDRESS_ENV,
    BalanceAssetType,
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.config.settings import AppSettings
from polysia.monitoring.readiness import build_deployment_readiness
from polysia.risk.kill_switch import KillSwitch

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
MonitorStatus = Literal["ready", "warning", "blocked"]
ReportFormat = Literal["json", "markdown"]

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
_LONG_TOKEN_RE = re.compile(r"\b[0-9]{30,}\b")


def utc_now() -> datetime:
    return datetime.now(UTC)


class TinyLiveMonitorAccountAdapter(Protocol):
    @property
    def is_connected(self) -> bool:
        """Whether the authenticated adapter is connected."""

    async def connect(self) -> None:
        """Connect to read-only authenticated account endpoints."""

    async def close(self) -> None:
        """Close authenticated resources."""

    def identity(self) -> Any:
        """Return sanitized signer/funder identity diagnostics."""

    async def get_balance_allowance(
        self,
        *,
        asset_type: BalanceAssetType,
        token_id: str | None = None,
    ) -> Any:
        """Read collateral balance and approval metadata."""

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        """Read open orders."""

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        """Read position count."""


class TinyLiveMonitorGeoblockCheck(Protocol):
    async def check(self) -> GeoblockStatus:
        """Return sanitized geoblock status."""


@dataclass(frozen=True, slots=True)
class TinyLiveMonitorConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path
    token_id: str | None = None
    market_slug: str | None = None
    auto_btc_5m: bool = False
    max_cycles: int = 1
    interval_seconds: int = 30
    redact_secrets: bool = True

    def __post_init__(self) -> None:
        if self.max_cycles < 1:
            raise ValueError("max_cycles must be at least 1.")
        if self.interval_seconds < 30:
            raise ValueError("interval_seconds must be at least 30 seconds.")


@dataclass(frozen=True, slots=True)
class TinyLiveMonitorCycle:
    cycle_number: int
    timestamp: datetime
    status: MonitorStatus
    trading_mode: str
    live_trading_enabled: bool
    kill_switch_active: bool
    geoblock_status: dict[str, object]
    signer_configured: bool
    funder_configured: bool
    balance_readable: bool
    approval_readable: bool
    open_orders_readable: bool
    open_order_count: int | None
    account_status_readable: bool
    account_status_summary: dict[str, object]
    deployment_readiness_status: str | None
    post_live_reconciliation_status: str | None
    observability_snapshot_status: str | None
    last_tiny_live_execution_summary: dict[str, object]
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "account_status_readable": self.account_status_readable,
            "account_status_summary": self.account_status_summary,
            "approval_readable": self.approval_readable,
            "balance_readable": self.balance_readable,
            "blocking_reasons": list(self.blocking_reasons),
            "cycle_number": self.cycle_number,
            "deployment_readiness_status": self.deployment_readiness_status,
            "funder_configured": self.funder_configured,
            "geoblock_status": self.geoblock_status,
            "kill_switch_active": self.kill_switch_active,
            "last_tiny_live_execution_summary": self.last_tiny_live_execution_summary,
            "live_trading_enabled": self.live_trading_enabled,
            "observability_snapshot_status": self.observability_snapshot_status,
            "open_order_count": self.open_order_count,
            "open_orders_readable": self.open_orders_readable,
            "post_live_reconciliation_status": self.post_live_reconciliation_status,
            "signer_configured": self.signer_configured,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "trading_mode": self.trading_mode,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class TinyLiveMonitorReport:
    timestamp: datetime
    status: MonitorStatus
    max_cycles: int
    interval_seconds: int
    redact_secrets: bool
    selected_market_slug: str | None
    selected_token_configured: bool
    token_allowlisted: bool | None
    cycles: tuple[TinyLiveMonitorCycle, ...]
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    no_live_trading_statement: str

    def to_dict(self) -> dict[str, object]:
        return {
            "blocking_reasons": list(self.blocking_reasons),
            "cycles": [cycle.to_dict() for cycle in self.cycles],
            "interval_seconds": self.interval_seconds,
            "max_cycles": self.max_cycles,
            "no_live_trading_statement": self.no_live_trading_statement,
            "redact_secrets": self.redact_secrets,
            "selected_market_slug": self.selected_market_slug,
            "selected_token_configured": self.selected_token_configured,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "token_allowlisted": self.token_allowlisted,
            "warnings": list(self.warnings),
        }


async def build_tiny_live_monitor(
    config: TinyLiveMonitorConfig,
    *,
    account_adapter: TinyLiveMonitorAccountAdapter | None = None,
    geoblock_check: TinyLiveMonitorGeoblockCheck | None = None,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    sleep: Sleeper = asyncio.sleep,
) -> TinyLiveMonitorReport:
    """Build a sanitized read-only tiny live monitor report."""

    cycles: list[TinyLiveMonitorCycle] = []
    for cycle_number in range(1, config.max_cycles + 1):
        cycles.append(
            await _build_cycle(
                config,
                cycle_number=cycle_number,
                account_adapter=account_adapter,
                geoblock_check=geoblock_check,
                kill_switch=kill_switch,
                clock=clock,
            )
        )
        if cycle_number < config.max_cycles:
            await sleep(config.interval_seconds)

    blocking = tuple(dict.fromkeys(reason for cycle in cycles for reason in cycle.blocking_reasons))
    warnings = tuple(dict.fromkeys(warning for cycle in cycles for warning in cycle.warnings))
    report = TinyLiveMonitorReport(
        timestamp=clock(),
        status=_classify(list(blocking), list(warnings)),
        max_cycles=config.max_cycles,
        interval_seconds=config.interval_seconds,
        redact_secrets=config.redact_secrets,
        selected_market_slug=config.market_slug,
        selected_token_configured=bool(config.token_id),
        token_allowlisted=_token_allowlisted(config),
        cycles=tuple(cycles),
        blocking_reasons=blocking,
        warnings=warnings,
        no_live_trading_statement=(
            "Tiny live monitor is read-only and never submits orders, cancels orders, "
            "runs strategy automation, retries, or market makes."
        ),
    )

    unsafe = _unsafe_rendered_values(config, report)
    if unsafe:
        blocking = (
            *blocking,
            "Generated tiny live monitor artifacts contained sensitive values.",
        )
        report = replace(
            report,
            blocking_reasons=blocking,
            status="blocked",
        )
    return report


async def write_tiny_live_monitor_reports(
    config: TinyLiveMonitorConfig,
    *,
    account_adapter: TinyLiveMonitorAccountAdapter | None = None,
    geoblock_check: TinyLiveMonitorGeoblockCheck | None = None,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    sleep: Sleeper = asyncio.sleep,
) -> TinyLiveMonitorReport:
    report = await build_tiny_live_monitor(
        config,
        account_adapter=account_adapter,
        geoblock_check=geoblock_check,
        kill_switch=kill_switch,
        clock=clock,
        sleep=sleep,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    for report_format in ("json", "markdown"):
        path = config.output_dir / tiny_live_monitor_filename(report_format)
        path.write_text(
            f"{render_tiny_live_monitor(report, report_format)}\n",
            encoding="utf-8",
        )
    return report


def render_tiny_live_monitor(
    report: TinyLiveMonitorReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return render_tiny_live_monitor_markdown(report)


def render_tiny_live_monitor_markdown(report: TinyLiveMonitorReport) -> str:
    blockers = "\n".join(f"- {reason}" for reason in report.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    latest = report.cycles[-1] if report.cycles else None
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Tiny Live Monitor",
            "",
            f"- Status: {report.status}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Max cycles: {report.max_cycles}",
            f"- Interval seconds: {report.interval_seconds}",
            f"- Redact secrets: {report.redact_secrets}",
            f"- Selected market slug: {report.selected_market_slug}",
            f"- Selected token configured: {report.selected_token_configured}",
            f"- Token allowlisted: {report.token_allowlisted}",
            "",
            "## Latest Cycle",
            "",
            _cycle_table(latest),
            "",
            "## Blocking Reasons",
            "",
            blockers,
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Live Trading",
            "",
            report.no_live_trading_statement,
            "",
        )
    )


def tiny_live_monitor_filename(report_format: ReportFormat) -> str:
    return {
        "json": "tiny-live-monitor.json",
        "markdown": "tiny-live-monitor.md",
    }[report_format]


async def _build_cycle(
    config: TinyLiveMonitorConfig,
    *,
    cycle_number: int,
    account_adapter: TinyLiveMonitorAccountAdapter | None,
    geoblock_check: TinyLiveMonitorGeoblockCheck | None,
    kill_switch: KillSwitch | None,
    clock: Clock,
) -> TinyLiveMonitorCycle:
    active_kill_switch = kill_switch or KillSwitch()
    geoblock = await _read_geoblock_status(geoblock_check)
    account = await _read_account_summary(config, account_adapter)
    deployment_status = _deployment_readiness_status(config.settings, config.project_root)
    post_live_status = _artifact_status(
        config.output_dir / "post-live-reconciliation.json",
        "reconciliation_status",
    )
    observability_status = _artifact_status(
        config.output_dir / "observability-snapshot.json",
        "status",
    )
    last_tiny = _last_tiny_live_summary(config.output_dir / "tiny_live_execution.json")

    blocking: list[str] = []
    warnings: list[str] = []
    if active_kill_switch.is_active():
        blocking.append("Kill switch is active.")
    if geoblock.get("blocked") is True:
        blocking.append("Geoblock status is blocked.")
    if account["account_readable"] is not True:
        warnings.append("Account status could not be read.")
    if account["open_orders_readable"] is not True:
        warnings.append("Open orders could not be read.")
    if geoblock.get("status") in {"error", "unavailable"}:
        warnings.append("Geoblock status could not be confirmed.")

    return TinyLiveMonitorCycle(
        cycle_number=cycle_number,
        timestamp=clock(),
        status=_classify(blocking, warnings),
        trading_mode=config.settings.trading_mode.value,
        live_trading_enabled=config.settings.live_trading_enabled,
        kill_switch_active=active_kill_switch.is_active(),
        geoblock_status=geoblock,
        signer_configured=account["signer_configured"] is True,
        funder_configured=account["funder_configured"] is True,
        balance_readable=account["balance_readable"] is True,
        approval_readable=account["approval_readable"] is True,
        open_orders_readable=account["open_orders_readable"] is True,
        open_order_count=_optional_int(account.get("open_order_count")),
        account_status_readable=account["account_readable"] is True,
        account_status_summary=account,
        deployment_readiness_status=deployment_status,
        post_live_reconciliation_status=post_live_status,
        observability_snapshot_status=observability_status,
        last_tiny_live_execution_summary=last_tiny,
        blocking_reasons=tuple(blocking),
        warnings=tuple(warnings),
    )


async def _read_geoblock_status(
    geoblock_check: TinyLiveMonitorGeoblockCheck | None,
) -> dict[str, object]:
    active_check = geoblock_check or PreLiveOrderGeoblockCheck()
    try:
        return active_check_to_dict(await active_check.check())
    except Exception as error:  # noqa: BLE001
        return {
            "blocked": None,
            "error_type": type(error).__name__,
            "status": "error",
        }


def active_check_to_dict(status: GeoblockStatus) -> dict[str, object]:
    safe = status.to_safe_dict()
    return {
        "blocked": _optional_bool(safe.get("blocked")),
        "error_type": _optional_str(safe.get("error_type")),
        "status": _optional_str(safe.get("status")) or "unavailable",
    }


async def _read_account_summary(
    config: TinyLiveMonitorConfig,
    adapter: TinyLiveMonitorAccountAdapter | None,
) -> dict[str, object]:
    settings = config.settings
    signer_configured = settings.polymarket_private_key is not None
    funder_configured = bool(settings.polymarket_funder_address)
    if adapter is None and not signer_configured:
        return _empty_account_summary(
            signer_configured=signer_configured,
            funder_configured=funder_configured,
            error_type="not_configured",
        )

    owns_adapter = adapter is None
    active_adapter = adapter or PolymarketSecureAdapter()
    _apply_secure_env_from_settings(settings)
    try:
        if not active_adapter.is_connected:
            await active_adapter.connect()
        identity = _safe_identity(active_adapter.identity())
        signer_configured = identity["signer_configured"]
        funder_configured = identity["funder_configured"]
        collateral = await active_adapter.get_balance_allowance(asset_type="COLLATERAL")
        balance = _safe_balance_allowance(collateral)
        open_orders_readable, open_order_count = await _read_open_orders(
            active_adapter,
            token_id=config.token_id,
            market_slug=config.market_slug,
        )
        positions_readable, positions_count = await _read_positions(active_adapter)
        return {
            "account_readable": True,
            "approval_readable": balance["approval_readable"],
            "balance_readable": balance["balance_readable"],
            "error_type": None,
            "funder_configured": funder_configured,
            "open_order_count": open_order_count,
            "open_orders_readable": open_orders_readable,
            "positions_count": positions_count,
            "positions_readable": positions_readable,
            "positive_approval_count": balance["positive_approval_count"],
            "signer_configured": signer_configured,
        }
    except PolymarketSecureAdapterError as error:
        return _empty_account_summary(
            signer_configured=signer_configured,
            funder_configured=funder_configured,
            error_type=type(error).__name__,
        )
    finally:
        if owns_adapter:
            await active_adapter.close()


async def _read_open_orders(
    adapter: TinyLiveMonitorAccountAdapter,
    *,
    token_id: str | None,
    market_slug: str | None,
) -> tuple[bool, int | None]:
    try:
        orders = await adapter.get_open_orders(token_id=token_id, market=market_slug)
    except PolymarketSecureAdapterError:
        return False, None
    return True, len(orders)


async def _read_positions(
    adapter: TinyLiveMonitorAccountAdapter,
) -> tuple[bool, int | None]:
    try:
        positions = await adapter.list_positions(size_threshold=0)
    except PolymarketSecureAdapterError:
        return False, None
    return True, len(positions)


def _empty_account_summary(
    *,
    signer_configured: bool,
    funder_configured: bool,
    error_type: str,
) -> dict[str, object]:
    return {
        "account_readable": False,
        "approval_readable": False,
        "balance_readable": False,
        "error_type": error_type,
        "funder_configured": funder_configured,
        "open_order_count": None,
        "open_orders_readable": False,
        "positions_count": None,
        "positions_readable": False,
        "positive_approval_count": 0,
        "signer_configured": signer_configured,
    }


def _safe_identity(identity: Any) -> dict[str, bool]:
    payload = _model_or_mapping_to_dict(identity)
    return {
        "funder_configured": payload.get("funder_configured") is True,
        "signer_configured": payload.get("signer_configured") is True,
    }


def _safe_balance_allowance(balance_allowance: object) -> dict[str, object]:
    data = _model_or_mapping_to_dict(balance_allowance)
    allowances = data.get("allowances")
    positive_approval_count = 0
    if isinstance(allowances, dict):
        for value in allowances.values():
            parsed = _parse_optional_decimal(value)
            if parsed is not None and parsed > 0:
                positive_approval_count += 1
    return {
        "approval_readable": isinstance(allowances, dict),
        "balance_readable": data.get("balance") is not None,
        "positive_approval_count": positive_approval_count,
    }


def _last_tiny_live_summary(path: Path) -> dict[str, object]:
    payload = _read_mapping(path)
    if not payload:
        return {"available": False, "final_result": None}
    return {
        "available": True,
        "dry_run": _optional_bool(payload.get("dry_run")),
        "final_result": _optional_str(payload.get("final_result")),
        "live_attempt_count": _optional_int(payload.get("live_attempt_count")),
        "max_notional": _optional_str(payload.get("max_notional")),
        "order_submitted": _optional_bool(payload.get("order_submitted")),
        "order_type": _optional_str(payload.get("order_type")),
        "outcome": _optional_str(payload.get("outcome")),
        "side": _optional_str(payload.get("side")),
    }


def _deployment_readiness_status(settings: AppSettings, project_root: Path) -> str | None:
    try:
        return build_deployment_readiness(
            settings=settings,
            project_root=project_root,
        ).status
    except (OSError, ValueError):
        return None


def _artifact_status(path: Path, key: str) -> str | None:
    payload = _read_mapping(path)
    return _optional_str(payload.get(key))


def _read_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cycle_table(cycle: TinyLiveMonitorCycle | None) -> str:
    if cycle is None:
        return "| Metric | Value |\n| --- | --- |\n| status | unavailable |"
    rows = {
        "account_status_readable": cycle.account_status_readable,
        "approval_readable": cycle.approval_readable,
        "balance_readable": cycle.balance_readable,
        "cycle_number": cycle.cycle_number,
        "deployment_readiness_status": cycle.deployment_readiness_status,
        "funder_configured": cycle.funder_configured,
        "geoblock_blocked": cycle.geoblock_status.get("blocked"),
        "geoblock_status": cycle.geoblock_status.get("status"),
        "kill_switch_active": cycle.kill_switch_active,
        "last_tiny_result": cycle.last_tiny_live_execution_summary.get("final_result"),
        "live_trading_enabled": cycle.live_trading_enabled,
        "observability_snapshot_status": cycle.observability_snapshot_status,
        "open_order_count": cycle.open_order_count,
        "open_orders_readable": cycle.open_orders_readable,
        "post_live_reconciliation_status": cycle.post_live_reconciliation_status,
        "signer_configured": cycle.signer_configured,
        "status": cycle.status,
        "trading_mode": cycle.trading_mode,
    }
    table_rows = [f"| {key} | {value} |" for key, value in rows.items()]
    return "\n".join(("| Metric | Value |", "| --- | --- |", *table_rows))


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


def _parse_optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    if isinstance(value, (bool, int, Decimal)):
        return str(value)
    return None


def _token_allowlisted(config: TinyLiveMonitorConfig) -> bool | None:
    if not config.token_id:
        return None
    return config.token_id in config.settings.polymarket_live_token_allowlist


def _classify(blocking: list[str], warnings: list[str]) -> MonitorStatus:
    if blocking:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"


def _unsafe_rendered_values(
    config: TinyLiveMonitorConfig,
    report: TinyLiveMonitorReport,
) -> tuple[str, ...]:
    rendered = render_tiny_live_monitor(report, "json") + render_tiny_live_monitor(
        report,
        "markdown",
    )
    unsafe: list[str] = []
    for value in _sensitive_values(config):
        if value in rendered:
            unsafe.append(value)
    if _TX_HASH_RE.search(rendered):
        unsafe.append("transaction_hash")
    if _ADDRESS_RE.search(rendered):
        unsafe.append("wallet_address")
    if _LONG_TOKEN_RE.search(rendered):
        unsafe.append("token_id")
    return tuple(unsafe)


def _sensitive_values(config: TinyLiveMonitorConfig) -> tuple[str, ...]:
    settings = config.settings
    values: list[str] = []
    if settings.polymarket_private_key is not None:
        values.append(settings.polymarket_private_key.get_secret_value())
    values.extend(
        value
        for value in (
            settings.polymarket_wallet_address,
            settings.polymarket_funder_address,
            config.token_id,
            *settings.polymarket_live_token_allowlist,
        )
        if value
    )
    return tuple(value for value in values if len(value) >= 4)


def _apply_secure_env_from_settings(settings: AppSettings) -> None:
    if os.environ.get(PRIVATE_KEY_ENV) is None and settings.polymarket_private_key is not None:
        os.environ[PRIVATE_KEY_ENV] = settings.polymarket_private_key.get_secret_value()
    if os.environ.get(FUNDER_ADDRESS_ENV) is None and settings.polymarket_funder_address:
        os.environ[FUNDER_ADDRESS_ENV] = settings.polymarket_funder_address
    if os.environ.get(WALLET_ADDRESS_ENV) is None and settings.polymarket_wallet_address:
        os.environ[WALLET_ADDRESS_ENV] = settings.polymarket_wallet_address
    if (
        os.environ.get(SIGNATURE_TYPE_ENV) is None
        and settings.polymarket_signature_type is not None
    ):
        os.environ[SIGNATURE_TYPE_ENV] = str(settings.polymarket_signature_type)


__all__ = [
    "TinyLiveMonitorAccountAdapter",
    "TinyLiveMonitorConfig",
    "TinyLiveMonitorCycle",
    "TinyLiveMonitorReport",
    "build_tiny_live_monitor",
    "render_tiny_live_monitor",
    "render_tiny_live_monitor_markdown",
    "tiny_live_monitor_filename",
    "write_tiny_live_monitor_reports",
]
