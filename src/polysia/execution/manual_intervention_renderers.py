from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from polysia.execution.manual_intervention_live_test import (
        ManualInterventionLiveTestReport,
    )

ReportFormat = Literal["json", "markdown"]


def render_manual_intervention_live_test(
    report: ManualInterventionLiveTestReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return render_manual_intervention_live_test_markdown(report)


def render_manual_intervention_live_test_markdown(
    report: ManualInterventionLiveTestReport,
) -> str:
    blockers = "\n".join(f"- {reason}" for reason in report.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    events = (
        "\n".join(f"- {event}" for event in report.reconciliation_event_types)
        or "- None"
    )
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Controlled Manual Intervention Live Test",
            "",
            f"- Final result: {report.final_result}",
            f"- Dry run: {report.dry_run}",
            f"- Order submitted: {report.order_submitted}",
            f"- Live attempt count: {report.live_attempt_count}",
            f"- Side/outcome: {report.side} {report.outcome}",
            f"- Order type: {report.order_type}",
            f"- Max notional: {report.max_notional}",
            f"- Token allowlisted: {report.token_allowlisted}",
            f"- Manual intervention detected: {report.manual_intervention_detected}",
            f"- Detection latency seconds: {report.detection_latency_seconds}",
            f"- Reconciliation status: {report.reconciliation_status}",
            f"- Trading should pause: {report.trading_should_pause}",
            f"- Requires manual acknowledgement: {report.requires_manual_acknowledgement}",
            f"- Safety pause activated: {report.safety_pause_activated}",
            "",
            "## Operator Instruction",
            "",
            f"- {report.operator_instruction}",
            "",
            "## Submitted Order State",
            "",
            f"- {report.submitted_order_state}",
            "",
            "## Reconciliation Events",
            "",
            events,
            "",
            "## Safety Statements",
            "",
            f"- {report.no_retry_statement}",
            f"- {report.no_cancel_statement}",
            f"- {report.no_strategy_statement}",
            "",
            "## Blocking Reasons",
            "",
            blockers,
            "",
            "## Warnings",
            "",
            warnings,
            "",
        )
    )
