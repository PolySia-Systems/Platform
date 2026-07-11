from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pm_trader.config.settings import AppSettings
from pm_trader.monitoring.production_gap_audit import (
    RECOMMENDED_MERGE_TARGET,
    RECOMMENDED_TAG,
)
from pm_trader.monitoring.readiness import build_deployment_readiness

Clock = Callable[[], datetime]
GitRunner = Callable[[Path, tuple[str, ...]], str]
ReportFormat = Literal["json", "markdown", "checklist"]

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
_LONG_TOKEN_RE = re.compile(r"\b[0-9]{30,}\b")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class MainMergeReviewConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class MainMergeReviewReport:
    timestamp: datetime
    status: str
    current_branch: str | None
    current_commit: str | None
    git_clean: bool | None
    local_tag_status: dict[str, object]
    remote_status: dict[str, object]
    recommended_tag_name: str
    recommended_merge_target: str
    quality_gate_summary: dict[str, object]
    production_gap_audit_status: str
    final_handoff_status: str
    deployment_readiness_status: str | None
    live_safety_baseline: tuple[str, ...]
    blocked_for_live_capabilities: tuple[str, ...]
    dry_run_only_capabilities: tuple[str, ...]
    human_approval_checklist: tuple[str, ...]
    rollback_checklist: tuple[str, ...]
    post_merge_verification_checklist: tuple[str, ...]
    explicit_non_approvals: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "blocked_for_live_capabilities": list(self.blocked_for_live_capabilities),
            "current_branch": self.current_branch,
            "current_commit": self.current_commit,
            "deployment_readiness_status": self.deployment_readiness_status,
            "dry_run_only_capabilities": list(self.dry_run_only_capabilities),
            "explicit_non_approvals": list(self.explicit_non_approvals),
            "final_handoff_status": self.final_handoff_status,
            "git_clean": self.git_clean,
            "human_approval_checklist": list(self.human_approval_checklist),
            "live_safety_baseline": list(self.live_safety_baseline),
            "local_tag_status": self.local_tag_status,
            "post_merge_verification_checklist": list(
                self.post_merge_verification_checklist
            ),
            "production_gap_audit_status": self.production_gap_audit_status,
            "quality_gate_summary": self.quality_gate_summary,
            "recommended_merge_target": self.recommended_merge_target,
            "recommended_tag_name": self.recommended_tag_name,
            "remote_status": self.remote_status,
            "rollback_checklist": list(self.rollback_checklist),
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


