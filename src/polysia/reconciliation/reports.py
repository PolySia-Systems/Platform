from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from polysia.config.settings import AppSettings
from polysia.reconciliation.models import (
    ReconciliationEvent,
    ReconciliationEventType,
    ReconciliationResult,
    ReconciliationSeverity,
    ReconciliationStatus,
)

ReportFormat = Literal["json", "markdown"]

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
_LONG_TOKEN_RE = re.compile(r"\b[0-9]{30,}\b")


@dataclass(frozen=True, slots=True)
class ReconciliationReportConfig:
    settings: AppSettings
    output_dir: Path


def write_reconciliation_reports(
    config: ReconciliationReportConfig,
    result: ReconciliationResult,
) -> ReconciliationResult:
    safe_result = _block_if_unsafe(config.settings, result)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    for report_format in ("json", "markdown"):
        path = config.output_dir / reconciliation_report_filename(report_format)
        path.write_text(
            f"{render_reconciliation_report(safe_result, report_format)}\n",
            encoding="utf-8",
        )
    return safe_result


def render_reconciliation_report(
    result: ReconciliationResult,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(result.to_dict(), indent=2, sort_keys=True)
    return render_reconciliation_report_markdown(result)


def render_reconciliation_report_markdown(result: ReconciliationResult) -> str:
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Reconciliation Report",
            "",
            "This report is read-only. It does not place, cancel, modify, retry, "
            "or automate live orders.",
            "",
            "## Status",
            "",
            f"- Status: {result.status.value}",
            f"- Checked at: {result.checked_at.isoformat()}",
            f"- Manual intervention detected: {result.manual_intervention_detected}",
            f"- Trading should pause: {result.trading_should_pause}",
            f"- Requires manual acknowledgement: {result.requires_manual_acknowledgement}",
            f"- Safety pause activated: {result.safety_pause_activated}",
            f"- Internal open order count: {result.internal_open_order_count}",
            f"- Actual open order count: {result.actual_open_order_count}",
            "- Last successful account read: "
            f"{_optional_datetime(result.last_successful_account_read_at)}",
            "",
            "## Events",
            "",
            _event_lines(result.detected_events),
            "",
            "## Blocking Reasons",
            "",
            _list(result.blocking_reasons),
            "",
            "## Warnings",
            "",
            _list(result.warnings),
            "",
            "## Operator Decision",
            "",
            "- Any mismatch pauses trading.",
            "- No automatic repair by trading is allowed.",
            "- Manual acknowledgement is required before further live activity when blocked.",
            "",
        )
    )


def reconciliation_report_filename(report_format: ReportFormat) -> str:
    return {
        "json": "reconciliation-report.json",
        "markdown": "reconciliation-report.md",
    }[report_format]


def _block_if_unsafe(
    settings: AppSettings,
    result: ReconciliationResult,
) -> ReconciliationResult:
    if not _unsafe_rendered_values(settings, result):
        return result

    safety_event = ReconciliationEvent(
        event_type=ReconciliationEventType.LIVE_STATE_UNAVAILABLE,
        severity=ReconciliationSeverity.BLOCKING,
        message="Generated reconciliation report contained sensitive values.",
        detected_at=result.checked_at,
        metadata={},
    )
    return replace(
        result,
        blocking_reasons=(
            *result.blocking_reasons,
            "Generated reconciliation report contained sensitive values.",
        ),
        detected_events=(*result.detected_events, safety_event),
        requires_manual_acknowledgement=True,
        status=ReconciliationStatus.BLOCKED,
        trading_should_pause=True,
    )


def _unsafe_rendered_values(
    settings: AppSettings,
    result: ReconciliationResult,
) -> tuple[str, ...]:
    rendered = render_reconciliation_report(result, "json") + render_reconciliation_report(
        result,
        "markdown",
    )
    unsafe: list[str] = []
    for value in _sensitive_values(settings):
        if value in rendered:
            unsafe.append(value)
    if _TX_HASH_RE.search(rendered):
        unsafe.append("transaction_hash")
    if _ADDRESS_RE.search(rendered):
        unsafe.append("wallet_address")
    if _LONG_TOKEN_RE.search(rendered):
        unsafe.append("token_id")
    return tuple(unsafe)


def _sensitive_values(settings: AppSettings) -> tuple[str, ...]:
    values: list[str] = []
    if settings.polymarket_private_key is not None:
        values.append(settings.polymarket_private_key.get_secret_value())
    values.extend(
        value
        for value in (
            settings.polymarket_wallet_address,
            settings.polymarket_funder_address,
            *settings.polymarket_live_token_allowlist,
        )
        if value
    )
    return tuple(value for value in values if len(value) >= 4)


def _event_lines(events: tuple[ReconciliationEvent, ...]) -> str:
    if not events:
        return "- None"
    return "\n".join(
        "- "
        f"{event.event_type.value}: {event.severity.value}; "
        f"manual_intervention={event.manual_intervention}"
        for event in events
    )


def _list(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values) or "- None"


def _optional_datetime(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


__all__ = [
    "ReconciliationReportConfig",
    "reconciliation_report_filename",
    "render_reconciliation_report",
    "render_reconciliation_report_markdown",
    "write_reconciliation_reports",
]
