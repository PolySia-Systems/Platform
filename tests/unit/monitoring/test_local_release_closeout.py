from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.monitoring import local_release_closeout as module
from pm_trader.monitoring.local_release_closeout import (
    FINAL_LOCAL_RELEASE_TAG,
    LocalReleaseCloseoutConfig,
    build_local_release_closeout,
    write_local_release_closeout_reports,
)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 2, 14, 30, tzinfo=UTC)


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


def test_local_release_closeout_writes_valid_sanitized_artifacts(tmp_path: Path) -> None:
    output_dir = ready_artifacts(tmp_path)

    report = write_local_release_closeout_reports(
        LocalReleaseCloseoutConfig(
            settings=safe_settings(),
            project_root=tmp_path,
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_runner=clean_git_no_remote,
    )

    json_path = output_dir / "local-release-closeout.json"
    markdown_path = output_dir / "local-release-closeout.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    combined = (
        json_path.read_text(encoding="utf-8")
        + markdown_path.read_text(encoding="utf-8")
    )
    assert report.status == "ready"
    assert payload["status"] == "ready"
    assert markdown_path.is_file()
    assert FINAL_LOCAL_RELEASE_TAG in combined
    assert "GitHub remote is not configured; warning only." in combined
    assert "not-for-output" not in combined
    assert "0x2222222222222222222222222222222222222222" not in combined
    assert "0x3333333333333333333333333333333333333333" not in combined
    assert "5797652204687091435321040411695795253208330542199837124800358911" not in combined
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in combined


def test_local_release_closeout_missing_remote_is_warning_only(tmp_path: Path) -> None:
    report = build_local_release_closeout(
        LocalReleaseCloseoutConfig(
            settings=safe_settings(),
            project_root=tmp_path,
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_runner=clean_git_no_remote,
    )

    assert report.status == "ready"
    assert report.github_remote_status["configured"] is False
    assert any("warning only" in warning for warning in report.warnings)


def test_local_release_closeout_keeps_live_capabilities_blocked(tmp_path: Path) -> None:
    report = build_local_release_closeout(
        LocalReleaseCloseoutConfig(
            settings=safe_settings(),
            project_root=tmp_path,
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_runner=clean_git_no_remote,
    )

    assert "live market making" in report.blocked_from_live
    assert "live strategy automation" in report.blocked_from_live
    assert "capital scaling" in report.blocked_from_live
    assert "repeated live tests" in report.blocked_from_live
    assert "Live trading remains disabled by default." in report.safety_closeout
    assert "DATA_ONLY remains the default mode." in report.safety_closeout


def test_local_release_closeout_never_references_live_submit_or_cancel() -> None:
    source = inspect.getsource(module)

    assert "LiveBroker" not in source
    assert "place_market_order" not in source
    assert "cancel_order" not in source


def ready_artifacts(project_root: Path) -> Path:
    output_dir = project_root / "release-artifacts"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "main-merge-review.json").write_text(
        json.dumps({"status": "ready"}),
        encoding="utf-8",
    )
    (output_dir / "production-gap-audit.json").write_text(
        json.dumps({"status": "ready"}),
        encoding="utf-8",
    )
    (output_dir / "final-handoff.md").write_text("# Final Handoff\n", encoding="utf-8")
    return output_dir


def clean_git_no_remote(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "chore/live-smoke-test-e2e\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "42f3a4f\n"
    if command == ("git", "status", "--short"):
        return ""
    if command == ("git", "tag", "--list", "v0.33.0-main-merge-review-ready"):
        return "v0.33.0-main-merge-review-ready\n"
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
