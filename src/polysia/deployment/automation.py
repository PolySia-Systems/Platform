from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from polysia.config.settings import AppSettings
from polysia.deployment.manifest import (
    GitRunner,
    ReleaseManifest,
    build_release_manifest,
)
from polysia.monitoring.metrics import build_operator_status
from polysia.monitoring.readiness import DeploymentReadinessReport
from polysia.monitoring.runbook import render_operator_runbook_markdown

Clock = Callable[[], datetime]
CommandRunner = Callable[[Path, tuple[str, ...]], int]
AutomationStepStatus = Literal["pass", "fail", "skipped"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DeploymentAutomationStep:
    """One deployment automation gate."""

    name: str
    status: AutomationStepStatus
    command: tuple[str, ...]
    returncode: int | None = None

    def to_dict(self) -> dict[str, int | list[str] | str | None]:
        return {
            "command": list(self.command),
            "name": self.name,
            "returncode": self.returncode,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class DeploymentAutomationResult:
    """Sanitized deployment automation result."""

    status: Literal["ready", "blocked"]
    timestamp: datetime
    quality_gates: tuple[DeploymentAutomationStep, ...]
    readiness: DeploymentReadinessReport
    release_manifest: ReleaseManifest
    artifacts: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "artifacts": self.artifacts,
            "quality_gates": [gate.to_dict() for gate in self.quality_gates],
            "readiness": self.readiness.to_dict(),
            "release_manifest": self.release_manifest.to_dict(),
            "status": self.status,
            "summary": _summarize_steps(self.quality_gates),
            "timestamp": self.timestamp.isoformat(),
        }


def run_deployment_automation(
    *,
    settings: AppSettings,
    project_root: Path,
    output_dir: Path,
    require_clean_git: bool = False,
    include_live_runbook: bool = False,
    run_quality_checks: bool = True,
    python_executable: str = sys.executable,
    clock: Clock = utc_now,
    command_runner: CommandRunner | None = None,
    git_runner: GitRunner | None = None,
) -> DeploymentAutomationResult:
    """Run local deployment automation and write sanitized handoff artifacts."""

    root = project_root.resolve()
    gates = _quality_gates(
        project_root=root,
        python_executable=python_executable,
        run_quality_checks=run_quality_checks,
        command_runner=command_runner or _run_command,
    )
    release_manifest = build_release_manifest(
        settings=settings,
        project_root=root,
        require_clean_git=require_clean_git,
        git_runner=git_runner,
    )
    readiness = release_manifest.readiness
    artifacts = _write_artifacts(
        output_dir=output_dir,
        release_manifest=release_manifest,
        operator_runbook=render_operator_runbook_markdown(
            operator_status=build_operator_status(settings=settings),
            readiness=readiness,
            include_live=include_live_runbook,
        ),
    )
    automation_path = output_dir / "deployment-automation.json"
    artifacts = {**artifacts, "deployment_automation": str(automation_path)}
    status: Literal["ready", "blocked"] = (
        "blocked"
        if release_manifest.status == "blocked"
        or readiness.status == "blocked"
        or any(gate.status == "fail" for gate in gates)
        else "ready"
    )
    result = DeploymentAutomationResult(
        status=status,
        timestamp=clock(),
        quality_gates=gates,
        readiness=readiness,
        release_manifest=release_manifest,
        artifacts=artifacts,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    automation_path.write_text(
        f"{json.dumps(result.to_dict(), indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    return result


def _quality_gates(
    *,
    project_root: Path,
    python_executable: str,
    run_quality_checks: bool,
    command_runner: CommandRunner,
) -> tuple[DeploymentAutomationStep, ...]:
    commands = (
        ("tests", (python_executable, "-m", "pytest")),
        ("lint", (python_executable, "-m", "ruff", "check", ".")),
        ("typecheck", (python_executable, "-m", "mypy", "src")),
    )
    if not run_quality_checks:
        return tuple(
            DeploymentAutomationStep(
                name=name,
                status="skipped",
                command=_display_command(command),
            )
            for name, command in commands
        )

    steps: list[DeploymentAutomationStep] = []
    for name, command in commands:
        returncode = command_runner(project_root, command)
        steps.append(
            DeploymentAutomationStep(
                name=name,
                status="pass" if returncode == 0 else "fail",
                command=_display_command(command),
                returncode=returncode,
            )
        )
    return tuple(steps)


def _display_command(command: tuple[str, ...]) -> tuple[str, ...]:
    if len(command) >= 3 and command[1] == "-m":
        return ("python", *command[1:])
    return command


def _write_artifacts(
    *,
    output_dir: Path,
    release_manifest: ReleaseManifest,
    operator_runbook: str,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    release_manifest_path = output_dir / "release-manifest.json"
    operator_runbook_path = output_dir / "operator-runbook.md"
    release_manifest_path.write_text(
        f"{json.dumps(release_manifest.to_dict(), indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    operator_runbook_path.write_text(operator_runbook, encoding="utf-8")
    return {
        "operator_runbook": str(operator_runbook_path),
        "release_manifest": str(release_manifest_path),
    }


def _run_command(project_root: Path, command: tuple[str, ...]) -> int:
    result = subprocess.run(
        list(command),
        check=False,
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode


def _summarize_steps(
    steps: tuple[DeploymentAutomationStep, ...],
) -> dict[str, int]:
    summary = {"fail": 0, "pass": 0, "skipped": 0}
    for step in steps:
        summary[step.status] += 1
    return summary
