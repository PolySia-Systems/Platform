from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.acceptance_audit import (
    AcceptanceAuditCheck,
    AcceptanceAuditConfig,
    ShadowProductionMetrics,
    build_acceptance_audit,
    render_acceptance_audit_html,
    render_acceptance_audit_json,
    render_acceptance_audit_markdown,
    score_acceptance_audit,
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
async def test_acceptance_audit_runs_mocked_shadow_without_live() -> None:
    report = await build_acceptance_audit(
        AcceptanceAuditConfig(
            settings=safe_settings(),
            project_root=Path("."),
            duration_minutes=1,
        ),
        clock=fixed_clock,
    )

    assert report.final_result == "READY_FOR_TINY_LIVE"
    assert report.metrics.total_events_received == 3
    assert report.metrics.orderbook_update_count == 3
    assert report.metrics.strategy_intent_count > 0
    assert report.metrics.risk_approved_count > 0
    assert report.metrics.paper_fill_count > 0
    assert _check_by_name(report.shadow_checks, "no-live-broker").status == "pass"


@pytest.mark.asyncio
async def test_acceptance_audit_blocks_live_mode_without_readonly_ack() -> None:
    report = await build_acceptance_audit(
        AcceptanceAuditConfig(
            settings=AppSettings(
                _env_file=None,
                TRADING_MODE=TradingMode.LIVE,
                LIVE_TRADING_ENABLED=False,
            ),
            project_root=Path("."),
        ),
        clock=fixed_clock,
    )

    assert report.final_result == "NOT_READY"
    assert _check_by_name(report.safety_checks, "trading-mode").status == "fail"


@pytest.mark.asyncio
async def test_acceptance_audit_blocks_when_live_flag_enabled() -> None:
    report = await build_acceptance_audit(
        AcceptanceAuditConfig(
            settings=AppSettings(
                _env_file=None,
                TRADING_MODE=TradingMode.DATA_ONLY,
                LIVE_TRADING_ENABLED=True,
            ),
            project_root=Path("."),
        ),
        clock=fixed_clock,
    )

    assert report.final_result == "NOT_READY"
    assert _check_by_name(report.safety_checks, "live-flag").status == "fail"


def test_acceptance_audit_scoring_reports_failures_first() -> None:
    metrics = _metrics(strategy_intent_count=1, paper_fill_count=1)

    result, reasons = score_acceptance_audit(
        safety_checks=(
            AcceptanceAuditCheck(
                name="live-flag",
                status="fail",
                message="LIVE_TRADING_ENABLED=true is forbidden.",
            ),
        ),
        system_checks=(),
        shadow_checks=(),
        metrics=metrics,
    )

    assert result == "NOT_READY"
    assert "live-flag" in reasons[0]


def test_acceptance_audit_scoring_ready_for_shadow_without_intents() -> None:
    result, reasons = score_acceptance_audit(
        safety_checks=(),
        system_checks=(),
        shadow_checks=(),
        metrics=_metrics(strategy_intent_count=0, paper_fill_count=0),
    )

    assert result == "READY_FOR_SHADOW"
    assert "no paper intents" in reasons[0]


@pytest.mark.asyncio
async def test_acceptance_audit_reports_are_sanitized() -> None:
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_PRIVATE_KEY="not-for-output",
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
    )
    report = await build_acceptance_audit(
        AcceptanceAuditConfig(settings=settings, project_root=Path(".")),
        clock=fixed_clock,
    )

    json_report = render_acceptance_audit_json(report)
    markdown_report = render_acceptance_audit_markdown(report)
    html_report = render_acceptance_audit_html(report)

    assert json.loads(json_report)["final_result"] == report.final_result
    assert markdown_report.startswith("# PolySia — Polymarket Adapter — Acceptance Audit")
    assert html_report.startswith("<!doctype html>")
    combined = json_report + markdown_report + html_report
    assert "not-for-output" not in combined
    assert "0xfunder" not in combined
    assert "0xwallet" not in combined
    assert "token-secret" not in combined


def _metrics(
    *,
    strategy_intent_count: int,
    paper_fill_count: int,
) -> ShadowProductionMetrics:
    return ShadowProductionMetrics(
        total_runtime_seconds=Decimal("60"),
        total_events_received=3,
        event_rate_per_second=Decimal("0.05"),
        stream_reconnect_count=0,
        stale_event_count=0,
        orderbook_update_count=3,
        strategy_intent_count=strategy_intent_count,
        risk_approved_count=strategy_intent_count,
        risk_rejected_count=0,
        paper_order_count=paper_fill_count,
        paper_fill_count=paper_fill_count,
        paper_pnl=Decimal("0"),
        max_paper_drawdown=Decimal("0"),
        average_decision_latency_ms=Decimal("1"),
        p95_decision_latency_ms=Decimal("1"),
        p99_decision_latency_ms=Decimal("1"),
    )


def _check_by_name(
    checks: tuple[AcceptanceAuditCheck, ...],
    name: str,
) -> AcceptanceAuditCheck:
    for check in checks:
        if check.name == name:
            return check
    raise AssertionError(f"missing check {name}")
