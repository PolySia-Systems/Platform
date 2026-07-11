from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.shadow_run import (
    ShadowRunConfig,
    ShadowRunMetrics,
    build_shadow_run,
    classify_shadow_run,
    render_shadow_run_html,
    render_shadow_run_json,
    render_shadow_run_markdown,
    render_shadow_run_timeseries_jsonl,
)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, tzinfo=UTC)


def safe_settings() -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
    )


@pytest.mark.asyncio
async def test_shadow_run_mocked_stream_is_healthy_and_paper_only() -> None:
    report = await build_shadow_run(
        ShadowRunConfig(
            settings=safe_settings(),
            project_root=Path("."),
            max_events=4,
        ),
        clock=fixed_clock,
    )

    assert report.classification == "SHADOW_HEALTHY"
    assert report.metrics.stream_health == "mocked_public_stream"
    assert report.metrics.event_count == 4
    assert report.metrics.orderbook_updates == 4
    assert report.metrics.strategy_intent_count > 0
    assert report.metrics.risk_approval_count > 0
    assert report.metrics.paper_fill_count > 0
    assert report.metrics.live_broker_used is False
    assert len(report.samples) == 4


@pytest.mark.asyncio
async def test_shadow_run_blocks_live_flag() -> None:
    report = await build_shadow_run(
        ShadowRunConfig(
            settings=AppSettings(
                _env_file=None,
                TRADING_MODE=TradingMode.DATA_ONLY,
                LIVE_TRADING_ENABLED=True,
            ),
            project_root=Path("."),
        ),
        clock=fixed_clock,
    )

    assert report.classification == "SHADOW_FAILED"
    assert "LIVE_TRADING_ENABLED=true" in report.reasons[0]
    assert report.metrics.live_broker_used is False


def test_shadow_run_classification_degraded_without_intents() -> None:
    classification, reasons = classify_shadow_run(
        _metrics(strategy_intent_count=0, risk_approval_count=0, paper_fill_count=0)
    )

    assert classification == "SHADOW_DEGRADED"
    assert "no paper intents" in reasons[0]


def test_shadow_run_classification_failed_if_live_broker_used() -> None:
    classification, reasons = classify_shadow_run(
        _metrics(
            strategy_intent_count=1,
            risk_approval_count=1,
            paper_fill_count=1,
            live_broker_used=True,
        )
    )

    assert classification == "SHADOW_FAILED"
    assert "live broker" in reasons[0]


@pytest.mark.asyncio
async def test_shadow_run_reports_and_timeseries_are_sanitized() -> None:
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_PRIVATE_KEY="not-for-output",
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
    )
    report = await build_shadow_run(
        ShadowRunConfig(settings=settings, project_root=Path("."), max_events=2),
        clock=fixed_clock,
    )

    json_report = render_shadow_run_json(report)
    markdown_report = render_shadow_run_markdown(report)
    html_report = render_shadow_run_html(report)
    timeseries = render_shadow_run_timeseries_jsonl(report)

    assert json.loads(json_report)["classification"] == "SHADOW_HEALTHY"
    assert markdown_report.startswith("# PolySia — Polymarket Adapter — Shadow Run")
    assert html_report.startswith("<!doctype html>")
    assert len(timeseries.splitlines()) == 2
    combined = json_report + markdown_report + html_report + timeseries
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined


def _metrics(
    *,
    strategy_intent_count: int,
    risk_approval_count: int,
    paper_fill_count: int,
    live_broker_used: bool = False,
) -> ShadowRunMetrics:
    start = fixed_clock()
    return ShadowRunMetrics(
        start_time=start,
        end_time=start,
        duration_seconds=Decimal("60"),
        selected_market="shadow-market",
        selected_token="shadow-token",
        event_count=3,
        event_rate_per_second=Decimal("0.05"),
        stream_health="mocked_public_stream",
        reconnect_count=0,
        stale_event_count=0,
        orderbook_updates=3,
        best_bid_observations=3,
        best_ask_observations=3,
        spread_observations=3,
        mid_observations=3,
        microprice_observations=3,
        strategy_intent_count=strategy_intent_count,
        risk_approval_count=risk_approval_count,
        risk_rejection_count=0,
        paper_order_count=paper_fill_count,
        paper_fill_count=paper_fill_count,
        paper_position=Decimal("1"),
        paper_realized_pnl=Decimal("0"),
        paper_unrealized_pnl=Decimal("0"),
        paper_total_pnl=Decimal("0"),
        max_drawdown=Decimal("0"),
        latency_average_ms=Decimal("1"),
        latency_p95_ms=Decimal("1"),
        latency_p99_ms=Decimal("1"),
        live_broker_used=live_broker_used,
    )
