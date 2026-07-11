from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring import main_merge_review as module
from polysia.monitoring.main_merge_review import (
    MainMergeReviewConfig,
    build_main_merge_review,
    write_main_merge_review_reports,
)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 2, 11, 15, tzinfo=UTC)


def safe_settings() -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_FUNDER_ADDRESS="0x3333333333333333333333333333333333333333",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=(
            "5797652204687091435321040411695795253208330542199837124800358911"
        ),
        POLYMARKET_WALLET_ADDRESS="0x2222222222222222222222222222222222222222",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


def test_main_merge_review_writes_valid_sanitized_artifacts(tmp_path: Path) -> None:
    output_dir = ready_artifacts(tmp_path)

    report = write_main_merge_review_reports(
        MainMergeReviewConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_runner=clean_git_no_remote,
    )

    json_path = output_dir / "main-merge-review.json"
    markdown_path = output_dir / "main-merge-review.md"
    checklist_path = output_dir / "tag-and-merge-checklist.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    combined = (
        json_path.read_text(encoding="utf-8")
        + markdown_path.read_text(encoding="utf-8")
        + checklist_path.read_text(encoding="utf-8")
    )
    assert report.status == "ready"
    assert payload["status"] == "ready"
    assert markdown_path.is_file()
    assert checklist_path.is_file()
    assert "v0.31.0-controlled-second-tiny-live-ready" in combined
    assert payload["recommended_merge_target"] == "main"
    assert "not-for-output" not in combined
    assert "0x2222222222222222222222222222222222222222" not in combined
    assert "0x3333333333333333333333333333333333333333" not in combined
    assert "5797652204687091435321040411695795253208330542199837124800358911" not in combined
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in combined


def test_main_merge_review_missing_remote_is_warning_only(tmp_path: Path) -> None:
    report = build_main_merge_review(
        MainMergeReviewConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_runner=clean_git_no_remote,
    )

    assert report.status == "ready"
    assert report.remote_status["configured"] is False
    assert any("remote" in warning.lower() for warning in report.warnings)


def test_main_merge_review_keeps_live_capabilities_blocked(tmp_path: Path) -> None:
    report = build_main_merge_review(
        MainMergeReviewConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_runner=clean_git_no_remote,
    )

    assert "live strategy automation" in report.blocked_for_live_capabilities
    assert "live market making" in report.blocked_for_live_capabilities
    assert "capital scaling" in report.blocked_for_live_capabilities
    assert "controlled-second-tiny-live" in report.dry_run_only_capabilities


def test_main_merge_review_never_references_live_submit_or_cancel() -> None:
    source = inspect.getsource(module)

    assert "LiveBroker" not in source
    assert "place_market_order" not in source
    assert "cancel_order" not in source


def ready_project(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Polymarket\n", encoding="utf-8")
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
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


def ready_artifacts(project_root: Path) -> Path:
    output_dir = project_root / "release-artifacts"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "production-gap-audit.json").write_text(
        json.dumps({"status": "ready"}),
        encoding="utf-8",
    )
    (output_dir / "final-handoff.md").write_text("# Final Handoff\n", encoding="utf-8")
    (output_dir / "deployment-automation.json").write_text(
        json.dumps(
            {
                "quality_gates": [
                    {"name": "tests", "status": "pass"},
                    {"name": "lint", "status": "pass"},
                    {"name": "typecheck", "status": "pass"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return output_dir


def clean_git_no_remote(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "chore/live-smoke-test-e2e\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "00816c9\n"
    if command == ("git", "status", "--short"):
        return ""
    if command == (
        "git",
        "tag",
        "--list",
        "v0.31.0-controlled-second-tiny-live-ready",
    ):
        return "v0.31.0-controlled-second-tiny-live-ready\n"
    if command == ("git", "remote", "-v"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
