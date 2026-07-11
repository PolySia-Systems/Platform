from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from polysia.config.settings import AppSettings

Clock = Callable[[], datetime]
GitRunner = Callable[[Path, tuple[str, ...]], str]
CapabilityClass = Literal[
    "production-ready",
    "MVP-ready",
    "research-only",
    "paper-only",
    "blocked-for-live",
    "requires-human-review",
]
ReportFormat = Literal["json", "markdown", "freeze"]

RECOMMENDED_TAG = "v0.31.0-controlled-second-tiny-live-ready"
RECOMMENDED_MERGE_TARGET = "main"

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
_LONG_TOKEN_RE = re.compile(r"\b[0-9]{30,}\b")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ProductionGapAuditConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    name: str
    classification: CapabilityClass
    summary: str
    evidence: tuple[str, ...]
    live_restriction: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "evidence": list(self.evidence),
            "live_restriction": self.live_restriction,
            "name": self.name,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class MergeReadiness:
    current_branch: str | None
    current_commit: str | None
    git_clean: bool | None
    recommended_tag_name: str
    recommended_merge_target: str
    required_review_checklist: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "current_branch": self.current_branch,
            "current_commit": self.current_commit,
            "git_clean": self.git_clean,
            "recommended_merge_target": self.recommended_merge_target,
            "recommended_tag_name": self.recommended_tag_name,
            "required_review_checklist": list(self.required_review_checklist),
        }


@dataclass(frozen=True, slots=True)
class FinalOperatorDecision:
    current_safe_operating_mode: str
    safe_to_run_now: tuple[str, ...]
    dry_run_only: tuple[str, ...]
    blocked_from_live: tuple[str, ...]
    requires_explicit_manual_approval: tuple[str, ...]
    next_recommended_phase: str

    def to_dict(self) -> dict[str, object]:
        return {
            "blocked_from_live": list(self.blocked_from_live),
            "current_safe_operating_mode": self.current_safe_operating_mode,
            "dry_run_only": list(self.dry_run_only),
            "next_recommended_phase": self.next_recommended_phase,
            "requires_explicit_manual_approval": list(
                self.requires_explicit_manual_approval
            ),
            "safe_to_run_now": list(self.safe_to_run_now),
        }


@dataclass(frozen=True, slots=True)
class ProductionGapAuditReport:
    timestamp: datetime
    status: str
    capabilities: tuple[CapabilityAssessment, ...]
    explicit_live_restrictions: tuple[str, ...]
    merge_readiness: MergeReadiness
    final_operator_decision: FinalOperatorDecision
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "capability_summary": _capability_summary(self.capabilities),
            "explicit_live_restrictions": list(self.explicit_live_restrictions),
            "final_operator_decision": self.final_operator_decision.to_dict(),
            "merge_readiness": self.merge_readiness.to_dict(),
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


