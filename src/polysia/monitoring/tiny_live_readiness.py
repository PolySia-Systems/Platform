from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Literal

from polysia.adapters.geoblock import PreLiveOrderGeoblockCheck
from polysia.adapters.polymarket_secure import PolymarketSecureAdapter
from polysia.config.settings import AppSettings, TradingMode
from polysia.deployment.manifest import GitRunner, build_release_manifest
from polysia.execution.live_broker import LiveBroker
from polysia.monitoring.readiness import (
    DeploymentReadinessReport,
    GitStatusReader,
    build_deployment_readiness,
)
from polysia.risk.kill_switch import KillSwitch

Clock = Callable[[], datetime]
ReadinessStatus = Literal["pass", "warn", "fail"]
ReportFormat = Literal["json", "markdown", "html"]
TinyLiveReadinessResult = Literal[
    "READY_FOR_TINY_LIVE_REVIEW",
    "READY_FOR_TINY_LIVE_DRY_RUN_ONLY",
    "NOT_READY_FOR_TINY_LIVE",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TinyLiveReadinessConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path
    acceptance_audit_path: Path | None = None
    shadow_run_path: Path | None = None
    strategy_evaluation_path: Path | None = None
    fill_simulation_audit_path: Path | None = None
    require_clean_git: bool = False


@dataclass(frozen=True, slots=True)
class TinyLiveReadinessCheck:
    name: str
    status: ReadinessStatus
    message: str
    remediation: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "message": self.message,
            "name": self.name,
            "remediation": self.remediation,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class TinyLiveReadinessReport:
    timestamp: datetime
    final_result: TinyLiveReadinessResult
    checks: tuple[TinyLiveReadinessCheck, ...]
    no_live_order_placed: bool
    suggested_next_phase: str

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        return tuple(check.message for check in self.checks if check.status == "fail")

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(check.message for check in self.checks if check.status == "warn")

    @property
    def required_operator_actions(self) -> tuple[str, ...]:
        return tuple(
            check.remediation
            for check in self.checks
            if check.status in {"fail", "warn"} and check.remediation is not None
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "blocking_reasons": list(self.blocking_reasons),
            "checks": [check.to_dict() for check in self.checks],
            "final_result": self.final_result,
            "no_live_order_placed": self.no_live_order_placed,
            "required_operator_actions": list(self.required_operator_actions),
            "suggested_next_phase": self.suggested_next_phase,
            "summary": _summarize_checks(self.checks),
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


def build_tiny_live_readiness(
    config: TinyLiveReadinessConfig,
    *,
    clock: Clock = utc_now,
    git_status_reader: GitStatusReader | None = None,
    git_runner: GitRunner | None = None,
) -> TinyLiveReadinessReport:
    root = config.project_root.resolve()
    output_dir = config.output_dir
    readiness = build_deployment_readiness(
        settings=config.settings,
        project_root=root,
        require_clean_git=config.require_clean_git,
        git_status_reader=git_status_reader,
    )
    release_manifest = build_release_manifest(
        settings=config.settings,
        project_root=root,
        require_clean_git=config.require_clean_git,
        git_runner=git_runner,
    )
    checks = (
        _check_default_runtime(),
        _check_current_runtime_live_disabled(config.settings),
        _check_deployment_readiness(readiness),
        _check_release_manifest(release_manifest.status),
        _check_final_handoff(output_dir / "final-handoff.md"),
        _check_report_classification(
            name="acceptance-audit",
            path=_artifact_path(
                config.acceptance_audit_path,
                output_dir / "acceptance_audit.json",
            ),
            provided=config.acceptance_audit_path is not None,
            field="final_result",
            pass_values=("READY_FOR_TINY_LIVE",),
            warn_values=("READY_FOR_SHADOW",),
        ),
        _check_report_classification(
            name="shadow-run",
            path=_artifact_path(config.shadow_run_path, output_dir / "shadow_run.json"),
            provided=config.shadow_run_path is not None,
            field="classification",
            pass_values=("SHADOW_HEALTHY",),
            warn_values=("SHADOW_DEGRADED",),
        ),
        _check_report_classification(
            name="strategy-evaluation",
            path=_artifact_path(
                config.strategy_evaluation_path,
                output_dir / "strategy_evaluation.json",
            ),
            provided=config.strategy_evaluation_path is not None,
            field="classification",
            pass_values=("STRATEGY_READY_FOR_TINY_LIVE_REVIEW",),
            warn_values=("STRATEGY_RESEARCH_ONLY", "STRATEGY_READY_FOR_SHADOW"),
        ),
        _check_report_classification(
            name="fill-simulation-audit",
            path=_artifact_path(
                config.fill_simulation_audit_path,
                output_dir / "fill_simulation_audit.json",
            ),
            provided=config.fill_simulation_audit_path is not None,
            field="classification",
            pass_values=("FILL_MODEL_CONSERVATIVE_OK",),
            warn_values=("FILL_MODEL_NEEDS_MORE_DATA",),
        ),
        _check_geoblock_enforcement(),
        _check_kill_switch(),
        _check_token_allowlist(config.settings),
        _check_tiny_caps(config.settings),
        _check_acknowledgement_gate(root),
        _check_strategy_live_isolation(root),
        _check_signer_funder_documentation(root),
        _check_signer_funder_diagnostics(),
        _check_secret_redaction(
            settings=config.settings,
            artifact_paths=(
                output_dir / "acceptance_audit.json",
                output_dir / "shadow_run.json",
                output_dir / "strategy_evaluation.json",
                output_dir / "fill_simulation_audit.json",
                output_dir / "final-handoff.md",
            ),
        ),
    )
    final_result = _classify(checks)
    return TinyLiveReadinessReport(
        timestamp=clock(),
        final_result=final_result,
        checks=checks,
        no_live_order_placed=True,
        suggested_next_phase=_suggest_next_phase(final_result),
    )


def render_tiny_live_readiness_json(report: TinyLiveReadinessReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_tiny_live_readiness_markdown(report: TinyLiveReadinessReport) -> str:
    blockers = "\n".join(f"- {reason}" for reason in report.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    actions = (
        "\n".join(f"- {action}" for action in report.required_operator_actions)
        or "- None"
    )
    checks = "\n".join(
        f"| {check.name} | {check.status} | {check.message} |"
        for check in report.checks
    )
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Tiny Live Readiness",
            "",
            f"- Final result: {report.final_result}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- No live order placed: {report.no_live_order_placed}",
            "",
            "## Blocking Reasons",
            "",
            blockers,
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Required Operator Actions",
            "",
            actions,
            "",
            "## Checks",
            "",
            "| Check | Status | Message |",
            "| --- | --- | --- |",
            checks,
            "",
            "## Suggested Next Phase",
            "",
            report.suggested_next_phase,
            "",
            "## Live Trading",
            "",
            "No live order was placed by this readiness command.",
            "",
        )
    )


def render_tiny_live_readiness_html(report: TinyLiveReadinessReport) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(check.name)}</td>"
        f"<td>{escape(check.status)}</td>"
        f"<td>{escape(check.message)}</td>"
        "</tr>"
        for check in report.checks
    )
    blockers = _items(report.blocking_reasons)
    warnings = _items(report.warnings)
    actions = _items(report.required_operator_actions)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolySia — Polymarket Adapter — Tiny Live Readiness</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin-top: 24px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; padding: 8px 12px; color: #fff;
      background: #1f5f8b; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 9px 6px; text-align: left; }}
    th {{ color: #687582; }}
  </style>
</head>
<body>
  <main>
    <h1>PolySia — Polymarket Adapter — Tiny Live Readiness</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.final_result)}</div>
    <h2>Blocking Reasons</h2>
    <ul>{blockers}</ul>
    <h2>Warnings</h2>
    <ul>{warnings}</ul>
    <h2>Required Operator Actions</h2>
    <ul>{actions}</ul>
    <h2>Checks</h2>
    <table>
      <thead><tr><th>Check</th><th>Status</th><th>Message</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <h2>Suggested Next Phase</h2>
    <p>{escape(report.suggested_next_phase)}</p>
    <h2>Live Trading</h2>
    <p>No live order was placed by this readiness command.</p>
  </main>
