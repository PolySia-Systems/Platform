from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from polysia.adapters.geoblock import GeoblockStatus
from polysia.adapters.polymarket_public import (
    MarketDetails,
    MarketOutcomeSummary,
    MarketSummary,
    PolymarketPublicAdapterError,
)
from polysia.cli import (
    _live_account_status,
    _live_limit_order,
    _safe_open_order_to_dict,
    _safe_order_response,
    app,
)
from polysia.config.settings import AppSettings, TradingMode
from polysia.execution.live_broker import LiveBrokerError
from polysia.execution.tiny_live_execution import TinyLiveExecutionReport
from polysia.monitoring.real_data_shadow_run import (
    RealDataShadowMetrics,
    RealDataShadowRunReport,
)

runner = CliRunner()


def _write_json_file(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _tiny_execution_report(
    *,
    final_result: str = "DRY_RUN_PASS",
    blocking_reasons: tuple[str, ...] = (),
) -> TinyLiveExecutionReport:
    return TinyLiveExecutionReport(
        timestamp=datetime(2026, 7, 1, tzinfo=UTC),
        dry_run=final_result.startswith("DRY_RUN"),
        final_result=final_result,  # type: ignore[arg-type]
        token_allowlisted=True,
        geoblock_status={"status": "error", "blocked": None},
        kill_switch_active=False,
        risk_decision={"approved": False, "reason": "mock"},
        order_type="FAK",
        side="BUY",
        outcome="YES",
        max_notional="1.00",
        order_submitted=False,
        order_filled=False,
        fill_summary={},
        rejection_summary={},
        live_attempt_count=0,
        no_retry_statement="No retry was attempted",
        one_attempt_statement="Only one order attempt was allowed",
        no_strategy_loop_statement="No strategy loop or market-making loop was used",
        blocking_reasons=blocking_reasons,
        warnings=(),
        operator_next_steps=("Fix blocking reasons and rerun dry-run only.",),
        diagnostics={},
    )


def _real_data_shadow_report() -> RealDataShadowRunReport:
    return RealDataShadowRunReport(
        timestamp=datetime(2026, 7, 1, tzinfo=UTC),
        final_result="REAL_DATA_SHADOW_HEALTHY",
        strategy="stale-price",
        metrics=RealDataShadowMetrics(
            selected_market_slug="btc-updown-5m-test",
            selected_token_configured=True,
            event_count=1,
            orderbook_updates=1,
            orderbook_freshness_age_ms=0,
            stream_health="public_stream",
            stream_warning_count=0,
            strategy_intent_count=1,
            risk_approval_count=1,
            risk_denial_count=0,
            paper_order_count=1,
            paper_fill_count=1,
            paper_position=Decimal("1"),
            paper_realized_pnl=Decimal("0"),
            paper_unrealized_pnl=Decimal("0"),
            paper_total_pnl=Decimal("0"),
            latency_average_ms=Decimal("1"),
            latency_p95_ms=Decimal("1"),
            latency_p99_ms=Decimal("1"),
            live_broker_used=False,
        ),
        warnings=(),
        reasons=("public data paper workflow exercised",),
        no_live_trading_statement="No live broker, submit, or cancel path was used.",
        events=({"event_index": 0, "event_type": "book", "selected_token": True},),
    )


class FakeSecureAdapter:
    instances: list[FakeSecureAdapter] = []

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.limit_order_calls: list[dict[str, object]] = []
        self.response: dict[str, object] = {
            "ok": True,
            "order_id": "order-1",
            "status": "live",
            "making_amount": Decimal("0.5"),
            "taking_amount": Decimal("1"),
            "trade_ids": (),
            "transactions_hashes": ("0xhash",),
        }
        self.instances.append(self)

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def place_limit_order(self, **kwargs: object) -> dict[str, object]:
        self.limit_order_calls.append(kwargs)
        return self.response


class FakeAccountStatusAdapter:
    instances: list[FakeAccountStatusAdapter] = []

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    def identity(self) -> SimpleNamespace:
        return SimpleNamespace(
            to_dict=lambda: {
                "active_wallet_source": "funder",
                "configured_signature_type": 3,
                "funder_configured": True,
                "legacy_wallet_configured": False,
                "sdk_signature_type": 3,
                "signature_type_matches_sdk": True,
                "signer_configured": True,
                "wallet_type": "DEPOSIT_WALLET",
            }
        )

    async def get_balance_allowance(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(balance=1000000, allowances={"exchange": 1, "adapter": 0})

    async def list_positions(self, **_kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(token_id="token-1", size=Decimal("1"))]

    async def get_open_orders(self, **_kwargs: object) -> list[SimpleNamespace]:
        return []


def test_health_command_returns_safe_payload(monkeypatch) -> None:
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_WALLET_ADDRESS", raising=False)
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)

    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["trading_mode"] == "DATA_ONLY"
    assert payload["live_trading_enabled"] is False
    assert payload["live_trading_allowed"] is False
    assert "polymarket_private_key" not in payload


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
        "polysia.cli.write_tiny_live_monitor_reports",
        fake_write_monitor_reports,
    )

    result = runner.invoke(
        app,
        [
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


def test_controlled_second_tiny_live_command_writes_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "controlled"

    async def fake_run_controlled(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "controlled-second-tiny-live.json").write_text(
            json.dumps({"final_result": "DRY_RUN_READY"}),
            encoding="utf-8",
        )
        (config.output_dir / "controlled-second-tiny-live.md").write_text(
            "# PolySia — Polymarket Adapter — Controlled Second Tiny Live\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            final_result="DRY_RUN_READY",
            live_attempt_count=0,
            order_submitted=False,
        )

    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-yes")
    monkeypatch.setattr(
        "polysia.cli.run_controlled_second_tiny_live",
        fake_run_controlled,
    )

    result = runner.invoke(
        app,
        [
            "controlled-second-tiny-live",
            "--token-id",
            "token-yes",
            "--market-slug",
            "btc-updown-5m-test",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FOK",
            "--dry-run",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] == "DRY_RUN_READY"
    assert payload["live_attempt_count"] == 0
    assert (output_dir / "controlled-second-tiny-live.json").is_file()
    assert (output_dir / "controlled-second-tiny-live.md").is_file()


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


def test_manual_intervention_live_test_command_writes_dry_run_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "manual-intervention"

    async def fake_resolve_live_smoke_selection(**_kwargs):
        return SimpleNamespace(
            condition_id="condition-1",
            market_slug="btc-updown-5m-test",
            token_id="token-yes",
        )

    async def fake_run_manual_intervention_live_test(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "manual-intervention-live-test.json").write_text(
            json.dumps({"final_result": "DRY_RUN_READY"}),
            encoding="utf-8",
        )
        (config.output_dir / "manual-intervention-live-test.md").write_text(
            "# PolySia — Polymarket Adapter — Controlled Manual Intervention Live Test\n",
            encoding="utf-8",
        )
        assert config.dry_run is True
        assert config.token_id == "token-yes"
        return SimpleNamespace(
            final_result="DRY_RUN_READY",
            live_attempt_count=0,
            manual_intervention_detected=False,
            order_submitted=False,
            trading_should_pause=False,
        )

    apply_calls = []

    def fake_apply_secure_env_from_settings(settings):
        apply_calls.append(settings)

    monkeypatch.setattr(
        "polysia.cli._resolve_live_smoke_selection",
        fake_resolve_live_smoke_selection,
    )
    monkeypatch.setattr(
        "polysia.cli.run_manual_intervention_live_test",
        fake_run_manual_intervention_live_test,
    )
    monkeypatch.setattr(
        "polysia.cli._apply_secure_env_from_settings",
        fake_apply_secure_env_from_settings,
    )

    result = runner.invoke(
        app,
        [
            "manual-intervention-live-test",
            "--auto-btc-5m",
            "--outcome",
            "YES",
            "--side",
            "BUY",
            "--max-notional",
            "1.00",
            "--order-type",
            "FOK",
            "--dry-run",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] == "DRY_RUN_READY"
    assert payload["live_attempt_count"] == 0
    assert payload["order_submitted"] is False
    assert len(apply_calls) == 1
    assert (output_dir / "manual-intervention-live-test.json").is_file()
    assert (output_dir / "manual-intervention-live-test.md").is_file()


def test_strategy_evaluation_command_writes_sanitized_reports(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    input_path = tmp_path / "shadow_run.json"
    output_dir = tmp_path / "reports"
    input_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "strategy_intent_count": 3,
                    "risk_approval_count": 3,
                    "risk_rejection_count": 0,
                    "paper_order_count": 3,
                    "paper_fill_count": 3,
                    "paper_total_pnl": "0.15",
                },
                "secret": "not-for-output",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "strategy-evaluation",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--min-sample-size",
            "3",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["classification"] == "STRATEGY_READY_FOR_TINY_LIVE_REVIEW"
    reports = [
        output_dir / "strategy_evaluation.json",
        output_dir / "strategy_evaluation.md",
        output_dir / "strategy_evaluation.html",
    ]
    assert all(path.is_file() for path in reports)
    combined = result.stdout + "".join(
        path.read_text(encoding="utf-8") for path in reports
    )
    assert "not-for-output" not in combined


def test_strategy_evaluation_command_rejects_malformed_input(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.json"
    input_path.write_text("{bad", encoding="utf-8")

    result = runner.invoke(app, ["strategy-evaluation", "--input", str(input_path)])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"


def test_strategy_evaluation_extended_command_writes_reports(tmp_path: Path) -> None:
    input_path = tmp_path / "shadow-run-real-data.json"
    output_dir = tmp_path / "reports"
    input_path.write_text(
        json.dumps(
            {
                "events_processed": 1,
                "intents_generated": 1,
                "metrics": {"paper_total_pnl": "0.01", "risk_approval_count": 1},
                "orders": [
                    {
                        "intent": {
                            "outcome": 1,
                            "p_model": "0.9",
                            "side": "BUY",
                        },
                        "order": {"status": "FILLED"},
                    }
                ],
                "orders_created": 1,
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "strategy-evaluation-extended",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] == "EXTENDED_EVALUATION_READY"
    assert (output_dir / "strategy-evaluation-extended.json").is_file()
    assert (output_dir / "strategy-evaluation-extended.md").is_file()
    assert (output_dir / "strategy-evaluation-extended.html").is_file()


def test_fill_simulation_audit_command_writes_sanitized_reports(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    input_path = tmp_path / "orders.json"
    output_dir = tmp_path / "reports"
    input_path.write_text(
        json.dumps(
            {
                "orders": [
                    {
                        "book": {
                            "ask_depth": "3",
                            "best_ask": "0.52",
                            "best_bid": "0.49",
                            "bid_depth": "10",
                        },
                        "intent": {
                            "price": "0.53",
                            "side": "BUY",
                            "size": "1",
                            "token_id": "token-1",
                        },
                        "order_id": "order-1",
                        "token_id": "token-1",
                    }
                ],
                "secret": "not-for-output",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "fill-simulation-audit",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "conservative",
            "--model",
            "top-of-book",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["classification"] == "FILL_MODEL_CONSERVATIVE_OK"
    reports = [
        output_dir / "fill_simulation_audit.json",
        output_dir / "fill_simulation_audit.md",
        output_dir / "fill_simulation_audit.html",
    ]
    assert all(path.is_file() for path in reports)
    combined = result.stdout + "".join(
        path.read_text(encoding="utf-8") for path in reports
    )
    assert "not-for-output" not in combined
    assert "No live trading" in combined


def test_fill_simulation_audit_command_rejects_bad_model() -> None:
    result = runner.invoke(app, ["fill-simulation-audit", "--model", "optimistic"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "model must be one of" in payload["message"]


def test_tiny_live_readiness_command_writes_sanitized_reports(
    monkeypatch, tmp_path: Path
) -> None:
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
            "tiny-live-readiness",
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
    combined = result.stdout + "".join(
        path.read_text(encoding="utf-8") for path in reports
    )
    assert "not-for-output" not in combined
    assert "No live order was placed" in combined


def test_tiny_live_execute_dry_run_writes_sanitized_reports(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-yes")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    output_dir = tmp_path / "reports"

    result = runner.invoke(
        app,
        [
            "tiny-live-execute",
            "--token-id",
            "token-yes",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FAK",
            "--market-slug",
            "btc-updown-5m-test",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["final_result"] == "DRY_RUN_PASS"
    assert payload["order_submitted"] is False
    reports = [
        output_dir / "tiny_live_execution.json",
        output_dir / "tiny_live_execution.md",
        output_dir / "tiny_live_execution.html",
    ]
    assert all(path.is_file() for path in reports)
    combined = result.stdout + "".join(
        path.read_text(encoding="utf-8") for path in reports
    )
    assert "not-for-output" not in combined
    assert "No retry was attempted" in combined


def test_tiny_live_execute_no_dry_run_blocks_without_ack(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-yes")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")

    result = runner.invoke(
        app,
        [
            "tiny-live-execute",
            "--token-id",
            "token-yes",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FOK",
            "--output-dir",
            str(tmp_path),
            "--no-dry-run",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["order_submitted"] is False


def test_tiny_live_execute_no_dry_run_blocks_without_allowlist(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.delenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", raising=False)

    result = runner.invoke(
        app,
        [
            "tiny-live-execute",
            "--token-id",
            "token-yes",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FAK",
            "--output-dir",
            str(tmp_path),
            "--no-dry-run",
            "--i-understand-this-places-one-real-order",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["live_attempt_count"] == 0


def test_tiny_live_execute_cli_geoblock_blocked_with_mock(
    monkeypatch, tmp_path: Path
) -> None:
    async def fake_run(*_args: object, **_kwargs: object) -> TinyLiveExecutionReport:
        return _tiny_execution_report(
            final_result="LIVE_ORDER_BLOCKED",
            blocking_reasons=("Polymarket geoblock check failed closed.",),
        )

    monkeypatch.setattr("polysia.cli.run_tiny_live_execution", fake_run)

    result = runner.invoke(
        app,
        [
            "tiny-live-execute",
            "--token-id",
            "token-yes",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FAK",
            "--output-dir",
            str(tmp_path),
            "--no-dry-run",
            "--i-understand-this-places-one-real-order",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"


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


def test_acceptance_audit_command_blocks_when_live_flag_enabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    result = runner.invoke(
        app,
        [
            "acceptance-audit",
            "--json",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    report = json.loads((tmp_path / "acceptance_audit.json").read_text(encoding="utf-8"))
    assert report["final_result"] == "NOT_READY"


def test_shadow_run_command_writes_sanitized_reports(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-secret")
    output_dir = tmp_path / "shadow"

    result = runner.invoke(
        app,
        [
            "shadow-run",
            "--max-events",
            "3",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["classification"] == "SHADOW_HEALTHY"
    assert (output_dir / "shadow_run.json").is_file()
    assert (output_dir / "shadow_run.md").is_file()
    assert (output_dir / "shadow_run.html").is_file()
    assert (output_dir / "shadow_run_timeseries.jsonl").is_file()
    combined = result.stdout + (output_dir / "shadow_run.json").read_text(
        encoding="utf-8"
    )
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined


def test_shadow_run_command_blocks_when_live_flag_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    result = runner.invoke(
        app,
        [
            "shadow-run",
            "--json",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    report = json.loads((tmp_path / "shadow_run.json").read_text(encoding="utf-8"))
    assert report["classification"] == "SHADOW_FAILED"


def test_shadow_run_real_data_command_writes_sanitized_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def fake_build(config):
        assert config.max_events == 1
        assert config.auto_btc_5m is True
        return _real_data_shadow_report()

    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xwallet")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-secret")
    monkeypatch.setattr("polysia.cli.build_real_data_shadow_run", fake_build)
    output_dir = tmp_path / "real-shadow"

    result = runner.invoke(
        app,
        [
            "shadow-run-real-data",
            "--auto-btc-5m",
            "--max-events",
            "1",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] == "REAL_DATA_SHADOW_HEALTHY"
    assert (output_dir / "shadow-run-real-data.json").is_file()
    assert (output_dir / "shadow-run-real-data.md").is_file()
    assert (output_dir / "shadow-run-real-data-events.jsonl").is_file()
    combined = (
        result.stdout
        + (output_dir / "shadow-run-real-data.json").read_text(encoding="utf-8")
        + (output_dir / "shadow-run-real-data.md").read_text(encoding="utf-8")
        + (output_dir / "shadow-run-real-data-events.jsonl").read_text(encoding="utf-8")
    )
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined


def test_discover_markets_command_prints_active_markets(monkeypatch) -> None:
    class FakeAdapter:
        async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]:
            assert page_size == 3
            return [
                MarketSummary(
                    id="123",
                    slug="example-market",
                    question="Will this test pass?",
                    category="Testing",
                )
            ]

    monkeypatch.setattr("polysia.cli.PolymarketPublicAdapter", FakeAdapter)

    result = runner.invoke(app, ["discover-markets", "--limit", "3"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["count"] == 1
    assert payload["markets"][0]["slug"] == "example-market"


def test_discover_markets_command_handles_adapter_errors(monkeypatch) -> None:
    class FakeAdapter:
        async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]:
            raise PolymarketPublicAdapterError("Could not list active Polymarket markets.")

    monkeypatch.setattr("polysia.cli.PolymarketPublicAdapter", FakeAdapter)

    result = runner.invoke(app, ["discover-markets", "--limit", "3"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"


def test_stream_market_command_delegates_to_async_runner(monkeypatch) -> None:
    calls = []

    async def fake_stream_market(
        *,
        token_id: str,
        max_events: int | None,
        stale_after_seconds: float,
    ) -> None:
        calls.append(
            {
                "max_events": max_events,
                "stale_after_seconds": stale_after_seconds,
                "token_id": token_id,
            }
        )

    monkeypatch.setattr("polysia.cli._stream_market", fake_stream_market)

    result = runner.invoke(
        app,
        [
            "stream-market",
            "--token-id",
            "token-1",
            "--max-events",
            "2",
            "--stale-after-seconds",
            "4",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "max_events": 2,
            "stale_after_seconds": 4.0,
            "token_id": "token-1",
        }
    ]


def test_live_smoke_test_auto_btc_5m_selects_market(monkeypatch) -> None:
    calls = []

    class FakePublicAdapter:
        async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
            assert "Bitcoin" in query
            assert page_size == 30
            return [
                MarketSummary(
                    id="market-1",
                    slug="btc-updown-5m-1783000000",
                    active=True,
                    closed=False,
                    accepting_orders=True,
                )
            ]

        async def get_market_by_slug(self, slug: str) -> MarketDetails:
            assert slug == "btc-updown-5m-1783000000"
            return MarketDetails(
                id="market-1",
                slug=slug,
                condition_id="condition-1",
                outcomes=(
                    MarketOutcomeSummary(label="Up", token_id="token-up"),
                    MarketOutcomeSummary(label="Down", token_id="token-down"),
                ),
            )

    async def fake_run_live_smoke_test(config):
        calls.append(config)
        return SimpleNamespace(final_result="PASS")

    monkeypatch.setattr("polysia.cli.PolymarketPublicAdapter", FakePublicAdapter)
    monkeypatch.setattr("polysia.cli.run_live_smoke_test", fake_run_live_smoke_test)

    result = runner.invoke(
        app,
        [
            "live-smoke-test",
            "--auto-btc-5m",
            "--outcome",
            "YES",
            "--side",
            "BUY",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert calls[0].market_slug == "btc-updown-5m-1783000000"
    assert calls[0].condition_id == "condition-1"
    assert calls[0].token_id == "token-up"
    assert calls[0].settings.polymarket_live_token_allowlist == ("token-up",)


def test_live_smoke_test_requires_selection_without_auto() -> None:
    result = runner.invoke(app, ["live-smoke-test", "--dry-run"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "--auto-btc-5m" in payload["message"]


@pytest.mark.asyncio
async def test_live_account_status_reports_signer_funder_diagnostics(monkeypatch) -> None:
    FakeAccountStatusAdapter.instances.clear()
    monkeypatch.setattr("polysia.cli.PolymarketSecureAdapter", FakeAccountStatusAdapter)
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        POLYMARKET_PRIVATE_KEY="not-for-output",
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    payload = await _live_account_status(
        settings=settings,
        i_understand_this_uses_live_account=True,
    )

    assert payload["status"] == "ok"
    assert payload["account_identity"] == {
        "active_wallet_source": "funder",
        "configured_signature_type": 3,
        "funder_configured": True,
        "legacy_wallet_configured": False,
        "sdk_signature_type": 3,
        "signature_type_matches_sdk": True,
        "signer_configured": True,
        "wallet_type": "DEPOSIT_WALLET",
    }
    assert payload["balance_readable"] is True
    assert payload["approval_readable"] is True
    assert payload["positive_approval_count"] == 1
    assert payload["open_order_count"] == 0
    assert payload["position_count"] == 1
    assert "not-for-output" not in str(payload)
    assert "0xfunder" not in str(payload)


def test_live_open_orders_blocks_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)

    result = runner.invoke(
        app,
        ["live-open-orders", "--i-understand-this-uses-live-account"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "TRADING_MODE=LIVE" in payload["message"]


def test_live_open_orders_command_delegates_to_async_runner(monkeypatch) -> None:
    calls = []

    async def fake_live_open_orders(**kwargs):
        calls.append(kwargs)
        return {
            "count": 0,
            "dry_run": False,
            "orders": [],
            "request": {"action": "get_open_orders", "token_id": "token-1"},
            "status": "ok",
        }

    monkeypatch.setattr("polysia.cli._live_open_orders", fake_live_open_orders)

    result = runner.invoke(
        app,
        [
            "live-open-orders",
            "--token-id",
            "token-1",
            "--i-understand-this-uses-live-account",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["request"] == {"action": "get_open_orders", "token_id": "token-1"}
    assert calls[0]["token_id"] == "token-1"
    assert calls[0]["i_understand_this_uses_live_account"] is True


def test_live_cancel_order_command_defaults_to_dry_run(monkeypatch) -> None:
    calls = []

    async def fake_live_cancel_order(**kwargs):
        calls.append(kwargs)
        return {
            "dry_run": kwargs["dry_run"],
            "request": {"action": "cancel_order", "order_id": kwargs["order_id"]},
            "response": None,
            "status": "ok",
            "submitted": False,
        }

    monkeypatch.setattr("polysia.cli._live_cancel_order", fake_live_cancel_order)

    result = runner.invoke(
        app,
        [
            "live-cancel-order",
            "--order-id",
            "order-1",
            "--i-understand-this-modifies-live-orders",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["submitted"] is False
    assert calls[0]["order_id"] == "order-1"
    assert calls[0]["dry_run"] is True
    assert calls[0]["i_understand_this_modifies_live_orders"] is True


def test_live_cancel_market_orders_command_delegates_token(monkeypatch) -> None:
    calls = []

    async def fake_live_cancel_market_orders(**kwargs):
        calls.append(kwargs)
        return {
            "dry_run": kwargs["dry_run"],
            "request": {
                "action": "cancel_market_orders",
                "token_id": kwargs["token_id"],
            },
            "response": None,
            "status": "ok",
            "submitted": False,
        }

    monkeypatch.setattr(
        "polysia.cli._live_cancel_market_orders",
        fake_live_cancel_market_orders,
    )

    result = runner.invoke(
        app,
        [
            "live-cancel-market-orders",
            "--token-id",
            "token-1",
            "--i-understand-this-modifies-live-orders",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["request"] == {
        "action": "cancel_market_orders",
        "token_id": "token-1",
    }
    assert calls[0]["token_id"] == "token-1"
    assert calls[0]["dry_run"] is True


def test_live_limit_order_blocks_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "live-limit-order",
            "--token-id",
            "token-1",
            "--price",
            "0.50",
            "--size",
            "1",
            "--i-understand-this-places-real-orders",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "TRADING_MODE=LIVE" in payload["message"]


def test_live_limit_order_command_defaults_to_dry_run(monkeypatch) -> None:
    calls = []

    async def fake_live_limit_order(**kwargs):
        calls.append(kwargs)
        return {
            "dry_run": kwargs["dry_run"],
            "request": {
                "action": "place_limit_order",
                "token_id": kwargs["token_id"],
                "price": str(kwargs["price"]),
                "size": str(kwargs["size"]),
                "post_only": True,
            },
            "response": None,
            "status": "ok",
            "submitted": False,
        }

    monkeypatch.setattr("polysia.cli._live_limit_order", fake_live_limit_order)

    result = runner.invoke(
        app,
        [
            "live-limit-order",
            "--token-id",
            "token-1",
            "--price",
            "0.44",
            "--size",
            "0.5",
            "--i-understand-this-places-real-orders",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["submitted"] is False
    assert calls[0]["dry_run"] is True
    assert calls[0]["price"] == Decimal("0.44")
    assert calls[0]["size"] == Decimal("0.5")


@pytest.mark.asyncio
async def test_live_limit_order_dry_run_does_not_connect(monkeypatch) -> None:
    FakeSecureAdapter.instances.clear()
    monkeypatch.setattr("polysia.cli.PolymarketSecureAdapter", FakeSecureAdapter)
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="1",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="1",
    )

    payload = await _live_limit_order(
        settings=settings,
        token_id="token-1",
        side="BUY",
        price=Decimal("0.50"),
        size=Decimal("1"),
        dry_run=True,
        strategy_id="operator-tiny-live",
        reason="unit test",
        current_position=Decimal("0"),
        current_market_position=Decimal("0"),
        daily_pnl=Decimal("0"),
        open_orders_count=0,
        market_data_age_ms=0,
        i_understand_this_places_real_orders=True,
    )

    adapter = FakeSecureAdapter.instances[-1]
    assert payload["dry_run"] is True
    assert payload["submitted"] is False
    assert payload["request"] == {
        "action": "place_limit_order",
        "token_id": "token-1",
        "side": "BUY",
        "price": "0.50",
        "size": "1",
        "post_only": True,
    }
    assert adapter.connected is False
    assert adapter.closed is True
    assert adapter.limit_order_calls == []


@pytest.mark.asyncio
async def test_live_limit_order_submit_uses_allowlisted_fake_adapter(monkeypatch) -> None:
    FakeSecureAdapter.instances.clear()
    monkeypatch.setattr("polysia.cli.PolymarketSecureAdapter", FakeSecureAdapter)
    monkeypatch.setattr(
        "polysia.execution.live_broker.PreLiveOrderGeoblockCheck",
        lambda: AllowGeoblock(),
    )
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="1",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="1",
    )

    payload = await _live_limit_order(
        settings=settings,
        token_id="token-1",
        side="SELL",
        price=Decimal("0.50"),
        size=Decimal("1"),
        dry_run=False,
        strategy_id="operator-tiny-live",
        reason="unit test",
        current_position=Decimal("1"),
        current_market_position=Decimal("1"),
        daily_pnl=Decimal("0"),
        open_orders_count=0,
        market_data_age_ms=0,
        i_understand_this_places_real_orders=True,
    )

    adapter = FakeSecureAdapter.instances[-1]
    assert payload["submitted"] is True
    assert payload["dry_run"] is False
    assert payload["response"] == {
        "ok": True,
        "order_id": "order-1",
        "status": "live",
        "making_amount": "0.5",
        "taking_amount": "1",
        "trade_count": 0,
        "transaction_count": 1,
    }
    assert "0xhash" not in str(payload)
    assert adapter.connected is True
    assert adapter.closed is True
    assert adapter.limit_order_calls == [
        {
            "token_id": "token-1",
            "side": "SELL",
            "price": Decimal("0.50"),
            "size": Decimal("1"),
            "post_only": True,
            "expiration": None,
            "builder_code": None,
        }
    ]


class AllowGeoblock:
    async def assert_allowed(self) -> GeoblockStatus:
        return GeoblockStatus(
            blocked=False,
            checked_at=datetime(2026, 7, 1, tzinfo=UTC),
            status="allowed",
        )


@pytest.mark.asyncio
async def test_live_limit_order_rejects_size_above_tiny_cap(monkeypatch) -> None:
    FakeSecureAdapter.instances.clear()
    monkeypatch.setattr("polysia.cli.PolymarketSecureAdapter", FakeSecureAdapter)
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="1",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="2",
    )

    with pytest.raises(LiveBrokerError, match="risk engine blocked"):
        await _live_limit_order(
            settings=settings,
            token_id="token-1",
            side="BUY",
            price=Decimal("0.50"),
            size=Decimal("2"),
            dry_run=True,
            strategy_id="operator-tiny-live",
            reason="unit test",
            current_position=Decimal("0"),
            current_market_position=Decimal("0"),
            daily_pnl=Decimal("0"),
            open_orders_count=0,
            market_data_age_ms=0,
            i_understand_this_places_real_orders=True,
        )

    adapter = FakeSecureAdapter.instances[-1]
    assert adapter.connected is False
    assert adapter.closed is True
    assert adapter.limit_order_calls == []


def test_safe_order_response_summarizes_transaction_hashes() -> None:
    payload = _safe_order_response(
        {
            "ok": True,
            "order_id": "order-1",
            "status": "live",
            "transactions_hashes": ("0xhash", "0xhash2"),
            "trade_ids": ("trade-1",),
        }
    )

    assert payload == {
        "ok": True,
        "order_id": "order-1",
        "status": "live",
        "trade_count": 1,
        "transaction_count": 2,
    }
    assert "0xhash" not in str(payload)


def test_live_open_order_serializer_excludes_wallet_addresses() -> None:
    order = SimpleNamespace(
        created_at=None,
        expires_at=None,
        id="order-1",
        maker_address="0xmaker",
        market="market-1",
        order_type="GTC",
        original_size=Decimal("10"),
        outcome="Yes",
        owner="0xowner",
        price=Decimal("0.55"),
        side="BUY",
        size_matched=Decimal("0"),
        status="live",
        token_id="token-1",
    )

    payload = _safe_open_order_to_dict(order)

    assert payload["id"] == "order-1"
    assert payload["price"] == "0.55"
    assert "owner" not in payload
    assert "maker_address" not in payload
    assert "0xowner" not in str(payload)
    assert "0xmaker" not in str(payload)


def test_paper_trade_command_runs_local_simulation() -> None:
    result = runner.invoke(
        app,
        [
            "paper-trade",
            "--token-id",
            "token-1",
            "--best-bid",
            "0.49",
            "--bid-size",
            "100",
            "--best-ask",
            "0.52",
            "--ask-size",
            "10",
            "--order-size",
            "1",
            "--initial-cash",
            "100",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["orders"][0]["order"]["status"] == "FILLED"
    assert payload["orders"][0]["order"]["side"] == "BUY"
    assert payload["positions"]["token-1"]["size"] == "1"


def test_paper_trade_command_supports_passive_market_maker() -> None:
    result = runner.invoke(
        app,
        [
            "paper-trade",
            "--strategy",
            "passive-market-maker",
            "--token-id",
            "token-1",
            "--best-bid",
            "0.40",
            "--bid-size",
            "100",
            "--best-ask",
            "0.50",
            "--ask-size",
            "10",
            "--order-size",
            "1",
            "--min-edge",
            "0.05",
            "--initial-cash",
            "100",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["orders"][0]["order"]["status"] == "ACCEPTED"
    assert payload["orders"][0]["order"]["side"] == "BUY"
    assert payload["positions"] == {}


def test_backtest_jsonl_command_replays_local_file(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event_type": "book",
                "payload": {
                    "asks": [{"price": "0.50", "size": "1"}],
                    "bids": [{"price": "0.40", "size": "10"}],
                },
                "raw_payload": {},
                "received_at": "2026-01-01T00:00:00+00:00",
                "source": "polymarket",
                "token_id": "token-1",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "backtest-jsonl",
            "--input",
            str(events_path),
            "--initial-cash",
            "100",
            "--order-size",
            "1",
            "--min-edge",
            "0.01",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["events_processed"] == 1
    assert payload["fills_created"] == 1
    assert payload["positions"]["token-1"]["size"] == "1"


def test_backtest_jsonl_command_supports_passive_market_maker(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event_type": "book",
                "payload": {
                    "asks": [{"price": "0.50", "size": "1"}],
                    "bids": [{"price": "0.40", "size": "10"}],
                },
                "raw_payload": {},
                "received_at": "2026-01-01T00:00:00+00:00",
                "source": "polymarket",
                "token_id": "token-1",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "backtest-jsonl",
            "--input",
            str(events_path),
            "--strategy",
            "passive-market-maker",
            "--initial-cash",
            "100",
            "--order-size",
            "1",
            "--min-edge",
            "0.05",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["intents_generated"] == 1
    assert payload["orders"][0]["order"]["status"] == "ACCEPTED"
    assert payload["fills_created"] == 0


def test_backtest_jsonl_command_handles_bad_input(tmp_path: Path) -> None:
    events_path = tmp_path / "bad.jsonl"
    events_path.write_text("{bad", encoding="utf-8")

    result = runner.invoke(app, ["backtest-jsonl", "--input", str(events_path)])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "invalid JSON" in payload["message"]
