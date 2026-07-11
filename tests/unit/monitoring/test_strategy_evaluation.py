from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.monitoring.strategy_evaluation import (
    StrategyEvaluationConfig,
    StrategyEvaluationError,
    build_strategy_evaluation,
    load_strategy_records,
    render_strategy_evaluation_html,
    render_strategy_evaluation_json,
    render_strategy_evaluation_markdown,
)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, tzinfo=UTC)


def test_strategy_evaluation_scores_shadow_run_metrics(tmp_path: Path) -> None:
    input_path = tmp_path / "shadow_run.json"
    input_path.write_text(json.dumps(_shadow_run_payload()), encoding="utf-8")

    report = build_strategy_evaluation(
        StrategyEvaluationConfig(
            input_path=input_path,
            min_sample_size=30,
            strategy="stale-price",
        ),
        clock=fixed_clock,
    )

    assert report.classification == "STRATEGY_READY_FOR_TINY_LIVE_REVIEW"
    assert report.signal_quality.total_signals == 40
    assert report.signal_quality.approval_rate == Decimal("0.8750")
    assert report.execution_quality.paper_fill_count == 30
    assert report.pnl_quality.total_paper_pnl == Decimal("1.25")
    assert "No live trading" in render_strategy_evaluation_markdown(report)


def test_strategy_evaluation_marks_small_sample_research_only(tmp_path: Path) -> None:
    payload = _shadow_run_payload()
    payload["metrics"]["strategy_intent_count"] = 2
    payload["metrics"]["risk_approval_count"] = 2
    payload["metrics"]["paper_order_count"] = 2
    payload["metrics"]["paper_fill_count"] = 2
    input_path = tmp_path / "small.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_strategy_evaluation(
        StrategyEvaluationConfig(input_path=input_path, min_sample_size=30),
        clock=fixed_clock,
    )

    assert report.classification == "STRATEGY_RESEARCH_ONLY"
    assert "sample size 2 is below minimum 30" in report.warnings


def test_strategy_evaluation_calibration_buckets_from_jsonl(tmp_path: Path) -> None:
    input_path = tmp_path / "calibration.jsonl"
    input_path.write_text(
        "\n".join(
            (
                json.dumps({"p_model": "0.7", "outcome": 1}),
                json.dumps({"p_model": "0.2", "outcome": 0}),
            )
        ),
        encoding="utf-8",
    )

    report = build_strategy_evaluation(
        StrategyEvaluationConfig(input_path=input_path, min_sample_size=10),
        clock=fixed_clock,
    )

    assert report.calibration.brier_score == Decimal("0.0650")
    assert len(report.calibration.buckets) == 10
    assert report.calibration.small_sample_warning is True


def test_strategy_evaluation_report_generation_is_sanitized(tmp_path: Path) -> None:
    payload = _shadow_run_payload()
    payload["secret"] = "not-for-output"
    input_path = tmp_path / "shadow_run.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_strategy_evaluation(
        StrategyEvaluationConfig(input_path=input_path, min_sample_size=30),
        clock=fixed_clock,
    )

    combined = (
        render_strategy_evaluation_json(report)
        + render_strategy_evaluation_markdown(report)
        + render_strategy_evaluation_html(report)
    )
    assert "not-for-output" not in combined
    assert "brier_score = mean((p_model - outcome)^2)" in combined


def test_strategy_evaluation_rejects_malformed_json(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.json"
    input_path.write_text("{bad", encoding="utf-8")

    with pytest.raises(StrategyEvaluationError):
        load_strategy_records(input_path)


def _shadow_run_payload() -> dict[str, object]:
    return {
        "metrics": {
            "strategy_intent_count": 40,
            "risk_approval_count": 35,
            "risk_rejection_count": 5,
            "paper_order_count": 35,
            "paper_fill_count": 30,
            "paper_total_pnl": "1.25",
            "paper_realized_pnl": "0.50",
            "paper_unrealized_pnl": "0.75",
            "max_drawdown": "-0.20",
        },
        "samples": [
            {
                "paper_fills": 1,
                "paper_total_pnl": "0.10",
                "risk_approved": 1,
                "risk_rejected": 0,
                "strategy_intents": 1,
            }
        ],
    }
