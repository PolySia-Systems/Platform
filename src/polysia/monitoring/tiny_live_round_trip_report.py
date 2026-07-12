from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from polysia.execution.tiny_live_round_trip import TinyLiveRoundTripReport

ReportFormat = Literal["json", "markdown"]
_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_SENSITIVE_KEYS = {
    "funder_address",
    "private_key",
    "secret",
    "signer_address",
    "wallet_address",
}


def write_tiny_live_round_trip_reports(
    report: TinyLiveRoundTripReport,
    output_dir: Path,
) -> dict[str, Path]:
    """Write immutable-run, operator-safe JSON and Markdown evidence."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "tiny-live-round-trip.json",
        "markdown": output_dir / "tiny-live-round-trip.md",
    }
    formats: tuple[ReportFormat, ...] = ("json", "markdown")
    for report_format in formats:
        path = paths[report_format]
        path.write_text(
            f"{render_tiny_live_round_trip(report, report_format)}\n",
            encoding="utf-8",
        )
    return paths


def render_tiny_live_round_trip(
    report: TinyLiveRoundTripReport,
    report_format: ReportFormat,
) -> str:
    payload = _sanitize(report.to_dict())
    if report_format == "json":
        return json.dumps(payload, indent=2, sort_keys=True)
    return _render_markdown(payload)


def _render_markdown(payload: dict[str, Any]) -> str:
    sections = (
        ("Account Snapshot", "account_snapshot"),
        ("Market Snapshot", "market_snapshot"),
        ("Strategy Decision", "strategy_decision"),
        ("Portfolio Decision", "portfolio_decision"),
        ("Risk Decision", "risk_decision"),
        ("Entry Order", "entry_order"),
        ("Exit Order", "exit_order"),
        ("Fees and Position", "fees"),
        ("Position State", "position_state"),
        ("Reconciliation", "reconciliation"),
        ("Ledger Entries", "ledger_entries"),
    )
    lines = [
        "# PolySia Tiny Live Round-Trip Evidence",
        "",
        f"- Run ID: `{payload.get('run_id')}`",
        f"- Git commit: `{payload.get('git_commit')}`",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Dry run: `{payload.get('dry_run')}`",
        f"- Final result: `{payload.get('final_result')}`",
        f"- Live entry attempts: `{payload.get('live_entry_attempt_count')}`",
        f"- Stop reason: `{payload.get('stop_reason')}`",
        "- Scope: execution-path validation only; no profitability claim.",
        "- Entry retry: disabled.",
    ]
    for title, key in sections:
        lines.extend(
            (
                "",
                f"## {title}",
                "",
                "```json",
                json.dumps(payload.get(key, {}), indent=2, sort_keys=True),
                "```",
            )
        )
    lines.extend(
        (
            "",
            "## Errors",
            "",
            *(f"- {error}" for error in payload.get("errors", [])),
            "",
            "## Evidence References",
            "",
            *(f"- `{item}`" for item in payload.get("evidence_references", [])),
        )
    )
    return "\n".join(lines)


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    normalized_key = (key or "").lower()
    if normalized_key in _SENSITIVE_KEYS or normalized_key.endswith("_private_key"):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        sanitized = _ADDRESS_RE.sub("<redacted-address>", value)
        for secret_name in ("POLYMARKET_PRIVATE_KEY",):
            secret = os.environ.get(secret_name)
            if secret and len(secret) >= 8:
                sanitized = sanitized.replace(secret, "<redacted>")
        return sanitized
    return value


__all__ = [
    "render_tiny_live_round_trip",
    "write_tiny_live_round_trip_reports",
]
