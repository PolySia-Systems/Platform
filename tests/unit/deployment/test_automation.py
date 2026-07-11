from __future__ import annotations

import json
from datetime import UTC, datetime

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.deployment.automation import run_deployment_automation


def test_deployment_automation_writes_sanitized_artifacts(tmp_path) -> None:
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )
    output_dir = tmp_path / "release-artifacts"

    result = run_deployment_automation(
        settings=settings,
        project_root=ready_project(tmp_path),
        output_dir=output_dir,
        include_live_runbook=True,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        command_runner=lambda _root, _command: 0,
        git_runner=clean_git,
    )
    payload = result.to_dict()

    assert payload["status"] == "ready"
    assert payload["summary"] == {"fail": 0, "pass": 3, "skipped": 0}
    assert (output_dir / "release-manifest.json").is_file()
    assert (output_dir / "operator-runbook.md").is_file()
    assert (output_dir / "deployment-automation.json").is_file()
    assert "not-for-output" not in str(payload)
    assert "0xwallet" not in str(payload)
    assert "token-secret" not in str(payload)
    assert "Live Dry-Run Only" in (output_dir / "operator-runbook.md").read_text(
        encoding="utf-8"
    )


def test_deployment_automation_blocks_failed_quality_gate(tmp_path) -> None:
    def failing_runner(_root, command: tuple[str, ...]) -> int:
        return 1 if command[-1] == "pytest" else 0

    result = run_deployment_automation(
        settings=AppSettings(),
        project_root=ready_project(tmp_path),
        output_dir=tmp_path / "release-artifacts",
        command_runner=failing_runner,
        git_runner=clean_git,
    )

    assert result.status == "blocked"
    assert result.quality_gates[0].name == "tests"
    assert result.quality_gates[0].status == "fail"


def test_deployment_automation_can_skip_quality_gates(tmp_path) -> None:
    result = run_deployment_automation(
        settings=AppSettings(),
        project_root=ready_project(tmp_path),
        output_dir=tmp_path / "release-artifacts",
        run_quality_checks=False,
        git_runner=clean_git,
    )

    assert result.status == "ready"
    assert {gate.status for gate in result.quality_gates} == {"skipped"}
    automation_payload = json.loads(
        (tmp_path / "release-artifacts" / "deployment-automation.json").read_text(
            encoding="utf-8"
        )
    )
    assert automation_payload["summary"] == {"fail": 0, "pass": 0, "skipped": 3}


def ready_project(tmp_path):
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "docs" / "OPERATOR_RUNBOOK.md").write_text("# Runbook\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "TRADING_MODE=DATA_ONLY",
                "LIVE_TRADING_ENABLED=false",
                "POLYMARKET_PRIVATE_KEY" + "=",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "\n".join(
            (
                ".env",
                ".env.*",
                "!.env.example",
                "*.key",
                "*.pem",
                "*.sqlite3",
                "secrets/",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
build-backend = "hatchling.build"

[project]
name = "polymarket-trading-system"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
pm-trader = "pm_trader.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/pm_trader"]
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


def clean_git(_root, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "main\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "abc1234\n"
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