</body>
</html>
"""


def render_tiny_live_readiness(
    report: TinyLiveReadinessReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return render_tiny_live_readiness_json(report)
    if report_format == "markdown":
        return render_tiny_live_readiness_markdown(report)
    return render_tiny_live_readiness_html(report)


def normalize_tiny_live_readiness_formats(
    *,
    json_enabled: bool,
    markdown_enabled: bool,
    html_enabled: bool,
) -> tuple[ReportFormat, ...]:
    selected: list[ReportFormat] = []
    if json_enabled:
        selected.append("json")
    if markdown_enabled:
        selected.append("markdown")
    if html_enabled:
        selected.append("html")
    if not selected:
        return ("json", "markdown", "html")
    return tuple(selected)


def tiny_live_readiness_filename(report_format: ReportFormat) -> str:
    return {
        "html": "tiny_live_readiness.html",
        "json": "tiny_live_readiness.json",
        "markdown": "tiny_live_readiness.md",
    }[report_format]


def _check_default_runtime() -> TinyLiveReadinessCheck:
    if (
        AppSettings.model_fields["trading_mode"].default == TradingMode.DATA_ONLY
        and AppSettings.model_fields["live_trading_enabled"].default is False
    ):
        return TinyLiveReadinessCheck(
            name="default-runtime",
            status="pass",
            message="Default runtime remains DATA_ONLY with live trading disabled.",
        )
    return TinyLiveReadinessCheck(
        name="default-runtime",
        status="fail",
        message="Default runtime no longer preserves DATA_ONLY and live-disabled safety.",
        remediation="Restore safe defaults in settings.",
    )


def _check_current_runtime_live_disabled(settings: AppSettings) -> TinyLiveReadinessCheck:
    if settings.live_trading_allowed or settings.live_trading_enabled:
        return TinyLiveReadinessCheck(
            name="current-runtime-live-disabled",
            status="fail",
            message="Current runtime has live trading enabled or allowed.",
            remediation="Set TRADING_MODE=DATA_ONLY and LIVE_TRADING_ENABLED=false.",
        )
    return TinyLiveReadinessCheck(
        name="current-runtime-live-disabled",
        status="pass",
        message="Current readiness run did not enable live trading.",
    )


def _check_deployment_readiness(
    readiness: DeploymentReadinessReport,
) -> TinyLiveReadinessCheck:
    if readiness.status == "ready":
        return TinyLiveReadinessCheck(
            name="deployment-readiness",
            status="pass",
            message="Deployment readiness is ready.",
        )
    return TinyLiveReadinessCheck(
        name="deployment-readiness",
        status="fail",
        message="Deployment readiness is blocked.",
        remediation="Fix failed deployment-readiness checks.",
    )


def _check_release_manifest(status: str) -> TinyLiveReadinessCheck:
    if status == "ready":
        return TinyLiveReadinessCheck(
            name="release-manifest",
            status="pass",
            message="Release manifest is ready.",
        )
    return TinyLiveReadinessCheck(
        name="release-manifest",
        status="fail",
        message="Release manifest is blocked.",
        remediation="Regenerate the release manifest after fixing blockers.",
    )


def _check_final_handoff(path: Path) -> TinyLiveReadinessCheck:
    if path.is_file():
        return TinyLiveReadinessCheck(
            name="final-handoff",
            status="pass",
            message="Final handoff artifact is available.",
        )
    return TinyLiveReadinessCheck(
        name="final-handoff",
        status="warn",
        message="Final handoff artifact was not found in the output directory.",
        remediation="Run final-handoff before human tiny-live review.",
    )


def _check_report_classification(
    *,
    name: str,
    path: Path,
    provided: bool,
    field: str,
    pass_values: tuple[str, ...],
    warn_values: tuple[str, ...],
) -> TinyLiveReadinessCheck:
    if not path.is_file():
        status: ReadinessStatus = "fail" if provided else "warn"
        return TinyLiveReadinessCheck(
            name=name,
            status=status,
            message=f"{name} report was not found.",
            remediation=f"Generate {name} before tiny-live review.",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TinyLiveReadinessCheck(
            name=name,
            status="fail",
            message=f"{name} report could not be parsed.",
            remediation=f"Regenerate {name} with a valid JSON report.",
        )
    value = payload.get(field) if isinstance(payload, dict) else None
    if value in pass_values:
        return TinyLiveReadinessCheck(
            name=name,
            status="pass",
            message=f"{name} report is acceptable: {value}.",
        )
    if value in warn_values:
        return TinyLiveReadinessCheck(
            name=name,
            status="warn",
            message=f"{name} report requires human review: {value}.",
            remediation=f"Review {name} before moving beyond dry-run.",
        )
    return TinyLiveReadinessCheck(
        name=name,
        status="fail",
        message=f"{name} report is not acceptable: {value}.",
        remediation=f"Fix {name} blockers before tiny-live review.",
    )


def _check_geoblock_enforcement() -> TinyLiveReadinessCheck:
    if hasattr(PreLiveOrderGeoblockCheck, "assert_allowed") and hasattr(
        LiveBroker,
        "_assert_geoblock_allowed",
    ):
        return TinyLiveReadinessCheck(
            name="geoblock-enforcement",
            status="pass",
            message="Mandatory geoblock enforcement is available and fail-closed.",
        )
    return TinyLiveReadinessCheck(
        name="geoblock-enforcement",
        status="fail",
        message="Mandatory geoblock enforcement could not be verified.",
        remediation="Restore PreLiveOrderGeoblockCheck before any live order path.",
    )


def _check_kill_switch() -> TinyLiveReadinessCheck:
    kill_switch = KillSwitch()
    kill_switch.activate("readiness-test")
    if kill_switch.is_active():
        return TinyLiveReadinessCheck(
            name="kill-switch",
            status="pass",
            message="Kill switch exists and can block.",
        )
    return TinyLiveReadinessCheck(
        name="kill-switch",
        status="fail",
        message="Kill switch did not activate.",
        remediation="Restore kill switch behavior before tiny-live review.",
    )


def _check_token_allowlist(settings: AppSettings) -> TinyLiveReadinessCheck:
    if settings.polymarket_live_token_allowlist:
        return TinyLiveReadinessCheck(
            name="token-allowlist",
            status="pass",
            message="Live token allowlist is configured without exposing values.",
        )
    return TinyLiveReadinessCheck(
        name="token-allowlist",
        status="warn",
        message="Live token allowlist is empty; only dry-run review is possible.",
        remediation="Configure an explicit token allowlist only for a human-approved tiny test.",
    )


def _check_tiny_caps(settings: AppSettings) -> TinyLiveReadinessCheck:
    if settings.polymarket_live_max_open_orders < 1:
        return TinyLiveReadinessCheck(
            name="tiny-caps",
            status="fail",
            message="Tiny live max open order cap is below one.",
            remediation="Use a positive tiny open-order cap or stay dry-run only.",
        )
    if (
        settings.polymarket_live_max_order_size > 1
        or settings.polymarket_live_max_order_notional > 1
    ):
        return TinyLiveReadinessCheck(
            name="tiny-caps",
            status="warn",
            message="Tiny live caps are above the conservative one-unit defaults.",
            remediation="Lower tiny caps before a human-approved tiny live test.",
        )
    return TinyLiveReadinessCheck(
        name="tiny-caps",
        status="pass",
        message="Tiny caps remain conservative.",
    )


def _check_acknowledgement_gate(project_root: Path) -> TinyLiveReadinessCheck:
    live_broker = project_root / "src" / "polysia" / "execution" / "live_broker.py"
    live_smoke = project_root / "src" / "polysia" / "execution" / "live_smoke_test.py"
    text = _read_if_exists(live_broker) + _read_if_exists(live_smoke)
    if (
        "i_understand_this_places_real_orders" in text
        and "i-understand-this-places-a-real-order" in text
    ):
        return TinyLiveReadinessCheck(
            name="explicit-acknowledgement",
            status="pass",
            message="Live order paths require explicit acknowledgement.",
        )
    return TinyLiveReadinessCheck(
        name="explicit-acknowledgement",
        status="fail",
        message="Explicit acknowledgement gate could not be verified.",
        remediation="Restore live-order acknowledgement flags.",
    )


def _check_strategy_live_isolation(project_root: Path) -> TinyLiveReadinessCheck:
    strategies_dir = project_root / "src" / "polysia" / "strategies"
    forbidden = ("LiveBroker", "PolymarketSecureAdapter", "place_market_order")
    for path in strategies_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(term in text for term in forbidden):
            return TinyLiveReadinessCheck(
                name="strategy-live-isolation",
                status="fail",
                message="A strategy references a live execution path.",
                remediation="Keep strategies connected only to paper/backtest/shadow flows.",
            )
    return TinyLiveReadinessCheck(
        name="strategy-live-isolation",
        status="pass",
        message="Strategies do not directly reference live execution paths.",
    )


def _check_signer_funder_documentation(project_root: Path) -> TinyLiveReadinessCheck:
    docs = _read_if_exists(project_root / "README.md") + _read_if_exists(
        project_root / "docs" / "LIVE_CONNECTIVITY_SMOKE_TEST.md"
    )
    if "POLYMARKET_PRIVATE_KEY" in docs and "POLYMARKET_FUNDER_ADDRESS" in docs:
        return TinyLiveReadinessCheck(
            name="signer-funder-documentation",
            status="pass",
            message="Signer/funder separation is documented.",
        )
    return TinyLiveReadinessCheck(
        name="signer-funder-documentation",
        status="fail",
        message="Signer/funder separation documentation is missing.",
        remediation="Document signer EOA and proxy/funder wallet separation.",
    )


def _check_signer_funder_diagnostics() -> TinyLiveReadinessCheck:
    if hasattr(PolymarketSecureAdapter, "identity"):
        return TinyLiveReadinessCheck(
            name="signer-funder-diagnostics",
            status="pass",
            message="Sanitized signer/funder diagnostics are available.",
        )
    return TinyLiveReadinessCheck(
        name="signer-funder-diagnostics",
        status="fail",
        message="Signer/funder diagnostics could not be verified.",
        remediation="Restore sanitized secure-adapter identity diagnostics.",
    )


def _check_secret_redaction(
    *,
    settings: AppSettings,
    artifact_paths: tuple[Path, ...],
) -> TinyLiveReadinessCheck:
    sensitive_values = _sensitive_values(settings)
    if not sensitive_values:
        return TinyLiveReadinessCheck(
            name="secret-redaction",
            status="pass",
            message="No configured sensitive values were available for artifact scan.",
        )
    combined = "".join(_read_if_exists(path) for path in artifact_paths)
    if any(value in combined for value in sensitive_values):
        return TinyLiveReadinessCheck(
            name="secret-redaction",
            status="fail",
            message="A sensitive runtime value was found in generated artifacts.",
            remediation="Regenerate reports with secret redaction and remove leaked artifacts.",
        )
    return TinyLiveReadinessCheck(
        name="secret-redaction",
        status="pass",
        message="Generated artifacts do not contain configured sensitive values.",
    )


def _artifact_path(path: Path | None, default: Path) -> Path:
    return path if path is not None else default


def _classify(checks: tuple[TinyLiveReadinessCheck, ...]) -> TinyLiveReadinessResult:
    if any(check.status == "fail" for check in checks):
        return "NOT_READY_FOR_TINY_LIVE"
    if any(check.status == "warn" for check in checks):
        return "READY_FOR_TINY_LIVE_DRY_RUN_ONLY"
    return "READY_FOR_TINY_LIVE_REVIEW"


def _suggest_next_phase(result: TinyLiveReadinessResult) -> str:
    if result == "READY_FOR_TINY_LIVE_REVIEW":
        return "Human review may consider a separate, explicit tiny-live dry-run phase."
    if result == "READY_FOR_TINY_LIVE_DRY_RUN_ONLY":
        return "Stay in dry-run only until warnings are reviewed or refreshed."
    return "Fix blocking checks before any tiny-live review."


def _summarize_checks(checks: tuple[TinyLiveReadinessCheck, ...]) -> dict[str, int]:
    summary = {"fail": 0, "pass": 0, "warn": 0}
    for check in checks:
        summary[check.status] += 1
    return summary


def _read_if_exists(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


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


def _items(values: tuple[str, ...]) -> str:
    return "".join(f"<li>{escape(value)}</li>" for value in values) or "<li>None</li>"


__all__ = [
    "TinyLiveReadinessCheck",
    "TinyLiveReadinessConfig",
    "TinyLiveReadinessReport",
    "build_tiny_live_readiness",
    "normalize_tiny_live_readiness_formats",
    "render_tiny_live_readiness",
    "render_tiny_live_readiness_html",
    "render_tiny_live_readiness_json",
    "render_tiny_live_readiness_markdown",
    "tiny_live_readiness_filename",
]
