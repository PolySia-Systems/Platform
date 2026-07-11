import json
from html import escape

from polysia.monitoring.acceptance_models import (
    AcceptanceAuditCheck,
    AcceptanceAuditReport,
    ReportFormat,
)


def render_acceptance_audit_json(report: AcceptanceAuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_acceptance_audit_markdown(report: AcceptanceAuditReport) -> str:
    reasons = "\n".join(f"- {reason}" for reason in report.reasons) or "- None"
    metrics = "\n".join(
        f"| {key} | {value} |" for key, value in sorted(report.metrics.to_dict().items())
    )
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Acceptance Audit",
            "",
            f"- Final result: {report.final_result}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Strategy: {report.strategy}",
            f"- Market slug: {report.selected_market['market_slug']}",
            f"- Token selected: {bool(report.selected_market['token_id'])}",
            "",
            "## Reasons",
            "",
            reasons,
            "",
            "## Safety Checks",
            "",
            _checks_markdown(report.safety_checks),
            "",
            "## System Checks",
            "",
            _checks_markdown(report.system_checks),
            "",
            "## Shadow Production Checks",
            "",
            _checks_markdown(report.shadow_checks),
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            metrics,
            "",
            "## Live Trading",
            "",
            "No live order was placed. No live cancel was sent.",
            "",
        )
    )


def render_acceptance_audit_html(report: AcceptanceAuditReport) -> str:
    metrics_rows = "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in sorted(report.metrics.to_dict().items())
    )
    reason_items = "".join(
        f"<li>{escape(reason)}</li>" for reason in report.reasons
    ) or "<li>None</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolySia — Polymarket Adapter — Acceptance Audit</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin-top: 24px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; padding: 8px 12px; color: #fff;
      background: #1f5f8b; font-weight: 700; }}
    .checks {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px; }}
    .check, section {{ border: 1px solid #d7dce0; border-radius: 8px; padding: 14px; }}
    .pass {{ border-left: 5px solid #0f7b4f; }}
    .warn {{ border-left: 5px solid #b7791f; }}
    .fail {{ border-left: 5px solid #b42318; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 9px 6px; text-align: left; }}
    tr:first-child th, tr:first-child td {{ border-top: 0; }}
    th {{ color: #687582; width: 44%; }}
  </style>
</head>
<body>
  <main>
    <h1>PolySia — Polymarket Adapter — Acceptance Audit</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.final_result)}</div>
    <h2>Reasons</h2>
    <ul>{reason_items}</ul>
    <h2>Safety Checks</h2>
    <div class="checks">{_checks_html(report.safety_checks)}</div>
    <h2>System Checks</h2>
    <div class="checks">{_checks_html(report.system_checks)}</div>
    <h2>Shadow Production Checks</h2>
    <div class="checks">{_checks_html(report.shadow_checks)}</div>
    <section>
      <h2>Metrics</h2>
      <table>{metrics_rows}</table>
    </section>
    <section>
      <h2>Live Trading</h2>
      <p>No live order was placed. No live cancel was sent.</p>
    </section>
  </main>
</body>
</html>
"""


def render_acceptance_audit(
    report: AcceptanceAuditReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return render_acceptance_audit_json(report)
    if report_format == "markdown":
        return render_acceptance_audit_markdown(report)
    return render_acceptance_audit_html(report)


def _checks_markdown(checks: tuple[AcceptanceAuditCheck, ...]) -> str:
    return "\n".join(
        f"- {check.name}: {check.status} - {check.message}" for check in checks
    )


def _checks_html(checks: tuple[AcceptanceAuditCheck, ...]) -> str:
    return "".join(
        f'<div class="check {escape(check.status)}">'
        f"<strong>{escape(check.name)}</strong>"
        f"<p>{escape(check.status)} - {escape(check.message)}</p>"
        "</div>"
        for check in checks
    )