def build_main_merge_review(
    config: MainMergeReviewConfig,
    *,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> MainMergeReviewReport:
    """Build a local release-owner review package without live trading behavior."""

    root = config.project_root.resolve()
    git = _git_snapshot(root, git_runner=git_runner)
    tag_status = _tag_status(root, git_runner=git_runner)
    remote_status = _remote_status(root, git_runner=git_runner)
    production_gap_status = _artifact_status(
        config.output_dir / "production-gap-audit.json",
        "status",
    )
    final_handoff_status = (
        "ready" if (config.output_dir / "final-handoff.md").is_file() else "missing"
    )
    deployment_readiness = _deployment_readiness_status(config.settings, root)
    warnings = _warnings(tag_status, remote_status, production_gap_status, final_handoff_status)
    clean_value = git.get("clean")
    git_clean = clean_value if isinstance(clean_value, bool) else None
    report = MainMergeReviewReport(
        timestamp=clock(),
        status="ready",
        current_branch=_optional_str(git.get("branch")),
        current_commit=_optional_str(git.get("commit")),
        git_clean=git_clean,
        local_tag_status=tag_status,
        remote_status=remote_status,
        recommended_tag_name=RECOMMENDED_TAG,
        recommended_merge_target=RECOMMENDED_MERGE_TARGET,
        quality_gate_summary=_quality_gate_summary(config.output_dir),
        production_gap_audit_status=production_gap_status,
        final_handoff_status=final_handoff_status,
        deployment_readiness_status=deployment_readiness,
        live_safety_baseline=_live_safety_baseline(config.settings),
        blocked_for_live_capabilities=(
            "live strategy automation",
            "live market making",
            "capital scaling",
            "repeated live tests",
        ),
        dry_run_only_capabilities=(
            "controlled-second-tiny-live",
            "second real tiny live test until separately approved",
        ),
        human_approval_checklist=_human_approval_checklist(),
        rollback_checklist=_rollback_checklist(),
        post_merge_verification_checklist=_post_merge_verification_checklist(),
        explicit_non_approvals=_explicit_non_approvals(),
        warnings=warnings,
    )
    if _unsafe_rendered_values(config.settings, report):
        report = replace(
            report,
            status="blocked",
            warnings=(
                *report.warnings,
                "Main merge review rendering contained sensitive values.",
            ),
        )
    return report


def write_main_merge_review_reports(
    config: MainMergeReviewConfig,
    *,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> MainMergeReviewReport:
    report = build_main_merge_review(config, clock=clock, git_runner=git_runner)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    for report_format in ("json", "markdown", "checklist"):
        path = config.output_dir / main_merge_review_filename(report_format)
        path.write_text(
            f"{render_main_merge_review(report, report_format)}\n",
            encoding="utf-8",
        )
    return report


def render_main_merge_review(
    report: MainMergeReviewReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if report_format == "checklist":
        return render_tag_and_merge_checklist(report)
    return render_main_merge_review_markdown(report)


def render_main_merge_review_markdown(report: MainMergeReviewReport) -> str:
    return "\n".join(
        (
            "# Polymarket Main Merge Review",
            "",
            f"- Status: {report.status}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Current branch: {report.current_branch}",
            f"- Current commit: {report.current_commit}",
            f"- Git clean: {report.git_clean}",
            f"- Recommended tag: {report.recommended_tag_name}",
            f"- Recommended merge target: {report.recommended_merge_target}",
            f"- Local tag present: {report.local_tag_status.get('present')}",
            f"- Remote configured: {report.remote_status.get('configured')}",
            f"- Production gap audit: {report.production_gap_audit_status}",
            f"- Final handoff: {report.final_handoff_status}",
            f"- Deployment readiness: {report.deployment_readiness_status}",
            "",
            "## Explicit Non-Approvals",
            "",
            _list(report.explicit_non_approvals),
            "",
            "## Live Safety Baseline",
            "",
            _list(report.live_safety_baseline),
            "",
            "## Blocked For Live",
            "",
            _list(report.blocked_for_live_capabilities),
            "",
            "## Dry-Run Only",
            "",
            _list(report.dry_run_only_capabilities),
            "",
            "## Human Approval Checklist",
            "",
            _list(report.human_approval_checklist),
            "",
            "## Rollback Checklist",
            "",
            _list(report.rollback_checklist),
            "",
            "## Post-Merge Verification Checklist",
            "",
            _list(report.post_merge_verification_checklist),
            "",
            "## Warnings",
            "",
            _list(report.warnings),
            "",
            "## Remote",
            "",
            "Remote push is not required for local release review.",
            "",
        )
    )


def render_tag_and_merge_checklist(report: MainMergeReviewReport) -> str:
    return "\n".join(
        (
            "# Tag and Merge Checklist",
            "",
            f"- Recommended tag: {report.recommended_tag_name}",
            f"- Recommended merge target: {report.recommended_merge_target}",
            f"- Current branch: {report.current_branch}",
            f"- Current commit: {report.current_commit}",
            f"- Git clean: {report.git_clean}",
            f"- Remote configured: {report.remote_status.get('configured')}",
            "",
            "## Before Merge",
            "",
            _list(report.human_approval_checklist),
            "",
            "## Rollback",
            "",
            _list(report.rollback_checklist),
            "",
            "## After Merge",
            "",
            _list(report.post_merge_verification_checklist),
            "",
            "## Non-Approvals",
            "",
            _list(report.explicit_non_approvals),
            "",
        )
    )


def main_merge_review_filename(report_format: ReportFormat) -> str:
    return {
        "checklist": "tag-and-merge-checklist.md",
        "json": "main-merge-review.json",
        "markdown": "main-merge-review.md",
    }[report_format]


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


def _tag_status(project_root: Path, *, git_runner: GitRunner | None) -> dict[str, object]:
    runner = git_runner or _run_git
    try:
        result = runner(project_root, ("git", "tag", "--list", RECOMMENDED_TAG)).strip()
    except (OSError, subprocess.SubprocessError):
        return {"name": RECOMMENDED_TAG, "present": False, "status": "unavailable"}
    return {
        "name": RECOMMENDED_TAG,
        "present": result == RECOMMENDED_TAG,
        "status": "present" if result == RECOMMENDED_TAG else "missing",
    }


def _remote_status(project_root: Path, *, git_runner: GitRunner | None) -> dict[str, object]:
    runner = git_runner or _run_git
    try:
        result = runner(project_root, ("git", "remote", "-v")).strip()
    except (OSError, subprocess.SubprocessError):
        return {"configured": False, "status": "missing"}
    remotes = tuple(
        line.split()[0] for line in result.splitlines() if line.strip() and line.split()
    )
    unique_remotes = tuple(dict.fromkeys(remotes))
    return {
        "configured": bool(unique_remotes),
        "remote_count": len(unique_remotes),
        "status": "configured" if unique_remotes else "missing",
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


def _quality_gate_summary(output_dir: Path) -> dict[str, object]:
    payload = _read_mapping(output_dir / "deployment-automation.json")
    gates = payload.get("quality_gates")
    if isinstance(gates, list):
        return {
            "available": True,
            "gates": [
                {
                    "name": gate.get("name"),
                    "status": gate.get("status"),
                }
                for gate in gates
                if isinstance(gate, dict)
            ],
        }
    return {"available": False, "gates": []}


def _artifact_status(path: Path, key: str) -> str:
    payload = _read_mapping(path)
    status = payload.get(key)
    return status if isinstance(status, str) else "missing"


def _deployment_readiness_status(settings: AppSettings, project_root: Path) -> str | None:
    try:
        return build_deployment_readiness(
            settings=settings,
            project_root=project_root,
        ).status
    except (OSError, ValueError):
        return None


def _read_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _warnings(
    tag_status: dict[str, object],
    remote_status: dict[str, object],
    production_gap_status: str,
    final_handoff_status: str,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if tag_status.get("present") is not True:
        warnings.append("Recommended local tag is missing.")
    if remote_status.get("configured") is not True:
        warnings.append("Git remote is not configured; this does not block local review.")
    if production_gap_status != "ready":
        warnings.append("Production gap audit is not ready.")
    if final_handoff_status != "ready":
        warnings.append("Final handoff artifact is not ready.")
    return tuple(warnings)


def _live_safety_baseline(settings: AppSettings) -> tuple[str, ...]:
    return (
        f"Current mode is {settings.trading_mode.value}.",
        f"LIVE_TRADING_ENABLED is {settings.live_trading_enabled}.",
        "This package does not approve live trading.",
        "This package does not approve a second real tiny live test.",
        "This package does not approve capital scaling.",
        "This package does not approve live market making.",
        "This package does not approve live strategy automation.",
        "Merge to main requires human release-owner approval.",
        "Remote push is not required for local release review.",
    )


def _explicit_non_approvals() -> tuple[str, ...]:
    return (
        "This package does not approve live trading.",
        "This package does not approve second real tiny live test.",
        "This package does not approve capital scaling.",
        "This package does not approve live market making.",
        "This package does not approve live strategy automation.",
        "Merge to main requires human release-owner approval.",
        "Remote push is not required for local release review.",
    )


def _human_approval_checklist() -> tuple[str, ...]:
    return (
        "Review production-gap-audit artifacts.",
        "Confirm blocked-for-live capabilities remain blocked.",
        "Confirm controlled second tiny live remains dry-run only.",
        "Confirm no live order was submitted after the first tiny live fill.",
        "Confirm local tag points to the intended release commit.",
        "Approve merge to main as release owner.",
    )


def _rollback_checklist() -> tuple[str, ...]:
    return (
        "Keep the current release branch available.",
        "Do not delete the recommended local tag during review.",
        "If merge is rejected, keep main unchanged and continue on the release branch.",
        "If a local merge is made by mistake, use a normal revert commit.",
    )


def _post_merge_verification_checklist() -> tuple[str, ...]:
    return (
        "Run pytest on main.",
        "Run ruff check on main.",
        "Run mypy on main.",
        "Run deployment-readiness on main.",
        "Run final-handoff on main.",
        "Confirm live trading remains disabled by default.",
    )


def _unsafe_rendered_values(
    settings: AppSettings,
    report: MainMergeReviewReport,
) -> tuple[str, ...]:
    rendered = render_main_merge_review(report, "json") + render_main_merge_review(
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


def _list(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values) or "- None"


__all__ = [
    "MainMergeReviewConfig",
    "MainMergeReviewReport",
    "build_main_merge_review",
    "main_merge_review_filename",
    "render_main_merge_review",
    "render_main_merge_review_markdown",
    "render_tag_and_merge_checklist",
    "write_main_merge_review_reports",
]
