from __future__ import annotations

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.deployment.automation import run_deployment_automation
from pm_trader.deployment.final_handoff import render_final_handoff_markdown


def test_final_handoff_markdown_is_sanitized(tmp_path) -> None:
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )
    result = run_deployment_automation(
        settings=settings,
        project_root=ready_project(tmp_path),
        output_dir=tmp_path / "release-artifacts",
        include_live_runbook=True,
        command_runner=lambda _root, _command: 0,
        git_runner=clean_git,
    )

    handoff = render_final_handoff_markdown(result)

    assert handoff.startswith("# Polymarket Final Handoff")
    assert "Final handoff status: ready" in handoff
    assert "Geoblock readiness: pass" in handoff
    assert "python -m pytest" in handoff
    assert "release-manifest.json" in handoff
    assert "not-for-output" not in handoff
    assert "0xwallet" not in handoff
    assert "token-secret" not in handoff


def test_final_handoff_marks_blocked_quality_gate(tmp_path) -> None:
    result = run_deployment_automation(
        settings=AppSettings(),
        project_root=ready_project(tmp_path),
        output_dir=tmp_path / "release-artifacts",
        command_runner=lambda _root, _command: 1,
        git_runner=clean_git,
    )

    handoff = render_final_handoff_markdown(result)

    assert "Final handoff status: blocked" in handoff
    assert "- tests: fail" in handoff


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
