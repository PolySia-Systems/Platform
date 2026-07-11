from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.tiny_live_readiness import (
    TinyLiveReadinessConfig,
    build_tiny_live_readiness,
    render_tiny_live_readiness_html,
    render_tiny_live_readiness_json,
    render_tiny_live_readiness_markdown,
)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, tzinfo=UTC)


def test_tiny_live_readiness_passes_when_all_inputs_are_ready(tmp_path: Path) -> None:
    project_root = ready_project(tmp_path)
    output_dir = ready_artifacts(tmp_path)
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )

    report = build_tiny_live_readiness(
        TinyLiveReadinessConfig(
            settings=settings,
            project_root=project_root,
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_status_reader=lambda _root: "",
        git_runner=clean_git,
    )

    assert report.final_result == "READY_FOR_TINY_LIVE_REVIEW"
    assert report.no_live_order_placed is True
    assert report.blocking_reasons == ()
    combined = (
        render_tiny_live_readiness_json(report)
        + render_tiny_live_readiness_markdown(report)
        + render_tiny_live_readiness_html(report)
    )
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined


def test_tiny_live_readiness_dry_run_only_without_allowlist(tmp_path: Path) -> None:
    report = build_tiny_live_readiness(
        TinyLiveReadinessConfig(
            settings=AppSettings(_env_file=None),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_status_reader=lambda _root: "",
        git_runner=clean_git,
    )

    assert report.final_result == "READY_FOR_TINY_LIVE_DRY_RUN_ONLY"
    assert any("allowlist" in warning.lower() for warning in report.warnings)


def test_tiny_live_readiness_blocks_when_live_is_enabled(tmp_path: Path) -> None:
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )

    report = build_tiny_live_readiness(
        TinyLiveReadinessConfig(
            settings=settings,
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_status_reader=lambda _root: "",
        git_runner=clean_git,
    )

    assert report.final_result == "NOT_READY_FOR_TINY_LIVE"
    assert any("live trading enabled" in reason.lower() for reason in report.blocking_reasons)


def test_tiny_live_readiness_blocks_strategy_not_ready(tmp_path: Path) -> None:
    project_root = ready_project(tmp_path)
    output_dir = ready_artifacts(tmp_path)
    (output_dir / "strategy_evaluation.json").write_text(
        json.dumps({"classification": "STRATEGY_NOT_READY"}),
        encoding="utf-8",
    )

    report = build_tiny_live_readiness(
        TinyLiveReadinessConfig(
            settings=AppSettings(_env_file=None),
            project_root=project_root,
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_status_reader=lambda _root: "",
        git_runner=clean_git,
    )

    assert report.final_result == "NOT_READY_FOR_TINY_LIVE"
    assert any("strategy-evaluation" in reason for reason in report.blocking_reasons)


def test_tiny_live_readiness_warns_for_missing_default_report(tmp_path: Path) -> None:
    project_root = ready_project(tmp_path)
    output_dir = ready_artifacts(tmp_path)
    (output_dir / "fill_simulation_audit.json").unlink()

    report = build_tiny_live_readiness(
        TinyLiveReadinessConfig(
            settings=AppSettings(_env_file=None),
            project_root=project_root,
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_status_reader=lambda _root: "",
        git_runner=clean_git,
    )

    assert report.final_result == "READY_FOR_TINY_LIVE_DRY_RUN_ONLY"
    assert any("fill-simulation-audit" in warning for warning in report.warnings)


def ready_artifacts(tmp_path: Path) -> Path:
    output_dir = tmp_path / "release-artifacts"
    output_dir.mkdir()
    (output_dir / "acceptance_audit.json").write_text(
        json.dumps({"final_result": "READY_FOR_TINY_LIVE"}),
        encoding="utf-8",
    )
    (output_dir / "shadow_run.json").write_text(
        json.dumps({"classification": "SHADOW_HEALTHY"}),
        encoding="utf-8",
    )
    (output_dir / "strategy_evaluation.json").write_text(
        json.dumps({"classification": "STRATEGY_READY_FOR_TINY_LIVE_REVIEW"}),
        encoding="utf-8",
    )
    (output_dir / "fill_simulation_audit.json").write_text(
        json.dumps({"classification": "FILL_MODEL_CONSERVATIVE_OK"}),
        encoding="utf-8",
    )
    (output_dir / "final-handoff.md").write_text("# Final Handoff\n", encoding="utf-8")
    return output_dir


def ready_project(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "src" / "polysia" / "execution").mkdir(parents=True)
    (tmp_path / "src" / "polysia" / "strategies").mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        "POLYMARKET_PRIVATE_KEY signer\nPOLYMARKET_FUNDER_ADDRESS funder\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "LIVE_CONNECTIVITY_SMOKE_TEST.md").write_text(
        "POLYMARKET_PRIVATE_KEY signer\nPOLYMARKET_FUNDER_ADDRESS funder\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "OPERATOR_RUNBOOK.md").write_text("# Runbook\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "TRADING_MODE=DATA_ONLY",
                "LIVE_TRADING_ENABLED=false",
                "POLYMARKET_PRIVATE_KEY=",
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
name = "polysia"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
polysia = "polysia.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/polysia"]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "src" / "polysia" / "execution" / "live_broker.py").write_text(
        "i_understand_this_places_real_orders\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "polysia" / "execution" / "live_smoke_test.py").write_text(
        "i-understand-this-places-a-real-order\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "polysia" / "strategies" / "safe.py").write_text(
        "class SafeStrategy: pass\n",
        encoding="utf-8",
    )
    return tmp_path


def clean_git(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "main\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "abc1234\n"
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
