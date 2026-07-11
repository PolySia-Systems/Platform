from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from polysia.monitoring import extended_strategy_evaluation as module
from polysia.monitoring.extended_strategy_evaluation import (
    ExtendedStrategyEvaluationConfig,
    ExtendedStrategyEvaluationError,
    build_extended_strategy_evaluation,
    write_extended_strategy_evaluation_reports,
)


def test_extended_strategy_evaluation_scores_core_metrics(tmp_path: Path) -> None:
    input_path = tmp_path / "shadow-run-real-data.json"
    input_path.write_text(
        json.dumps(
            {
                "events_processed": 4,
                "fills_created": 2,
                "intents_generated": 3,
                "metrics": {
                    "max_position_limit": "3",
                    "paper_position": "1.5",
                    "paper_realized_pnl": "0.30",
                    "paper_total_pnl": "0.25",
                    "paper_unrealized_pnl": "-0.05",
                    "risk_approval_count": 2,
                    "risk_denial_count": 1,
                },
                "orders": [
                    {
                        "intent": {
                            "confidence": "0.70",
                            "modeled_edge": "0.04",
                            "outcome": "1",
                            "p_model": "0.70",
                            "price": "0.50",
                            "side": "BUY",
                        },
                        "order": {
                            "avg_fill_price": "0.51",
                            "paper_pnl": "0.20",
                            "status": "FILLED",
                        },
                        "risk_decision": {"approved": True},
                    },
                    {
                        "intent": {
                            "confidence": "0.40",
                            "modeled_edge": "-0.02",
                            "outcome": "0",
                            "p_model": "0.20",
                            "price": "0.60",
                            "side": "SELL",
                        },
                        "order": {
                            "avg_fill_price": "0.59",
                            "paper_pnl": "-0.05",
                            "status": "FILLED",
                        },
                        "risk_decision": {"approved": True},
                    },
                    {
                        "intent": {
                            "confidence": "0.50",
                            "modeled_edge": "0.01",
                            "outcome": "1",
                            "p_model": "0.55",
                            "price": "0.55",
                            "side": "BUY",
                        },
                        "order": {"status": "REJECTED"},
                        "risk_decision": {
                            "approved": False,
                            "reason": "max notional cap",
                        },
                    },
                ],
                "orders_created": 3,
                "samples": [
                    {"paper_total_pnl": "0.00"},
                    {"paper_total_pnl": "0.40"},
                    {"paper_total_pnl": "-0.10"},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_extended_strategy_evaluation(
        ExtendedStrategyEvaluationConfig(input_path=input_path),
        clock=lambda: datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert report.final_result == "EXTENDED_EVALUATION_READY"
    assert report.signal_metrics.intent_count == 3
    assert report.signal_metrics.buy_count == 2
    assert report.signal_metrics.sell_count == 1
    assert report.risk_metrics.approvals == 2
    assert report.risk_metrics.denials == 1
    assert report.risk_metrics.denial_reasons == {"max_notional": 1}
    assert report.execution_metrics.paper_order_count == 3
    assert report.execution_metrics.paper_fill_count == 2
    assert report.execution_metrics.missed_fill_count == 1
    assert str(report.execution_metrics.fill_ratio) == "0.6667"
    assert str(report.pnl_metrics.max_drawdown) == "-0.50"
    assert report.pnl_metrics.win_count == 1
    assert report.pnl_metrics.loss_count == 1
    assert str(report.calibration_metrics.brier_score) == "0.1108"


def test_extended_strategy_evaluation_warns_without_outcomes(tmp_path: Path) -> None:
    input_path = tmp_path / "shadow.json"
    input_path.write_text(
        json.dumps(
            {
                "events_processed": 1,
                "intents_generated": 1,
                "orders": [{"intent": {"p_model": "0.55", "side": "BUY"}}],
                "orders_created": 0,
            }
        ),
        encoding="utf-8",
    )

    report = build_extended_strategy_evaluation(
        ExtendedStrategyEvaluationConfig(input_path=input_path)
    )

    assert report.final_result == "EXTENDED_EVALUATION_WARNING"
    assert report.calibration_metrics.brier_score is None
    assert any("outcomes are not available" in warning for warning in report.warnings)


def test_extended_strategy_evaluation_handles_empty_trades(tmp_path: Path) -> None:
    input_path = tmp_path / "empty.json"
    input_path.write_text(json.dumps({"metrics": {"event_count": 1}}), encoding="utf-8")

    report = build_extended_strategy_evaluation(
        ExtendedStrategyEvaluationConfig(input_path=input_path)
    )

    assert report.final_result == "EXTENDED_EVALUATION_NO_DATA"
    assert report.execution_metrics.paper_order_count == 0
    assert report.pnl_metrics.total_pnl == 0


def test_extended_strategy_evaluation_calculates_brier_from_jsonl(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "records.jsonl"
    input_path.write_text(
        "\n".join(
            (
                json.dumps({"p_model": "0.70", "outcome": 1, "side": "BUY"}),
                json.dumps({"p_model": "0.20", "outcome": 0, "side": "SELL"}),
            )
        ),
        encoding="utf-8",
    )

    report = build_extended_strategy_evaluation(
        ExtendedStrategyEvaluationConfig(input_path=input_path)
    )

    assert report.signal_metrics.intent_count == 2
    assert str(report.calibration_metrics.brier_score) == "0.0650"
    bucket_counts = [
        bucket["count"] for bucket in report.calibration_metrics.probability_buckets
    ]
    assert bucket_counts[2] == 1
    assert bucket_counts[7] == 1


def test_extended_strategy_evaluation_reports_are_sanitized(tmp_path: Path) -> None:
    input_path = tmp_path / "shadow.json"
    output_dir = tmp_path / "reports"
    input_path.write_text(
        json.dumps(
            {
                "events_processed": 1,
                "intents_generated": 1,
                "orders": [
                    {
                        "intent": {"outcome": 1, "p_model": "0.9", "side": "BUY"},
                        "order": {"status": "FILLED"},
                    }
                ],
                "orders_created": 1,
                "secret_token": "token-not-for-output",
                "tx_hash": "0x" + "a" * 64,
                "wallet": "0x1111111111111111111111111111111111111111",
            }
        ),
        encoding="utf-8",
    )

    report = build_extended_strategy_evaluation(
        ExtendedStrategyEvaluationConfig(input_path=input_path)
    )
    artifacts = write_extended_strategy_evaluation_reports(report, output_dir)
    combined = "".join(Path(path).read_text(encoding="utf-8") for path in artifacts.values())

    assert "token-not-for-output" not in combined
    assert "0x1111111111111111111111111111111111111111" not in combined
    assert "0x" + "a" * 64 not in combined


def test_extended_strategy_evaluation_rejects_bad_input(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.json"
    input_path.write_text("{bad", encoding="utf-8")

    with pytest.raises(ExtendedStrategyEvaluationError):
        build_extended_strategy_evaluation(
            ExtendedStrategyEvaluationConfig(input_path=input_path)
        )


def test_extended_strategy_evaluation_never_references_live_broker() -> None:
    source = inspect.getsource(module)

    assert "LiveBroker" not in source
    assert "place_market_order" not in source
