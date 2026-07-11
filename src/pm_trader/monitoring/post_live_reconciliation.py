from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any, Literal, Protocol

from pm_trader.adapters.polymarket_secure import (
    FUNDER_ADDRESS_ENV,
    PRIVATE_KEY_ENV,
    SIGNATURE_TYPE_ENV,
    WALLET_ADDRESS_ENV,
    BalanceAssetType,
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from pm_trader.config.settings import AppSettings
from pm_trader.monitoring.readiness import build_deployment_readiness
from pm_trader.risk.kill_switch import KillSwitch

Clock = Callable[[], datetime]
GitRunner = Callable[[Path, tuple[str, ...]], str]
ReconciliationStatus = Literal["ready", "warning", "blocked"]
ReportFormat = Literal["json", "markdown"]

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")


def utc_now() -> datetime:
    return datetime.now(UTC)


class PostLiveAccountAdapter(Protocol):
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
        """Read open order count."""

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        """Read position count."""


@dataclass(frozen=True, slots=True)
class PostLiveReconciliationConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class PostLiveReconciliationReport:
    timestamp: datetime
    branch: str | None
    latest_commit: str | None
    git_clean: bool | None
    trading_mode: str
    live_trading_enabled: bool
    kill_switch_active: bool
    deployment_readiness_status: str | None
    final_handoff_status: str
    tiny_live_execution_summary: dict[str, object]
    live_attempt_count: int | None
    order_submitted: bool | None
    order_type: str | None
    side: str | None
    outcome: str | None
    max_notional: str | None
    open_order_count: int | None
    open_orders_readable: bool
    account_status_summary: dict[str, object]
    geoblock_status: dict[str, object]
    signer_configured: bool
    funder_configured: bool
    token_allowlist_count: int
    reconciliation_status: ReconciliationStatus
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    operator_next_steps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "account_status_summary": self.account_status_summary,
            "blocking_reasons": list(self.blocking_reasons),
            "branch": self.branch,
            "deployment_readiness_status": self.deployment_readiness_status,
            "final_handoff_status": self.final_handoff_status,
            "funder_configured": self.funder_configured,
            "geoblock_status": self.geoblock_status,
            "git_clean": self.git_clean,
            "kill_switch_active": self.kill_switch_active,
            "latest_commit": self.latest_commit,
            "live_attempt_count": self.live_attempt_count,
            "live_trading_enabled": self.live_trading_enabled,
            "max_notional": self.max_notional,
            "open_order_count": self.open_order_count,
            "open_orders_readable": self.open_orders_readable,
            "operator_next_steps": list(self.operator_next_steps),
            "order_submitted": self.order_submitted,
            "order_type": self.order_type,
            "outcome": self.outcome,
            "reconciliation_status": self.reconciliation_status,
            "side": self.side,
            "signer_configured": self.signer_configured,
            "timestamp": self.timestamp.isoformat(),
            "tiny_live_execution_summary": self.tiny_live_execution_summary,
            "token_allowlist_count": self.token_allowlist_count,
            "trading_mode": self.trading_mode,
            "warnings": list(self.warnings),
        }


