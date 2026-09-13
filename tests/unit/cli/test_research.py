from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.cli import app
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)
from polysia.monitoring.real_data_shadow_run import RealDataShadowMetrics, RealDataShadowRunReport
from polysia.storage.research_evidence import ResearchEvidenceStore

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


def test_source_benchmark_command_writes_sanitized_report(monkeypatch, tmp_path: Path) -> None:
    async def fake_benchmark(**kwargs):
        del kwargs
        return {
            "run_id": "run-1",
            "wallet": "0x1111111111111111111111111111111111111111",
            "selection": {"qualified": False, "reason": "fixture"},
        }

    monkeypatch.setattr(
        "polysia.cli_commands.research_evidence_cli.build_public_benchmark",
        fake_benchmark,
    )
    output = tmp_path / "bench.json"
    result = runner.invoke(
        app,
        [
            "research",
            "source-benchmark",
            "--duration-seconds",
            "1",
            "--database",
            str(tmp_path / "research.sqlite3"),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "0x1111111111111111111111111111111111111111" not in result.stdout
    assert payload["wallet"] == "0xREDACTED"
    assert "0x1111111111111111111111111111111111111111" not in output.read_text(encoding="utf-8")


def test_prospective_replay_requires_recorded_run(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "research",
            "prospective-replay",
            "--database",
            str(tmp_path / "missing.sqlite3"),
            "--run-id",
            "missing",
        ],
    )
    assert result.exit_code == 1
    assert not (tmp_path / "missing.sqlite3").exists()
    result = runner.invoke(
        app,
        ["research", "shadow-replay", "--backup-dir", str(tmp_path / "missing")],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"


def test_prospective_replay_emits_versioned_economic_evidence(tmp_path: Path) -> None:
    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    store.start_or_resume_experiment(
        requested_run_id="economic-run",
        duration=timedelta(hours=1),
        max_events=100,
        max_bytes=10_000_000,
        code_sha="a" * 40,
        configuration_digest="configuration",
    )
    collector = ProspectiveCollector(store, run_id="economic-run")
    observed = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    quote = CanonicalResearchEvent(
        evidence_id="quote",
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="market",
        event_kind=ObservationKind.MARKET_STATE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference="market-a",
        outcome_reference="token-a",
        side="BUY",
        price=Decimal("0.51"),
        size=Decimal("20"),
        source_time=observed - timedelta(seconds=1),
        observed_time=observed - timedelta(seconds=1),
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.NOT_APPLICABLE,
        leader_alias=None,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": "quote"}),
        provenance={
            "book_levels": [{"price": "0.51", "size": "20"}],
            "execution_evidence": True,
            "execution_evidence_version": "order-book-depth-v1",
            "fee_exponent": "0",
            "fee_rate": "0",
            "fee_taker_only": True,
            "fees_enabled": False,
        },
        run_id="economic-run",
    )
    wallet = CanonicalResearchEvent(
        evidence_id="wallet",
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="wallet",
        event_kind=ObservationKind.WALLET_TRADE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference="market-a",
        outcome_reference="token-a",
        side="BUY",
        price=Decimal("0.50"),
        size=Decimal("10"),
        source_time=observed - timedelta(seconds=2),
        observed_time=observed,
        receive_monotonic_ns=3,
        normalize_monotonic_ns=4,
        attribution_status=AttributionStatus.WALLET_ALIASED,
        leader_alias="pub-wallet",
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": "wallet"}),
        provenance={},
        source_event_id="source-wallet",
        run_id="economic-run",
    )
    collector.ingest(quote)
    collector.ingest(wallet)
    collector.close_window(complete=True)
    output = tmp_path / "analysis.json"

    result = runner.invoke(
        app,
        [
            "research",
            "prospective-replay",
            "--database",
            str(database),
            "--run-id",
            "economic-run",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    stdout = json.loads(result.stdout)
    assert payload["experiment_contract"]["version"] == "prospective-economic-v2"
    assert payload["summary"]["economic"] == "INSUFFICIENT_DATA"
    assert payload["decision_evidence"][0]["snapshot_evidence_id"] == "quote"
    assert len(payload["source_database_sha256"]) == 64
    assert "decision_evidence" not in stdout
    assert "control_decisions" not in stdout
    assert stdout["engine_version"]
    assert stdout["result_hash"]
    assert len(result.stdout.encode()) < 5120


def test_prospective_replay_does_not_mutate_source_or_companions(tmp_path: Path) -> None:
    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    store.start_or_resume_experiment(
        requested_run_id="readonly-run",
        duration=timedelta(hours=1),
        max_events=100,
        max_bytes=10_000_000,
        code_sha="a" * 40,
        configuration_digest="configuration",
    )
    collector = ProspectiveCollector(store, run_id="readonly-run")
    collector.close_window(complete=True)
    from polysia.backtesting.prospective_analysis import (
        capture_protected_artifacts,
        sqlite_companion_paths,
    )

    before = capture_protected_artifacts(database=database)
    names_before = {path.name for path in sqlite_companion_paths(database) if path.exists()}
    result = runner.invoke(
        app,
        [
            "research",
            "prospective-replay",
            "--database",
            str(database),
            "--run-id",
            "readonly-run",
        ],
    )
    assert result.exit_code == 0, result.output
    after = capture_protected_artifacts(database=database)
    names_after = {path.name for path in sqlite_companion_paths(database) if path.exists()}
    assert after.digests == before.digests
    assert names_after == names_before


def test_prospective_replay_compare_reports_identity_and_deltas(tmp_path: Path) -> None:
    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    store.start_or_resume_experiment(
        requested_run_id="compare-run",
        duration=timedelta(hours=1),
        max_events=100,
        max_bytes=10_000_000,
        code_sha="a" * 40,
        configuration_digest="configuration",
    )
    collector = ProspectiveCollector(store, run_id="compare-run")
    collector.close_window(complete=True)
    output = tmp_path / "baseline.json"
    first = runner.invoke(
        app,
        [
            "research",
            "prospective-replay",
            "--database",
            str(database),
            "--run-id",
            "compare-run",
            "--output",
            str(output),
        ],
    )
    assert first.exit_code == 0, first.output
    compared = runner.invoke(
        app,
        [
            "research",
            "prospective-replay",
            "--database",
            str(database),
            "--run-id",
            "compare-run",
            "--compare",
            str(output),
        ],
    )
    assert compared.exit_code == 0, compared.output
    payload = json.loads(compared.stdout)
    assert payload["comparison"]["classification"] == "identical"
    assert payload["comparison"]["first_material_difference"] is None


def test_prospective_health_reads_sanitized_file(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    health.write_text(
        json.dumps(
            {
                "fatal": None,
                "stale": False,
                "wallet": "0x1111111111111111111111111111111111111111",
                "lifecycle": "OPEN",
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["research", "prospective-health", "--health-report", str(health)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["lifecycle"] == "OPEN"
    assert "0x1111111111111111111111111111111111111111" not in result.stdout
    assert payload["wallet"] == "0xREDACTED"


def test_prospective_health_rejects_stale_file(tmp_path: Path) -> None:
    import os
    import time

    health = tmp_path / "health.json"
    health.write_text(
        json.dumps({"fatal": None, "stale": False, "lifecycle": "OPEN"}),
        encoding="utf-8",
    )
    fresh = runner.invoke(
        app,
        [
            "research",
            "prospective-health",
            "--health-report",
            str(health),
            "--require-fresh-seconds",
            "30",
        ],
    )
    assert fresh.exit_code == 0, fresh.output
    os.utime(health, (time.time() - 10, time.time() - 10))
    stale = runner.invoke(
        app,
        [
            "research",
            "prospective-health",
            "--health-report",
            str(health),
            "--require-fresh-seconds",
            "1",
        ],
    )
    assert stale.exit_code == 1


def test_prospective_health_can_require_research_eligibility(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    health.write_text(
        json.dumps(
            {
                "fatal": None,
                "stale": False,
                "lifecycle": "OPEN",
                "research_data_eligible": False,
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "research",
            "prospective-health",
            "--health-report",
            str(health),
            "--require-research-eligible",
        ],
    )

    assert result.exit_code == 1
