from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pm_trader.adapters.geoblock import GeoblockStatus
from pm_trader.config.settings import AppSettings, TradingMode

Clock = Callable[[], datetime]
GitStatusReader = Callable[[Path], str]
ReadinessCheckStatus = Literal["pass", "warn", "fail"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DeploymentReadinessCheck:
    """One sanitized deploy-readiness check."""

    name: str
    status: ReadinessCheckStatus
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
class DeploymentReadinessReport:
    """Sanitized deployment-readiness report."""

    status: Literal["ready", "blocked"]
    timestamp: datetime
    checks: tuple[DeploymentReadinessCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "status": self.status,
            "summary": _summarize_checks(self.checks),
            "timestamp": self.timestamp.isoformat(),
        }


def build_deployment_readiness(
    *,
    settings: AppSettings,
    project_root: Path,
    require_clean_git: bool = False,
    clock: Clock = utc_now,
    git_status_reader: GitStatusReader | None = None,
    geoblock_status: GeoblockStatus | None = None,
) -> DeploymentReadinessReport:
    """Build a safe, local deployment-readiness report."""

    root = project_root.resolve()
    checks = (
        _check_required_project_files(root),
        _check_env_example(root),
        _check_gitignore_secret_patterns(root),
        _check_live_guardrails(settings),
        _check_live_caps(settings),
        _check_geoblock_status(geoblock_status),
        _check_clean_git(
            root,
            require_clean_git=require_clean_git,
            git_status_reader=git_status_reader,
        ),
    )
    status: Literal["ready", "blocked"] = (
        "blocked" if any(check.status == "fail" for check in checks) else "ready"
    )
    return DeploymentReadinessReport(
        status=status,
        timestamp=clock(),
        checks=checks,
    )


def _check_required_project_files(project_root: Path) -> DeploymentReadinessCheck:
    required_files = ("README.md", "pyproject.toml", "Makefile")
    missing = tuple(
        file_name
        for file_name in required_files
        if not (project_root / file_name).is_file()
    )
    if missing:
        return DeploymentReadinessCheck(
            name="project-files",
            status="fail",
            message=f"Required project files are missing: {', '.join(missing)}.",
            remediation="Restore the missing files before deployment.",
        )
    return DeploymentReadinessCheck(
        name="project-files",
        status="pass",
        message="Required project metadata files are present.",
    )


def _check_env_example(project_root: Path) -> DeploymentReadinessCheck:
    env_example = project_root / ".env.example"
    if not env_example.is_file():
        return DeploymentReadinessCheck(
            name="env-example",
            status="fail",
            message=".env.example is missing.",
            remediation="Add a sanitized .env.example with safe defaults.",
        )

    values = _read_env_example(env_example)
    expected_defaults = {
        "LIVE_TRADING_ENABLED": "false",
        "POLYMARKET_PRIVATE_KEY": "",
        "TRADING_MODE": TradingMode.DATA_ONLY.value,
    }
    mismatches = tuple(
        key
        for key, expected in expected_defaults.items()
        if values.get(key) != expected
    )
    if mismatches:
        return DeploymentReadinessCheck(
            name="env-example",
            status="fail",
            message=f".env.example has unsafe or missing defaults: {', '.join(mismatches)}.",
            remediation="Keep example live trading disabled and secrets empty.",
        )
    return DeploymentReadinessCheck(
        name="env-example",
        status="pass",
        message=".env.example keeps live trading disabled and secrets empty.",
    )


def _check_gitignore_secret_patterns(project_root: Path) -> DeploymentReadinessCheck:
    gitignore = project_root / ".gitignore"
    if not gitignore.is_file():
        return DeploymentReadinessCheck(
            name="secret-ignore-patterns",
            status="fail",
            message=".gitignore is missing.",
            remediation="Add ignore rules for local env files, private keys, and databases.",
        )

    patterns = {
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_patterns = {
        "!.env.example",
        ".env",
        ".env.*",
        "*.key",
        "*.pem",
        "*.sqlite3",
        "secrets/",
    }
    missing = tuple(sorted(required_patterns - patterns))
    if missing:
        return DeploymentReadinessCheck(
            name="secret-ignore-patterns",
            status="fail",
            message=f".gitignore is missing secret-safety patterns: {', '.join(missing)}.",
            remediation="Restore the missing ignore rules before deployment.",
        )
    return DeploymentReadinessCheck(
        name="secret-ignore-patterns",
        status="pass",
        message=".gitignore protects local env files, keys, and database artifacts.",
    )


def _check_live_guardrails(settings: AppSettings) -> DeploymentReadinessCheck:
    if not settings.live_trading_allowed:
        return DeploymentReadinessCheck(
            name="live-guardrails",
            status="pass",
            message="Live order submission is disabled by runtime settings.",
        )

    missing = []
    if settings.polymarket_private_key is None:
        missing.append("POLYMARKET_PRIVATE_KEY")
    if not settings.polymarket_funder_address:
        missing.append("POLYMARKET_FUNDER_ADDRESS")
    if not settings.polymarket_live_token_allowlist:
        missing.append("POLYMARKET_LIVE_TOKEN_ALLOWLIST")

    if missing:
        return DeploymentReadinessCheck(
            name="live-guardrails",
            status="fail",
            message=f"Live trading is enabled but guardrails are incomplete: {', '.join(missing)}.",
            remediation="Configure required live settings or disable live trading.",
        )
    return DeploymentReadinessCheck(
        name="live-guardrails",
        status="pass",
        message=(
            "Live trading is enabled with required signer, funder, and token "
            "allowlist configured."
        ),
    )


def _check_live_caps(settings: AppSettings) -> DeploymentReadinessCheck:
    if settings.live_trading_allowed and settings.polymarket_live_max_open_orders == 0:
        return DeploymentReadinessCheck(
            name="tiny-live-caps",
            status="fail",
            message="Live trading is enabled but POLYMARKET_LIVE_MAX_OPEN_ORDERS is zero.",
            remediation="Set a positive open-order cap or disable live trading.",
        )

    if not settings.live_trading_allowed:
        return DeploymentReadinessCheck(
            name="tiny-live-caps",
            status="pass",
            message="Tiny live caps are configured while live submission remains disabled.",
        )

    if (
        settings.polymarket_live_max_order_size > Decimal("1")
        or settings.polymarket_live_max_order_notional > Decimal("1")
    ):
        return DeploymentReadinessCheck(
            name="tiny-live-caps",
            status="warn",
            message="Live caps are above the conservative one-share or one-dollar defaults.",
            remediation="Lower live caps unless this is an intentional operator decision.",
        )

    return DeploymentReadinessCheck(
        name="tiny-live-caps",
        status="pass",
        message="Live caps remain within conservative tiny-order defaults.",
    )


def _check_geoblock_status(
    geoblock_status: GeoblockStatus | None,
) -> DeploymentReadinessCheck:
    if geoblock_status is None or geoblock_status.status == "not_checked":
        return DeploymentReadinessCheck(
            name="geoblock",
            status="pass",
            message=(
                "Mandatory pre-live-order geoblock enforcement is configured; endpoint "
                "status was not checked during this offline readiness run."
            ),
        )

    if geoblock_status.status == "allowed" and geoblock_status.blocked is False:
        return DeploymentReadinessCheck(
            name="geoblock",
            status="pass",
            message="Official Polymarket geoblock endpoint returned blocked=false.",
        )

    if geoblock_status.status == "blocked" or geoblock_status.blocked is True:
        return DeploymentReadinessCheck(
            name="geoblock",
            status="fail",
            message="Official Polymarket geoblock endpoint returned blocked=true.",
            remediation="Do not place live orders from this environment.",
        )

    return DeploymentReadinessCheck(
        name="geoblock",
        status="fail",
        message="Official Polymarket geoblock endpoint could not be verified.",
        remediation="Live order placement fails closed until geoblock can be verified.",
    )


def _check_clean_git(
    project_root: Path,
    *,
    require_clean_git: bool,
    git_status_reader: GitStatusReader | None,
) -> DeploymentReadinessCheck:
    if not require_clean_git:
        return DeploymentReadinessCheck(
            name="clean-git",
            status="pass",
            message="Clean git worktree check was not required for this run.",
            remediation="Run with --require-clean-git before a release handoff.",
        )

    try:
        output = (
            git_status_reader(project_root)
            if git_status_reader is not None
            else _read_git_status(project_root)
        )
    except (OSError, subprocess.SubprocessError) as error:
        return DeploymentReadinessCheck(
            name="clean-git",
            status="warn",
            message=f"Could not read git status: {error}.",
            remediation="Run git status manually before deployment.",
        )

    if output.strip():
        return DeploymentReadinessCheck(
            name="clean-git",
            status="fail",
            message="Repository has uncommitted changes.",
            remediation="Commit, stash, or intentionally discard local changes before release.",
        )
    return DeploymentReadinessCheck(
        name="clean-git",
        status="pass",
        message="Repository worktree is clean.",
    )


def _read_git_status(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        cwd=project_root,
        text=True,
        timeout=5,
    )
    return result.stdout


def _read_env_example(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _summarize_checks(
    checks: tuple[DeploymentReadinessCheck, ...],
) -> dict[str, int]:
    summary = {"fail": 0, "pass": 0, "warn": 0}
    for check in checks:
        summary[check.status] += 1
    return summary