async def build_post_live_reconciliation(
    config: PostLiveReconciliationConfig,
    *,
    account_adapter: PostLiveAccountAdapter | None = None,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> PostLiveReconciliationReport:
    """Build a sanitized post-live reconciliation report without submit/cancel calls."""

    root = config.project_root.resolve()
    output_dir = config.output_dir
    active_kill_switch = kill_switch or KillSwitch()
    git = _git_snapshot(root, git_runner=git_runner)
    tiny_summary = _read_tiny_live_execution_summary(output_dir / "tiny_live_execution.json")
    account_summary = await _read_account_summary(config.settings, account_adapter)
    deployment_status = _deployment_readiness_status(config.settings, root)

    blocking: list[str] = []
    warnings: list[str] = []
    if active_kill_switch.is_active():
        blocking.append("Kill switch is active.")
    if config.settings.live_trading_enabled:
        blocking.append("LIVE_TRADING_ENABLED remains true after post-live testing.")
    if account_summary["open_orders_readable"] is not True:
        warnings.append("Open orders could not be read.")
    if account_summary["account_readable"] is not True:
        warnings.append("Account status could not be read.")
    if account_summary["open_order_count"] not in (None, 0):
        blocking.append("Open orders remain after tiny live execution.")
    if tiny_summary["available"] is not True:
        warnings.append("Tiny live execution report was not found.")
    elif _optional_int(tiny_summary.get("live_attempt_count")) not in (0, 1):
        blocking.append("Tiny live execution report shows more than one live attempt.")

    report = PostLiveReconciliationReport(
        timestamp=clock(),
        branch=_optional_str(git["branch"]),
        latest_commit=_optional_str(git["commit"]),
        git_clean=_optional_bool(git["clean"]),
        trading_mode=config.settings.trading_mode.value,
        live_trading_enabled=config.settings.live_trading_enabled,
        kill_switch_active=active_kill_switch.is_active(),
        deployment_readiness_status=deployment_status,
        final_handoff_status=_final_handoff_status(output_dir / "final-handoff.md"),
        tiny_live_execution_summary=tiny_summary,
        live_attempt_count=_optional_int(tiny_summary.get("live_attempt_count")),
        order_submitted=_optional_bool(tiny_summary.get("order_submitted")),
        order_type=_optional_str(tiny_summary.get("order_type")),
        side=_optional_str(tiny_summary.get("side")),
        outcome=_optional_str(tiny_summary.get("outcome")),
        max_notional=_optional_str(tiny_summary.get("max_notional")),
        open_order_count=_optional_int(account_summary.get("open_order_count")),
        open_orders_readable=account_summary["open_orders_readable"] is True,
        account_status_summary=account_summary,
        geoblock_status=_safe_geoblock_status(tiny_summary.get("geoblock_status")),
        signer_configured=account_summary["signer_configured"] is True,
        funder_configured=account_summary["funder_configured"] is True,
        token_allowlist_count=len(config.settings.polymarket_live_token_allowlist),
        reconciliation_status=_classify(blocking, warnings),
        blocking_reasons=tuple(blocking),
        warnings=tuple(warnings),
        operator_next_steps=_operator_next_steps(blocking, warnings),
    )

    unsafe = _unsafe_rendered_values(config.settings, report)
    if unsafe:
        blocking.append("Generated post-live reconciliation artifacts contained sensitive values.")
        report = replace(
            report,
            blocking_reasons=tuple(blocking),
            reconciliation_status=_classify(blocking, warnings),
            operator_next_steps=_operator_next_steps(blocking, warnings),
        )
    return report


async def write_post_live_reconciliation_reports(
    config: PostLiveReconciliationConfig,
    *,
    account_adapter: PostLiveAccountAdapter | None = None,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> PostLiveReconciliationReport:
    report = await build_post_live_reconciliation(
        config,
        account_adapter=account_adapter,
        kill_switch=kill_switch,
        clock=clock,
        git_runner=git_runner,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    for report_format in ("json", "markdown"):
        path = config.output_dir / post_live_reconciliation_filename(report_format)
        path.write_text(
            f"{render_post_live_reconciliation(report, report_format)}\n",
            encoding="utf-8",
        )
    return report


def render_post_live_reconciliation(
    report: PostLiveReconciliationReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return render_post_live_reconciliation_markdown(report)


def render_post_live_reconciliation_markdown(
    report: PostLiveReconciliationReport,
) -> str:
    blockers = "\n".join(f"- {reason}" for reason in report.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    next_steps = "\n".join(f"- {step}" for step in report.operator_next_steps) or "- None"
    return "\n".join(
        (
            "# Polymarket Post-Live Reconciliation",
            "",
            f"- Reconciliation status: {report.reconciliation_status}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Branch: {report.branch}",
            f"- Latest commit: {report.latest_commit}",
            f"- Git clean: {report.git_clean}",
            f"- Trading mode: {report.trading_mode}",
            f"- Live trading enabled: {report.live_trading_enabled}",
            f"- Kill switch active: {report.kill_switch_active}",
            f"- Deployment readiness: {report.deployment_readiness_status}",
            f"- Final handoff: {report.final_handoff_status}",
            "",
            "## Tiny Live Summary",
            "",
            f"- Live attempt count: {report.live_attempt_count}",
            f"- Order submitted: {report.order_submitted}",
            f"- Order type: {report.order_type}",
            f"- Side/outcome: {report.side} {report.outcome}",
            f"- Max notional: {report.max_notional}",
            f"- Geoblock status: {report.geoblock_status.get('status')}",
            "",
            "## Account Summary",
            "",
            f"- Signer configured: {report.signer_configured}",
            f"- Funder configured: {report.funder_configured}",
            f"- Token allowlist count: {report.token_allowlist_count}",
            f"- Account readable: {report.account_status_summary.get('account_readable')}",
            f"- Balance readable: {report.account_status_summary.get('balance_readable')}",
            f"- Approval readable: {report.account_status_summary.get('approval_readable')}",
            "- Positive approval count: "
            f"{report.account_status_summary.get('positive_approval_count')}",
            f"- Open orders readable: {report.open_orders_readable}",
            f"- Open order count: {report.open_order_count}",
            f"- Positions readable: {report.account_status_summary.get('positions_readable')}",
            f"- Positions count: {report.account_status_summary.get('positions_count')}",
            "",
            "## Blocking Reasons",
            "",
            blockers,
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Operator Next Steps",
            "",
            next_steps,
            "",
        )
    )


def render_post_live_reconciliation_html_fragment(
    report: PostLiveReconciliationReport,
) -> str:
    return escape(render_post_live_reconciliation_markdown(report))


def post_live_reconciliation_filename(report_format: ReportFormat) -> str:
    return {
        "json": "post-live-reconciliation.json",
        "markdown": "post-live-reconciliation.md",
    }[report_format]


async def _read_account_summary(
    settings: AppSettings,
    adapter: PostLiveAccountAdapter | None,
) -> dict[str, object]:
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
        signer_configured = identity.get("signer_configured") is True
        funder_configured = identity.get("funder_configured") is True
        collateral = await active_adapter.get_balance_allowance(asset_type="COLLATERAL")
        balance = _safe_balance_allowance(collateral)
        try:
            open_orders = await active_adapter.get_open_orders()
            open_orders_readable = True
            open_order_count = len(open_orders)
        except PolymarketSecureAdapterError:
            open_orders_readable = False
            open_order_count = None
        try:
            positions = await active_adapter.list_positions(size_threshold=0)
            positions_readable = True
            positions_count = len(positions)
        except PolymarketSecureAdapterError:
            positions_readable = False
            positions_count = None
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


def _read_tiny_live_execution_summary(path: Path) -> dict[str, object]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "available": False,
            "final_result": None,
            "geoblock_status": None,
            "live_attempt_count": None,
            "max_notional": None,
            "order_submitted": None,
            "order_type": None,
            "outcome": None,
            "side": None,
        }
    return {
        "available": True,
        "dry_run": _optional_bool(payload.get("dry_run")),
        "final_result": _optional_str(payload.get("final_result")),
        "geoblock_status": _safe_geoblock_status(payload.get("geoblock_status")),
        "live_attempt_count": _optional_int(payload.get("live_attempt_count")),
        "max_notional": _optional_str(payload.get("max_notional")),
        "no_retry_statement": _optional_str(payload.get("no_retry_statement")),
        "order_submitted": _optional_bool(payload.get("order_submitted")),
        "order_type": _optional_str(payload.get("order_type")),
        "outcome": _optional_str(payload.get("outcome")),
        "side": _optional_str(payload.get("side")),
    }


def _safe_geoblock_status(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"blocked": None, "status": "unavailable"}
    return {
        "blocked": _optional_bool(value.get("blocked")),
        "status": _optional_str(value.get("status")) or "unavailable",
    }


def _deployment_readiness_status(settings: AppSettings, project_root: Path) -> str | None:
    try:
        return build_deployment_readiness(
            settings=settings,
            project_root=project_root,
        ).status
    except (OSError, ValueError):
        return None


def _final_handoff_status(path: Path) -> str:
    return "available" if path.is_file() else "missing"


def _git_snapshot(project_root: Path, *, git_runner: GitRunner | None) -> dict[str, object]:
    runner = git_runner or _run_git
    try:
        branch = runner(project_root, ("git", "branch", "--show-current")).strip()
        commit = runner(project_root, ("git", "rev-parse", "--short", "HEAD")).strip()
        status = runner(project_root, ("git", "status", "--short")).strip()
    except (OSError, subprocess.SubprocessError):
        return {"branch": None, "clean": None, "commit": None}
    return {
        "branch": branch or "detached",
        "clean": status == "",
        "commit": commit or None,
    }


def _run_git(project_root: Path, command: tuple[str, ...]) -> str:
    result = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        cwd=project_root,
        text=True,
        timeout=5,
    )
    return result.stdout


def _read_json(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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


def _classify(blocking: list[str], warnings: list[str]) -> ReconciliationStatus:
    if blocking:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"


def _operator_next_steps(
    blocking: list[str],
    warnings: list[str],
) -> tuple[str, ...]:
    if blocking:
        return (
            "Disable live trading flags, resolve blockers, and rerun reconciliation.",
            "Do not run additional live tests until reconciliation is ready.",
        )
    if warnings:
        return (
            "Review warnings and rerun read-only account checks before the next phase.",
        )
    return (
        "Keep live trading disabled by default and continue with the next development phase.",
    )


def _unsafe_rendered_values(
    settings: AppSettings,
    report: PostLiveReconciliationReport,
) -> tuple[str, ...]:
    rendered = render_post_live_reconciliation(report, "json") + render_post_live_reconciliation(
        report,
        "markdown",
    )
    unsafe: list[str] = []
    for value in _sensitive_values(settings):
        if value in rendered:
            unsafe.append(value)
    if _TX_HASH_RE.search(rendered):
        unsafe.append("transaction_hash")
    if _ADDRESS_RE.search(rendered):
        unsafe.append("wallet_address")
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
    "PostLiveAccountAdapter",
    "PostLiveReconciliationConfig",
    "PostLiveReconciliationReport",
    "build_post_live_reconciliation",
    "post_live_reconciliation_filename",
    "render_post_live_reconciliation",
    "render_post_live_reconciliation_markdown",
    "write_post_live_reconciliation_reports",
]
