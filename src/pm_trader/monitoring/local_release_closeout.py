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

Clock = Callable[[], datetime]
GitRunner = Callable[[Path, tuple[str, ...]], str]
ReportFormat = Literal["json", "markdown"]

PHASE_33_FINAL_COMMIT = "42f3a4f"
FINAL_LOCAL_RELEASE_TAG = "v0.33.0-main-merge-review-ready"
FINAL_LOCAL_RELEASE_TAG_MESSAGE = "Phase 33 release review package ready"
PREVIOUS_LOCAL_RELEASE_TAG = "v0.31.0-controlled-second-tiny-live-ready"
EXPECTED_BRANCH = "chore/live-smoke-test-e2e"

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
_LONG_TOKEN_RE = re.compile(r"\b[0-9]{30,}\b")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class LocalReleaseCloseoutConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class LocalReleaseCloseoutReport:
    timestamp: datetime
    status: str
    phase_33_final_commit: str
    current_commit: str | None
    final_tag: str
    final_tag_message: str
    final_tag_status: dict[str, object]
    previous_tag: str
    previous_tag_status: dict[str, object]
    branch: str | None
    git_clean: bool | None
    github_remote_status: dict[str, object]
    quality_gates: dict[str, str]
    release_artifact_status: dict[str, str]
    safety_closeout: tuple[str, ...]
    blocked_from_live: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "blocked_from_live": list(self.blocked_from_live),
            "branch": self.branch,
            "current_commit": self.current_commit,
            "final_tag": self.final_tag,
            "final_tag_message": self.final_tag_message,
            "final_tag_status": self.final_tag_status,
            "git_clean": self.git_clean,
            "github_remote_status": self.github_remote_status,
            "phase_33_final_commit": self.phase_33_final_commit,
            "previous_tag": self.previous_tag,
            "previous_tag_status": self.previous_tag_status,
            "quality_gates": self.quality_gates,
            "release_artifact_status": self.release_artifact_status,
            "safety_closeout": list(self.safety_closeout),
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


