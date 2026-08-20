"""Operational reporting, readiness, and reconciliation CLI commands."""

from __future__ import annotations

import asyncio
import json
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from pathlib import Path
from typing import Annotated

import typer

from polysia import cli_support
from polysia.adapters.polymarket.geoblock import PreLiveOrderGeoblockCheck
from polysia.adapters.polymarket.lifecycle_monitoring import PolymarketLifecycleHealthReader
from polysia.adapters.polymarket.public import PolymarketPublicAdapterError
from polysia.adapters.polymarket.round_trip_reconciliation import (
    PolymarketRoundTripReader,
    PolymarketRoundTripReadError,
)
from polysia.adapters.polymarket.secure import (
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.cli_commands import core, print_error_and_exit
from polysia.config.settings import (
    AppSettings,
    TradingMode,
)
from polysia.config.structured_logging import configure_logging
from polysia.deployment.automation import run_deployment_automation
from polysia.deployment.final_handoff import render_final_handoff_markdown
from polysia.deployment.manifest import build_release_manifest
from polysia.execution.tiny_live_round_trip import AUTHORIZATION_ID
from polysia.monitoring.acceptance_audit import (
    AcceptanceAuditConfig,
    acceptance_report_filename,
    build_acceptance_audit,
    normalize_acceptance_report_formats,
    render_acceptance_audit,
)
from polysia.monitoring.live_round_trip import (
    LiveRoundTripMonitorConfig,
    monitor_live_round_trip,
    write_live_round_trip_monitor_reports,
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
from polysia.monitoring.report import render_operator_report
from polysia.monitoring.runbook import render_operator_runbook_markdown
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
from polysia.risk.kill_switch import KillSwitch


def operator_status() -> None:
    """Print sanitized operator readiness and guardrail status."""
    settings = AppSettings()
    configure_logging(settings)
    status = build_operator_status(settings=settings)
    typer.echo(json.dumps(status.to_dict(), sort_keys=True))


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
        print_error_and_exit(error)

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
        print_error_and_exit(error)

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
    cli_support.apply_secure_env_from_settings(settings)
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
        print_error_and_exit(error)

    typer.echo(json.dumps(report.to_dict(), sort_keys=True))
    if report.status == "blocked":
        raise typer.Exit(code=1)


def monitor_live_round_trip_command(
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
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for sanitized lifecycle reports."),
    ] = Path("release-artifacts/live-round-trip-monitor"),
    stale_after_seconds: Annotated[
        int,
        typer.Option("--stale-after-seconds", min=60),
    ] = 300,
    max_cycles: Annotated[
        int,
        typer.Option("--max-cycles", min=1, max=10),
    ] = 1,
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", min=30),
    ] = 30,
) -> None:
    """Monitor one persisted lifecycle through bounded read-only venue calls."""

    settings = AppSettings()
    configure_logging(settings)
    cli_support.apply_secure_env_from_settings(settings)
    try:
        report = asyncio.run(
            monitor_live_round_trip(
                LiveRoundTripMonitorConfig(
                    database_path=database_path,
                    run_id=run_id,
                    authorization_id=authorization_id,
                    stale_after=timedelta(seconds=stale_after_seconds),
                    max_cycles=max_cycles,
                    interval_seconds=interval_seconds,
                ),
                venue_reader=PolymarketRoundTripReader(),
                health_reader=PolymarketLifecycleHealthReader(),
            )
        )
        artifacts = write_live_round_trip_monitor_reports(report, output_dir)
    except (OSError, ValueError) as error:
        print_error_and_exit(error)

    payload = {
        "alert_codes": sorted({alert.code for cycle in report.cycles for alert in cycle.alerts}),
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "duplicate_alert_count": report.duplicate_alert_count,
        "monitor_status": report.status,
        "new_alert_count": report.new_alert_count,
        "status": "blocked" if report.status == "blocked" else "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.status == "blocked":
        raise typer.Exit(code=1)


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
            selected_market_slug = asyncio.run(core.resolve_monitor_btc_5m_market_slug())
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
        print_error_and_exit(error)

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

    cli_support.apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    try:
        await adapter.connect()
        try:
            raw_open_orders = await adapter.get_open_orders()
            open_orders = cli_support.order_snapshots_from_external(raw_open_orders)
            open_orders_readable = True
        except PolymarketSecureAdapterError:
            open_orders = ()
            open_orders_readable = False

        try:
            raw_positions = await adapter.list_positions(size_threshold=0)
            positions = cli_support.position_snapshots_from_external(raw_positions)
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
