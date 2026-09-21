"""Research and evidence-generation CLI commands."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import (
    TYPE_CHECKING,
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

if TYPE_CHECKING:
    from polysia.application.ports.research_evidence import ResearchObservationSource
    from polysia.deployment.research_experiment_runner import ResearchExperimentRunner


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
    output: Annotated[Path | None, typer.Option("--output")] = None,
    compare: Annotated[
        Path | None,
        typer.Option("--compare", help="Optional baseline report JSON to compare."),
    ] = None,
) -> None:
    """Validate, replay, and economically evaluate one recorded experiment."""

    from polysia.backtesting.prospective_analysis import open_recorded_experiment_store
    from polysia.backtesting.prospective_replay import replay_recorded_experiment
    from polysia.backtesting.replay_report import (
        COMPACT_STDOUT_LIMIT,
        compact_replay_payload,
        compare_replay_reports,
        detailed_replay_payload,
    )
    from polysia.cli_commands.research_evidence_cli import sanitize_report
    from polysia.storage.research_evidence import ResearchEvidenceStoreError

    try:
        with open_recorded_experiment_store(database) as store:
            scoped = replay_recorded_experiment(store, run_id=run_id)
            experiment = store.load_experiment(run_id)
            if experiment is None:
                raise ValueError("recorded experiment not found")
            from polysia.storage.immutable_sqlite import sha256_file

            payload = sanitize_report(
                detailed_replay_payload(
                    scoped,
                    experiment=experiment,
                    run_id=run_id,
                    source_database_sha256=sha256_file(database),
                )
            )
            compact = compact_replay_payload(payload)
            if compare is not None:
                baseline = json.loads(compare.read_text(encoding="utf-8"))
                if not isinstance(baseline, dict):
                    raise ValueError("comparison report must be a JSON object")
                compact["comparison"] = compare_replay_reports(payload, baseline)
    except (OSError, ValueError, ResearchEvidenceStoreError) as error:
        print_error_and_exit(error)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{json.dumps(payload, sort_keys=True)}\n", encoding="utf-8")
        compact = {**compact, "output": str(output)}
    text = json.dumps(compact, sort_keys=True)
    if len(text.encode()) > COMPACT_STDOUT_LIMIT:
        print_error_and_exit(RuntimeError("prospective replay stdout exceeded 5 KiB"))
    typer.echo(text)


def prospective_reanalyze(
    database: Annotated[Path, typer.Option("--database")],
    run_id: Annotated[str, typer.Option("--run-id")],
    analysis_dir: Annotated[
        Path,
        typer.Option("--analysis-dir", help="Directory for additive analysis results."),
    ],
    code_sha: Annotated[str, typer.Option("--code-sha")],
    analysis_id: Annotated[str | None, typer.Option("--analysis-id")] = None,
    hypothesis_file: Annotated[
        Path | None,
        typer.Option("--hypothesis-file", help="Frozen prior hypothesis JSON."),
    ] = None,
    bundle_root: Annotated[Path | None, typer.Option("--bundle-root")] = None,
    compare: Annotated[
        Path | None,
        typer.Option("--compare", help="Optional baseline report JSON to compare."),
    ] = None,
) -> None:
    """Write an immutable reanalysis beside captured evidence without mutating it."""

    from polysia.backtesting.prospective_reanalysis import (
        ProspectiveReanalysisError,
        write_reanalysis,
    )
    from polysia.backtesting.replay_report import COMPACT_STDOUT_LIMIT, compare_replay_reports
    from polysia.cli_commands.research_evidence_cli import sanitize_report
    from polysia.storage.research_evidence import ResearchEvidenceStoreError

    try:
        hypothesis: dict[str, object] | None = None
        if hypothesis_file is not None:
            loaded = json.loads(hypothesis_file.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("hypothesis file must be a JSON object")
            hypothesis = loaded
        summary = write_reanalysis(
            database=database,
            run_id=run_id,
            analysis_code_sha=code_sha,
            analysis_dir=analysis_dir,
            analysis_id=analysis_id,
            hypothesis=hypothesis,
            bundle_root=bundle_root,
        )
        if compare is not None:
            result_path = Path(str(summary["path"])) / "result.json"
            current = json.loads(result_path.read_text(encoding="utf-8"))
            baseline = json.loads(compare.read_text(encoding="utf-8"))
            if not isinstance(current, dict) or not isinstance(baseline, dict):
                raise ValueError("comparison report must be a JSON object")
            summary["comparison"] = compare_replay_reports(current, baseline)
        payload = sanitize_report(dict(summary))
    except (OSError, ValueError, ResearchEvidenceStoreError, ProspectiveReanalysisError) as error:
        print_error_and_exit(error)
    text = json.dumps(payload, sort_keys=True)
    if len(text.encode()) > COMPACT_STDOUT_LIMIT:
        print_error_and_exit(RuntimeError("prospective reanalyze stdout exceeded 5 KiB"))
    typer.echo(text)


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
    experiment_duration_seconds: Annotated[
        int,
        typer.Option("--experiment-duration-seconds", min=600, max=604800),
    ] = 14_400,
    experiment_max_events: Annotated[
        int,
        typer.Option("--experiment-max-events", min=1),
    ] = 750_000,
    experiment_max_bytes: Annotated[
        int,
        typer.Option("--experiment-max-bytes", min=1_048_576),
    ] = 805_306_368,
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
        aliases = discovery["followed_aliases"]
        tokens = discovery["market_tokens"]
        if (
            not isinstance(required, list)
            or not isinstance(optional, list)
            or not isinstance(aliases, list)
            or not isinstance(tokens, list)
        ):
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
                tracked_wallet_aliases=tuple(str(item) for item in aliases),
                tracked_market_tokens=tuple(str(item) for item in tokens),
                code_sha=code_sha,
                experiment_duration=timedelta(seconds=experiment_duration_seconds),
                experiment_max_events=experiment_max_events,
                experiment_max_bytes=experiment_max_bytes,
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
    require_research_eligible: Annotated[
        bool,
        typer.Option("--require-research-eligible"),
    ] = False,
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
    if require_research_eligible and payload.get("research_data_eligible") is not True:
        raise typer.Exit(code=1)
    from polysia.cli_commands.research_evidence_cli import sanitize_report

    typer.echo(json.dumps(sanitize_report(payload), sort_keys=True))


def prospective_finalize(
    database: Annotated[Path, typer.Option("--database")],
    run_id: Annotated[str, typer.Option("--run-id")],
    bundle_root: Annotated[Path, typer.Option("--bundle-root")],
) -> None:
    """Finalize a stopped bounded experiment into verified replayable evidence."""

    from polysia.deployment.research_experiment_bundle import finalize_research_experiment
    from polysia.storage.research_evidence import ResearchEvidenceStoreError

    try:
        bundle = finalize_research_experiment(database, bundle_root, run_id=run_id)
    except (OSError, ValueError, ResearchEvidenceStoreError) as error:
        print_error_and_exit(error)
    typer.echo(
        json.dumps(
            {
                "bundle": str(bundle.path),
                "manifest": str(bundle.manifest_path),
                "outcome": bundle.outcome,
                "run_id": run_id,
                "sha256": bundle.sha256,
                "verified": bundle.verified,
            },
            sort_keys=True,
        )
    )


def prospective_prove(
    work_dir: Annotated[
        Path,
        typer.Option("--work-dir", help="Isolated directory for synthetic proof artifacts."),
    ] = Path("artifacts/offline-research-lab"),
) -> None:
    """Run the deterministic production-path laboratory through real PolySia components."""

    from polysia.backtesting.offline_research_lab import run_offline_proof
    from polysia.backtesting.replay_report import compact_replay_payload
    from polysia.cli_commands.research_evidence_cli import sanitize_report

    try:
        results = asyncio.run(run_offline_proof(work_dir))
    except (OSError, ValueError, RuntimeError) as error:
        print_error_and_exit(error)
    payload = sanitize_report(
        {
            "command": "prospective-prove",
            "scenarios": {
                name: {
                    "bundle_outcome": result.bundle_outcome,
                    "bundle_verified": result.bundle_verified,
                    "replay_hashes": list(result.replay_hashes),
                    "run_id": result.run_id,
                    "source_hash_after": result.source_hash_after,
                    "source_hash_before": result.source_hash_before,
                    **compact_replay_payload(result.report),
                }
                for name, result in results.items()
            },
        }
    )
    typer.echo(json.dumps(payload, sort_keys=True))


def _research_runner() -> ResearchExperimentRunner:
    from collections.abc import Mapping

    from polysia.cli_commands.research_evidence_cli import (
        build_persistent_runner_sources,
        build_persistent_sources_from_aliases,
    )
    from polysia.deployment.research_experiment_runner import (
        ResearchExperimentRunner,
        ResearchRunnerError,
    )
    from polysia.deployment.research_wallet_selection import ResearchWalletSelectionError

    async def source_factory(
        *,
        wallet_count: int | None = None,
        selection_policy: str | None = None,
        **_kwargs: object,
    ) -> tuple[tuple[ResearchObservationSource, ...], Mapping[str, object]]:
        del _kwargs
        try:
            return await build_persistent_runner_sources(
                wallet_count=wallet_count,
                selection_policy=selection_policy,
            )
        except ResearchWalletSelectionError as error:
            raise ResearchRunnerError(str(error)) from error

    async def rebuild_sources(
        aliases: Mapping[str, str],
    ) -> tuple[tuple[ResearchObservationSource, ...], Mapping[str, object]]:
        return await build_persistent_sources_from_aliases(aliases)

    return ResearchExperimentRunner(
        source_factory=source_factory,
        source_rebuilder=rebuild_sources,
    )


def _echo_runner_payload(payload: dict[str, object]) -> None:
    from polysia.backtesting.replay_report import COMPACT_STDOUT_LIMIT
    from polysia.cli_commands.research_evidence_cli import sanitize_report

    text = json.dumps(sanitize_report(dict(payload)), sort_keys=True)
    if len(text.encode()) > COMPACT_STDOUT_LIMIT:
        print_error_and_exit(RuntimeError("prospective-run stdout exceeded 5 KiB"))
    typer.echo(text)


def prospective_run_start(
    state_root: Annotated[
        Path,
        typer.Option("--state-root"),
    ] = Path("/var/lib/polysia/research-run"),
    profile: Annotated[str, typer.Option("--profile")] = "canary",
    code_sha: Annotated[str, typer.Option("--code-sha")] = "",
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    image_sha: Annotated[str | None, typer.Option("--image-sha")] = None,
    spec_file: Annotated[
        Path | None,
        typer.Option("--spec-file", help="Versioned ResearchRunSpec JSON."),
    ] = None,
) -> None:
    """Prepare, collect, verify, and close one isolated research experiment."""

    try:
        spec_payload = _load_run_spec(spec_file)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print_error_and_exit(error)
    if spec_payload is not None:
        profile = str(spec_payload["profile"])
        code_sha = code_sha or str(spec_payload["code_sha"])
        run_id = run_id or (
            str(spec_payload["run_id"]) if spec_payload.get("run_id") is not None else None
        )
        image_sha = image_sha or (
            str(spec_payload["image_sha"]) if spec_payload.get("image_sha") is not None else None
        )
    if not code_sha:
        print_error_and_exit(ValueError("code SHA is required"))
    from polysia.deployment.research_experiment_runner import (
        ResearchRunnerConflictError,
        ResearchRunnerError,
    )
    from polysia.storage.research_evidence import ResearchEvidenceStoreError

    try:
        payload = asyncio.run(
            _research_runner().start(
                state_root,
                profile=profile,
                code_sha=code_sha,
                run_id=run_id,
                image_sha=image_sha,
                spec=spec_payload,
            )
        )
    except ResearchRunnerConflictError as error:
        _echo_runner_payload(error.payload)
        raise typer.Exit(code=1) from error
    except (OSError, ValueError, ResearchRunnerError, ResearchEvidenceStoreError) as error:
        print_error_and_exit(error)
    _echo_runner_payload(payload)


def prospective_run_status(
    state_root: Annotated[
        Path,
        typer.Option("--state-root"),
    ] = Path("/var/lib/polysia/research-run"),
) -> None:
    """Report runner phase and health without mutating the run."""

    from polysia.deployment.research_experiment_runner import ResearchRunnerError

    try:
        payload = _research_runner().status(state_root)
    except (OSError, ValueError, ResearchRunnerError) as error:
        print_error_and_exit(error)
    _echo_runner_payload(payload)


def prospective_run_resume(
    state_root: Annotated[
        Path,
        typer.Option("--state-root"),
    ] = Path("/var/lib/polysia/research-run"),
    profile: Annotated[str, typer.Option("--profile")] = "canary",
    code_sha: Annotated[str, typer.Option("--code-sha")] = "",
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    image_sha: Annotated[str | None, typer.Option("--image-sha")] = None,
    spec_file: Annotated[
        Path | None,
        typer.Option("--spec-file", help="Versioned ResearchRunSpec JSON."),
    ] = None,
) -> None:
    """Resume the first incomplete phase of a frozen research run."""

    try:
        spec_payload = _load_run_spec(spec_file)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print_error_and_exit(error)
    if spec_payload is not None:
        profile = str(spec_payload["profile"])
        code_sha = code_sha or str(spec_payload["code_sha"])
        run_id = run_id or (
            str(spec_payload["run_id"]) if spec_payload.get("run_id") is not None else None
        )
        image_sha = image_sha or (
            str(spec_payload["image_sha"]) if spec_payload.get("image_sha") is not None else None
        )
    if not code_sha:
        print_error_and_exit(ValueError("code SHA is required"))
    from polysia.deployment.research_experiment_runner import (
        ResearchRunnerConflictError,
        ResearchRunnerError,
    )
    from polysia.storage.research_evidence import ResearchEvidenceStoreError

    try:
        payload = asyncio.run(
            _research_runner().resume(
                state_root,
                profile=profile,
                code_sha=code_sha,
                run_id=run_id,
                image_sha=image_sha,
                spec=spec_payload,
            )
        )
    except ResearchRunnerConflictError as error:
        _echo_runner_payload(error.payload)
        raise typer.Exit(code=1) from error
    except (OSError, ValueError, ResearchRunnerError, ResearchEvidenceStoreError) as error:
        print_error_and_exit(error)
    _echo_runner_payload(payload)


def prospective_run_stop(
    state_root: Annotated[
        Path,
        typer.Option("--state-root"),
    ] = Path("/var/lib/polysia/research-run"),
    reason: Annotated[str, typer.Option("--reason")] = "operator_stop",
    command_id: Annotated[str, typer.Option("--command-id")] = "stop",
    expected_revision: Annotated[int | None, typer.Option("--expected-revision")] = None,
) -> None:
    """Request bounded shutdown of the active research runner."""

    from polysia.deployment.research_experiment_runner import ResearchRunnerError

    try:
        payload = _research_runner().request_stop(
            state_root,
            reason=reason,
            command_id=command_id,
            expected_revision=expected_revision,
        )
    except (OSError, ValueError, ResearchRunnerError) as error:
        print_error_and_exit(error)
    _echo_runner_payload(payload)


def prospective_run_verify(
    state_root: Annotated[
        Path,
        typer.Option("--state-root"),
    ] = Path("/var/lib/polysia/research-run"),
    code_sha: Annotated[str | None, typer.Option("--code-sha")] = None,
) -> None:
    """Verify collected evidence and complete or resume finalization."""

    from polysia.deployment.research_experiment_runner import (
        ResearchRunnerConflictError,
        ResearchRunnerError,
    )
    from polysia.storage.research_evidence import ResearchEvidenceStoreError

    try:
        payload = asyncio.run(
            _research_runner().verify(state_root, finalization_code_sha=code_sha)
        )
    except ResearchRunnerConflictError as error:
        _echo_runner_payload(error.payload)
        raise typer.Exit(code=1) from error
    except (OSError, ValueError, ResearchRunnerError, ResearchEvidenceStoreError) as error:
        print_error_and_exit(error)
    _echo_runner_payload(payload)


def prospective_run_result(
    state_root: Annotated[
        Path,
        typer.Option("--state-root"),
    ] = Path("/var/lib/polysia/research-run"),
) -> None:
    """Return the closed research result without rerunning collection."""

    from polysia.deployment.research_experiment_runner import ResearchRunnerError

    try:
        payload = _research_runner().result(state_root)
    except (OSError, ValueError, ResearchRunnerError) as error:
        print_error_and_exit(error)
    _echo_runner_payload(payload)


def _load_run_spec(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    from polysia.deployment.research_run_contract import parse_research_run_spec

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research-run Spec must be a JSON object")
    parsed = parse_research_run_spec(payload)
    return {
        "code_sha": parsed.code_sha,
        "image_sha": parsed.image_sha,
        "profile": parsed.profile,
        "run_id": parsed.run_id,
        "selection_policy": parsed.selection_policy,
        "spec_version": parsed.spec_version,
        "wallet_count": parsed.wallet_count,
    }