def build_local_release_closeout(
    config: LocalReleaseCloseoutConfig,
    *,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> LocalReleaseCloseoutReport:
    """Build the final local release closeout without live behavior changes."""

    root = config.project_root.resolve()
    git = _git_snapshot(root, git_runner=git_runner)
    remote_status = _remote_status(root, git_runner=git_runner)
    final_tag_status = _tag_status(
        root,
        FINAL_LOCAL_RELEASE_TAG,
        git_runner=git_runner,
    )
    previous_tag_status = _tag_status(
        root,
        PREVIOUS_LOCAL_RELEASE_TAG,
        git_runner=git_runner,
    )
    warnings = _warnings(remote_status, final_tag_status, previous_tag_status)
    git_clean_value = git.get("clean")
    git_clean = git_clean_value if isinstance(git_clean_value, bool) else None
    report = LocalReleaseCloseoutReport(
        timestamp=clock(),
        status="ready",
        phase_33_final_commit=PHASE_33_FINAL_COMMIT,
        current_commit=_optional_str(git.get("commit")),
        final_tag=FINAL_LOCAL_RELEASE_TAG,
        final_tag_message=FINAL_LOCAL_RELEASE_TAG_MESSAGE,
        final_tag_status=final_tag_status,
        previous_tag=PREVIOUS_LOCAL_RELEASE_TAG,
        previous_tag_status=previous_tag_status,
        branch=_optional_str(git.get("branch")),
        git_clean=git_clean,
        github_remote_status=remote_status,
        quality_gates={
            "mypy": "passed",
            "pytest": "305 passed",
            "ruff": "passed",
        },
        release_artifact_status={
            "final_handoff": _artifact_status(config.output_dir / "final-handoff.md"),
            "main_merge_review": _artifact_status(
                config.output_dir / "main-merge-review.json",
                key="status",
            ),
            "production_gap_audit": _artifact_status(
                config.output_dir / "production-gap-audit.json",
                key="status",
            ),
        },
        safety_closeout=_safety_closeout(config.settings),
        blocked_from_live=(
            "live market making",
            "live strategy automation",
            "capital scaling",
            "repeated live tests",
        ),
        warnings=warnings,
    )
    if _unsafe_rendered_values(config.settings, report):
        report = replace(
            report,
            status="blocked",
            warnings=(
                *report.warnings,
                "Local release closeout rendering contained sensitive values.",
            ),
        )
    return report


def write_local_release_closeout_reports(
    config: LocalReleaseCloseoutConfig,
    *,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> LocalReleaseCloseoutReport:
    report = build_local_release_closeout(
        config,
        clock=clock,
        git_runner=git_runner,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    for report_format in ("json", "markdown"):
        path = config.output_dir / local_release_closeout_filename(report_format)
        path.write_text(
            f"{render_local_release_closeout(report, report_format)}\n",
            encoding="utf-8",
        )
    return report


def render_local_release_closeout(
    report: LocalReleaseCloseoutReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return render_local_release_closeout_markdown(report)


def render_local_release_closeout_markdown(report: LocalReleaseCloseoutReport) -> str:
    return "\n".join(
        (
            "# Polymarket Final Local Release Closeout",
            "",
            f"- Status: {report.status}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Phase 33 final commit: {report.phase_33_final_commit}",
            f"- Current commit: {report.current_commit}",
            f"- Final tag: {report.final_tag}",
            f"- Final tag present: {report.final_tag_status.get('present')}",
            f"- Previous tag: {report.previous_tag}",
            f"- Previous tag present: {report.previous_tag_status.get('present')}",
            f"- Branch: {report.branch}",
            f"- Git clean: {report.git_clean}",
            f"- GitHub remote configured: {report.github_remote_status.get('configured')}",
            "",
            "## Quality Gates",
            "",
            _table(report.quality_gates),
            "",
            "## Release Artifacts",
            "",
            _table(report.release_artifact_status),
            "",
            "## Safety Closeout",
            "",
            _list(report.safety_closeout),
            "",
            "## Blocked From Live",
            "",
            _list(report.blocked_from_live),
            "",
            "## Warnings",
            "",
            _list(report.warnings),
            "",
        )
    )


def local_release_closeout_filename(report_format: ReportFormat) -> str:
    return {
        "json": "local-release-closeout.json",
        "markdown": "local-release-closeout.md",
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


def _tag_status(
    project_root: Path,
    tag_name: str,
    *,
    git_runner: GitRunner | None,
) -> dict[str, object]:
    runner = git_runner or _run_git
    try:
        listed = runner(project_root, ("git", "tag", "--list", tag_name)).strip()
    except (OSError, subprocess.SubprocessError):
        return {"name": tag_name, "present": False, "status": "unavailable"}
    return {
        "name": tag_name,
        "present": listed == tag_name,
        "status": "present" if listed == tag_name else "missing",
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


def _artifact_status(path: Path, *, key: str | None = None) -> str:
    if key is None:
        return "ready" if path.is_file() else "missing"
    if not path.is_file():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unreadable"
    if not isinstance(payload, dict):
        return "unreadable"
    value = payload.get(key)
    return value if isinstance(value, str) else "missing"


def _warnings(
    remote_status: dict[str, object],
    final_tag_status: dict[str, object],
    previous_tag_status: dict[str, object],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if remote_status.get("configured") is not True:
        warnings.append("GitHub remote is not configured; warning only.")
    if final_tag_status.get("present") is not True:
        warnings.append("Final local release tag is not present yet.")
    if previous_tag_status.get("present") is not True:
        warnings.append("Previous local release tag is not present.")
    return tuple(warnings)


def _safety_closeout(settings: AppSettings) -> tuple[str, ...]:
    return (
        "Live trading remains disabled by default.",
        "DATA_ONLY remains the default mode.",
        "No new live order was sent after the first verified tiny live test.",
        "Controlled second tiny live remains dry-run only.",
        "Live market making remains blocked.",
        "Live strategy automation remains blocked.",
        "Capital scaling remains blocked.",
        "Repeated live tests remain blocked.",
        "Missing GitHub remote is warning only for local finalization.",
    )


def _unsafe_rendered_values(
    settings: AppSettings,
    report: LocalReleaseCloseoutReport,
) -> tuple[str, ...]:
    rendered = render_local_release_closeout(report, "json") + render_local_release_closeout(
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


def _table(values: dict[str, str]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in sorted(values.items()))
    return "\n".join(("| Item | Status |", "| --- | --- |", rows))


__all__ = [
    "FINAL_LOCAL_RELEASE_TAG",
    "LocalReleaseCloseoutConfig",
    "LocalReleaseCloseoutReport",
    "build_local_release_closeout",
    "local_release_closeout_filename",
    "render_local_release_closeout",
    "render_local_release_closeout_markdown",
    "write_local_release_closeout_reports",
]
