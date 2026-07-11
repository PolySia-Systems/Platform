from __future__ import annotations

import json
from html import escape
from typing import Literal, cast

from polysia.monitoring.metrics import OperatorStatus

ReportFormat = Literal["html", "json", "markdown"]


def render_operator_report(status: OperatorStatus, report_format: str) -> str:
    """Render one sanitized operator status report."""
    normalized_format = _normalize_report_format(report_format)
    if normalized_format == "json":
        return render_operator_report_json(status)
    if normalized_format == "markdown":
        return render_operator_report_markdown(status)
    return render_operator_report_html(status)


def render_operator_report_json(status: OperatorStatus) -> str:
    return json.dumps(status.to_dict(), indent=2, sort_keys=True)


def render_operator_report_markdown(status: OperatorStatus) -> str:
    payload = status.to_dict()
    runtime = payload["runtime"]
    if not isinstance(runtime, dict):
        raise TypeError("operator status runtime payload must be a dict")

    warnings = payload["warnings"]
    if not isinstance(warnings, list):
        raise TypeError("operator status warnings payload must be a list")

    warning_lines = "\n".join(f"- {warning}" for warning in warnings) or "- None"
    runtime_lines = "\n".join(
        f"| {key} | {value} |" for key, value in sorted(runtime.items())
    )
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Operator Report",
            "",
            f"- Status: {payload['status']}",
            f"- Generated at: {payload['timestamp']}",
            f"- Tiny live orders ready: {payload['tiny_live_orders_ready']}",
            f"- Kill switch active: {payload['kill_switch_active']}",
            "",
            "## Warnings",
            "",
            warning_lines,
            "",
            "## Runtime",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            runtime_lines,
            "",
        )
    )


def render_operator_report_html(status: OperatorStatus) -> str:
    payload = status.to_dict()
    runtime = payload["runtime"]
    if not isinstance(runtime, dict):
        raise TypeError("operator status runtime payload must be a dict")

    warnings = payload["warnings"]
    if not isinstance(warnings, list):
        raise TypeError("operator status warnings payload must be a list")

    status_text = str(payload["status"])
    status_class = "ok" if status_text == "ok" else "blocked"
    tiny_ready = escape(str(payload["tiny_live_orders_ready"]))
    kill_switch_active = escape(str(payload["kill_switch_active"]))
    warning_items = "".join(
        f"<li>{escape(str(warning))}</li>" for warning in warnings
    ) or "<li>None</li>"
    runtime_rows = "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in sorted(runtime.items())
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolySia — Polymarket Adapter — Operator Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #687582;
      --line: #d7dce0;
      --ok: #0f7b4f;
      --blocked: #b42318;
      --accent: #1f5f8b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 32px 20px;
    }}
    header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .timestamp {{ color: var(--muted); margin: 0; }}
    .badge {{
      border-radius: 8px;
      color: #ffffff;
      font-weight: 700;
      padding: 8px 12px;
      text-transform: uppercase;
    }}
    .badge.ok {{ background: var(--ok); }}
    .badge.blocked {{ background: var(--blocked); }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric span {{
      color: var(--muted);
      display: block;
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .metric strong {{
      color: var(--accent);
      font-size: 18px;
    }}
    section {{ margin-top: 16px; }}
    h2 {{
      font-size: 18px;
      margin: 0 0 12px;
      letter-spacing: 0;
    }}
    ul {{ margin: 0; padding-left: 20px; }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border-top: 1px solid var(--line);
      padding: 10px 6px;
      text-align: left;
      vertical-align: top;
    }}
    tr:first-child th, tr:first-child td {{ border-top: 0; }}
    th {{ color: var(--muted); font-weight: 600; width: 42%; }}
    @media (max-width: 640px) {{
      header {{ display: block; }}
      .badge {{ display: inline-block; margin-top: 14px; }}
      main {{ padding: 22px 14px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>PolySia — Polymarket Adapter — Operator Report</h1>
        <p class="timestamp">{escape(str(payload['timestamp']))}</p>
      </div>
      <div class="badge {status_class}">{escape(status_text)}</div>
    </header>
    <div class="summary">
      <div class="metric"><span>Tiny Live Orders Ready</span><strong>{tiny_ready}</strong></div>
      <div class="metric"><span>Kill Switch Active</span><strong>{kill_switch_active}</strong></div>
      <div class="metric"><span>Warnings</span><strong>{len(warnings)}</strong></div>
    </div>
    <section>
      <h2>Warnings</h2>
      <ul>{warning_items}</ul>
    </section>
    <section>
      <h2>Runtime</h2>
      <table>{runtime_rows}</table>
    </section>
  </main>
</body>
</html>
"""


def _normalize_report_format(report_format: str) -> ReportFormat:
    normalized = report_format.strip().lower()
    if normalized in ("html", "json", "markdown"):
        return cast(ReportFormat, normalized)
    raise ValueError("report format must be html, json, or markdown")