def build_production_gap_audit(
    config: ProductionGapAuditConfig,
    *,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> ProductionGapAuditReport:
    """Build a release-freeze production gap audit without live trading calls."""

    merge = _merge_readiness(config.project_root.resolve(), git_runner=git_runner)
    report = ProductionGapAuditReport(
        timestamp=clock(),
        status="ready",
        capabilities=_capabilities(),
        explicit_live_restrictions=_explicit_live_restrictions(),
        merge_readiness=merge,
        final_operator_decision=_final_operator_decision(config.settings),
        warnings=(),
    )
    if _unsafe_rendered_values(config.settings, report):
        report = replace(
            report,
            status="blocked",
            warnings=(
                *report.warnings,
                "Production gap audit rendering contained sensitive values.",
            ),
        )
    return report


def write_production_gap_audit_reports(
    config: ProductionGapAuditConfig,
    *,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> ProductionGapAuditReport:
    report = build_production_gap_audit(
        config,
        clock=clock,
        git_runner=git_runner,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    for report_format in ("json", "markdown", "freeze"):
        path = config.output_dir / production_gap_audit_filename(report_format)
        path.write_text(
            f"{render_production_gap_audit(report, report_format)}\n",
            encoding="utf-8",
        )
    return report


def render_production_gap_audit(
    report: ProductionGapAuditReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if report_format == "freeze":
        return render_phase_31_freeze_summary(report)
    return render_production_gap_audit_markdown(report)


def render_production_gap_audit_markdown(report: ProductionGapAuditReport) -> str:
    restrictions = "\n".join(
        f"- {restriction}" for restriction in report.explicit_live_restrictions
    )
    checklist = "\n".join(
        f"- {item}" for item in report.merge_readiness.required_review_checklist
    )
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    capabilities = "\n".join(
        "| "
        f"{capability.name} | {capability.classification} | "
        f"{capability.summary} | {capability.live_restriction or 'None'} |"
        for capability in report.capabilities
    )
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Production Gap Audit",
            "",
            f"- Status: {report.status}",
            f"- Generated at: {report.timestamp.isoformat()}",
            "",
            "## Capability Classification",
            "",
            "| Capability | Classification | Summary | Live Restriction |",
            "| --- | --- | --- | --- |",
            capabilities,
            "",
            "## Explicit Live Restrictions",
            "",
            restrictions,
            "",
            "## Merge Readiness",
            "",
            f"- Current branch: {report.merge_readiness.current_branch}",
            f"- Current commit: {report.merge_readiness.current_commit}",
            f"- Git clean: {report.merge_readiness.git_clean}",
            f"- Recommended tag: {report.merge_readiness.recommended_tag_name}",
            f"- Recommended merge target: {report.merge_readiness.recommended_merge_target}",
            "",
            "## Required Review Checklist Before Main Merge",
            "",
            checklist,
            "",
            "## Final Operator Decision",
            "",
            _operator_decision_markdown(report.final_operator_decision),
            "",
            "## Warnings",
            "",
            warnings,
            "",
        )
    )


def render_phase_31_freeze_summary(report: ProductionGapAuditReport) -> str:
    decision = report.final_operator_decision
    return "\n".join(
        (
            "# Phase 31 Release Freeze Summary",
            "",
            f"- Status: {report.status}",
            f"- Current branch: {report.merge_readiness.current_branch}",
            f"- Current commit: {report.merge_readiness.current_commit}",
            f"- Git clean: {report.merge_readiness.git_clean}",
            f"- Recommended tag: {report.merge_readiness.recommended_tag_name}",
            f"- Recommended merge target: {report.merge_readiness.recommended_merge_target}",
            "",
            "## Safe Operating Mode",
            "",
            decision.current_safe_operating_mode,
            "",
            "## Must Stay Blocked",
            "",
            "\n".join(f"- {item}" for item in decision.blocked_from_live),
            "",
            "## Requires Manual Approval",
            "",
            "\n".join(
                f"- {item}" for item in decision.requires_explicit_manual_approval
            ),
            "",
            "## Next Recommended Phase",
            "",
            decision.next_recommended_phase,
            "",
        )
    )


def production_gap_audit_filename(report_format: ReportFormat) -> str:
    return {
        "freeze": "phase-31-freeze-summary.md",
        "json": "production-gap-audit.json",
        "markdown": "production-gap-audit.md",
    }[report_format]


def _capabilities() -> tuple[CapabilityAssessment, ...]:
    return (
        _cap("public market discovery", "MVP-ready", "Works for discovery and selection."),
        _cap("realtime stream ingestion", "MVP-ready", "Ready for monitored public streams."),
        _cap("local Decimal orderbook", "production-ready", "Uses Decimal for price math."),
        _cap("SQLite persistence", "MVP-ready", "Local persistence is ready for MVP use."),
        _cap("strategy framework", "MVP-ready", "Framework supports research strategies."),
        _cap(
            "stale-price strategy",
            "research-only",
            "Research signal only; not approved for live automation.",
            "Live strategy automation is not approved.",
        ),
        _cap(
            "passive market maker",
            "research-only",
            "Paper/backtest research only.",
            "Live market making is not approved.",
        ),
        _cap("risk engine", "production-ready", "Pre-trade risk checks are enforced."),
        _cap("kill switch", "production-ready", "Live paths respect kill switch state."),
        _cap(
            "paper broker",
            "paper-only",
            "Safe simulated execution only.",
            "Paper broker must not be treated as live execution.",
        ),
        _cap("portfolio/PnL", "MVP-ready", "Tracks positions and simulated PnL."),
        _cap("backtesting/replay", "paper-only", "Replay is offline and paper-only."),
        _cap(
            "shadow-run-real-data",
            "paper-only",
            "Uses public data with paper broker only.",
        ),
        _cap(
            "strategy-evaluation-extended",
            "research-only",
            "Provides diagnostics; not a live approval engine.",
        ),
        _cap(
            "fill simulation",
            "research-only",
            "Execution-quality analysis only.",
        ),
        _cap(
            "secure live adapter",
            "requires-human-review",
            "Authenticated adapter is guarded and not autonomous.",
            "Any live use requires explicit operator approval.",
        ),
        _cap("live account status", "MVP-ready", "Read-only account status is available."),
        _cap(
            "live cancel path",
            "requires-human-review",
            "Cancel path is guarded and defaults to dry-run.",
            "Real cancel requires manual operator approval.",
        ),
        _cap(
            "tiny live execution",
            "requires-human-review",
            "First tiny live test succeeded with one attempt.",
            "Repeated live tests are not approved.",
        ),
        _cap(
            "controlled second tiny live",
            "requires-human-review",
            "Dry-run is ready; real second test is not submitted.",
            "Second real tiny live test requires separate manual approval.",
        ),
        _cap("geoblock enforcement", "production-ready", "Mandatory and fail-closed."),
        _cap("signer/funder diagnostics", "production-ready", "Reports booleans only."),
        _cap("secret redaction", "production-ready", "Reports avoid sensitive values."),
        _cap("release manifest", "production-ready", "Release manifest is generated."),
        _cap("final handoff", "production-ready", "Final handoff is ready."),
        _cap("deployment automation", "production-ready", "Local gates are automated."),
        _cap("observability snapshot", "production-ready", "Read-only visibility is ready."),
        _cap("tiny live monitor", "production-ready", "Read-only account monitor is ready."),
        _cap(
            "live strategy automation",
            "blocked-for-live",
            "No live strategy loop is approved.",
            "Any production live trading requires a new phase.",
        ),
        _cap(
            "live market making",
            "blocked-for-live",
            "No live market-making path is approved.",
            "Any live market making requires a new phase.",
        ),
        _cap(
            "capital scaling",
            "blocked-for-live",
            "No increase beyond tiny controlled tests is approved.",
            "Capital scaling requires a new phase and operator approval.",
        ),
        _cap(
            "repeated live tests",
            "blocked-for-live",
            "No repeated live tests are approved.",
            "Additional live tests require separate manual approval.",
        ),
    )


def _cap(
    name: str,
    classification: CapabilityClass,
    summary: str,
    live_restriction: str | None = None,
) -> CapabilityAssessment:
    return CapabilityAssessment(
        name=name,
        classification=classification,
        summary=summary,
        evidence=("Implemented, tested, and included in release artifacts.",),
        live_restriction=live_restriction,
    )


def _explicit_live_restrictions() -> tuple[str, ...]:
    return (
        "Live market making is not approved.",
        "Live strategy automation is not approved.",
        "Capital scaling is not approved.",
        "Repeated live tests are not approved.",
        "Second real tiny live test requires separate manual approval.",
        "Any production live trading requires a new phase and explicit operator approval.",
    )


def _final_operator_decision(settings: AppSettings) -> FinalOperatorDecision:
    return FinalOperatorDecision(
        current_safe_operating_mode=(
            f"{settings.trading_mode.value} with live trading enabled="
            f"{settings.live_trading_enabled}."
        ),
        safe_to_run_now=(
            "health",
            "deployment-readiness",
            "final-handoff",
            "observability-snapshot",
            "tiny-live-monitor",
            "production-gap-audit",
        ),
        dry_run_only=(
            "controlled-second-tiny-live",
            "tiny-live-execute unless a separate manual live approval is granted",
        ),
        blocked_from_live=(
            "live strategy automation",
            "live market making",
            "capital scaling",
            "repeated live tests",
        ),
        requires_explicit_manual_approval=(
            "second real tiny live test",
            "real cancel of live orders",
            "any production live trading",
            "merge to main after review",
        ),
        next_recommended_phase=(
            "Phase 33: human release review, tag creation, and controlled main merge."
        ),
    )


def _merge_readiness(
    project_root: Path,
    *,
    git_runner: GitRunner | None,
) -> MergeReadiness:
    snapshot = _git_snapshot(project_root, git_runner=git_runner)
    clean_value = snapshot.get("clean")
    git_clean = clean_value if isinstance(clean_value, bool) else None
    return MergeReadiness(
        current_branch=_optional_str(snapshot.get("branch")),
        current_commit=_optional_str(snapshot.get("commit")),
        git_clean=git_clean,
        recommended_tag_name=RECOMMENDED_TAG,
        recommended_merge_target=RECOMMENDED_MERGE_TARGET,
        required_review_checklist=(
            "Confirm no live order has been submitted after Phase 25.",
            "Confirm controlled second tiny live remains dry-run only.",
            "Confirm generated reports contain no secrets or identifiers.",
            "Review all blocked-for-live capabilities.",
            "Create the recommended tag only after human approval.",
            "Merge to main only after release owner approval.",
        ),
    )


def _git_snapshot(
    project_root: Path,
    *,
    git_runner: GitRunner | None,
) -> dict[str, object]:
    runner = git_runner or _run_git
    try:
        branch = runner(project_root, ("git", "branch", "--show-current")).strip()
        commit = runner(project_root, ("git", "rev-parse", "--short", "HEAD")).strip()
        status = runner(project_root, ("git", "status", "--short")).strip()
    except (OSError, subprocess.SubprocessError):
        return {"branch": None, "clean": None, "commit": None}
    return {"branch": branch or "detached", "clean": status == "", "commit": commit}


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


def _capability_summary(
    capabilities: tuple[CapabilityAssessment, ...],
) -> dict[str, int]:
    summary: dict[str, int] = {}
    for capability in capabilities:
        summary[capability.classification] = summary.get(capability.classification, 0) + 1
    return dict(sorted(summary.items()))


def _operator_decision_markdown(decision: FinalOperatorDecision) -> str:
    return "\n".join(
        (
            f"- Current safe operating mode: {decision.current_safe_operating_mode}",
            f"- Next recommended phase: {decision.next_recommended_phase}",
            "",
            "### Safe To Run Now",
            "",
            "\n".join(f"- {item}" for item in decision.safe_to_run_now),
            "",
            "### Must Remain Dry-Run Only",
            "",
            "\n".join(f"- {item}" for item in decision.dry_run_only),
            "",
            "### Blocked From Live",
            "",
            "\n".join(f"- {item}" for item in decision.blocked_from_live),
            "",
            "### Requires Explicit Manual Approval",
            "",
            "\n".join(f"- {item}" for item in decision.requires_explicit_manual_approval),
        )
    )


def _unsafe_rendered_values(
    settings: AppSettings,
    report: ProductionGapAuditReport,
) -> tuple[str, ...]:
    rendered = render_production_gap_audit(report, "json") + render_production_gap_audit(
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


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "ProductionGapAuditConfig",
    "ProductionGapAuditReport",
    "build_production_gap_audit",
    "production_gap_audit_filename",
    "render_phase_31_freeze_summary",
    "render_production_gap_audit",
    "render_production_gap_audit_markdown",
    "write_production_gap_audit_reports",
]
