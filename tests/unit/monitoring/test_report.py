from __future__ import annotations

import json

import pytest

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.metrics import build_operator_status
from polysia.monitoring.report import (
    render_operator_report,
    render_operator_report_html,
    render_operator_report_json,
    render_operator_report_markdown,
)


def live_status():
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )
    return build_operator_status(settings=settings)


def test_json_report_is_sanitized_and_parseable() -> None:
    report = render_operator_report_json(live_status())
    payload = json.loads(report)

    assert payload["status"] == "ok"
    assert payload["runtime"]["private_key_configured"] is True
    assert "not-for-output" not in report
    assert "0xwallet" not in report
    assert "token-secret" not in report


def test_markdown_report_includes_operator_sections() -> None:
    report = render_operator_report_markdown(live_status())

    assert "# PolySia — Polymarket Adapter — Operator Report" in report
    assert "## Warnings" in report
    assert "## Runtime" in report
    assert "not-for-output" not in report
    assert "0xwallet" not in report
    assert "token-secret" not in report


def test_html_report_is_sanitized_dashboard_markup() -> None:
    report = render_operator_report_html(live_status())

    assert report.startswith("<!doctype html>")
    assert "PolySia — Polymarket Adapter — Operator Report" in report
    assert "Tiny Live Orders Ready" in report
    assert "not-for-output" not in report
    assert "0xwallet" not in report
    assert "token-secret" not in report


def test_render_operator_report_dispatches_formats() -> None:
    status = live_status()

    assert render_operator_report(status, "json").startswith("{")
    assert render_operator_report(status, "markdown").startswith("# PolySia")
    assert render_operator_report(status, "html").startswith("<!doctype html>")


def test_render_operator_report_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="html, json, or markdown"):
        render_operator_report(live_status(), "pdf")
