from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from polysia.cli import app
from polysia.monitoring.real_data_shadow_run import RealDataShadowMetrics, RealDataShadowRunReport

runner = CliRunner()


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


def test_strategy_evaluation_command_writes_sanitized_reports(monkeypatch, tmp_path: Path) -> None:
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
            "research",
            "evaluate",
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
    combined = result.stdout + "".join(path.read_text(encoding="utf-8") for path in reports)
    assert "not-for-output" not in combined


def test_strategy_evaluation_command_rejects_malformed_input(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.json"
    input_path.write_text("{bad", encoding="utf-8")

    result = runner.invoke(app, ["research", "evaluate", "--input", str(input_path)])

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
            "research",
            "evaluate-extended",
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
            "research",
            "fill-audit",
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
    combined = result.stdout + "".join(path.read_text(encoding="utf-8") for path in reports)
    assert "not-for-output" not in combined
    assert "No live trading" in combined


def test_fill_simulation_audit_command_rejects_bad_model() -> None:
    result = runner.invoke(app, ["research", "fill-audit", "--model", "optimistic"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "model must be one of" in payload["message"]


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
            "research",
            "shadow",
            "--max-events",
            "3",
            "--control-database-path",
            str(tmp_path / "control.sqlite3"),
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
    combined = result.stdout + (output_dir / "shadow_run.json").read_text(encoding="utf-8")
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined


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
    monkeypatch.setattr("polysia.cli_commands.research.build_real_data_shadow_run", fake_build)
    output_dir = tmp_path / "real-shadow"

    result = runner.invoke(
        app,
        [
            "research",
            "shadow-public",
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
