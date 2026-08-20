from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from polysia.cli import app

runner = CliRunner()


def test_operator_status_command_returns_sanitized_payload(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")

    result = runner.invoke(app, ["operator-status"])

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

    result = runner.invoke(app, ["operator-report", "--format", "markdown"])

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
        ["operator-report", "--format", "html", "--output", str(output)],
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
        ["observability-snapshot", "--output-dir", str(output_dir)],
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
        "polysia.cli.write_production_gap_audit_reports",
        fake_write_production_gap_audit_reports,
    )

    result = runner.invoke(
        app,
        ["production-gap-audit", "--output-dir", str(output_dir)],
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
        "polysia.cli.write_main_merge_review_reports",
        fake_write_main_merge_review_reports,
    )

    result = runner.invoke(
        app,
        ["main-merge-review", "--output-dir", str(output_dir)],
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
        "polysia.cli.write_local_release_closeout_reports",
        fake_write_local_release_closeout_reports,
    )

    result = runner.invoke(
        app,
        ["local-release-closeout", "--output-dir", str(output_dir)],
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

    monkeypatch.setattr("polysia.cli._reconcile_account", fake_reconcile_account)

    result = runner.invoke(
        app,
        ["reconcile-account", "--output-dir", str(output_dir)],
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
    result = runner.invoke(app, ["operator-report", "--format", "pdf"])

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

    result = runner.invoke(app, ["deployment-readiness"])

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

    result = runner.invoke(app, ["operator-runbook", "--include-live"])

    assert result.exit_code == 0
    assert result.stdout.startswith("# PolySia — Polymarket Adapter — Operator Runbook")
    assert "Live Dry-Run Only" in result.stdout
    assert "not-for-output" not in result.stdout
    assert "0xwallet" not in result.stdout
    assert "token-1" not in result.stdout


def test_operator_runbook_command_writes_markdown_file(tmp_path: Path) -> None:
    output = tmp_path / "operator-runbook.md"

    result = runner.invoke(app, ["operator-runbook", "--output", str(output)])

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

    result = runner.invoke(app, ["release-manifest"])

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

    result = runner.invoke(app, ["release-manifest", "--output", str(output)])

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
    combined = result.stdout + (output_dir / "acceptance_audit.json").read_text(
        encoding="utf-8"
    )
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined
