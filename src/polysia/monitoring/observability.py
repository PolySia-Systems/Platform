from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Literal

from polysia.config.settings import AppSettings
from polysia.monitoring.metrics import build_operator_status
from polysia.monitoring.readiness import build_deployment_readiness
from polysia.risk.kill_switch import KillSwitch

Clock = Callable[[], datetime]
GitRunner = Callable[[Path, tuple[str, ...]], str]
ObservabilityStatus = Literal["ready", "warning", "blocked"]
ReportFormat = Literal["json", "markdown", "html"]

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ObservabilitySnapshotConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class ObservabilitySnapshot:
    timestamp: datetime
    status: ObservabilityStatus
    git: dict[str, object]
    runtime: dict[str, object]
    live_path_readiness: dict[str, object]
    public_data_status: dict[str, object]
    stream_health: dict[str, object]
    orderbook_freshness: dict[str, object]
    paper_trading_status: dict[str, object]
    backtest_status: dict[str, object]
    open_order_read_status: dict[str, object]
    last_live_result_summary: dict[str, object]
    latency_metrics: dict[str, object]
    health_counters: dict[str, object]
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "backtest_status": self.backtest_status,
            "blocking_reason_count": len(self.blocking_reasons),
            "blocking_reasons": list(self.blocking_reasons),
            "git": self.git,
            "health_counters": self.health_counters,
            "last_live_result_summary": self.last_live_result_summary,
            "latency_metrics": self.latency_metrics,
            "live_path_readiness": self.live_path_readiness,
            "open_order_read_status": self.open_order_read_status,
            "orderbook_freshness": self.orderbook_freshness,
            "paper_trading_status": self.paper_trading_status,
            "public_data_status": self.public_data_status,
            "runtime": self.runtime,
            "status": self.status,
            "stream_health": self.stream_health,
            "timestamp": self.timestamp.isoformat(),
            "warning_count": len(self.warnings),
            "warnings": list(self.warnings),
        }


