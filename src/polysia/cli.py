from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import typer

from polysia.adapters.polymarket.geoblock import PreLiveOrderGeoblockCheck
from polysia.adapters.polymarket.public import (
    PolymarketPublicAdapter,
    PolymarketPublicAdapterError,
)
from polysia.adapters.polymarket.round_trip_reconciliation import (
    PolymarketRoundTripReader,
    PolymarketRoundTripReadError,
)
from polysia.adapters.polymarket.secure import (
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.adapters.polymarket.stream import (
    MarketStream,
    MarketStreamConfig,
    MarketStreamError,
)
from polysia.backtesting.replay import (
    BacktestConfig,
    BacktestEngine,
    ReplayError,
    load_market_data_events_jsonl,
)
from polysia.bus.events import market_data_event_to_dict
from polysia.bus.in_memory_bus import InMemoryEventBus
from polysia.cli_support import (
    apply_secure_env_from_settings as _apply_secure_env_from_settings,
)
from polysia.cli_support import (
    build_research_strategy as _build_research_strategy,
)
from polysia.cli_support import (
    intent_to_dict as _intent_to_dict,
)
from polysia.cli_support import (
    local_market_event as _local_market_event,
)
from polysia.cli_support import (
    order_snapshots_from_external as _order_snapshots_from_external,
)
from polysia.cli_support import (
    parse_decimal as _parse_decimal,
)
from polysia.cli_support import (
    parse_optional_decimal as _parse_optional_decimal,
)
from polysia.cli_support import (
    parse_order_type as _parse_order_type,
)
from polysia.cli_support import (
    parse_outcome as _parse_outcome,
)
from polysia.cli_support import (
    parse_side as _parse_side,
)
from polysia.cli_support import (
    position_snapshots_from_external as _position_snapshots_from_external,
)
from polysia.cli_support import (
    read_safe_balance_allowance as _read_safe_balance_allowance,
)
from polysia.cli_support import (
    read_safe_open_orders as _read_safe_open_orders,
)
from polysia.cli_support import (
    read_safe_positions as _read_safe_positions,
)
from polysia.cli_support import (
    safe_cancel_response as _safe_cancel_response,
)
from polysia.cli_support import (
    safe_open_order_to_dict as _safe_open_order_to_dict,
)
from polysia.cli_support import (
    safe_order_response as _safe_order_response,
)
from polysia.config.logging import configure_logging
from polysia.config.settings import AppSettings, TradingMode
from polysia.deployment.automation import run_deployment_automation
from polysia.deployment.final_handoff import render_final_handoff_markdown
from polysia.deployment.manifest import build_release_manifest
from polysia.domain.market import MarketDetails, MarketSummary
from polysia.execution.controlled_second_tiny_live import (
    ControlledSecondTinyLiveConfig,
    controlled_second_tiny_live_filename,
    run_controlled_second_tiny_live,
)
from polysia.execution.intents import ApprovedOrderIntent, OrderIntent
from polysia.execution.live_broker import LiveBroker, LiveBrokerError
from polysia.execution.live_smoke_test import (
    LiveSmokeTestConfig,
    run_live_smoke_test,
)
from polysia.execution.manual_intervention_live_test import (
    ManualInterventionLiveTestConfig,
    manual_intervention_live_test_filename,
    run_manual_intervention_live_test,
)
from polysia.execution.paper_broker import PaperBroker
from polysia.execution.tiny_live_execution import (
    TinyLiveExecutionConfig,
    normalize_tiny_live_execution_formats,
    render_tiny_live_execution,
    run_tiny_live_execution,
    tiny_live_execution_filename,
)
from polysia.execution.tiny_live_round_trip import (
    AUTHORIZATION_ID,
    TinyLiveRoundTripConfig,
    run_tiny_live_round_trip,
)
from polysia.monitoring.acceptance_audit import (
    AcceptanceAuditConfig,
    acceptance_report_filename,
    build_acceptance_audit,
    normalize_acceptance_report_formats,
    render_acceptance_audit,
)
from polysia.monitoring.extended_strategy_evaluation import (
    ExtendedStrategyEvaluationConfig,
    ExtendedStrategyEvaluationError,
    build_extended_strategy_evaluation,
    write_extended_strategy_evaluation_reports,
)
from polysia.monitoring.fill_simulation import (
    FillSimulationAuditConfig,
    FillSimulationAuditError,
    build_fill_simulation_audit,
    fill_simulation_filename,
    normalize_fill_models,
    normalize_fill_report_formats,
    render_fill_simulation_audit,
)
from polysia.monitoring.local_release_closeout import (
    LocalReleaseCloseoutConfig,
    local_release_closeout_filename,
    write_local_release_closeout_reports,
)
from polysia.monitoring.main_merge_review import (
    MainMergeReviewConfig,
    main_merge_review_filename,
    write_main_merge_review_reports,
)
from polysia.monitoring.metrics import build_operator_status
from polysia.monitoring.observability import (
    ObservabilitySnapshotConfig,
    observability_snapshot_filename,
    write_observability_snapshot,
)
from polysia.monitoring.post_live_reconciliation import (
    PostLiveReconciliationConfig,
    post_live_reconciliation_filename,
    write_post_live_reconciliation_reports,
)
from polysia.monitoring.production_gap_audit import (
    ProductionGapAuditConfig,
    production_gap_audit_filename,
    write_production_gap_audit_reports,
)
from polysia.monitoring.readiness import build_deployment_readiness
from polysia.monitoring.real_data_shadow_run import (
    RealDataShadowRunConfig,
    build_real_data_shadow_run,
    real_data_shadow_run_filename,
    write_real_data_shadow_run_reports,
)
from polysia.monitoring.report import render_operator_report
from polysia.monitoring.runbook import render_operator_runbook_markdown
from polysia.monitoring.shadow_run import (
    ShadowRunConfig,
    build_shadow_run,
    normalize_shadow_report_formats,
    render_shadow_run,
    render_shadow_run_timeseries_jsonl,
    shadow_report_filename,
)
from polysia.monitoring.strategy_evaluation import (
    StrategyEvaluationConfig,
    StrategyEvaluationError,
    build_strategy_evaluation,
    normalize_strategy_evaluation_formats,
    render_strategy_evaluation,
    strategy_evaluation_filename,
)
from polysia.monitoring.tiny_live_monitor import (
    TinyLiveMonitorConfig,
    tiny_live_monitor_filename,
    write_tiny_live_monitor_reports,
)
from polysia.monitoring.tiny_live_readiness import (
    TinyLiveReadinessConfig,
    build_tiny_live_readiness,
    normalize_tiny_live_readiness_formats,
    render_tiny_live_readiness,
    tiny_live_readiness_filename,
)
from polysia.monitoring.tiny_live_round_trip_report import (
    write_tiny_live_round_trip_reports,
)
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.pnl import calculate_portfolio_pnl
from polysia.portfolio.positions import PositionLedger
from polysia.reconciliation import (
    ActualAccountState,
    InternalExpectedState,
    KillSwitchSafetyPause,
    ReconciliationInput,
    ReconciliationManager,
    ReconciliationReportConfig,
    ReconciliationResult,
    reconciliation_report_filename,
    write_reconciliation_reports,
)
from polysia.reconciliation.live_round_trip import (
    LiveRoundTripReconciliationConfig,
    LiveRoundTripReconciliationError,
    reconcile_live_round_trip,
)
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits
from polysia.strategies.base import StrategyContext

app = typer.Typer(
    help="PolySia — Polymarket-first trading platform.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class LiveSmokeSelection:
    market_slug: str
    condition_id: str
    token_id: str


@app.callback()
def main() -> None:
    """Run polysia commands."""


@app.command()
def health() -> None:
    """Print a safe runtime health response."""
    settings = AppSettings()
    configure_logging(settings)

    payload = {
        "app_env": settings.app_env,
        "live_trading_allowed": settings.live_trading_allowed,
        "live_trading_enabled": settings.live_trading_enabled,
        "service": "polysia",
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "trading_mode": settings.trading_mode.value,
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("operator-status")
def operator_status() -> None:
    """Print sanitized operator readiness and guardrail status."""
    settings = AppSettings()
    configure_logging(settings)
    status = build_operator_status(settings=settings)
    typer.echo(json.dumps(status.to_dict(), sort_keys=True))


@app.command("operator-report")
def operator_report(
    report_format: Annotated[
        str,
        typer.Option("--format", help="Report format: html, json, or markdown."),
    ] = "html",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional output file path."),
    ] = None,
) -> None:
    """Print or write a sanitized operator report."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        status = build_operator_status(settings=settings)
        report = render_operator_report(status, report_format)
    except ValueError as error:
        _print_error_and_exit(error)

    if output is None:
        typer.echo(report)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    payload = {
        "format": report_format.lower(),
        "output": str(output),
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("deployment-readiness")
def deployment_readiness(
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root to inspect."),
    ] = Path("."),
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
) -> None:
    """Print a sanitized deployment-readiness report."""
    settings = AppSettings()
    configure_logging(settings)

    report = build_deployment_readiness(
        settings=settings,
        project_root=project_root,
        require_clean_git=require_clean_git,
    )
    typer.echo(json.dumps(report.to_dict(), sort_keys=True))
    if report.status == "blocked":
        raise typer.Exit(code=1)


@app.command("operator-runbook")
def operator_runbook(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional markdown output file path."),
    ] = None,
    include_live: Annotated[
        bool,
        typer.Option("--include-live"),
    ] = False,
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root to inspect."),
    ] = Path("."),
) -> None:
    """Print or write a sanitized operator runbook."""
    settings = AppSettings()
    configure_logging(settings)

    status = build_operator_status(settings=settings)
    readiness = build_deployment_readiness(
        settings=settings,
        project_root=project_root,
    )
    runbook = render_operator_runbook_markdown(
        operator_status=status,
        readiness=readiness,
        include_live=include_live,
    )

    if output is None:
        typer.echo(runbook)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(runbook, encoding="utf-8")
    payload = {
        "include_live": include_live,
        "output": str(output),
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("release-manifest")
def release_manifest(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON output file path."),
    ] = None,
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root to inspect."),
    ] = Path("."),
) -> None:
    """Print or write a sanitized release handoff manifest."""
    settings = AppSettings()
    configure_logging(settings)

    manifest = build_release_manifest(
        settings=settings,
        project_root=project_root,
        require_clean_git=require_clean_git,
    )
    manifest_json = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)

    if output is None:
        typer.echo(manifest_json)
        if manifest.status == "blocked":
            raise typer.Exit(code=1)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{manifest_json}\n", encoding="utf-8")
    payload = {
        "output": str(output),
        "release_status": manifest.status,
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if manifest.status == "blocked":
        raise typer.Exit(code=1)


@app.command("deployment-automation")
def deployment_automation(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for generated handoff artifacts."),
    ] = Path("release-artifacts"),
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
    include_live_runbook: Annotated[
        bool,
        typer.Option("--include-live-runbook"),
    ] = False,
    run_quality_checks: Annotated[
        bool,
        typer.Option("--quality-checks/--skip-quality-checks"),
    ] = True,
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root to inspect."),
    ] = Path("."),
) -> None:
    """Run local sanitized deployment automation."""
    settings = AppSettings()
    configure_logging(settings)

    result = run_deployment_automation(
        settings=settings,
        project_root=project_root,
        output_dir=output_dir,
        require_clean_git=require_clean_git,
        include_live_runbook=include_live_runbook,
        run_quality_checks=run_quality_checks,
    )
    typer.echo(json.dumps(result.to_dict(), sort_keys=True))
    if result.status == "blocked":
        raise typer.Exit(code=1)


@app.command("final-handoff")
def final_handoff(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional markdown output file path."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for generated handoff artifacts."),
    ] = Path("release-artifacts"),
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
    include_live_runbook: Annotated[
        bool,
        typer.Option("--include-live-runbook"),
    ] = True,
    run_quality_checks: Annotated[
        bool,
        typer.Option("--quality-checks/--skip-quality-checks"),
    ] = True,
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root to inspect."),
    ] = Path("."),
) -> None:
    """Run final sanitized project handoff."""
    settings = AppSettings()
    configure_logging(settings)

    result = run_deployment_automation(
        settings=settings,
        project_root=project_root,
        output_dir=output_dir,
        require_clean_git=require_clean_git,
        include_live_runbook=include_live_runbook,
        run_quality_checks=run_quality_checks,
    )
    handoff = render_final_handoff_markdown(result)
    output_path = output or output_dir / "final-handoff.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(handoff, encoding="utf-8")
    payload = {
        "artifacts": {**result.artifacts, "final_handoff": str(output_path)},
        "handoff_status": result.status,
        "output": str(output_path),
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if result.status == "blocked":
        raise typer.Exit(code=1)


@app.command("acceptance-audit")
def acceptance_audit(
    duration_minutes: Annotated[
        int,
        typer.Option("--duration-minutes", min=1),
    ] = 1,
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug"),
    ] = None,
    token_id: Annotated[
        str | None,
        typer.Option("--token-id"),
    ] = None,
    strategy: Annotated[
        str,
        typer.Option("--strategy"),
    ] = "stale-price",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for acceptance-audit reports."),
    ] = Path("release-artifacts"),
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
    json_report: Annotated[
        bool,
        typer.Option("--json"),
    ] = False,
    markdown_report: Annotated[
        bool,
        typer.Option("--markdown"),
    ] = False,
    html_report: Annotated[
        bool,
        typer.Option("--html"),
    ] = False,
    allow_live_readonly: Annotated[
        bool,
        typer.Option("--allow-live-readonly"),
    ] = False,
) -> None:
    """Run a no-live-order acceptance audit and shadow-production simulation."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        report = asyncio.run(
            build_acceptance_audit(
                AcceptanceAuditConfig(
                    settings=settings,
                    project_root=Path("."),
                    duration_minutes=duration_minutes,
                    market_slug=market_slug,
                    token_id=token_id,
                    strategy=strategy,
                    require_clean_git=require_clean_git,
                    allow_live_readonly=allow_live_readonly,
                )
            )
        )
        formats = normalize_acceptance_report_formats(
            json_enabled=json_report,
            markdown_enabled=markdown_report,
            html_enabled=html_report,
        )
    except ValueError as error:
        _print_error_and_exit(error)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / acceptance_report_filename(report_format)
        path.write_text(
            f"{render_acceptance_audit(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)

    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "status": "ok" if report.final_result != "NOT_READY" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result == "NOT_READY":
        raise typer.Exit(code=1)


@app.command("production-gap-audit")
def production_gap_audit(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for production gap audit reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Write a read-only production gap audit and release-freeze summary."""
    settings = AppSettings()
    configure_logging(settings)

    report = write_production_gap_audit_reports(
        ProductionGapAuditConfig(
            settings=settings,
            project_root=Path("."),
            output_dir=output_dir,
        )
    )
    artifacts = {
        "freeze_summary": str(output_dir / production_gap_audit_filename("freeze")),
        "json": str(output_dir / production_gap_audit_filename("json")),
        "markdown": str(output_dir / production_gap_audit_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "audit_status": report.status,
        "status": "ok" if report.status != "blocked" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.status == "blocked":
        raise typer.Exit(code=1)


@app.command("main-merge-review")
def main_merge_review(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for main merge review reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Write a local human release review package for controlled main merge."""
    settings = AppSettings()
    configure_logging(settings)

    report = write_main_merge_review_reports(
        MainMergeReviewConfig(
            settings=settings,
            project_root=Path("."),
            output_dir=output_dir,
        )
    )
    artifacts = {
        "checklist": str(output_dir / main_merge_review_filename("checklist")),
        "json": str(output_dir / main_merge_review_filename("json")),
        "markdown": str(output_dir / main_merge_review_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "review_status": report.status,
        "status": "ok" if report.status != "blocked" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.status == "blocked":
        raise typer.Exit(code=1)


@app.command("local-release-closeout")
def local_release_closeout(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for final local closeout reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Write the final local release closeout package."""
    settings = AppSettings()
    configure_logging(settings)

    report = write_local_release_closeout_reports(
        LocalReleaseCloseoutConfig(
            settings=settings,
            project_root=Path("."),
            output_dir=output_dir,
        )
    )
    artifacts = {
        "json": str(output_dir / local_release_closeout_filename("json")),
        "markdown": str(output_dir / local_release_closeout_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "closeout_status": report.status,
        "status": "ok" if report.status != "blocked" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.status == "blocked":
        raise typer.Exit(code=1)


@app.command("reconcile-account")
def reconcile_account(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for reconciliation reports."),
    ] = Path("release-artifacts"),
    i_understand_this_uses_live_account: Annotated[
        bool,
        typer.Option("--i-understand-this-uses-live-account"),
    ] = False,
) -> None:
    """Run read-only account reconciliation and manual-intervention detection."""
    settings = AppSettings()
    configure_logging(settings)

    result = asyncio.run(
        _reconcile_account(
            settings=settings,
            output_dir=output_dir,
            i_understand_this_uses_live_account=i_understand_this_uses_live_account,
        )
    )
    artifacts = {
        "json": str(output_dir / reconciliation_report_filename("json")),
        "markdown": str(output_dir / reconciliation_report_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "manual_intervention_detected": result.manual_intervention_detected,
        "reconciliation_status": result.status.value,
        "status": "ok" if result.status.value != "blocked" else "blocked",
        "trading_should_pause": result.trading_should_pause,
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if result.status.value == "blocked":
        raise typer.Exit(code=1)


@app.command("shadow-run")
def shadow_run(
    duration_minutes: Annotated[
        int,
        typer.Option("--duration-minutes", min=1),
    ] = 1,
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug"),
    ] = None,
    token_id: Annotated[
        str | None,
        typer.Option("--token-id"),
    ] = None,
    strategy: Annotated[
        str,
        typer.Option("--strategy"),
    ] = "stale-price",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for shadow-run reports."),
    ] = Path("release-artifacts"),
    sample_interval_seconds: Annotated[
        int,
        typer.Option("--sample-interval-seconds", min=1),
    ] = 10,
    max_events: Annotated[
        int | None,
        typer.Option("--max-events", min=1),
    ] = None,
    json_report: Annotated[
        bool,
        typer.Option("--json"),
    ] = False,
    markdown_report: Annotated[
        bool,
        typer.Option("--markdown"),
    ] = False,
    html_report: Annotated[
        bool,
        typer.Option("--html"),
    ] = False,
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
) -> None:
    """Run a paper-only real-time shadow-run report."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        report = asyncio.run(
            build_shadow_run(
                ShadowRunConfig(
                    settings=settings,
                    project_root=Path("."),
                    duration_minutes=duration_minutes,
                    market_slug=market_slug,
                    token_id=token_id,
                    strategy=strategy,
                    sample_interval_seconds=sample_interval_seconds,
                    max_events=max_events,
                    require_clean_git=require_clean_git,
                )
            )
        )
        formats = normalize_shadow_report_formats(
            json_enabled=json_report,
            markdown_enabled=markdown_report,
            html_enabled=html_report,
        )
    except ValueError as error:
        _print_error_and_exit(error)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / shadow_report_filename(report_format)
        path.write_text(
            f"{render_shadow_run(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)

    timeseries_path = output_dir / "shadow_run_timeseries.jsonl"
    timeseries_text = render_shadow_run_timeseries_jsonl(report)
    timeseries_path.write_text(
        f"{timeseries_text}\n" if timeseries_text else "",
        encoding="utf-8",
    )
    artifacts["timeseries"] = str(timeseries_path)

    payload = {
        "artifacts": artifacts,
        "classification": report.classification,
        "status": "ok" if report.classification != "SHADOW_FAILED" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.classification == "SHADOW_FAILED":
        raise typer.Exit(code=1)


@app.command("shadow-run-real-data")
def shadow_run_real_data(
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug"),
    ] = None,
    auto_btc_5m: Annotated[bool, typer.Option("--auto-btc-5m")] = False,
    max_events: Annotated[int, typer.Option("--max-events", min=1)] = 100,
    strategy: Annotated[
        Literal["stale-price", "passive-market-maker"],
        typer.Option("--strategy"),
    ] = "stale-price",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for real-data shadow reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Run a public-data, paper-only shadow simulation; never touches live trading."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        report = asyncio.run(
            build_real_data_shadow_run(
                RealDataShadowRunConfig(
                    settings=settings,
                    project_root=Path("."),
                    output_dir=output_dir,
                    market_slug=market_slug,
                    auto_btc_5m=auto_btc_5m,
                    max_events=max_events,
                    strategy=strategy,
                )
            )
        )
    except ValueError as error:
        _print_error_and_exit(error)

    artifacts = write_real_data_shadow_run_reports(report, output_dir)
    payload = {
        "artifacts": {
            **artifacts,
            "json": str(output_dir / real_data_shadow_run_filename("json")),
            "markdown": str(output_dir / real_data_shadow_run_filename("markdown")),
        },
        "final_result": report.final_result,
        "status": "blocked" if report.final_result == "REAL_DATA_SHADOW_FAILED" else "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result == "REAL_DATA_SHADOW_FAILED":
        raise typer.Exit(code=1)


@app.command("strategy-evaluation")
def strategy_evaluation(
    input_path: Annotated[
        Path | None,
        typer.Option("--input", help="Backtest, shadow-run, audit, paper, or JSONL input."),
    ] = None,
    strategy: Annotated[
        str,
        typer.Option("--strategy"),
    ] = "stale-price",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for strategy evaluation reports."),
    ] = Path("release-artifacts"),
    min_sample_size: Annotated[
        int,
        typer.Option("--min-sample-size", min=1),
    ] = 30,
    json_report: Annotated[
        bool,
        typer.Option("--json"),
    ] = False,
    markdown_report: Annotated[
        bool,
        typer.Option("--markdown"),
    ] = False,
    html_report: Annotated[
        bool,
        typer.Option("--html"),
    ] = False,
) -> None:
    """Evaluate paper/backtest/shadow outputs without enabling live trading."""

    try:
        report = build_strategy_evaluation(
            StrategyEvaluationConfig(
                input_path=input_path,
                strategy=strategy,
                min_sample_size=min_sample_size,
            )
        )
        formats = normalize_strategy_evaluation_formats(
            json_enabled=json_report,
            markdown_enabled=markdown_report,
            html_enabled=html_report,
        )
    except (StrategyEvaluationError, ValueError) as error:
        _print_error_and_exit(error)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / strategy_evaluation_filename(report_format)
        path.write_text(
            f"{render_strategy_evaluation(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)

    payload = {
        "artifacts": artifacts,
        "classification": report.classification,
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("strategy-evaluation-extended")
def strategy_evaluation_extended(
    input_path: Annotated[
        Path,
        typer.Option("--input", help="Shadow-run, backtest, paper, or JSONL input."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for extended evaluation reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Build an extended read-only strategy evaluation report."""

    try:
        report = build_extended_strategy_evaluation(
            ExtendedStrategyEvaluationConfig(input_path=input_path)
        )
        artifacts = write_extended_strategy_evaluation_reports(report, output_dir)
    except ExtendedStrategyEvaluationError as error:
        _print_error_and_exit(error)

    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("fill-simulation-audit")
def fill_simulation_audit(
    input_path: Annotated[
        Path | None,
        typer.Option("--input", help="Backtest, paper, audit, or JSONL input."),
    ] = None,
    strategy: Annotated[
        str,
        typer.Option("--strategy"),
    ] = "stale-price",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for fill-simulation reports."),
    ] = Path("release-artifacts"),
    models: Annotated[
        list[str] | None,
        typer.Option("--model", help="Fill model to run; repeat this option."),
    ] = None,
    json_report: Annotated[
        bool,
        typer.Option("--json"),
    ] = False,
    markdown_report: Annotated[
        bool,
        typer.Option("--markdown"),
    ] = False,
    html_report: Annotated[
        bool,
        typer.Option("--html"),
    ] = False,
) -> None:
    """Audit paper fill realism without using live trading."""

    try:
        report = build_fill_simulation_audit(
            FillSimulationAuditConfig(
                input_path=input_path,
                strategy=strategy,
                models=normalize_fill_models(models),
            )
        )
        formats = normalize_fill_report_formats(
            json_enabled=json_report,
            markdown_enabled=markdown_report,
            html_enabled=html_report,
        )
    except (FillSimulationAuditError, ValueError) as error:
        _print_error_and_exit(error)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / fill_simulation_filename(report_format)
        path.write_text(
            f"{render_fill_simulation_audit(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)

    payload = {
        "artifacts": artifacts,
        "classification": report.classification,
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("tiny-live-readiness")
def tiny_live_readiness(
    acceptance_audit: Annotated[
        Path | None,
        typer.Option("--acceptance-audit", help="acceptance_audit.json path."),
    ] = None,
    shadow_run_report: Annotated[
        Path | None,
        typer.Option("--shadow-run", help="shadow_run.json path."),
    ] = None,
    strategy_evaluation_report: Annotated[
        Path | None,
        typer.Option("--strategy-evaluation", help="strategy_evaluation.json path."),
    ] = None,
    fill_simulation_audit_report: Annotated[
        Path | None,
        typer.Option(
            "--fill-simulation-audit",
            help="fill_simulation_audit.json path.",
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for tiny-live readiness reports."),
    ] = Path("release-artifacts"),
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
    json_report: Annotated[
        bool,
        typer.Option("--json"),
    ] = False,
    markdown_report: Annotated[
        bool,
        typer.Option("--markdown"),
    ] = False,
    html_report: Annotated[
        bool,
        typer.Option("--html"),
    ] = False,
) -> None:
    """Aggregate conservative tiny-live readiness without placing live orders."""

    settings = AppSettings()
    configure_logging(settings)

    report = build_tiny_live_readiness(
        TinyLiveReadinessConfig(
            settings=settings,
            project_root=Path("."),
            output_dir=output_dir,
            acceptance_audit_path=acceptance_audit,
            shadow_run_path=shadow_run_report,
            strategy_evaluation_path=strategy_evaluation_report,
            fill_simulation_audit_path=fill_simulation_audit_report,
            require_clean_git=require_clean_git,
        )
    )
    formats = normalize_tiny_live_readiness_formats(
        json_enabled=json_report,
        markdown_enabled=markdown_report,
        html_enabled=html_report,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / tiny_live_readiness_filename(report_format)
        path.write_text(
            f"{render_tiny_live_readiness(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)

    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "no_live_order_placed": report.no_live_order_placed,
        "status": "ok" if report.final_result != "NOT_READY_FOR_TINY_LIVE" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result == "NOT_READY_FOR_TINY_LIVE":
        raise typer.Exit(code=1)


@app.command("discover-markets")
def discover_markets(
    limit: Annotated[int, typer.Option(min=1, max=100)] = 10,
) -> None:
    """Print active Polymarket markets from the public SDK."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        markets = asyncio.run(_discover_markets(limit))
    except PolymarketPublicAdapterError as error:
        error_payload = {
            "message": str(error),
            "status": "error",
        }
        typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error

    success_payload = {
        "count": len(markets),
        "markets": [market.model_dump(mode="json") for market in markets],
        "status": "ok",
    }
    typer.echo(json.dumps(success_payload, sort_keys=True))


async def _discover_markets(limit: int) -> list[MarketSummary]:
    adapter = PolymarketPublicAdapter()
    return await adapter.list_active_markets(page_size=limit)


async def _resolve_live_smoke_selection(
    *,
    market_slug: str | None,
    condition_id: str | None,
    token_id: str | None,
    outcome: Literal["YES", "NO"],
    auto_btc_5m: bool,
) -> LiveSmokeSelection:
    if not auto_btc_5m:
        if not market_slug or not condition_id or not token_id:
            raise ValueError(
                "market_slug, condition_id, and token_id are required unless "
                "--auto-btc-5m is used."
            )
        return LiveSmokeSelection(
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
        )

    adapter = PolymarketPublicAdapter()
    markets = await adapter.search_markets("Bitcoin Up or Down 5m", page_size=30)
    candidates = [
        market
        for market in markets
        if _is_active_btc_5m_candidate(market)
    ]
    candidates.sort(key=lambda market: market.end_date or datetime.max.replace(tzinfo=UTC))

    for candidate in candidates:
        if candidate.slug is None:
            continue
        details = await adapter.get_market_by_slug(candidate.slug)
        selected_token = _token_id_for_smoke_outcome(details, outcome)
        if details.condition_id and selected_token:
            return LiveSmokeSelection(
                market_slug=candidate.slug,
                condition_id=details.condition_id,
                token_id=selected_token,
            )

    raise ValueError("Could not auto-select an active BTC 5m market with a token id.")


async def _resolve_monitor_btc_5m_market_slug() -> str:
    adapter = PolymarketPublicAdapter()
    markets = await adapter.search_markets("Bitcoin Up or Down 5m", page_size=30)
    candidates = [market for market in markets if _is_active_btc_5m_candidate(market)]
    candidates.sort(key=lambda market: market.end_date or datetime.max.replace(tzinfo=UTC))
    for candidate in candidates:
        if candidate.slug is not None:
            return candidate.slug
    raise ValueError("Could not auto-select an active BTC 5m market.")


def _is_active_btc_5m_candidate(market: MarketSummary) -> bool:
    if market.slug is None or not market.slug.startswith("btc-updown-5m-"):
        return False
    if market.active is not True or market.closed is True or market.accepting_orders is False:
        return False
    if market.end_date is None:
        return True
    end_date = market.end_date
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=UTC)
    return end_date > datetime.now(UTC) + timedelta(seconds=45)


def _token_id_for_smoke_outcome(
    market: MarketDetails,
    outcome: Literal["YES", "NO"],
) -> str | None:
    preferred_labels = {"yes", "up"} if outcome == "YES" else {"no", "down"}
    for market_outcome in market.outcomes:
        if market_outcome.label.lower() in preferred_labels:
            return market_outcome.token_id

    fallback_index = 0 if outcome == "YES" else 1
    if len(market.outcomes) <= fallback_index:
        return None
    return market.outcomes[fallback_index].token_id


@app.command("stream-market")
def stream_market(
    token_id: Annotated[str, typer.Option("--token-id", help="Polymarket outcome token ID.")],
    max_events: Annotated[int | None, typer.Option(min=1)] = None,
    stale_after_seconds: Annotated[float, typer.Option(min=1.0)] = 30.0,
) -> None:
    """Print normalized realtime market events for one token."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        asyncio.run(
            _stream_market(
                token_id=token_id,
                max_events=max_events,
                stale_after_seconds=stale_after_seconds,
            )
        )
    except MarketStreamError as error:
        error_payload = {
            "message": str(error),
            "status": "error",
        }
        typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error


async def _stream_market(
    *,
    token_id: str,
    max_events: int | None,
    stale_after_seconds: float,
) -> None:
    bus = InMemoryEventBus()
    subscription = bus.subscribe()
    stream = MarketStream(
        bus=bus,
        config=MarketStreamConfig(
            token_ids=(token_id,),
            stale_after=timedelta(seconds=stale_after_seconds),
        ),
    )
    runner = asyncio.create_task(stream.run(max_events=max_events))
    printed = 0

    try:
        async with subscription:
            while max_events is None or printed < max_events:
                next_event = asyncio.create_task(anext(subscription))
                done, pending = await asyncio.wait(
                    {next_event, runner},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if next_event in done:
                    event = next_event.result()
                    typer.echo(json.dumps(market_data_event_to_dict(event), sort_keys=True))
                    printed += 1
                    continue

                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                _raise_runner_error(runner)
                break
    finally:
        if not runner.done():
            runner.cancel()
            with suppress(asyncio.CancelledError):
                await runner
        await subscription.close()
        await bus.close()


def _raise_runner_error(runner: asyncio.Task[None]) -> None:
    error = runner.exception()
    if error is not None:
        raise error


@app.command("paper-trade")
def paper_trade(
    token_id: Annotated[str, typer.Option("--token-id", help="Polymarket outcome token ID.")],
    strategy: Annotated[str, typer.Option("--strategy")] = "stale-price",
    best_bid: Annotated[str, typer.Option("--best-bid")] = "0.49",
    bid_size: Annotated[str, typer.Option("--bid-size")] = "100",
    best_ask: Annotated[str, typer.Option("--best-ask")] = "0.52",
    ask_size: Annotated[str, typer.Option("--ask-size")] = "10",
    order_size: Annotated[str, typer.Option("--order-size")] = "1",
    min_edge: Annotated[str, typer.Option("--min-edge")] = "0.01",
    initial_cash: Annotated[str, typer.Option("--initial-cash")] = "100",
) -> None:
    """Run a deterministic paper-trading simulation from a local book."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _paper_trade(
                token_id=token_id,
                strategy=strategy,
                best_bid=_parse_decimal(best_bid, "best_bid"),
                bid_size=_parse_decimal(bid_size, "bid_size"),
                best_ask=_parse_decimal(best_ask, "best_ask"),
                ask_size=_parse_decimal(ask_size, "ask_size"),
                order_size=_parse_decimal(order_size, "order_size"),
                min_edge=_parse_decimal(min_edge, "min_edge"),
                initial_cash=_parse_decimal(initial_cash, "initial_cash"),
            )
        )
    except ValueError as error:
        error_payload = {
            "message": str(error),
            "status": "error",
        }
        typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("backtest-jsonl")
def backtest_jsonl(
    input_path: Annotated[Path, typer.Option("--input", help="JSONL market event file.")],
    strategy: Annotated[str, typer.Option("--strategy")] = "stale-price",
    initial_cash: Annotated[str, typer.Option("--initial-cash")] = "100",
    order_size: Annotated[str, typer.Option("--order-size")] = "1",
    min_edge: Annotated[str, typer.Option("--min-edge")] = "0.01",
    max_order_notional: Annotated[str, typer.Option("--max-order-notional")] = "10",
    max_position_per_token: Annotated[str, typer.Option("--max-position-per-token")] = "100",
    max_position_per_market: Annotated[str, typer.Option("--max-position-per-market")] = "250",
    max_open_orders: Annotated[int, typer.Option("--max-open-orders", min=0)] = 20,
    max_events: Annotated[int | None, typer.Option("--max-events", min=1)] = None,
) -> None:
    """Replay JSONL market events through strategy, risk, and paper broker."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _backtest_jsonl(
                input_path=input_path,
                strategy=strategy,
                initial_cash=_parse_decimal(initial_cash, "initial_cash"),
                order_size=_parse_decimal(order_size, "order_size"),
                min_edge=_parse_decimal(min_edge, "min_edge"),
                max_order_notional=_parse_decimal(
                    max_order_notional,
                    "max_order_notional",
                ),
                max_position_per_token=_parse_decimal(
                    max_position_per_token,
                    "max_position_per_token",
                ),
                max_position_per_market=_parse_decimal(
                    max_position_per_market,
                    "max_position_per_market",
                ),
                max_open_orders=max_open_orders,
                max_events=max_events,
            )
        )
    except (ReplayError, ValueError) as error:
        _print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("live-open-orders")
def live_open_orders(
    token_id: Annotated[str | None, typer.Option("--token-id")] = None,
    order_id: Annotated[str | None, typer.Option("--order-id")] = None,
    market: Annotated[str | None, typer.Option("--market")] = None,
    redact_secrets: Annotated[bool, typer.Option("--redact-secrets")] = False,
    i_understand_this_uses_live_account: Annotated[
        bool,
        typer.Option("--i-understand-this-uses-live-account"),
    ] = False,
) -> None:
    """Read authenticated live open orders; never submits or cancels."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_open_orders(
                settings=settings,
                token_id=token_id,
                order_id=order_id,
                market=market,
                i_understand_this_uses_live_account=(
                    i_understand_this_uses_live_account or redact_secrets
                ),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        _print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("live-account-status")
def live_account_status(
    redact_secrets: Annotated[bool, typer.Option("--redact-secrets")] = False,
    i_understand_this_uses_live_account: Annotated[
        bool,
        typer.Option("--i-understand-this-uses-live-account"),
    ] = False,
) -> None:
    """Read a sanitized live account status; never submits or cancels."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_account_status(
                settings=settings,
                i_understand_this_uses_live_account=(
                    i_understand_this_uses_live_account or redact_secrets
                ),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        _print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("live-cancel-order")
def live_cancel_order(
    order_id: Annotated[str, typer.Option("--order-id")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--submit")] = True,
    i_understand_this_modifies_live_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-modifies-live-orders"),
    ] = False,
) -> None:
    """Cancel one live order; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_cancel_order(
                settings=settings,
                order_id=order_id,
                dry_run=dry_run,
                i_understand_this_modifies_live_orders=(
                    i_understand_this_modifies_live_orders
                ),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        _print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("live-cancel-market-orders")
def live_cancel_market_orders(
    token_id: Annotated[str, typer.Option("--token-id")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--submit")] = True,
    i_understand_this_modifies_live_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-modifies-live-orders"),
    ] = False,
) -> None:
    """Cancel live orders for one allowlisted token; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_cancel_market_orders(
                settings=settings,
                token_id=token_id,
                dry_run=dry_run,
                i_understand_this_modifies_live_orders=(
                    i_understand_this_modifies_live_orders
                ),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        _print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("live-smoke-test")
def live_smoke_test(
    market_slug: Annotated[str | None, typer.Option("--market-slug")] = None,
    condition_id: Annotated[str | None, typer.Option("--condition-id")] = None,
    token_id: Annotated[str | None, typer.Option("--token-id")] = None,
    outcome: Annotated[str, typer.Option("--outcome", help="YES or NO.")] = "YES",
    side: Annotated[str, typer.Option("--side", help="BUY or SELL.")] = "BUY",
    max_notional: Annotated[str, typer.Option("--max-notional")] = "1.00",
    order_type: Annotated[str, typer.Option("--order-type", help="FAK or FOK.")] = "FAK",
    max_slippage_bps: Annotated[int, typer.Option("--max-slippage-bps", min=0)] = 200,
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = True,
    require_clean_git: Annotated[bool, typer.Option("--require-clean-git")] = False,
    auto_btc_5m: Annotated[bool, typer.Option("--auto-btc-5m")] = False,
    i_understand_this_places_a_real_order: Annotated[
        bool,
        typer.Option("--i-understand-this-places-a-real-order"),
    ] = False,
) -> None:
    """Run one guarded live connectivity smoke test; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)
    _apply_secure_env_from_settings(settings)

    try:
        parsed_outcome = _parse_outcome(outcome)
        selection = asyncio.run(
            _resolve_live_smoke_selection(
                market_slug=market_slug,
                condition_id=condition_id,
                token_id=token_id,
                outcome=parsed_outcome,
                auto_btc_5m=auto_btc_5m,
            )
        )
        if auto_btc_5m and selection.token_id not in settings.polymarket_live_token_allowlist:
            settings = settings.model_copy(
                update={"polymarket_live_token_allowlist": (selection.token_id,)}
            )
        report = asyncio.run(
            run_live_smoke_test(
                LiveSmokeTestConfig(
                    settings=settings,
                    market_slug=selection.market_slug,
                    condition_id=selection.condition_id,
                    token_id=selection.token_id,
                    outcome=parsed_outcome,
                    side=_parse_side(side),
                    max_notional=_parse_decimal(max_notional, "max_notional"),
                    order_type=_parse_order_type(order_type),
                    max_slippage_bps=max_slippage_bps,
                    dry_run=dry_run,
                    require_clean_git=require_clean_git,
                    acknowledgement=i_understand_this_places_a_real_order,
                    project_root=Path("."),
                )
            )
        )
    except (PolymarketPublicAdapterError, ValueError) as error:
        _print_error_and_exit(error)

    payload = {
        "final_result": report.final_result,
        "report_json": "live_smoke_test.json",
        "report_markdown": "live_smoke_test.md",
        "status": "ok" if report.final_result == "PASS" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result != "PASS":
        raise typer.Exit(code=1)


@app.command("tiny-live-execute")
def tiny_live_execute(
    token_id: Annotated[str, typer.Option("--token-id")],
    side: Annotated[Literal["BUY", "SELL"], typer.Option("--side")],
    outcome: Annotated[Literal["YES", "NO"], typer.Option("--outcome")],
    max_notional: Annotated[str, typer.Option("--max-notional")],
    order_type: Annotated[Literal["FAK", "FOK"], typer.Option("--order-type")],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for tiny live execution reports."),
    ] = Path("release-artifacts"),
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = True,
    require_clean_git: Annotated[bool, typer.Option("--require-clean-git")] = False,
    i_understand_this_places_one_real_order: Annotated[
        bool,
        typer.Option("--i-understand-this-places-one-real-order"),
    ] = False,
    market_slug: Annotated[str | None, typer.Option("--market-slug")] = None,
    condition_id: Annotated[str | None, typer.Option("--condition-id")] = None,
    price: Annotated[str | None, typer.Option("--price")] = None,
    redact_secrets: Annotated[
        bool,
        typer.Option("--redact-secrets/--no-redact-secrets"),
    ] = True,
    json_report: Annotated[bool, typer.Option("--json")] = False,
    markdown_report: Annotated[bool, typer.Option("--markdown")] = False,
    html_report: Annotated[bool, typer.Option("--html")] = False,
) -> None:
    """Preview or submit exactly one guarded tiny live FAK/FOK order."""

    settings = AppSettings()
    configure_logging(settings)
    _apply_secure_env_from_settings(settings)

    try:
        report = asyncio.run(
            run_tiny_live_execution(
                TinyLiveExecutionConfig(
                    settings=settings,
                    token_id=token_id,
                    side=side,
                    outcome=outcome,
                    max_notional=_parse_decimal(max_notional, "max_notional"),
                    order_type=order_type,
                    output_dir=output_dir,
                    dry_run=dry_run,
                    require_clean_git=require_clean_git,
                    acknowledgement=i_understand_this_places_one_real_order,
                    market_slug=market_slug,
                    condition_id=condition_id,
                    price=_parse_optional_decimal(price),
                    redact_secrets=redact_secrets,
                    project_root=Path("."),
                )
            )
        )
        formats = normalize_tiny_live_execution_formats(
            json_enabled=json_report,
            markdown_enabled=markdown_report,
            html_enabled=html_report,
        )
    except ValueError as error:
        _print_error_and_exit(error)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / tiny_live_execution_filename(report_format)
        path.write_text(
            f"{render_tiny_live_execution(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)

    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "live_attempt_count": report.live_attempt_count,
        "order_submitted": report.order_submitted,
        "status": "ok" if not report.blocking_reasons else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.blocking_reasons:
        raise typer.Exit(code=1)


@app.command("tiny-live-round-trip")
def tiny_live_round_trip(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Base directory for immutable run evidence."),
    ] = Path("release-artifacts/tiny-live-round-trip"),
    submit: Annotated[
        bool,
        typer.Option("--submit/--dry-run", help="Submit only after every merged-code gate."),
    ] = False,
    acknowledge: Annotated[
        str | None,
        typer.Option("--acknowledge", help=f"Required live acknowledgement: {AUTHORIZATION_ID}"),
    ] = None,
    verified_ci_commit: Annotated[
        str | None,
        typer.Option("--verified-ci-commit", help="Exact green-CI commit required for submit."),
    ] = None,
) -> None:
    """Discover and validate one BTC 15m favorite round trip; dry-run by default."""

    settings = AppSettings()
    configure_logging(settings)
    _apply_secure_env_from_settings(settings)
    run_id = str(uuid4())
    run_output_dir = output_dir / run_id
    try:
        report = asyncio.run(
            run_tiny_live_round_trip(
                TinyLiveRoundTripConfig(
                    settings=settings,
                    project_root=Path("."),
                    output_dir=run_output_dir,
                    database_path=Path("data/polysia.sqlite3"),
                    dry_run=not submit,
                    acknowledgement=acknowledge == AUTHORIZATION_ID,
                    verified_ci_commit=verified_ci_commit,
                    run_id=run_id,
                )
            )
        )
        artifacts = write_tiny_live_round_trip_reports(report, run_output_dir)
    except (OSError, ValueError) as error:
        _print_error_and_exit(error)

    safe_results = {"COMPLETED_ROUND_TRIP", "ENTRY_FILLED_EXIT_OPEN"}
    payload = {
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "final_result": report.final_result,
        "live_entry_attempt_count": report.live_entry_attempt_count,
        "run_id": report.run_id,
        "status": "ok" if report.final_result in safe_results else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result not in safe_results:
        raise typer.Exit(code=1)


@app.command("post-live-reconciliation")
def post_live_reconciliation(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for post-live reconciliation reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Write sanitized post-live reconciliation artifacts; never submits or cancels."""
    settings = AppSettings()
    configure_logging(settings)

    report = asyncio.run(
        write_post_live_reconciliation_reports(
            PostLiveReconciliationConfig(
                settings=settings,
                project_root=Path("."),
                output_dir=output_dir,
            )
        )
    )
    artifacts = {
        "json": str(output_dir / post_live_reconciliation_filename("json")),
        "markdown": str(output_dir / post_live_reconciliation_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "reconciliation_status": report.reconciliation_status,
        "status": "ok" if report.reconciliation_status != "blocked" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.reconciliation_status == "blocked":
        raise typer.Exit(code=1)


@app.command("reconcile-live-round-trip")
def reconcile_live_round_trip_command(
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Persisted live round-trip run identifier."),
    ],
    authorization_id: Annotated[
        str,
        typer.Option("--authorization-id", help="Consumed owner authorization identifier."),
    ] = AUTHORIZATION_ID,
    database_path: Annotated[
        Path,
        typer.Option("--database", help="PolySia SQLite state database."),
    ] = Path("data/polysia.sqlite3"),
) -> None:
    """Reconcile a persisted round trip through authenticated read-only venue calls."""

    settings = AppSettings()
    configure_logging(settings)
    _apply_secure_env_from_settings(settings)
    try:
        report = asyncio.run(
            reconcile_live_round_trip(
                LiveRoundTripReconciliationConfig(
                    database_path=database_path,
                    run_id=run_id,
                    authorization_id=authorization_id,
                ),
                venue_reader=PolymarketRoundTripReader(),
            )
        )
    except (
        LiveRoundTripReconciliationError,
        PolymarketRoundTripReadError,
        OSError,
        ValueError,
    ) as error:
        _print_error_and_exit(error)

    typer.echo(json.dumps(report.to_dict(), sort_keys=True))
    if report.status == "blocked":
        raise typer.Exit(code=1)


@app.command("observability-snapshot")
def observability_snapshot(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for observability snapshot reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Write sanitized local observability snapshot artifacts; no submit/cancel calls."""
    settings = AppSettings()
    configure_logging(settings)

    snapshot = write_observability_snapshot(
        ObservabilitySnapshotConfig(
            settings=settings,
            project_root=Path("."),
            output_dir=output_dir,
        )
    )
    artifacts = {
        "html": str(output_dir / observability_snapshot_filename("html")),
        "json": str(output_dir / observability_snapshot_filename("json")),
        "markdown": str(output_dir / observability_snapshot_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "observability_status": snapshot.status,
        "status": "ok" if snapshot.status != "blocked" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if snapshot.status == "blocked":
        raise typer.Exit(code=1)


@app.command("tiny-live-monitor")
def tiny_live_monitor(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for tiny live monitor reports."),
    ] = Path("release-artifacts"),
    redact_secrets: Annotated[
        bool,
        typer.Option("--redact-secrets/--no-redact-secrets"),
    ] = True,
    token_id: Annotated[
        str | None,
        typer.Option("--token-id", help="Optional allowlisted token to read only."),
    ] = None,
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug", help="Optional market slug to monitor."),
    ] = None,
    auto_btc_5m: Annotated[
        bool,
        typer.Option("--auto-btc-5m"),
    ] = False,
    max_cycles: Annotated[
        int,
        typer.Option("--max-cycles", min=1),
    ] = 1,
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", min=30),
    ] = 30,
) -> None:
    """Write a read-only tiny live monitor report; never submits or cancels."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        selected_market_slug = market_slug
        if auto_btc_5m and selected_market_slug is None:
            selected_market_slug = asyncio.run(_resolve_monitor_btc_5m_market_slug())
        report = asyncio.run(
            write_tiny_live_monitor_reports(
                TinyLiveMonitorConfig(
                    settings=settings,
                    project_root=Path("."),
                    output_dir=output_dir,
                    token_id=token_id,
                    market_slug=selected_market_slug,
                    auto_btc_5m=auto_btc_5m,
                    max_cycles=max_cycles,
                    interval_seconds=interval_seconds,
                    redact_secrets=redact_secrets,
                )
            )
        )
    except (PolymarketPublicAdapterError, ValueError) as error:
        _print_error_and_exit(error)

    artifacts = {
        "json": str(output_dir / tiny_live_monitor_filename("json")),
        "markdown": str(output_dir / tiny_live_monitor_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "monitor_status": report.status,
        "status": "ok" if report.status != "blocked" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("controlled-second-tiny-live")
def controlled_second_tiny_live(
    auto_btc_5m: Annotated[
        bool,
        typer.Option("--auto-btc-5m"),
    ] = False,
    token_id: Annotated[
        str | None,
        typer.Option("--token-id", help="Optional allowlisted BTC 5m token."),
    ] = None,
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug", help="BTC Up/Down 5m market slug."),
    ] = None,
    side: Annotated[Literal["BUY", "SELL"], typer.Option("--side")] = "BUY",
    outcome: Annotated[Literal["YES", "NO"], typer.Option("--outcome")] = "YES",
    max_notional: Annotated[str, typer.Option("--max-notional")] = "1.00",
    order_type: Annotated[Literal["FAK", "FOK"], typer.Option("--order-type")] = "FOK",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Keep this run dry. Default when --submit is absent."),
    ] = False,
    submit: Annotated[
        bool,
        typer.Option("--submit", help="Request the one real second tiny live attempt."),
    ] = False,
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
    i_understand_this_places_real_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-places-real-orders"),
    ] = False,
    i_confirm_this_is_the_second_controlled_tiny_live_test: Annotated[
        bool,
        typer.Option("--i-confirm-this-is-the-second-controlled-tiny-live-test"),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for controlled second tiny reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Prepare or submit one stricter controlled second tiny live attempt."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        selected_token = token_id
        selected_market_slug = market_slug
        if auto_btc_5m:
            selection = asyncio.run(
                _resolve_live_smoke_selection(
                    market_slug=None,
                    condition_id=None,
                    token_id=None,
                    outcome=outcome,
                    auto_btc_5m=True,
                )
            )
            selected_token = selection.token_id
            selected_market_slug = selection.market_slug
        if selected_token is None or selected_market_slug is None:
            raise ValueError(
                "--token-id and --market-slug are required unless --auto-btc-5m is used."
            )
        report = asyncio.run(
            run_controlled_second_tiny_live(
                ControlledSecondTinyLiveConfig(
                    settings=settings,
                    output_dir=output_dir,
                    token_id=selected_token,
                    side=side,
                    outcome=outcome,
                    max_notional=_parse_decimal(max_notional, "max_notional"),
                    order_type=order_type,
                    market_slug=selected_market_slug,
                    dry_run=(not submit) or dry_run,
                    submit_requested=submit,
                    acknowledgement=i_understand_this_places_real_orders,
                    second_acknowledgement=(
                        i_confirm_this_is_the_second_controlled_tiny_live_test
                    ),
                    auto_btc_5m=auto_btc_5m,
                    require_clean_git=require_clean_git,
                    project_root=Path("."),
                )
            )
        )
    except (PolymarketPublicAdapterError, ValueError) as error:
        _print_error_and_exit(error)

    artifacts = {
        "json": str(output_dir / controlled_second_tiny_live_filename("json")),
        "markdown": str(output_dir / controlled_second_tiny_live_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "live_attempt_count": report.live_attempt_count,
        "order_submitted": report.order_submitted,
        "status": "ok" if report.final_result != "BLOCKED" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result == "BLOCKED":
        raise typer.Exit(code=1)


@app.command("manual-intervention-live-test")
def manual_intervention_live_test(
    auto_btc_5m: Annotated[bool, typer.Option("--auto-btc-5m")] = False,
    token_id: Annotated[
        str | None,
        typer.Option("--token-id", help="Optional allowlisted BTC 5m token."),
    ] = None,
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug", help="BTC Up/Down 5m market slug."),
    ] = None,
    condition_id: Annotated[
        str | None,
        typer.Option("--condition-id", help="Optional selected market condition id."),
    ] = None,
    outcome: Annotated[Literal["YES", "NO"], typer.Option("--outcome")] = "YES",
    side: Annotated[Literal["BUY", "SELL"], typer.Option("--side")] = "BUY",
    max_notional: Annotated[str, typer.Option("--max-notional")] = "1.00",
    order_type: Annotated[Literal["FAK", "FOK"], typer.Option("--order-type")] = "FOK",
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = True,
    require_clean_git: Annotated[bool, typer.Option("--require-clean-git")] = False,
    poll_attempts: Annotated[int, typer.Option("--poll-attempts", min=1)] = 30,
    poll_interval_seconds: Annotated[
        float,
        typer.Option("--poll-interval-seconds", min=0.0),
    ] = 2.0,
    i_understand_this_places_one_real_order: Annotated[
        bool,
        typer.Option("--i-understand-this-places-one-real-order"),
    ] = False,
    i_will_manually_cancel_or_close: Annotated[
        bool,
        typer.Option("--i-will-manually-cancel-or-close"),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for manual-intervention reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Run a controlled manual-intervention test; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        selected_token = token_id
        selected_market_slug = market_slug
        selected_condition_id = condition_id
        if auto_btc_5m:
            selection = asyncio.run(
                _resolve_live_smoke_selection(
                    market_slug=None,
                    condition_id=None,
                    token_id=None,
                    outcome=outcome,
                    auto_btc_5m=True,
                )
            )
            selected_token = selection.token_id
            selected_market_slug = selection.market_slug
            selected_condition_id = selection.condition_id
        if selected_token is None or selected_market_slug is None:
            raise ValueError(
                "--token-id and --market-slug are required unless --auto-btc-5m is used."
            )
        if auto_btc_5m and selected_token not in settings.polymarket_live_token_allowlist:
            settings = settings.model_copy(
                update={"polymarket_live_token_allowlist": (selected_token,)}
            )
        _apply_secure_env_from_settings(settings)
        report = asyncio.run(
            run_manual_intervention_live_test(
                ManualInterventionLiveTestConfig(
                    settings=settings,
                    output_dir=output_dir,
                    token_id=selected_token,
                    side=side,
                    outcome=outcome,
                    max_notional=_parse_decimal(max_notional, "max_notional"),
                    order_type=order_type,
                    market_slug=selected_market_slug,
                    condition_id=selected_condition_id,
                    dry_run=dry_run,
                    acknowledgement=i_understand_this_places_one_real_order,
                    manual_intervention_acknowledgement=i_will_manually_cancel_or_close,
                    require_clean_git=require_clean_git,
                    poll_attempts=poll_attempts,
                    poll_interval_seconds=poll_interval_seconds,
                    project_root=Path("."),
                )
            )
        )
    except (PolymarketPublicAdapterError, ValueError) as error:
        _print_error_and_exit(error)

    artifacts = {
        "json": str(output_dir / manual_intervention_live_test_filename("json")),
        "markdown": str(output_dir / manual_intervention_live_test_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "live_attempt_count": report.live_attempt_count,
        "manual_intervention_detected": report.manual_intervention_detected,
        "order_submitted": report.order_submitted,
        "status": "ok" if report.final_result != "BLOCKED" else "blocked",
        "trading_should_pause": report.trading_should_pause,
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result == "BLOCKED":
        raise typer.Exit(code=1)


@app.command("live-limit-order")
def live_limit_order(
    token_id: Annotated[str, typer.Option("--token-id", help="Allowlisted outcome token ID.")],
    side: Annotated[str, typer.Option("--side", help="BUY or SELL.")] = "BUY",
    price: Annotated[str, typer.Option("--price", help="Limit price in [0, 1].")] = "0.01",
    size: Annotated[str, typer.Option("--size", help="Share size capped by settings.")] = "1",
    dry_run: Annotated[bool, typer.Option("--dry-run/--submit")] = True,
    strategy_id: Annotated[str, typer.Option("--strategy-id")] = "operator-tiny-live",
    reason: Annotated[str, typer.Option("--reason")] = "manual tiny live limit order",
    current_position: Annotated[str, typer.Option("--current-position")] = "0",
    current_market_position: Annotated[str, typer.Option("--current-market-position")] = "0",
    daily_pnl: Annotated[str, typer.Option("--daily-pnl")] = "0",
    open_orders_count: Annotated[int, typer.Option("--open-orders-count", min=0)] = 0,
    market_data_age_ms: Annotated[int, typer.Option("--market-data-age-ms", min=0)] = 0,
    i_understand_this_places_real_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-places-real-orders"),
    ] = False,
) -> None:
    """Place or preview one tiny post-only live limit order; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_limit_order(
                settings=settings,
                token_id=token_id,
                side=side,
                price=_parse_decimal(price, "price"),
                size=_parse_decimal(size, "size"),
                dry_run=dry_run,
                strategy_id=strategy_id,
                reason=reason,
                current_position=_parse_decimal(current_position, "current_position"),
                current_market_position=_parse_decimal(
                    current_market_position,
                    "current_market_position",
                ),
                daily_pnl=_parse_decimal(daily_pnl, "daily_pnl"),
                open_orders_count=open_orders_count,
                market_data_age_ms=market_data_age_ms,
                i_understand_this_places_real_orders=(
                    i_understand_this_places_real_orders
                ),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError, ValueError) as error:
        _print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


async def _live_open_orders(
    *,
    settings: AppSettings,
    token_id: str | None,
    order_id: str | None,
    market: str | None,
    i_understand_this_uses_live_account: bool,
) -> dict[str, object]:
    _apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_live_broker(settings=settings, adapter=adapter)
    try:
        result = await broker.get_open_orders(
            token_id=token_id,
            order_id=order_id,
            market=market,
            i_understand_this_uses_live_account=i_understand_this_uses_live_account,
        )
        orders = [_safe_open_order_to_dict(order) for order in result.response or []]
        return {
            "count": len(orders),
            "dry_run": result.dry_run,
            "orders": orders,
            "request": result.request,
            "status": "ok",
        }
    finally:
        await adapter.close()


async def _reconcile_account(
    *,
    settings: AppSettings,
    output_dir: Path,
    i_understand_this_uses_live_account: bool,
) -> ReconciliationResult:
    checked_at = datetime.now(UTC)
    internal = InternalExpectedState(
        last_successful_account_read_at=None,
        updated_at=checked_at,
    )
    actual = await _read_actual_reconciliation_state(
        settings=settings,
        checked_at=checked_at,
        i_understand_this_uses_live_account=i_understand_this_uses_live_account,
    )
    kill_switch = KillSwitch()
    manager = ReconciliationManager(
        safety_pause=KillSwitchSafetyPause(kill_switch),
    )
    result = manager.reconcile(
        ReconciliationInput(
            actual=actual,
            checked_at=checked_at,
            internal=internal,
            live_mode=settings.trading_mode == TradingMode.LIVE,
        )
    )
    return write_reconciliation_reports(
        ReconciliationReportConfig(settings=settings, output_dir=output_dir),
        result,
    )


async def _read_actual_reconciliation_state(
    *,
    settings: AppSettings,
    checked_at: datetime,
    i_understand_this_uses_live_account: bool,
) -> ActualAccountState:
    if settings.trading_mode != TradingMode.LIVE:
        return ActualAccountState(
            account_error_type="data_only_mode",
            account_readable=False,
            geoblock_readable=None,
            open_orders_readable=False,
            positions_readable=False,
            read_at=checked_at,
        )
    if not i_understand_this_uses_live_account:
        return ActualAccountState(
            account_error_type="acknowledgement_required",
            account_readable=False,
            geoblock_readable=None,
            open_orders_readable=False,
            positions_readable=False,
            read_at=checked_at,
        )

    geoblock_readable: bool | None = True
    geoblock_status: str | None = None
    geoblock_error_type: str | None = None
    geoblock = await PreLiveOrderGeoblockCheck().check()
    geoblock_status = geoblock.status
    if geoblock.status == "error":
        geoblock_readable = False
        geoblock_error_type = geoblock.error_type or "geoblock_error"

    _apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    try:
        await adapter.connect()
        try:
            raw_open_orders = await adapter.get_open_orders()
            open_orders = _order_snapshots_from_external(raw_open_orders)
            open_orders_readable = True
        except PolymarketSecureAdapterError:
            open_orders = ()
            open_orders_readable = False

        try:
            raw_positions = await adapter.list_positions(size_threshold=0)
            positions = _position_snapshots_from_external(raw_positions)
            positions_readable = True
        except PolymarketSecureAdapterError:
            positions = ()
            positions_readable = False

        return ActualAccountState(
            account_readable=open_orders_readable and positions_readable,
            geoblock_error_type=geoblock_error_type,
            geoblock_readable=geoblock_readable,
            geoblock_status=geoblock_status,
            open_orders=open_orders,
            open_orders_readable=open_orders_readable,
            positions=positions,
            positions_readable=positions_readable,
            read_at=checked_at,
        )
    except PolymarketSecureAdapterError as error:
        return ActualAccountState(
            account_error_type=type(error).__name__,
            account_readable=False,
            geoblock_error_type=geoblock_error_type,
            geoblock_readable=geoblock_readable,
            geoblock_status=geoblock_status,
            open_orders_readable=False,
            positions_readable=False,
            read_at=checked_at,
        )
    finally:
        await adapter.close()


async def _live_account_status(
    *,
    settings: AppSettings,
    i_understand_this_uses_live_account: bool,
) -> dict[str, object]:
    if settings.trading_mode != TradingMode.LIVE:
        raise LiveBrokerError("live account reads require TRADING_MODE=LIVE.")
    if not i_understand_this_uses_live_account:
        raise LiveBrokerError(
            "live account reads require --redact-secrets or "
            "--i-understand-this-uses-live-account."
        )

    _apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    try:
        await adapter.connect()
        identity = adapter.identity().to_dict()
        collateral = await _read_safe_balance_allowance(adapter)
        positions = await _read_safe_positions(adapter)
        open_orders = await _read_safe_open_orders(adapter)
        return {
            "account_identity": identity,
            "balance_readable": collateral["balance_readable"],
            "approval_readable": collateral["approval_readable"],
            "collateral": collateral,
            "open_order_count": open_orders["count"],
            "open_orders_readable": open_orders["readable"],
            "position_count": positions["count"],
            "positions_preview": positions["positions_preview"],
            "positions_readable": positions["readable"],
            "positions_truncated": positions["truncated"],
            "positive_approval_count": collateral["positive_approval_count"],
            "status": "ok",
        }
    finally:
        await adapter.close()


async def _backtest_jsonl(
    *,
    input_path: Path,
    strategy: str,
    initial_cash: Decimal,
    order_size: Decimal,
    min_edge: Decimal,
    max_order_notional: Decimal,
    max_position_per_token: Decimal,
    max_position_per_market: Decimal,
    max_open_orders: int,
    max_events: int | None,
) -> dict[str, object]:
    events = load_market_data_events_jsonl(input_path, max_events=max_events)
    strategy_instance = _build_research_strategy(
        strategy=strategy,
        order_size=order_size,
        min_edge=min_edge,
    )
    engine = BacktestEngine(
        strategy=strategy_instance,
        config=BacktestConfig(
            initial_cash=initial_cash,
            max_order_notional=max_order_notional,
            max_position_per_token=max_position_per_token,
            max_position_per_market=max_position_per_market,
            max_open_orders=max_open_orders,
        ),
    )
    result = await engine.run(events)
    return result.to_dict()


async def _live_cancel_order(
    *,
    settings: AppSettings,
    order_id: str,
    dry_run: bool,
    i_understand_this_modifies_live_orders: bool,
) -> dict[str, object]:
    _apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_live_broker(settings=settings, adapter=adapter)
    try:
        result = await broker.cancel_order(
            order_id=order_id,
            dry_run=dry_run,
            i_understand_this_modifies_live_orders=i_understand_this_modifies_live_orders,
        )
        return {
            "dry_run": result.dry_run,
            "request": result.request,
            "response": _safe_cancel_response(result.response),
            "status": "ok",
            "submitted": result.submitted,
        }
    finally:
        await adapter.close()


async def _live_cancel_market_orders(
    *,
    settings: AppSettings,
    token_id: str,
    dry_run: bool,
    i_understand_this_modifies_live_orders: bool,
) -> dict[str, object]:
    _apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_live_broker(settings=settings, adapter=adapter)
    try:
        result = await broker.cancel_market_orders(
            token_id=token_id,
            dry_run=dry_run,
            i_understand_this_modifies_live_orders=i_understand_this_modifies_live_orders,
        )
        return {
            "dry_run": result.dry_run,
            "request": result.request,
            "response": _safe_cancel_response(result.response),
            "status": "ok",
            "submitted": result.submitted,
        }
    finally:
        await adapter.close()


async def _live_limit_order(
    *,
    settings: AppSettings,
    token_id: str,
    side: str,
    price: Decimal,
    size: Decimal,
    dry_run: bool,
    strategy_id: str,
    reason: str,
    current_position: Decimal,
    current_market_position: Decimal,
    daily_pnl: Decimal,
    open_orders_count: int,
    market_data_age_ms: int,
    i_understand_this_places_real_orders: bool,
) -> dict[str, object]:
    _apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_tiny_live_order_broker(settings=settings, adapter=adapter)
    try:
        intent = OrderIntent(
            strategy_id=strategy_id,
            token_id=token_id,
            side=side,  # type: ignore[arg-type]
            price=price,
            size=size,
            reason=reason,
            confidence=Decimal("1"),
        )
        result = await broker.place_limit_order(
            intent,
            RiskContext(
                current_position=current_position,
                current_market_position=current_market_position,
                daily_pnl=daily_pnl,
                open_orders_count=open_orders_count,
                market_data_age_ms=market_data_age_ms,
            ),
            dry_run=dry_run,
            post_only=True,
            i_understand_this_places_real_orders=i_understand_this_places_real_orders,
        )
        return {
            "dry_run": result.dry_run,
            "request": result.request,
            "response": _safe_order_response(result.response),
            "status": "ok",
            "submitted": result.submitted,
        }
    finally:
        await adapter.close()


def _build_live_broker(*, settings: AppSettings, adapter: PolymarketSecureAdapter) -> LiveBroker:
    return LiveBroker(
        adapter=adapter,
        risk_engine=RiskEngine(),
        settings=settings,
        allowed_token_ids=settings.polymarket_live_token_allowlist,
    )


def _build_tiny_live_order_broker(
    *,
    settings: AppSettings,
    adapter: PolymarketSecureAdapter,
) -> LiveBroker:
    return LiveBroker(
        adapter=adapter,
        risk_engine=RiskEngine(
            limits=RiskLimits(
                max_order_notional=settings.polymarket_live_max_order_notional,
                max_position_per_token=settings.polymarket_live_max_order_size,
                max_position_per_market=settings.polymarket_live_max_order_size,
                max_open_orders=settings.polymarket_live_max_open_orders,
                allow_live_trading=True,
            )
        ),
        settings=settings,
        allowed_token_ids=settings.polymarket_live_token_allowlist,
    )


async def _paper_trade(
    *,
    token_id: str,
    strategy: str,
    best_bid: Decimal,
    bid_size: Decimal,
    best_ask: Decimal,
    ask_size: Decimal,
    order_size: Decimal,
    min_edge: Decimal,
    initial_cash: Decimal,
) -> dict[str, object]:
    book = LocalOrderBook(token_id=token_id)
    book.apply_snapshot(
        bids=((best_bid, bid_size),),
        asks=((best_ask, ask_size),),
    )
    market_event = _local_market_event(token_id)
    strategy_instance = _build_research_strategy(
        strategy=strategy,
        order_size=order_size,
        min_edge=min_edge,
    )
    intents = await strategy_instance.on_market_event(
        market_event,
        StrategyContext(orderbook=book),
    )
    if not intents:
        return {
            "book": book.snapshot(),
            "intents": [],
            "orders": [],
            "portfolio": None,
            "status": "ok",
        }

    ledger = PositionLedger(cash=initial_cash)
    risk_engine = RiskEngine(
        limits=RiskLimits(
            max_order_notional=initial_cash,
            max_position_per_token=order_size,
            max_position_per_market=order_size,
        )
    )
    broker = PaperBroker(ledger=ledger)
    orders = []
    for intent in intents:
        decision = risk_engine.evaluate(
            intent,
            RiskContext(
                trading_mode=TradingMode.PAPER,
                current_position=ledger.get(intent.token_id).size,
                current_market_position=ledger.get(intent.token_id).size,
                market_data_age_ms=0,
                edge=min_edge,
            ),
        )
        if not decision.approved or decision.adjusted_size is None:
            orders.append(
                {
                    "intent": _intent_to_dict(intent),
                    "risk_decision": {
                        "approved": decision.approved,
                        "reason": decision.reason,
                    },
                }
            )
            continue
        approved = ApprovedOrderIntent(
            intent=intent,
            approved_size=decision.adjusted_size,
            risk_reason=decision.reason,
            approved_at=datetime.now(UTC),
        )
        order = broker.submit_limit_order(approved, book)
        orders.append(
            {
                "intent": _intent_to_dict(intent),
                "order": order.to_dict(),
                "risk_decision": {
                    "approved": decision.approved,
                    "reason": decision.reason,
                },
            }
        )

    mark_price = book.mid or best_bid
    pnl = calculate_portfolio_pnl(ledger, {token_id: mark_price})
    return {
        "book": book.snapshot(),
        "cash": str(ledger.cash),
        "orders": orders,
        "portfolio": {
            "gross_market_value": str(pnl.gross_market_value),
            "realized_pnl": str(pnl.realized_pnl),
            "total_equity": str(pnl.total_equity),
            "unrealized_pnl": str(pnl.unrealized_pnl),
        },
        "positions": {
            position_token_id: {
                "avg_price": str(position.avg_price),
                "size": str(position.size),
            }
            for position_token_id, position in ledger.positions.items()
        },
        "status": "ok",
    }


def _print_error_and_exit(error: Exception) -> None:
    error_payload = {
        "message": str(error),
        "status": "error",
    }
    typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
    raise typer.Exit(code=1) from error


if __name__ == "__main__":
    app()
