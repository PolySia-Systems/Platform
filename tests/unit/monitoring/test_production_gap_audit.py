from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring import production_gap_audit as module
from polysia.monitoring.production_gap_audit import (
    ProductionGapAuditConfig,
    build_production_gap_audit,
    write_production_gap_audit_reports,
)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 2, 9, 30, tzinfo=UTC)


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


def test_production_gap_audit_writes_valid_sanitized_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "release-artifacts"

    report = write_production_gap_audit_reports(
        ProductionGapAuditConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    json_path = output_dir / "production-gap-audit.json"
    markdown_path = output_dir / "production-gap-audit.md"
    freeze_path = output_dir / "phase-31-freeze-summary.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    combined = (
        json_path.read_text(encoding="utf-8")
        + markdown_path.read_text(encoding="utf-8")
        + freeze_path.read_text(encoding="utf-8")
    )
    assert report.status == "ready"
    assert payload["status"] == "ready"
    assert markdown_path.is_file()
    assert freeze_path.is_file()
    assert "not-for-output" not in combined
    assert "0x2222222222222222222222222222222222222222" not in combined
    assert "0x3333333333333333333333333333333333333333" not in combined
    assert "5797652204687091435321040411695795253208330542199837124800358911" not in combined
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in combined
    assert "signed_payload" not in combined
    assert "api_secret" not in combined


def test_production_gap_audit_classifies_live_blockers(tmp_path: Path) -> None:
    report = build_production_gap_audit(
        ProductionGapAuditConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=tmp_path,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )
    capabilities = {
        capability.name: capability.classification for capability in report.capabilities
    }

    assert capabilities["live strategy automation"] == "blocked-for-live"
    assert capabilities["live market making"] == "blocked-for-live"
    assert capabilities["capital scaling"] == "blocked-for-live"
    assert capabilities["repeated live tests"] == "blocked-for-live"


def test_research_and_paper_capabilities_are_not_production_ready(
    tmp_path: Path,
) -> None:
    report = build_production_gap_audit(
        ProductionGapAuditConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=tmp_path,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )
    capabilities = {
        capability.name: capability.classification for capability in report.capabilities
    }

    assert capabilities["stale-price strategy"] == "research-only"
    assert capabilities["passive market maker"] == "research-only"
    assert capabilities["paper broker"] == "paper-only"
    assert capabilities["shadow-run-real-data"] == "paper-only"


def test_production_gap_audit_merge_readiness_and_operator_decision(
    tmp_path: Path,
) -> None:
    report = build_production_gap_audit(
        ProductionGapAuditConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=tmp_path,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert report.merge_readiness.recommended_tag_name == (
        "v0.31.0-controlled-second-tiny-live-ready"
    )
    assert report.merge_readiness.recommended_merge_target == "main"
    assert report.merge_readiness.git_clean is True
    decision = report.final_operator_decision
    assert "production-gap-audit" in decision.safe_to_run_now
    assert "controlled-second-tiny-live" in decision.dry_run_only
    assert "live market making" in decision.blocked_from_live
    assert "second real tiny live test" in decision.requires_explicit_manual_approval


def test_production_gap_audit_never_references_live_submit_or_cancel() -> None:
    source = inspect.getsource(module)

    assert "LiveBroker" not in source
    assert "place_market_order" not in source
    assert "cancel_order" not in source


def ready_project(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Polymarket\n", encoding="utf-8")
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


def clean_git(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "chore/live-smoke-test-e2e\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "1fa024e\n"
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