def build_observability_snapshot(
    config: ObservabilitySnapshotConfig,
    *,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> ObservabilitySnapshot:
    """Build a local, sanitized operator observability snapshot."""

    root = config.project_root.resolve()
    output_dir = config.output_dir
    now = clock()
    active_kill_switch = kill_switch or KillSwitch()
    operator_status = build_operator_status(
        settings=config.settings,
        kill_switch=active_kill_switch,
        clock=lambda: now,
    )
    readiness = build_deployment_readiness(settings=config.settings, project_root=root)
    shadow_run = _read_mapping(output_dir / "shadow_run.json")
    strategy_evaluation = _read_mapping(output_dir / "strategy_evaluation.json")
    post_live = _read_mapping(output_dir / "post-live-reconciliation.json")
    tiny_live = _read_mapping(output_dir / "tiny_live_execution.json")

    warnings: list[str] = []
    blocking: list[str] = []
    if active_kill_switch.is_active():
        blocking.append("Kill switch is active.")
    if config.settings.live_trading_enabled:
        blocking.append("LIVE_TRADING_ENABLED is true during observability snapshot.")
    if readiness.status == "blocked":
        warnings.append("Deployment readiness is blocked.")
    if not shadow_run:
        warnings.append("Shadow-run artifact is unavailable.")
    if not strategy_evaluation:
        warnings.append("Strategy-evaluation artifact is unavailable.")
    if not post_live:
        warnings.append("Post-live reconciliation artifact is unavailable.")

    stream_health = _stream_health(shadow_run)
    orderbook_freshness = _orderbook_freshness(shadow_run, now)
    paper_status = _paper_trading_status(shadow_run)
    backtest_status = _backtest_status(strategy_evaluation)
    open_order_status = _open_order_read_status(post_live)
    last_live_summary = _last_live_result_summary(tiny_live or post_live)
    latency = _latency_metrics(shadow_run)

    for status_payload in (
        stream_health,
        orderbook_freshness,
        paper_status,
        backtest_status,
        open_order_status,
    ):
        if status_payload.get("status") == "warning":
            message = status_payload.get("message")
            if isinstance(message, str):
                warnings.append(message)

    health_counters: dict[str, object] = {
        "artifact_count": sum(
            1 for payload in (shadow_run, strategy_evaluation, post_live, tiny_live) if payload
        ),
        "blocking_reason_count": len(blocking),
        "deployment_readiness_status": readiness.status,
        "healthy_section_count": sum(
            1
            for payload in (
                stream_health,
                orderbook_freshness,
                paper_status,
                backtest_status,
                open_order_status,
            )
            if payload.get("status") == "ok"
        ),
        "operator_warning_count": len(operator_status.warnings),
        "warning_count": len(warnings),
    }
    snapshot = ObservabilitySnapshot(
        timestamp=now,
        status=_classify(blocking, warnings),
        git=_git_snapshot(root, git_runner=git_runner),
        runtime={
            "kill_switch_active": active_kill_switch.is_active(),
            "live_trading_enabled": config.settings.live_trading_enabled,
            "trading_mode": config.settings.trading_mode.value,
        },
        live_path_readiness={
            "allowed_live_path_ready": operator_status.tiny_live_orders_ready,
            "status": operator_status.status,
            "warning_count": len(operator_status.warnings),
        },
        public_data_status={
            "status": "available" if shadow_run else "not_checked",
            "source": "shadow_run_artifact" if shadow_run else "local_snapshot_only",
        },
        stream_health=stream_health,
        orderbook_freshness=orderbook_freshness,
        paper_trading_status=paper_status,
        backtest_status=backtest_status,
        open_order_read_status=open_order_status,
        last_live_result_summary=last_live_summary,
        latency_metrics=latency,
        health_counters=health_counters,
        blocking_reasons=tuple(blocking),
        warnings=tuple(dict.fromkeys(warnings)),
    )
    unsafe = _unsafe_rendered_values(config.settings, snapshot)
    if unsafe:
        blocking.append("Generated observability snapshot contained sensitive values.")
        snapshot = replace(
            snapshot,
            blocking_reasons=tuple(blocking),
            status="blocked",
            health_counters={
                **snapshot.health_counters,
                "blocking_reason_count": len(blocking),
            },
        )
    return snapshot


def write_observability_snapshot(
    config: ObservabilitySnapshotConfig,
    *,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
    git_runner: GitRunner | None = None,
) -> ObservabilitySnapshot:
    snapshot = build_observability_snapshot(
        config,
        kill_switch=kill_switch,
        clock=clock,
        git_runner=git_runner,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    for report_format in ("json", "markdown", "html"):
        path = config.output_dir / observability_snapshot_filename(report_format)
        path.write_text(
            f"{render_observability_snapshot(snapshot, report_format)}\n",
            encoding="utf-8",
        )
    return snapshot


def render_observability_snapshot(
    snapshot: ObservabilitySnapshot,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(snapshot.to_dict(), indent=2, sort_keys=True)
    if report_format == "markdown":
        return render_observability_snapshot_markdown(snapshot)
    return render_observability_snapshot_html(snapshot)


def render_observability_snapshot_markdown(snapshot: ObservabilitySnapshot) -> str:
    blockers = "\n".join(f"- {reason}" for reason in snapshot.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in snapshot.warnings) or "- None"
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Observability Snapshot",
            "",
            f"- Status: {snapshot.status}",
            f"- Generated at: {snapshot.timestamp.isoformat()}",
            f"- Trading mode: {snapshot.runtime['trading_mode']}",
            f"- Live enabled: {snapshot.runtime['live_trading_enabled']}",
            f"- Kill switch active: {snapshot.runtime['kill_switch_active']}",
            f"- Warning count: {len(snapshot.warnings)}",
            f"- Blocking reason count: {len(snapshot.blocking_reasons)}",
            "",
            "## Dashboard Sections",
            "",
            _table(
                {
                    "live_path_readiness": snapshot.live_path_readiness.get("status"),
                    "public_data_status": snapshot.public_data_status.get("status"),
                    "stream_health": snapshot.stream_health.get("status"),
                    "orderbook_freshness": snapshot.orderbook_freshness.get("status"),
                    "paper_trading_status": snapshot.paper_trading_status.get("status"),
                    "backtest_status": snapshot.backtest_status.get("status"),
                    "open_order_read_status": snapshot.open_order_read_status.get("status"),
                    "last_live_result": snapshot.last_live_result_summary.get("final_result"),
                }
            ),
            "",
            "## Latency",
            "",
            _table(snapshot.latency_metrics),
            "",
            "## Health Counters",
            "",
            _table(snapshot.health_counters),
            "",
            "## Blocking Reasons",
            "",
            blockers,
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Live Trading",
            "",
            "This command does not submit orders, cancel orders, retry, loop, "
            "or run a live strategy.",
            "",
        )
    )


def render_observability_snapshot_html(snapshot: ObservabilitySnapshot) -> str:
    payload = snapshot.to_dict()
    summary_rows = "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in sorted(snapshot.health_counters.items())
    )
    sections = {
        "Live Path Readiness": snapshot.live_path_readiness,
        "Public Data": snapshot.public_data_status,
        "Stream Health": snapshot.stream_health,
        "Orderbook Freshness": snapshot.orderbook_freshness,
        "Paper Trading": snapshot.paper_trading_status,
        "Backtest": snapshot.backtest_status,
        "Open Orders": snapshot.open_order_read_status,
        "Last Live Result": snapshot.last_live_result_summary,
        "Latency": snapshot.latency_metrics,
    }
    section_markup = "".join(
        f"<section><h2>{escape(title)}</h2><table>{_html_rows(values)}</table></section>"
        for title, values in sections.items()
    )
    warning_items = _html_items(snapshot.warnings)
    blocker_items = _html_items(snapshot.blocking_reasons)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolySia — Polymarket Adapter — Observability Snapshot</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933;
      background: #f7f8f6; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 0 0 12px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; color: #fff; font-weight: 700;
      padding: 8px 12px; background: #1f5f8b; text-transform: uppercase; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px; margin-top: 18px; }}
    section {{ background: #fff; border: 1px solid #d7dce0; border-radius: 8px;
      padding: 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 8px 6px; text-align: left;
      vertical-align: top; }}
    tr:first-child th, tr:first-child td {{ border-top: 0; }}
    th {{ color: #687582; width: 48%; }}
  </style>
</head>
<body>
  <main>
    <h1>PolySia — Polymarket Adapter — Observability Snapshot</h1>
    <p>{escape(str(payload["timestamp"]))}</p>
    <div class="badge">{escape(snapshot.status)}</div>
    <section>
      <h2>Health Counters</h2>
      <table>{summary_rows}</table>
    </section>
    <div class="grid">{section_markup}</div>
    <section>
      <h2>Blocking Reasons</h2>
      <ul>{blocker_items}</ul>
    </section>
    <section>
      <h2>Warnings</h2>
      <ul>{warning_items}</ul>
    </section>
  </main>
</body>
</html>
"""


def observability_snapshot_filename(report_format: ReportFormat) -> str:
    return {
        "html": "observability-dashboard.html",
        "json": "observability-snapshot.json",
        "markdown": "observability-snapshot.md",
    }[report_format]


def _stream_health(shadow_run: dict[str, object]) -> dict[str, object]:
    metrics = _mapping(shadow_run.get("metrics"))
    if not metrics:
        return {"message": "Stream health is unavailable.", "status": "warning"}
    return {
        "reconnect_count": _optional_int(metrics.get("reconnect_count")),
        "stale_event_count": _optional_int(metrics.get("stale_event_count")),
        "status": "ok",
        "stream_health": _optional_str(metrics.get("stream_health")),
    }


def _orderbook_freshness(
    shadow_run: dict[str, object],
    now: datetime,
) -> dict[str, object]:
    metrics = _mapping(shadow_run.get("metrics"))
    if not metrics:
        return {"message": "Orderbook freshness is unavailable.", "status": "warning"}
    end_time = _parse_datetime(metrics.get("end_time"))
    age_seconds = None if end_time is None else max(0, int((now - end_time).total_seconds()))
    return {
        "age_seconds": age_seconds,
        "orderbook_updates": _optional_int(metrics.get("orderbook_updates")),
        "status": "ok",
    }


def _paper_trading_status(shadow_run: dict[str, object]) -> dict[str, object]:
    metrics = _mapping(shadow_run.get("metrics"))
    if not metrics:
        return {"message": "Paper trading status is unavailable.", "status": "warning"}
    return {
        "paper_fill_count": _optional_int(metrics.get("paper_fill_count")),
        "paper_order_count": _optional_int(metrics.get("paper_order_count")),
        "status": "ok",
        "total_pnl": _optional_str(metrics.get("paper_total_pnl")),
    }


def _backtest_status(strategy_evaluation: dict[str, object]) -> dict[str, object]:
    if not strategy_evaluation:
        return {"message": "Backtest or evaluation status is unavailable.", "status": "warning"}
    signal_quality = _mapping(strategy_evaluation.get("signal_quality"))
    execution_quality = _mapping(strategy_evaluation.get("execution_quality"))
    return {
        "classification": _optional_str(strategy_evaluation.get("classification")),
        "paper_fill_count": _optional_int(execution_quality.get("paper_fill_count")),
        "paper_order_count": _optional_int(execution_quality.get("paper_order_count")),
        "status": "ok",
        "total_signals": _optional_int(signal_quality.get("total_signals")),
    }


def _open_order_read_status(post_live: dict[str, object]) -> dict[str, object]:
    if not post_live:
        return {"message": "Open order read status is unavailable.", "status": "warning"}
    readable = post_live.get("open_orders_readable") is True
    return {
        "open_order_count": _optional_int(post_live.get("open_order_count")),
        "readable": readable,
        "status": "ok" if readable else "warning",
    }


def _last_live_result_summary(source: dict[str, object]) -> dict[str, object]:
    if not source:
        return {"available": False, "final_result": None}
    summary = _mapping(source.get("tiny_live_execution_summary")) or source
    return {
        "available": True,
        "dry_run": _optional_bool(summary.get("dry_run")),
        "final_result": _optional_str(summary.get("final_result")),
        "live_attempt_count": _optional_int(summary.get("live_attempt_count")),
        "max_notional": _optional_str(summary.get("max_notional")),
        "order_submitted": _optional_bool(summary.get("order_submitted")),
        "order_type": _optional_str(summary.get("order_type")),
        "outcome": _optional_str(summary.get("outcome")),
        "side": _optional_str(summary.get("side")),
    }


def _latency_metrics(shadow_run: dict[str, object]) -> dict[str, object]:
    metrics = _mapping(shadow_run.get("metrics"))
    if not metrics:
        return {
            "average_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "status": "unavailable",
        }
    return {
        "average_ms": _optional_str(metrics.get("latency_average_ms")),
        "p95_ms": _optional_str(metrics.get("latency_p95_ms")),
        "p99_ms": _optional_str(metrics.get("latency_p99_ms")),
        "status": "available",
    }


def _read_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _git_snapshot(project_root: Path, *, git_runner: GitRunner | None) -> dict[str, object]:
    runner = git_runner or _run_git
    try:
        branch = runner(project_root, ("git", "branch", "--show-current")).strip()
        commit = runner(project_root, ("git", "rev-parse", "--short", "HEAD")).strip()
        status = runner(project_root, ("git", "status", "--short")).strip()
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "branch": None, "clean": None, "commit": None}
    return {
        "available": True,
        "branch": branch or "detached",
        "clean": status == "",
        "commit": commit or None,
    }


def _run_git(project_root: Path, command: tuple[str, ...]) -> str:
    result = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        cwd=project_root,
        text=True,
        timeout=5,
    )
    return result.stdout


def _classify(
    blocking: list[str],
    warnings: list[str],
) -> ObservabilityStatus:
    if blocking:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    if isinstance(value, (bool, int)):
        return str(value)
    return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _table(values: dict[str, object]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in sorted(values.items()))
    return "\n".join(("| Metric | Value |", "| --- | --- |", rows))


def _html_rows(values: dict[str, object]) -> str:
    return "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in sorted(values.items())
    )


def _html_items(values: tuple[str, ...]) -> str:
    return "".join(f"<li>{escape(value)}</li>" for value in values) or "<li>None</li>"


def _unsafe_rendered_values(
    settings: AppSettings,
    snapshot: ObservabilitySnapshot,
) -> tuple[str, ...]:
    rendered = render_observability_snapshot(snapshot, "json") + render_observability_snapshot(
        snapshot,
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


__all__ = [
    "ObservabilitySnapshot",
    "ObservabilitySnapshotConfig",
    "build_observability_snapshot",
    "observability_snapshot_filename",
    "render_observability_snapshot",
    "render_observability_snapshot_html",
    "render_observability_snapshot_markdown",
    "write_observability_snapshot",
]
