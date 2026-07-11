from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pm_trader.config.settings import AppSettings
from pm_trader.monitoring.readiness import (
    DeploymentReadinessReport,
    build_deployment_readiness,
)

Clock = Callable[[], datetime]
GitRunner = Callable[[Path, tuple[str, ...]], str]
ReleaseCheckStatus = Literal["pass", "warn", "fail"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PackageMetadata:
    """Sanitized Python package metadata for release handoff."""

    name: str | None
    version: str | None
    requires_python: str | None
    build_backend: str | None
    cli_entrypoint: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "build_backend": self.build_backend,
            "cli_entrypoint": self.cli_entrypoint,
            "name": self.name,
            "requires_python": self.requires_python,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class GitSnapshot:
    """Sanitized git state for release handoff."""

    available: bool
    branch: str | None
    commit: str | None
    clean: bool

    def to_dict(self) -> dict[str, bool | str | None]:
        return {
            "available": self.available,
            "branch": self.branch,
            "clean": self.clean,
            "commit": self.commit,
        }


@dataclass(frozen=True, slots=True)
class ReleaseManifestCheck:
    """One sanitized release-manifest check."""

    name: str
    status: ReleaseCheckStatus
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
class ReleaseManifest:
    """Release handoff manifest with only safe operational metadata."""

    status: Literal["ready", "blocked"]
    timestamp: datetime
    package: PackageMetadata
    git: GitSnapshot
    readiness: DeploymentReadinessReport
    checks: tuple[ReleaseManifestCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "git": self.git.to_dict(),
            "package": self.package.to_dict(),
            "readiness": self.readiness.to_dict(),
            "status": self.status,
            "summary": _summarize_checks(self.checks),
            "timestamp": self.timestamp.isoformat(),
        }


def build_release_manifest(
    *,
    settings: AppSettings,
    project_root: Path,
    require_clean_git: bool = False,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> ReleaseManifest:
    """Build a sanitized release handoff manifest."""

    root = project_root.resolve()
    pyproject = _read_pyproject(root / "pyproject.toml")
    package = _package_metadata(pyproject)
    git = _git_snapshot(root, git_runner=git_runner)
    readiness = build_deployment_readiness(
        settings=settings,
        project_root=root,
        require_clean_git=require_clean_git,
    )
    checks = (
        _check_package_metadata(package),
        _check_wheel_package_config(pyproject),
        _check_operator_artifacts(root),
        _check_git_snapshot(git, require_clean_git=require_clean_git),
    )
    status: Literal["ready", "blocked"] = (
        "blocked"
        if readiness.status == "blocked" or any(check.status == "fail" for check in checks)
        else "ready"
    )
    return ReleaseManifest(
        status=status,
        timestamp=clock(),
        package=package,
        git=git,
        readiness=readiness,
        checks=checks,
    )


def _read_pyproject(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return dict(data)


def _package_metadata(pyproject: dict[str, Any]) -> PackageMetadata:
    build_system = _mapping(pyproject.get("build-system"))
    project = _mapping(pyproject.get("project"))
    scripts = _mapping(project.get("scripts"))
    return PackageMetadata(
        name=_string_or_none(project.get("name")),
        version=_string_or_none(project.get("version")),
        requires_python=_string_or_none(project.get("requires-python")),
        build_backend=_string_or_none(build_system.get("build-backend")),
        cli_entrypoint=_string_or_none(scripts.get("pm-trader")),
    )


def _check_package_metadata(package: PackageMetadata) -> ReleaseManifestCheck:
    missing = [
        name
        for name, value in package.to_dict().items()
        if value is None or value == ""
    ]
    if missing:
        return ReleaseManifestCheck(
            name="package-metadata",
            status="fail",
            message=f"Package metadata is incomplete: {', '.join(missing)}.",
            remediation="Complete pyproject.toml package metadata before release.",
        )
    if package.build_backend != "hatchling.build":
        return ReleaseManifestCheck(
            name="package-metadata",
            status="fail",
            message="Build backend is not hatchling.build.",
            remediation="Use the configured hatchling build backend for this package.",
        )
    if package.cli_entrypoint != "pm_trader.cli:app":
        return ReleaseManifestCheck(
            name="package-metadata",
            status="fail",
            message="pm-trader CLI entrypoint is missing or unexpected.",
            remediation="Restore [project.scripts] pm-trader = pm_trader.cli:app.",
        )
    return ReleaseManifestCheck(
        name="package-metadata",
        status="pass",
        message="Package metadata and CLI entrypoint are configured.",
    )


def _check_wheel_package_config(pyproject: dict[str, Any]) -> ReleaseManifestCheck:
    packages = _wheel_packages(pyproject)
    if "src/pm_trader" not in packages:
        return ReleaseManifestCheck(
            name="wheel-package-config",
            status="fail",
            message="Wheel package config does not include src/pm_trader.",
            remediation="Restore [tool.hatch.build.targets.wheel] packages.",
        )
    return ReleaseManifestCheck(
        name="wheel-package-config",
        status="pass",
        message="Wheel config includes the pm_trader source package.",
    )


def _check_operator_artifacts(project_root: Path) -> ReleaseManifestCheck:
    required = ("README.md", "docs/OPERATOR_RUNBOOK.md")
    missing = tuple(path for path in required if not (project_root / path).is_file())
    if missing:
        return ReleaseManifestCheck(
            name="operator-artifacts",
            status="fail",
            message=f"Release operator artifacts are missing: {', '.join(missing)}.",
            remediation="Restore README.md and docs/OPERATOR_RUNBOOK.md before release.",
        )
    return ReleaseManifestCheck(
        name="operator-artifacts",
        status="pass",
        message="Release operator artifacts are present.",
    )


def _check_git_snapshot(
    git: GitSnapshot,
    *,
    require_clean_git: bool,
) -> ReleaseManifestCheck:
    if not git.available:
        return ReleaseManifestCheck(
            name="git-snapshot",
            status="warn",
            message="Git metadata is not available.",
            remediation="Run git status manually before a release handoff.",
        )
    if require_clean_git and not git.clean:
        return ReleaseManifestCheck(
            name="git-snapshot",
            status="fail",
            message="Git worktree has uncommitted changes.",
            remediation="Commit or intentionally clear local changes before release.",
        )
    if not require_clean_git and not git.clean:
        return ReleaseManifestCheck(
            name="git-snapshot",
            status="warn",
            message="Git worktree has uncommitted changes.",
            remediation="Use --require-clean-git for strict release handoff checks.",
        )
    return ReleaseManifestCheck(
        name="git-snapshot",
        status="pass",
        message="Git metadata is available and worktree is clean.",
    )


def _git_snapshot(project_root: Path, *, git_runner: GitRunner | None) -> GitSnapshot:
    runner = git_runner or _run_git
    try:
        branch = runner(project_root, ("git", "branch", "--show-current")).strip()
        commit = runner(project_root, ("git", "rev-parse", "--short", "HEAD")).strip()
        status = runner(project_root, ("git", "status", "--short")).strip()
    except (OSError, subprocess.SubprocessError):
        return GitSnapshot(available=False, branch=None, commit=None, clean=False)
    return GitSnapshot(
        available=True,
        branch=branch or "detached",
        commit=commit or None,
        clean=status == "",
    )


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


def _wheel_packages(pyproject: dict[str, Any]) -> tuple[str, ...]:
    tool = _mapping(pyproject.get("tool"))
    hatch = _mapping(tool.get("hatch"))
    build = _mapping(hatch.get("build"))
    targets = _mapping(build.get("targets"))
    wheel = _mapping(targets.get("wheel"))
    packages = wheel.get("packages")
    if isinstance(packages, list):
        return tuple(str(package) for package in packages)
    if isinstance(packages, tuple):
        return tuple(str(package) for package in packages)
    return ()


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _summarize_checks(checks: tuple[ReleaseManifestCheck, ...]) -> dict[str, int]:
    summary = {"fail": 0, "pass": 0, "warn": 0}
    for check in checks:
        summary[check.status] += 1
    return summary
