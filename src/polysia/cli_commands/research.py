"""Research and evidence-generation CLI commands."""

from __future__ import annotations

import asyncio
import json
import sqlite3
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
