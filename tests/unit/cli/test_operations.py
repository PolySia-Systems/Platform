from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from polysia.cli import app
from polysia.reconciliation.live_round_trip import LiveRoundTripReconciliationReport

runner = CliRunner()


def _live_round_trip_reconciliation_report() -> LiveRoundTripReconciliationReport:
    return LiveRoundTripReconciliationReport(
        run_id="live-run",
        authorization_id="POLYSIA-LIVE-004",
        classification="COMPLETED_ROUND_TRIP",
        status="ready",
        observed_order_status="MATCHED",
        confirmed_exit_size=Decimal("5"),
        expected_remaining_position=Decimal("0"),
        observed_position_size=Decimal("0"),
        weighted_average_exit_price=Decimal("0.58"),
        gross_exit_proceeds=Decimal("2.90"),
        allocated_entry_cost=Decimal("2.68736"),
        exit_fee=Decimal("0"),
        fee_status="confirmed",
        net_realized_pnl=Decimal("0.21264"),
        fill_count=1,
        new_fill_count=1,
        new_ledger_event_count=2,
        duplicate_fill_count=0,
        observation_recorded=True,
        observation_id="observation-1",
        warnings=(),
        blocking_reasons=(),
    )


def _write_json_file(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_operator_status_command_returns_sanitized_payload(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")

    result = runner.invoke(app, ["system", "status"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["tiny_live_orders_ready"] is True
    assert payload["runtime"]["private_key_configured"] is True
    assert payload["runtime"]["funder_address_configured"] is True
    assert payload["runtime"]["wallet_address_configured"] is True
    assert "not-for-output" not in result.stdout
    assert "0xfunder" not in result.stdout
    assert "0xwallet" not in result.stdout
    assert "token-1" not in result.stdout


def test_operator_report_command_prints_markdown(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")

    result = runner.invoke(app, ["system", "report", "--format", "markdown"])

    assert result.exit_code == 0
    assert result.stdout.startswith("# PolySia — Polymarket Adapter — Operator Report")
    assert "## Runtime" in result.stdout
    assert "not-for-output" not in result.stdout
    assert "0xfunder" not in result.stdout
    assert "0xwallet" not in result.stdout
    assert "token-1" not in result.stdout


def test_operator_report_command_writes_html_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")
    output = tmp_path / "operator-report.html"

    result = runner.invoke(
        app,
        ["system", "report", "--format", "html", "--output", str(output)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["format"] == "html"
    report = output.read_text(encoding="utf-8")
    assert report.startswith("<!doctype html>")
    assert "PolySia — Polymarket Adapter — Operator Report" in report
    assert "not-for-output" not in report
    assert "0xfunder" not in report
    assert "0xwallet" not in report
    assert "token-1" not in report


def test_observability_snapshot_command_writes_sanitized_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")
    output_dir = tmp_path / "observability"

    result = runner.invoke(
        app,
        ["system", "observability", "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["observability_status"] in {"ready", "warning"}
    assert (output_dir / "observability-snapshot.json").is_file()
    assert (output_dir / "observability-snapshot.md").is_file()
    assert (output_dir / "observability-dashboard.html").is_file()
    combined = (
        result.stdout
        + (output_dir / "observability-snapshot.json").read_text(encoding="utf-8")
        + (output_dir / "observability-snapshot.md").read_text(encoding="utf-8")
        + (output_dir / "observability-dashboard.html").read_text(encoding="utf-8")
    )
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-1" not in combined


def test_production_gap_audit_command_writes_reports(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "production-gap"

    def fake_write_production_gap_audit_reports(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "production-gap-audit.json").write_text(
            json.dumps({"status": "ready"}),
            encoding="utf-8",
        )
        (config.output_dir / "production-gap-audit.md").write_text(
            "# PolySia — Polymarket Adapter — Production Gap Audit\n",
            encoding="utf-8",
        )
        (config.output_dir / "phase-31-freeze-summary.md").write_text(
            "# Phase 31 Release Freeze Summary\n",
            encoding="utf-8",
        )
        return SimpleNamespace(status="ready")

    monkeypatch.setattr(
        "polysia.cli_commands.operations.write_production_gap_audit_reports",
        fake_write_production_gap_audit_reports,
    )

    result = runner.invoke(
        app,
        ["ops", "production-gap-audit", "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["audit_status"] == "ready"
    assert (output_dir / "production-gap-audit.json").is_file()
    assert (output_dir / "production-gap-audit.md").is_file()
    assert (output_dir / "phase-31-freeze-summary.md").is_file()


def test_main_merge_review_command_writes_reports(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "main-merge"

    def fake_write_main_merge_review_reports(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "main-merge-review.json").write_text(
            json.dumps({"status": "ready"}),
            encoding="utf-8",
        )
        (config.output_dir / "main-merge-review.md").write_text(
            "# PolySia — Polymarket Adapter — Main Merge Review\n",
            encoding="utf-8",
        )
        (config.output_dir / "tag-and-merge-checklist.md").write_text(
            "# Tag and Merge Checklist\n",
            encoding="utf-8",
        )
        return SimpleNamespace(status="ready")

    monkeypatch.setattr(
        "polysia.cli_commands.operations.write_main_merge_review_reports",
        fake_write_main_merge_review_reports,
    )

    result = runner.invoke(
        app,
        ["ops", "main-merge-review", "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["review_status"] == "ready"
    assert (output_dir / "main-merge-review.json").is_file()
    assert (output_dir / "main-merge-review.md").is_file()
    assert (output_dir / "tag-and-merge-checklist.md").is_file()


def test_local_release_closeout_command_writes_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "local-closeout"

    def fake_write_local_release_closeout_reports(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "local-release-closeout.json").write_text(
            json.dumps({"status": "ready"}),
            encoding="utf-8",
        )
        (config.output_dir / "local-release-closeout.md").write_text(
            "# PolySia — Polymarket Adapter — Final Local Release Closeout\n",
            encoding="utf-8",
        )
        return SimpleNamespace(status="ready")

    monkeypatch.setattr(
        "polysia.cli_commands.operations.write_local_release_closeout_reports",
        fake_write_local_release_closeout_reports,
    )

    result = runner.invoke(
        app,
        ["ops", "local-release-closeout", "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["closeout_status"] == "ready"
    assert (output_dir / "local-release-closeout.json").is_file()
    assert (output_dir / "local-release-closeout.md").is_file()


def test_reconcile_account_command_writes_reports(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "reconciliation"

    async def fake_reconcile_account(**kwargs):
        output_dir_arg = kwargs["output_dir"]
        output_dir_arg.mkdir(parents=True, exist_ok=True)
        (output_dir_arg / "reconciliation-report.json").write_text(
            json.dumps({"status": "ready"}),
            encoding="utf-8",
        )
        (output_dir_arg / "reconciliation-report.md").write_text(
            "# PolySia — Polymarket Adapter — Reconciliation Report\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            manual_intervention_detected=False,
            status=SimpleNamespace(value="ready"),
            trading_should_pause=False,
        )

    monkeypatch.setattr(
        "polysia.cli_commands.operations._reconcile_account", fake_reconcile_account
    )

    result = runner.invoke(
        app,
        ["ops", "reconcile-account", "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["reconciliation_status"] == "ready"
    assert payload["manual_intervention_detected"] is False
    assert payload["trading_should_pause"] is False
    assert (output_dir / "reconciliation-report.json").is_file()
    assert (output_dir / "reconciliation-report.md").is_file()


def test_operator_report_command_rejects_unknown_format() -> None:
    result = runner.invoke(app, ["system", "report", "--format", "pdf"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "html, json, or markdown" in payload["message"]


def test_deployment_readiness_command_returns_sanitized_payload(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")

    result = runner.invoke(app, ["ops", "deployment-readiness"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["summary"]["fail"] == 0
    assert "not-for-output" not in result.stdout
    assert "0xwallet" not in result.stdout
    assert "token-1" not in result.stdout


def test_operator_runbook_command_prints_markdown(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")

    result = runner.invoke(app, ["system", "runbook", "--include-live"])

    assert result.exit_code == 0
    assert result.stdout.startswith("# PolySia — Polymarket Adapter — Operator Runbook")
    assert "Live Dry-Run Only" in result.stdout
    assert "not-for-output" not in result.stdout
    assert "0xwallet" not in result.stdout
    assert "token-1" not in result.stdout


def test_operator_runbook_command_writes_markdown_file(tmp_path: Path) -> None:
    output = tmp_path / "operator-runbook.md"

    result = runner.invoke(app, ["system", "runbook", "--output", str(output)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["include_live"] is False
    runbook = output.read_text(encoding="utf-8")
    assert runbook.startswith("# PolySia — Polymarket Adapter — Operator Runbook")
    assert "Live Dry-Run Only" not in runbook


def test_release_manifest_command_prints_sanitized_json(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")

    result = runner.invoke(app, ["ops", "release-manifest"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["package"]["cli_entrypoint"] == "polysia.cli:app"
    assert payload["readiness"]["status"] == "ready"
    assert "not-for-output" not in result.stdout
    assert "0xwallet" not in result.stdout
    assert "token-1" not in result.stdout


def test_release_manifest_command_writes_json_file(tmp_path: Path) -> None:
    output = tmp_path / "release-manifest.json"

    result = runner.invoke(app, ["ops", "release-manifest", "--output", str(output)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["release_status"] == "ready"
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["status"] == "ready"
    assert manifest["package"]["name"] == "polysia"


def test_deployment_automation_command_writes_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "release-artifacts"

    result = runner.invoke(
        app,
        [
            "ops",
            "deployment-automation",
            "--skip-quality-checks",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["summary"] == {"fail": 0, "pass": 0, "skipped": 3}
    assert (output_dir / "release-manifest.json").is_file()
    assert (output_dir / "operator-runbook.md").is_file()
    assert (output_dir / "deployment-automation.json").is_file()


def test_final_handoff_command_writes_markdown(tmp_path: Path) -> None:
    output_dir = tmp_path / "release-artifacts"

    result = runner.invoke(
        app,
        [
            "ops",
            "final-handoff",
            "--skip-quality-checks",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["handoff_status"] == "ready"
    assert (output_dir / "deployment-automation.json").is_file()
    assert (output_dir / "release-manifest.json").is_file()
    assert (output_dir / "operator-runbook.md").is_file()
    final_handoff = output_dir / "final-handoff.md"
    assert final_handoff.is_file()
    assert final_handoff.read_text(encoding="utf-8").startswith(
        "# PolySia — Polymarket Adapter — Final Handoff"
    )


def test_acceptance_audit_command_writes_sanitized_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-secret")
    output_dir = tmp_path / "acceptance"

    result = runner.invoke(
        app,
        [
            "ops",
            "acceptance-audit",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] in {"READY_FOR_SHADOW", "READY_FOR_TINY_LIVE"}
    assert (output_dir / "acceptance_audit.json").is_file()
    assert (output_dir / "acceptance_audit.md").is_file()
    assert (output_dir / "acceptance_audit.html").is_file()
    combined = result.stdout + (output_dir / "acceptance_audit.json").read_text(encoding="utf-8")
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined


def test_reconcile_live_round_trip_command_uses_read_only_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    reader = object()

    async def fake_reconcile(config, *, venue_reader):
        captured["config"] = config
        captured["reader"] = venue_reader
        return _live_round_trip_reconciliation_report()

    monkeypatch.setattr("polysia.cli_commands.operations.configure_logging", lambda _settings: None)
    monkeypatch.setattr(
        "polysia.cli_commands.operations.cli_support.apply_secure_env_from_settings",
        lambda _settings: None,
    )
    monkeypatch.setattr("polysia.cli_commands.operations.PolymarketRoundTripReader", lambda: reader)
    monkeypatch.setattr("polysia.cli_commands.operations.reconcile_live_round_trip", fake_reconcile)

    database_path = tmp_path / "state.sqlite3"
    result = runner.invoke(
        app,
        [
            "ops",
            "reconcile-live-round-trip",
            "--run-id",
            "live-run",
            "--database",
            str(database_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["classification"] == "COMPLETED_ROUND_TRIP"
    assert payload["net_realized_pnl"] == "0.21264"
    assert captured["reader"] is reader
    assert captured["config"].database_path == database_path


def test_monitor_live_round_trip_command_uses_bounded_read_only_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    venue_reader = object()
    health_reader = object()

    async def fake_monitor(config, *, venue_reader, health_reader):
        captured["config"] = config
        captured["venue_reader"] = venue_reader
        captured["health_reader"] = health_reader
        return SimpleNamespace(
            status="warning",
            cycles=(
                SimpleNamespace(
                    alerts=(SimpleNamespace(code="EXIT_ORDER_STALE"),),
                ),
            ),
            new_alert_count=1,
            duplicate_alert_count=0,
        )

    def fake_write(_report, output_dir: Path):
        return {
            "json": output_dir / "live-round-trip-monitor.json",
            "markdown": output_dir / "live-round-trip-monitor.md",
        }

    monkeypatch.setattr("polysia.cli_commands.operations.configure_logging", lambda _settings: None)
    monkeypatch.setattr(
        "polysia.cli_commands.operations.cli_support.apply_secure_env_from_settings",
        lambda _settings: None,
    )
    monkeypatch.setattr(
        "polysia.cli_commands.operations.PolymarketRoundTripReader", lambda: venue_reader
    )
    monkeypatch.setattr(
        "polysia.cli_commands.operations.PolymarketLifecycleHealthReader", lambda: health_reader
    )
    monkeypatch.setattr("polysia.cli_commands.operations.monitor_live_round_trip", fake_monitor)
    monkeypatch.setattr(
        "polysia.cli_commands.operations.write_live_round_trip_monitor_reports", fake_write
    )

    database_path = tmp_path / "state.sqlite3"
    result = runner.invoke(
        app,
        [
            "ops",
            "monitor-live-round-trip",
            "--run-id",
            "live-run",
            "--database",
            str(database_path),
            "--output-dir",
            str(tmp_path / "reports"),
            "--max-cycles",
            "2",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["monitor_status"] == "warning"
    assert payload["alert_codes"] == ["EXIT_ORDER_STALE"]
    assert captured["venue_reader"] is venue_reader
    assert captured["health_reader"] is health_reader
    assert captured["config"].database_path == database_path
    assert captured["config"].max_cycles == 2


def test_tiny_live_monitor_command_writes_reports(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "monitor"

    async def fake_write_monitor_reports(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "tiny-live-monitor.json").write_text(
            json.dumps({"status": "ready"}),
            encoding="utf-8",
        )
        (config.output_dir / "tiny-live-monitor.md").write_text(
            "# PolySia — Polymarket Adapter — Tiny Live Monitor\n",
            encoding="utf-8",
        )
        return SimpleNamespace(status="ready")

    monkeypatch.setattr(
        "polysia.cli_commands.operations.write_tiny_live_monitor_reports",
        fake_write_monitor_reports,
    )

    result = runner.invoke(
        app,
        [
            "ops",
            "tiny-live-monitor",
            "--output-dir",
            str(output_dir),
            "--redact-secrets",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["monitor_status"] == "ready"
    assert (output_dir / "tiny-live-monitor.json").is_file()
    assert (output_dir / "tiny-live-monitor.md").is_file()


def test_tiny_live_readiness_command_writes_sanitized_reports(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    acceptance = _write_json_file(
        tmp_path / "acceptance_audit.json",
        {"final_result": "READY_FOR_SHADOW"},
    )
    shadow = _write_json_file(
        tmp_path / "shadow_run.json",
        {"classification": "SHADOW_HEALTHY"},
    )
    strategy = _write_json_file(
        tmp_path / "strategy_evaluation.json",
        {"classification": "STRATEGY_READY_FOR_SHADOW"},
    )
    fill = _write_json_file(
        tmp_path / "fill_simulation_audit.json",
        {"classification": "FILL_MODEL_NEEDS_MORE_DATA"},
    )

    result = runner.invoke(
        app,
        [
            "live",
            "readiness",
            "--acceptance-audit",
            str(acceptance),
            "--shadow-run",
            str(shadow),
            "--strategy-evaluation",
            str(strategy),
            "--fill-simulation-audit",
            str(fill),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] == "READY_FOR_TINY_LIVE_DRY_RUN_ONLY"
    assert payload["no_live_order_placed"] is True
    reports = [
        output_dir / "tiny_live_readiness.json",
        output_dir / "tiny_live_readiness.md",
        output_dir / "tiny_live_readiness.html",
    ]
    assert all(path.is_file() for path in reports)
    combined = result.stdout + "".join(path.read_text(encoding="utf-8") for path in reports)
    assert "not-for-output" not in combined
    assert "No live order was placed" in combined
