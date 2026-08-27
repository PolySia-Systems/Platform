from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.observability import (
    ObservabilitySnapshotConfig,
    build_observability_snapshot,
    render_observability_snapshot,
    write_observability_snapshot,
)
from polysia.risk.kill_switch import KillSwitch


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, 12, 30, tzinfo=UTC)


def safe_settings(*, live_enabled: bool = False) -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=live_enabled,
        POLYMARKET_FUNDER_ADDRESS="0x3333333333333333333333333333333333333333",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        POLYMARKET_WALLET_ADDRESS="0x2222222222222222222222222222222222222222",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


def test_observability_snapshot_schema_is_stable(tmp_path: Path) -> None:
    output_dir = ready_artifacts(tmp_path)

    snapshot = build_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )
    payload = snapshot.to_dict()

    assert tuple(sorted(payload)) == (
        "backtest_status",
        "blocking_reason_count",
        "blocking_reasons",
        "git",
        "health_counters",
        "last_live_result_summary",
        "latency_metrics",
        "latency_performance_intelligence",
        "live_path_readiness",
        "open_order_read_status",
        "orderbook_freshness",
        "paper_trading_status",
        "public_data_status",
        "runtime",
        "status",
        "stream_health",
        "timestamp",
        "warning_count",
        "warnings",
    )
    assert payload["status"] == "ready"
    assert payload["latency_metrics"] == {
        "average_ms": "1.5",
        "p95_ms": "2.0",
        "p99_ms": "2.5",
        "status": "available",
    }
    assert payload["latency_performance_intelligence"]["confidence"] == "INSUFFICIENT_DATA"
    assert payload["latency_performance_intelligence"]["execution"]["submit"]["status"] == (
        "UNKNOWN"
    )


def test_observability_snapshot_writes_json_markdown_and_html(tmp_path: Path) -> None:
    output_dir = ready_artifacts(tmp_path)

    snapshot = write_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    json_path = output_dir / "observability-snapshot.json"
    markdown_path = output_dir / "observability-snapshot.md"
    html_path = output_dir / "observability-dashboard.html"
    assert snapshot.status == "ready"
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "ready"
    assert markdown_path.read_text(encoding="utf-8").startswith(
        "# PolySia — Polymarket Adapter — Observability Snapshot"
    )
    assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_observability_snapshot_redacts_secrets_and_identifiers(tmp_path: Path) -> None:
    output_dir = ready_artifacts(tmp_path)
    snapshot = build_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    rendered = (
        render_observability_snapshot(snapshot, "json")
        + render_observability_snapshot(snapshot, "markdown")
        + render_observability_snapshot(snapshot, "html")
    )

    assert "not-for-output" not in rendered
    assert "token-secret" not in rendered
    assert "0x2222222222222222222222222222222222222222" not in rendered
    assert "0x3333333333333333333333333333333333333333" not in rendered
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in rendered
    assert "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in rendered


def test_observability_snapshot_counts_warnings_when_artifacts_missing(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "release-artifacts"
    output_dir.mkdir()

    snapshot = build_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=AppSettings(_env_file=None),
            project_root=ready_project(tmp_path),
            output_dir=output_dir,
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    payload = snapshot.to_dict()
    assert payload["status"] == "warning"
    assert payload["warning_count"] > 0
    assert payload["blocking_reason_count"] == 0


def test_observability_snapshot_blocks_when_live_flag_enabled(tmp_path: Path) -> None:
    snapshot = build_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=safe_settings(live_enabled=True),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert snapshot.status == "blocked"
    assert any("LIVE_TRADING_ENABLED" in reason for reason in snapshot.blocking_reasons)


def test_observability_snapshot_blocks_when_kill_switch_active(tmp_path: Path) -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual stop")

    snapshot = build_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        kill_switch=kill_switch,
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert snapshot.status == "blocked"
    assert any("Kill switch" in reason for reason in snapshot.blocking_reasons)


def test_observability_snapshot_never_uses_live_submit_or_cancel(tmp_path: Path) -> None:
    snapshot = build_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    rendered = render_observability_snapshot(snapshot, "markdown")
    assert "does not submit orders" in rendered
    assert "cancel orders" in rendered
    assert snapshot.status == "ready"


def ready_project(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Polymarket\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "TRADING_MODE=DATA_ONLY",
                "LIVE_TRADING_ENABLED=false",
                "POLYMARKET_PRIVATE_KEY=",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "\n".join(
            (
                ".env",
                ".env.*",
                "!.env.example",
                "*.key",
                "*.pem",
                "*.sqlite3",
                "secrets/",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
build-backend = "hatchling.build"

[project]
name = "polysia"
version = "0.1.0"
requires-python = ">=3.11"
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


def ready_artifacts(project_root: Path) -> Path:
    output_dir = project_root / "release-artifacts"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "shadow_run.json").write_text(
        json.dumps(
            {
                "classification": "SHADOW_HEALTHY",
                "metrics": {
                    "end_time": "2026-07-01T12:29:30+00:00",
                    "latency_average_ms": "1.5",
                    "latency_p95_ms": "2.0",
                    "latency_p99_ms": "2.5",
                    "orderbook_updates": 10,
                    "paper_fill_count": 3,
                    "paper_order_count": 3,
                    "paper_total_pnl": "0.01",
                    "reconnect_count": 0,
                    "stale_event_count": 0,
                    "stream_health": "mocked_public_stream",
                },
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "strategy_evaluation.json").write_text(
        json.dumps(
            {
                "classification": "STRATEGY_READY_FOR_SHADOW",
                "execution_quality": {"paper_fill_count": 3, "paper_order_count": 3},
                "signal_quality": {"total_signals": 3},
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "post-live-reconciliation.json").write_text(
        json.dumps(
            {
                "open_order_count": 0,
                "open_orders_readable": True,
                "reconciliation_status": "ready",
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "tiny_live_execution.json").write_text(
        json.dumps(
            {
                "dry_run": False,
                "final_result": "LIVE_ORDER_FILLED",
                "live_attempt_count": 1,
                "max_notional": "1.00",
                "order_submitted": True,
                "order_type": "FOK",
                "outcome": "YES",
                "side": "BUY",
                "token_id": "token-secret",
                "transaction_hash": (
                    "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                ),
                "wallet_address": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        ),
        encoding="utf-8",
    )
    return output_dir


def clean_git(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "chore/live-smoke-test-e2e\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "f8af613\n"
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
