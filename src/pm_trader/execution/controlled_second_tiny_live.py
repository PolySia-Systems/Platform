from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.execution.tiny_live_execution import (
    TinyExecutionAdapter,
    TinyExecutionGeoblockCheck,
    TinyLiveExecutionConfig,
    TinyLiveExecutionReport,
    TinyOrderType,
    TinyOutcome,
    TinySide,
    render_tiny_live_execution,
    run_tiny_live_execution,
)
from pm_trader.risk.checks import RiskEngine

Clock = Callable[[], datetime]
GitReader = Callable[[Path, tuple[str, ...]], str]
ControlledSecondResult = Literal[
    "DRY_RUN_READY",
    "BLOCKED",
    "LIVE_ORDER_SUBMITTED",
    "LIVE_ORDER_FILLED",
    "LIVE_ORDER_REJECTED",
    "LIVE_ORDER_STATUS_UNKNOWN",
]
ReportFormat = Literal["json", "markdown"]

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
_LONG_TOKEN_RE = re.compile(r"\b[0-9]{30,}\b")
_MAX_SECOND_TINY_NOTIONAL = Decimal("1.00")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ControlledSecondTinyLiveConfig:
    settings: AppSettings
    output_dir: Path
    token_id: str
    side: TinySide
    outcome: TinyOutcome
    max_notional: Decimal
    order_type: TinyOrderType
    market_slug: str
    dry_run: bool = True
    submit_requested: bool = False
    acknowledgement: bool = False
    second_acknowledgement: bool = False
    auto_btc_5m: bool = False
    require_clean_git: bool = False
    redact_secrets: bool = True
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class ControlledSecondTinyLiveReport:
    timestamp: datetime
    dry_run: bool
    submit_requested: bool
    order_submitted: bool
    live_attempt_count: int
    side: TinySide
    outcome: TinyOutcome
    order_type: TinyOrderType
    max_notional: str
    token_allowlisted: bool
    geoblock_status: dict[str, object] | None
    signer_configured: bool
    funder_configured: bool
    risk_decision_summary: dict[str, object]
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    final_result: ControlledSecondResult
    no_retry_statement: str
    one_attempt_statement: str
    no_strategy_statement: str
    selected_market_slug: str
    selected_token_configured: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "blocking_reasons": list(self.blocking_reasons),
            "dry_run": self.dry_run,
            "final_result": self.final_result,
            "funder_configured": self.funder_configured,
            "geoblock_status": self.geoblock_status,
            "live_attempt_count": self.live_attempt_count,
            "max_notional": self.max_notional,
            "no_retry_statement": self.no_retry_statement,
            "no_strategy_statement": self.no_strategy_statement,
            "one_attempt_statement": self.one_attempt_statement,
            "order_submitted": self.order_submitted,
            "order_type": self.order_type,
            "outcome": self.outcome,
            "risk_decision_summary": self.risk_decision_summary,
            "selected_market_slug": self.selected_market_slug,
            "selected_token_configured": self.selected_token_configured,
            "side": self.side,
            "signer_configured": self.signer_configured,
            "submit_requested": self.submit_requested,
            "timestamp": self.timestamp.isoformat(),
            "token_allowlisted": self.token_allowlisted,
            "warnings": list(self.warnings),
        }


async def run_controlled_second_tiny_live(
    config: ControlledSecondTinyLiveConfig,
    *,
    adapter: TinyExecutionAdapter | None = None,
    geoblock_check: TinyExecutionGeoblockCheck | None = None,
    risk_engine: RiskEngine | None = None,
    clock: Clock = utc_now,
    git_reader: GitReader | None = None,
) -> ControlledSecondTinyLiveReport:
    """Run a stricter controlled second tiny live dry-run or one submit attempt."""

    blocking = list(_static_blocking_reasons(config))
    if blocking:
        report = _blocked_report(config, blocking=tuple(blocking), clock=clock)
        return write_controlled_second_tiny_live_reports(report, config.output_dir)

    tiny_report = await run_tiny_live_execution(
        TinyLiveExecutionConfig(
            settings=config.settings,
            token_id=config.token_id,
            side=config.side,
            outcome=config.outcome,
            max_notional=config.max_notional,
            order_type=config.order_type,
            output_dir=config.output_dir,
            dry_run=config.dry_run,
            require_clean_git=config.require_clean_git,
            acknowledgement=config.acknowledgement and config.second_acknowledgement,
            market_slug=config.market_slug,
            redact_secrets=config.redact_secrets,
            project_root=config.project_root,
        ),
        adapter=adapter,
        geoblock_check=geoblock_check,
        risk_engine=risk_engine,
        clock=clock,
        git_reader=git_reader,
    )
    report = _from_tiny_report(config, tiny_report, timestamp=clock())
    return write_controlled_second_tiny_live_reports(report, config.output_dir)


