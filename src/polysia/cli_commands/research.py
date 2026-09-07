"""Research and evidence-generation CLI commands."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import (
    Annotated,
    Literal,
)

import typer

from polysia.cli_commands import print_error_and_exit
from polysia.config.settings import AppSettings
from polysia.config.structured_logging import configure_logging
from polysia.control.cli import DEFAULT_CONTROL_DATABASE
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
from polysia.monitoring.real_data_shadow_run import (
    RealDataShadowRunConfig,
    build_real_data_shadow_run,
    real_data_shadow_run_filename,
    write_real_data_shadow_run_reports,
)
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
from polysia.storage.control import ControlRepository
from polysia.storage.db import SQLiteDatabase


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
    control_database_path: Annotated[
        Path,
        typer.Option(
            "--control-database-path",
            help="Persisted SHADOW operational-state database.",
        ),
    ] = DEFAULT_CONTROL_DATABASE,
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
        config = ShadowRunConfig(
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
        with SQLiteDatabase(control_database_path) as database:
            report = asyncio.run(
                build_shadow_run(
                    config,
                    control_store=ControlRepository(database.connection),
                )
            )
        formats = normalize_shadow_report_formats(
            json_enabled=json_report,
            markdown_enabled=markdown_report,
            html_enabled=html_report,
        )
    except sqlite3.DatabaseError:
        print_error_and_exit(RuntimeError("Shadow control database failed safely."))
    except ValueError as error:
        print_error_and_exit(error)

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
        print_error_and_exit(error)

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
        print_error_and_exit(error)

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
        print_error_and_exit(error)

    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "status": "ok",
    }
    typer.echo(json.dumps(payload, sort_keys=True))


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
        print_error_and_exit(error)

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


def shadow_historical_replay(
    backup_dir: Annotated[
        Path,
        typer.Option(
            "--backup-dir",
            help="Read-only Helsinki-final backup directory. Never written.",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help="Optional JSON path under artifacts/; not committed to Git.",
        ),
    ] = None,
) -> None:
    """Replay Current Control vs Target Exposure v1 from an immutable backup."""

    from polysia.backtesting.shadow_historical_baseline import (
        HistoricalBaselineError,
        run_backup_research,
    )
    from polysia.storage.immutable_sqlite import ImmutableSqliteError

    try:
        payload = run_backup_research(backup_dir)
    except (HistoricalBaselineError, ImmutableSqliteError, OSError, ValueError) as error:
        print_error_and_exit(error)

    text = json.dumps(payload, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{text}\n", encoding="utf-8")
        payload = {**payload, "output": str(output)}
        text = json.dumps(payload, sort_keys=True)
    typer.echo(text)


def source_benchmark(
    duration_seconds: Annotated[
        int,
        typer.Option("--duration-seconds", min=1, max=1200),
    ] = 600,
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Isolated research-evidence SQLite path. Never the Stage 4B financial DB.",
        ),
    ] = Path("artifacts/research-evidence.sqlite3"),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional sanitized JSON path under artifacts/."),
    ] = None,
    code_sha: Annotated[
        str | None,
        typer.Option("--code-sha", help="Optional deploy SHA recorded with evidence."),
    ] = None,
) -> None:
    """Benchmark public wallet REST sources and official market-state streaming."""

    from polysia.application.services.source_benchmark import run_source_benchmark
    from polysia.cli_commands.research_evidence_cli import (
        build_public_benchmark,
        sanitize_report,
    )

    try:
        payload = asyncio.run(
            build_public_benchmark(
                duration_seconds=duration_seconds,
                database=database,
                code_sha=code_sha,
                runner=run_source_benchmark,
            )
        )
    except (OSError, ValueError, RuntimeError) as error:
        print_error_and_exit(error)
    payload = sanitize_report(payload)
    text = json.dumps(payload, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{text}\n", encoding="utf-8")
        payload = {**payload, "output": str(output)}
        text = json.dumps(payload, sort_keys=True)
    typer.echo(text)


def prospective_replay(
    database: Annotated[
        Path,
        typer.Option("--database"),
    ],
    run_id: Annotated[str, typer.Option("--run-id")],
) -> None:
    """Replay Current Control vs Target Exposure v1 from recorded research evidence."""

    from polysia.backtesting.prospective_replay import replay_recorded_run
    from polysia.cli_commands.research_evidence_cli import sanitize_report
    from polysia.storage.research_evidence import ResearchEvidenceStore, ResearchEvidenceStoreError

    try:
        store = ResearchEvidenceStore(database)
        store.initialize()
        interval = store.load_interval_for_run(run_id)
        if interval is None:
            raise ValueError("no recorded research evidence for run_id")
        result = replay_recorded_run(store, run_id=run_id, interval=interval)
        payload = sanitize_report(
            {
                "control_digest": result.control_digest,
                "invalidated": result.invalidated,
                "interval_validity": interval.validity.value,
                "run_id": run_id,
                "target_digest": result.target_digest,
                "unknown_count": result.unknown_count,
                "control_decisions": [
                    {"evidence_id": evidence_id, "decision": decision.value}
                    for evidence_id, decision in result.control_decisions
                ],
                "target_decisions": [
                    {"evidence_id": evidence_id, "decision": str(decision)}
                    for evidence_id, decision in result.target_decisions
                ],
            }
        )
    except (OSError, ValueError, ResearchEvidenceStoreError) as error:
        print_error_and_exit(error)
    typer.echo(json.dumps(payload, sort_keys=True))


def prospective_collect(
    database: Annotated[
        Path,
        typer.Option("--database"),
    ] = Path("/var/lib/polysia/data/research-evidence.sqlite3"),
    health_report: Annotated[
        Path,
        typer.Option("--health-report"),
    ] = Path("/var/lib/polysia/reports/research-evidence-health.json"),
    report_dir: Annotated[
        Path,
        typer.Option("--report-dir"),
    ] = Path("/var/lib/polysia/reports/research-evidence"),
    window_seconds: Annotated[
        int,
        typer.Option("--window-seconds", min=1, max=1200),
    ] = 600,
    code_sha: Annotated[str | None, typer.Option("--code-sha")] = None,
    cycles: Annotated[int | None, typer.Option("--cycles", min=1)] = None,
) -> None:
    """Run the persistent DATA_ONLY prospective collector."""

    settings = AppSettings()
    configure_logging(settings)
    from datetime import timedelta

    from polysia.application.services.persistent_prospective_collector import (
        PersistentCollectorConfig,
        PersistentProspectiveCollector,
        install_signal_handlers,
    )
    from polysia.cli_commands.research_evidence_cli import build_persistent_public_sources
    from polysia.storage.research_evidence import ResearchEvidenceStore, ResearchWriterLockError

    async def _run() -> None:
        sources, discovery = await build_persistent_public_sources()
        store = ResearchEvidenceStore(database)
        required = discovery["required_source_ids"]
        optional = discovery["optional_source_ids"]
        if not isinstance(required, list) or not isinstance(optional, list):
            raise ValueError("source discovery payload is invalid")
        collector = PersistentProspectiveCollector(
            store,
            sources,
            config=PersistentCollectorConfig(
                window=timedelta(seconds=window_seconds),
                health_path=health_report,
                report_dir=report_dir,
                required_source_ids=tuple(str(item) for item in required),
                optional_source_ids=tuple(str(item) for item in optional),
                code_sha=code_sha,
            ),
        )
        install_signal_handlers(collector)
        await collector.run(cycles=cycles)

    try:
        asyncio.run(_run())
    except ResearchWriterLockError as error:
        print_error_and_exit(error)
    except (OSError, ValueError, RuntimeError) as error:
        print_error_and_exit(error)


def prospective_health(
    health_report: Annotated[
        Path,
        typer.Option("--health-report"),
    ] = Path("/var/lib/polysia/reports/research-evidence-health.json"),
    require_fresh_seconds: Annotated[
        int,
        typer.Option("--require-fresh-seconds", min=1),
    ] = 120,
) -> None:
    """Read the sanitized collector health file without querying the writer database."""

    try:
        age_seconds = time.time() - health_report.stat().st_mtime
        payload = json.loads(health_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print_error_and_exit(error)
    if age_seconds > require_fresh_seconds:
        raise typer.Exit(code=1)
    if not isinstance(payload, dict):
        print_error_and_exit(ValueError("health payload is invalid"))
    if payload.get("fatal") or payload.get("stale") is True:
        raise typer.Exit(code=1)
    from polysia.cli_commands.research_evidence_cli import sanitize_report

    typer.echo(json.dumps(sanitize_report(payload), sort_keys=True))