def write_controlled_second_tiny_live_reports(
    report: ControlledSecondTinyLiveReport,
    output_dir: Path,
) -> ControlledSecondTinyLiveReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    final_report = report
    if _contains_sensitive_pattern(
        render_controlled_second_tiny_live(report, "json")
        + render_controlled_second_tiny_live(report, "markdown")
    ):
        final_report = replace(
            report,
            blocking_reasons=(
                *report.blocking_reasons,
                "Generated controlled second tiny live artifacts contained sensitive values.",
            ),
            final_result="BLOCKED",
        )
    for report_format in ("json", "markdown"):
        path = output_dir / controlled_second_tiny_live_filename(report_format)
        path.write_text(
            f"{render_controlled_second_tiny_live(final_report, report_format)}\n",
            encoding="utf-8",
        )
    return final_report


def render_controlled_second_tiny_live(
    report: ControlledSecondTinyLiveReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return render_controlled_second_tiny_live_markdown(report)


def render_controlled_second_tiny_live_markdown(
    report: ControlledSecondTinyLiveReport,
) -> str:
    blockers = "\n".join(f"- {reason}" for reason in report.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    return "\n".join(
        (
            "# Polymarket Controlled Second Tiny Live",
            "",
            f"- Final result: {report.final_result}",
            f"- Dry run: {report.dry_run}",
            f"- Submit requested: {report.submit_requested}",
            f"- Order submitted: {report.order_submitted}",
            f"- Live attempt count: {report.live_attempt_count}",
            f"- Side/outcome: {report.side} {report.outcome}",
            f"- Order type: {report.order_type}",
            f"- Max notional: {report.max_notional}",
            f"- Token allowlisted: {report.token_allowlisted}",
            f"- Signer configured: {report.signer_configured}",
            f"- Funder configured: {report.funder_configured}",
            f"- Geoblock status: {_safe_status(report.geoblock_status)}",
            f"- Selected market slug: {report.selected_market_slug}",
            f"- Selected token configured: {report.selected_token_configured}",
            "",
            "## Risk Decision",
            "",
            f"- Approved: {report.risk_decision_summary.get('approved')}",
            f"- Reason: {report.risk_decision_summary.get('reason')}",
            "",
            "## Safety Statements",
            "",
            f"- {report.no_retry_statement}",
            f"- {report.one_attempt_statement}",
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


def controlled_second_tiny_live_filename(report_format: ReportFormat) -> str:
    return {
        "json": "controlled-second-tiny-live.json",
        "markdown": "controlled-second-tiny-live.md",
    }[report_format]


def _static_blocking_reasons(
    config: ControlledSecondTinyLiveConfig,
) -> tuple[str, ...]:
    blocking: list[str] = []
    if config.dry_run and config.submit_requested:
        blocking.append("--submit cannot be combined with --dry-run.")
    if not config.token_id.strip():
        blocking.append("A selected token is required.")
    if not _is_btc_updown_5m_slug(config.market_slug):
        blocking.append("Second tiny live is restricted to BTC Up/Down 5m tokens.")
    if config.order_type not in {"FAK", "FOK"}:
        blocking.append("Only FOK or FAK orders are allowed.")
    if config.max_notional <= 0:
        blocking.append("max_notional must be positive.")
    if config.max_notional > _MAX_SECOND_TINY_NOTIONAL:
        blocking.append("max_notional above 1.00 is rejected.")
    if config.token_id not in config.settings.polymarket_live_token_allowlist:
        blocking.append("Selected token is not allowlisted.")
    if config.dry_run:
        return tuple(blocking)
    if not config.submit_requested:
        blocking.append("Real submit requires explicit --submit.")
    if config.settings.trading_mode != TradingMode.LIVE:
        blocking.append("Real submit requires TRADING_MODE=LIVE.")
    if not config.settings.live_trading_enabled:
        blocking.append("Real submit requires LIVE_TRADING_ENABLED=true.")
    if not config.acknowledgement:
        blocking.append("Real submit requires --i-understand-this-places-real-orders.")
    if not config.second_acknowledgement:
        blocking.append(
            "Real submit requires "
            "--i-confirm-this-is-the-second-controlled-tiny-live-test."
        )
    if config.settings.polymarket_private_key is None:
        blocking.append("Real submit requires POLYMARKET_PRIVATE_KEY.")
    if not config.settings.polymarket_funder_address:
        blocking.append("Real submit requires POLYMARKET_FUNDER_ADDRESS.")
    return tuple(blocking)


def _blocked_report(
    config: ControlledSecondTinyLiveConfig,
    *,
    blocking: tuple[str, ...],
    clock: Clock,
) -> ControlledSecondTinyLiveReport:
    return ControlledSecondTinyLiveReport(
        timestamp=clock(),
        dry_run=config.dry_run,
        submit_requested=config.submit_requested,
        order_submitted=False,
        live_attempt_count=0,
        side=config.side,
        outcome=config.outcome,
        order_type=config.order_type,
        max_notional=str(config.max_notional),
        token_allowlisted=config.token_id in config.settings.polymarket_live_token_allowlist,
        geoblock_status={"blocked": None, "status": "not_checked"},
        signer_configured=config.settings.polymarket_private_key is not None,
        funder_configured=bool(config.settings.polymarket_funder_address),
        risk_decision_summary={"approved": False, "reason": "static gates blocked"},
        blocking_reasons=blocking,
        warnings=(),
        final_result="BLOCKED",
        no_retry_statement="No retry is available in this command.",
        one_attempt_statement="At most one live order attempt is allowed.",
        no_strategy_statement="No strategy automation, loop, or market making is used.",
        selected_market_slug=config.market_slug,
        selected_token_configured=bool(config.token_id),
    )


def _from_tiny_report(
    config: ControlledSecondTinyLiveConfig,
    tiny_report: TinyLiveExecutionReport,
    *,
    timestamp: datetime,
) -> ControlledSecondTinyLiveReport:
    rendered_tiny = render_tiny_live_execution(tiny_report, "json")
    if _contains_sensitive_pattern(rendered_tiny):
        blocking = (
            *tiny_report.blocking_reasons,
            "Underlying tiny live report contained sensitive values.",
        )
    else:
        blocking = tiny_report.blocking_reasons
    return ControlledSecondTinyLiveReport(
        timestamp=timestamp,
        dry_run=config.dry_run,
        submit_requested=config.submit_requested,
        order_submitted=tiny_report.order_submitted,
        live_attempt_count=tiny_report.live_attempt_count,
        side=config.side,
        outcome=config.outcome,
        order_type=config.order_type,
        max_notional=str(config.max_notional),
        token_allowlisted=tiny_report.token_allowlisted,
        geoblock_status=_safe_geoblock_status(tiny_report.geoblock_status),
        signer_configured=_identity_bool(tiny_report, "signer_configured", config),
        funder_configured=_identity_bool(tiny_report, "funder_configured", config),
        risk_decision_summary=_risk_summary(tiny_report),
        blocking_reasons=blocking,
        warnings=tiny_report.warnings,
        final_result=_map_final_result(tiny_report),
        no_retry_statement="No retry is available in this command.",
        one_attempt_statement="At most one live order attempt is allowed.",
        no_strategy_statement="No strategy automation, loop, or market making is used.",
        selected_market_slug=config.market_slug,
        selected_token_configured=bool(config.token_id),
    )


def _map_final_result(report: TinyLiveExecutionReport) -> ControlledSecondResult:
    if report.final_result == "DRY_RUN_PASS":
        return "DRY_RUN_READY"
    if report.final_result == "LIVE_ORDER_FILLED":
        return "LIVE_ORDER_FILLED"
    if report.final_result == "LIVE_ORDER_SUBMITTED":
        return "LIVE_ORDER_SUBMITTED"
    if report.final_result in {"LIVE_ORDER_REJECTED", "LIVE_ORDER_EXPIRED"}:
        return "LIVE_ORDER_REJECTED"
    if report.live_attempt_count > 0 and report.final_result == "LIVE_ORDER_ERROR":
        return "LIVE_ORDER_STATUS_UNKNOWN"
    if report.live_attempt_count > 0:
        return "LIVE_ORDER_STATUS_UNKNOWN"
    return "BLOCKED"


def _risk_summary(report: TinyLiveExecutionReport) -> dict[str, object]:
    return {
        "approved": report.risk_decision.get("approved") is True,
        "reason": report.risk_decision.get("reason"),
    }


def _safe_geoblock_status(value: dict[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "blocked": value.get("blocked") if isinstance(value.get("blocked"), bool) else None,
        "status": value.get("status") if isinstance(value.get("status"), str) else None,
    }


def _identity_bool(
    report: TinyLiveExecutionReport,
    key: str,
    config: ControlledSecondTinyLiveConfig,
) -> bool:
    identity = report.diagnostics.get("identity")
    if isinstance(identity, dict) and isinstance(identity.get(key), bool):
        return identity[key]
    if key == "signer_configured":
        return config.settings.polymarket_private_key is not None
    return bool(config.settings.polymarket_funder_address)


def _safe_status(status: dict[str, object] | None) -> object:
    if status is None:
        return None
    return status.get("status")


def _is_btc_updown_5m_slug(market_slug: str) -> bool:
    normalized = market_slug.lower().replace("_", "-")
    return "btc" in normalized and "5m" in normalized and (
        "updown" in normalized or ("up" in normalized and "down" in normalized)
    )


def _contains_sensitive_pattern(text: str) -> bool:
    return bool(
        _ADDRESS_RE.search(text)
        or _TX_HASH_RE.search(text)
        or _LONG_TOKEN_RE.search(text)
    )


__all__ = [
    "ControlledSecondTinyLiveConfig",
    "ControlledSecondTinyLiveReport",
    "controlled_second_tiny_live_filename",
    "render_controlled_second_tiny_live",
    "render_controlled_second_tiny_live_markdown",
    "run_controlled_second_tiny_live",
    "write_controlled_second_tiny_live_reports",
]
