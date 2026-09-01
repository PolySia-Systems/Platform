from __future__ import annotations

import asyncio
import json
import signal
import sqlite3
import time
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Never

import typer

from polysia.adapters.polycop import PolyCopCandidateWalletSource
from polysia.adapters.polymarket.copytrading_source import (
    PolymarketCopyTradingSource,
    PolymarketMarketScope,
)
from polysia.adapters.polymarket.public import PolymarketPublicAdapter
from polysia.application.ports.candidate_intelligence import (
    CandidatePipelineBusyError,
    CandidatePipelineLeaseLostError,
)
from polysia.application.services.candidate_intelligence import (
    CandidateIntelligenceError,
    WalletIntelligencePipelineService,
)
from polysia.application.services.candidate_wallet_sync import (
    CandidateWalletSyncError,
    CandidateWalletSyncService,
)
from polysia.application.services.continuous_shadow import (
    ContinuousShadowError,
    ContinuousShadowService,
)
from polysia.application.services.continuous_shadow_failures import (
    FAILURE_CATEGORY_MARKET_READ_FAILED,
    FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
    FAILURE_CATEGORY_SQLITE_BUSY,
    FAILURE_STAGE_REPORT_HEALTH,
    classify_continuous_shadow_failure,
)
from polysia.application.services.copyability_selection import CopyabilitySelectionError
from polysia.application.services.dynamic_live_handoff import (
    DynamicLiveHandoffConfig,
    DynamicLiveHandoffError,
    DynamicLiveHandoffService,
)
from polysia.application.services.dynamic_shadow import DynamicShadowError, DynamicShadowService
from polysia.config.settings import AppSettings, TradingMode
from polysia.deployment.continuous_shadow_migration import (
    migrate_continuous_shadow_database,
)
from polysia.deployment.wallet_intelligence_backup import (
    backup_continuous_shadow_database,
    backup_wallet_intelligence_database,
    backup_wallet_intelligence_state,
    rehearse_continuous_shadow_restore,
    rehearse_latency_telemetry_restore,
    rehearse_wallet_intelligence_restore,
)
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.copytrading.dynamic_shadow import DynamicShadowConfig, DynamicShadowMode
from polysia.domain.wallet_intelligence.copyability_selection import (
    CopyabilityPoolRow,
    SelectionPoolId,
    SelectionStatus,
)
from polysia.monitoring.latency_intelligence.identity import (
    load_runtime_identity,
    probes_enabled,
    telemetry_enabled,
)
from polysia.monitoring.latency_intelligence.policy import LatencyPolicy
from polysia.monitoring.latency_intelligence.probes import (
    POLYMARKET_READ_ENDPOINTS,
    probe_endpoint,
    record_probe,
)
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.monitoring.latency_intelligence.report import (
    build_latency_performance_intelligence,
    insufficient_report,
)
from polysia.monitoring.wallet_intelligence_health import (
    WalletIntelligenceHealthReportError,
    read_wallet_intelligence_health_payload,
    write_candidate_health_report,
    write_wallet_intelligence_health_payload,
)
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.continuous_shadow import (
    ContinuousShadowLeaseRepository,
    ContinuousShadowRepository,
    ContinuousShadowStoreError,
)
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.dynamic_shadow import DynamicShadowRepository, DynamicShadowStoreError
from polysia.storage.latency_telemetry import (
    LatencyTelemetryStore,
    copy_latency_telemetry_from_financial,
    default_latency_telemetry_path,
)
from polysia.storage.wallet_intelligence import CandidateStoreError, WalletIntelligenceRepository

DEFAULT_DATABASE = Path("data/wallet-intelligence.sqlite3")
DEFAULT_CONTINUOUS_SHADOW_DATABASE = Path("data/continuous-shadow.sqlite3")
DEFAULT_BACKUP_DIR = Path("backups/wallet-intelligence")
DEFAULT_HEALTH_REPORT = Path("reports/wallet-intelligence/latest.json")
DEFAULT_CONTINUOUS_SHADOW_HEALTH = Path(
    "reports/wallet-intelligence/continuous-shadow.json"
)
DEFAULT_LATENCY_REPORT = Path(
    "reports/wallet-intelligence/latency-performance-intelligence.json"
)
_RETRYABLE_PERSISTENT_SHADOW_FAILURES = frozenset(
    {
        FAILURE_CATEGORY_MARKET_READ_FAILED,
        FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
        FAILURE_CATEGORY_SQLITE_BUSY,
    }
)


def sync(
    source: Annotated[
        str,
        typer.Option("--source", help="Explicit source adapter id."),
    ] = "polycop",
    database: Annotated[
        Path,
        typer.Option("--database", help="Separate protected wallet-intelligence SQLite file."),
    ] = DEFAULT_DATABASE,
    backup_dir: Annotated[
        Path,
        typer.Option("--backup-dir", help="Protected checksummed backup directory."),
    ] = DEFAULT_BACKUP_DIR,
    health_report: Annotated[
        Path,
        typer.Option("--health-report", help="Sanitized atomic health-report path."),
    ] = DEFAULT_HEALTH_REPORT,
    scheduled_for: Annotated[
        str | None,
        typer.Option("--scheduled-for", help="UTC schedule date (YYYY-MM-DD)."),
    ] = None,
    force_new: Annotated[
        bool,
        typer.Option("--force-new", help="Permit a corrected second snapshot for the same date."),
    ] = False,
    create_backup: Annotated[
        bool,
        typer.Option("--backup/--no-backup", help="Back up each newly accepted snapshot."),
    ] = True,
    backup_keep: Annotated[int, typer.Option("--backup-keep", min=1, max=90)] = 14,
    history_days: Annotated[int, typer.Option("--history-days", min=30)] = 365,
    quarantine_days: Annotated[int, typer.Option("--quarantine-days", min=7)] = 30,
) -> None:
    """Fetch, validate, and atomically promote one complete candidate-wallet snapshot."""
    source_adapter = _source(source)
    repository = WalletIntelligenceRepository(database)
    service = CandidateWalletSyncService(source_adapter, repository)
    pipeline = WalletIntelligencePipelineService(
        source_adapter,
        repository,
        CandidateIntelligenceRepository(database),
        chain="polygon",
    )
    schedule_date = _schedule_date(scheduled_for)
    try:
        outcome = asyncio.run(
            pipeline.sync_source_only(
                scheduled_for=schedule_date,
                force_new=force_new,
                history_days=history_days,
                quarantine_days=quarantine_days,
            )
        )
    except (
        CandidatePipelineBusyError,
        CandidatePipelineLeaseLostError,
        CandidateWalletSyncError,
        CandidateStoreError,
        ValueError,
    ) as error:
        _emit_failed_sync(service, health_report, error)
    except Exception:
        _emit_failed_sync(
            service,
            health_report,
            CandidateWalletSyncError(
                "candidate_sync_failed",
                "Candidate-wallet synchronization failed safely.",
            ),
        )

    backup_payload: dict[str, object] | None = None
    if create_backup:
        try:
            backup = backup_wallet_intelligence_database(
                database,
                backup_dir,
                keep=backup_keep,
            )
            backup_payload = {
                "path": str(backup.backup_path),
                "sha256": backup.sha256,
                "verified": True,
            }
        except Exception as error:
            try:
                report = service.health()
                write_candidate_health_report(report, health_report)
                health_payload: dict[str, object] = report.to_dict()
            except Exception:
                health_payload = {
                    "level": "unavailable",
                    "reasons": ["health_check_failed"],
                }
            typer.echo(
                json.dumps(
                    {
                        "error_code": "backup_failed",
                        "health": health_payload,
                        "message": "Snapshot succeeded but its local backup failed.",
                        "status": "failed",
                    },
                    sort_keys=True,
                ),
                err=True,
            )
            raise typer.Exit(code=1) from error

    try:
        report = service.health()
        write_candidate_health_report(report, health_report)
    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": "health_report_failed",
                    "message": "Snapshot and backup succeeded but health reporting failed.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    payload = outcome.to_dict()
    payload["backup"] = backup_payload
    payload["health"] = report.to_dict()
    typer.echo(json.dumps(payload, sort_keys=True))


def ensure(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    continuous_shadow_database: Annotated[
        Path,
        typer.Option(
            "--continuous-shadow-database",
            help="Standalone Stage 4B SQLite path; backed up when present.",
        ),
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    backup_dir: Annotated[Path, typer.Option("--backup-dir")] = DEFAULT_BACKUP_DIR,
    health_report: Annotated[Path, typer.Option("--health-report")] = DEFAULT_HEALTH_REPORT,
    scheduled_for: Annotated[str | None, typer.Option("--scheduled-for")] = None,
    create_backup: Annotated[bool, typer.Option("--backup/--no-backup")] = True,
    backup_keep: Annotated[int, typer.Option("--backup-keep", min=1, max=90)] = 14,
    history_days: Annotated[int, typer.Option("--history-days", min=30)] = 365,
    quarantine_days: Annotated[int, typer.Option("--quarantine-days", min=7)] = 30,
    intelligence_history_days: Annotated[
        int, typer.Option("--intelligence-history-days", min=365)
    ] = 365,
    fresh_hours: Annotated[int, typer.Option("--fresh-hours", min=1)] = 24,
    stale_hours: Annotated[int, typer.Option("--stale-hours", min=2)] = 36,
    lease_minutes: Annotated[int, typer.Option("--lease-minutes", min=1, max=1440)] = 30,
) -> None:
    """Reuse or refresh Stage 1, then atomically publish Candidate Intelligence."""
    if stale_hours <= fresh_hours:
        raise typer.BadParameter("stale-hours must be greater than fresh-hours")
    source_adapter = _source(source)
    source_store = WalletIntelligenceRepository(database)
    intelligence_store = CandidateIntelligenceRepository(database)
    selection_store = CopyabilitySelectionRepository(database)
    pipeline = WalletIntelligencePipelineService(
        source_adapter,
        source_store,
        intelligence_store,
        chain="polygon",
        selection_store=selection_store,
    )
    try:
        outcome = asyncio.run(
            pipeline.ensure(
                scheduled_for=_schedule_date(scheduled_for),
                fresh_after=timedelta(hours=fresh_hours),
                stale_after=timedelta(hours=stale_hours),
                lease_duration=timedelta(minutes=lease_minutes),
                history_days=history_days,
                quarantine_days=quarantine_days,
                intelligence_history_days=intelligence_history_days,
            )
        )
        backup_payload: dict[str, object] | None = None
        if create_backup:
            backup_result = backup_wallet_intelligence_database(
                database,
                backup_dir,
                keep=backup_keep,
            )
            backup_payload = {
                "path": str(backup_result.backup_path),
                "sha256": backup_result.sha256,
                "verified": True,
            }
            if continuous_shadow_database.is_file():
                shadow_backup = backup_continuous_shadow_database(
                    continuous_shadow_database,
                    backup_dir,
                    keep=backup_keep,
                )
                backup_payload["continuous_shadow_path"] = str(
                    shadow_backup.backup_path
                )
                backup_payload["continuous_shadow_sha256"] = shadow_backup.sha256
        health_payload, _ = _combined_health(
            source_adapter,
            source_store,
            intelligence_store,
            warning_after=timedelta(hours=stale_hours),
            critical_after=timedelta(hours=max(72, stale_hours + 1)),
        )
        write_wallet_intelligence_health_payload(health_payload, health_report)
    except (
        CandidateIntelligenceError,
        CopyabilitySelectionError,
        CandidatePipelineBusyError,
        CandidatePipelineLeaseLostError,
        CandidateWalletSyncError,
        CandidateStoreError,
        ValueError,
    ) as error:
        _emit_failed_pipeline(
            source_adapter,
            source_store,
            intelligence_store,
            health_report,
            error,
        )
    except Exception:
        _emit_failed_pipeline(
            source_adapter,
            source_store,
            intelligence_store,
            health_report,
            CandidateIntelligenceError(
                "wallet_intelligence_pipeline_failed",
                "Wallet-intelligence pipeline failed safely.",
            ),
        )
    payload = outcome.to_dict()
    payload["backup"] = backup_payload
    payload["health"] = health_payload
    typer.echo(json.dumps(payload, sort_keys=True))


def health(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    health_report: Annotated[Path, typer.Option("--health-report")] = DEFAULT_HEALTH_REPORT,
    warning_hours: Annotated[int, typer.Option("--warning-hours", min=1)] = 36,
    critical_hours: Annotated[int, typer.Option("--critical-hours", min=2)] = 72,
) -> None:
    """Inspect freshness and the most recent source-run outcome without exposing wallets."""
    if critical_hours <= warning_hours:
        raise typer.BadParameter("critical-hours must be greater than warning-hours")
    source_adapter = _source(source)
    source_store = WalletIntelligenceRepository(database)
    intelligence_store = CandidateIntelligenceRepository(database)
    try:
        source_store.initialize()
        intelligence_store.initialize()
        payload, exit_code = _combined_health(
            source_adapter,
            source_store,
            intelligence_store,
            warning_after=timedelta(hours=warning_hours),
            critical_after=timedelta(hours=critical_hours),
        )
        write_wallet_intelligence_health_payload(payload, health_report)
    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": "health_check_failed",
                    "message": "Wallet-intelligence health check failed.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(payload, sort_keys=True))
    if exit_code:
        raise typer.Exit(code=exit_code)


def pool(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100_000)] = 100,
    selected_only: Annotated[bool, typer.Option("--selected-only/--all-statuses")] = True,
) -> None:
    """Read a deterministic protected Top-N candidate pool without exposing addresses."""
    source_adapter = _source(source)
    repository = CandidateIntelligenceRepository(database)
    try:
        repository.initialize()
        rows = repository.current_pool(
            source_adapter.source_id,
            limit=limit,
            selected_only=selected_only,
        )
    except (CandidateStoreError, ValueError) as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": "candidate_pool_read_failed",
                    "message": "Candidate pool could not be read safely.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "count": len(rows),
                "rows": [
                    {
                        "candidate_rank": row.candidate_rank,
                        "candidate_status": row.candidate_status.value,
                        "chain": row.chain,
                        "data_readiness_status": row.data_readiness_status.value,
                        "effective_at": row.effective_at.isoformat(),
                        "presence_ratio": format(row.presence_ratio, "f"),
                        "source_rank": row.source_rank,
                        "source_score": None
                        if row.source_score is None
                        else format(row.source_score, "f"),
                        "wallet_id": row.wallet_id,
                    }
                    for row in rows
                ],
                "source_id": source_adapter.source_id,
                "status": "succeeded",
            },
            sort_keys=True,
        )
    )


def selection(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    pool: Annotated[
        str,
        typer.Option(
            "--pool",
            help="SHADOW_ALPHA, SHADOW_STRESS, LIVE_REVIEW_CANDIDATE, REJECTED, or WATCHLIST.",
        ),
    ] = "SHADOW_ALPHA",
    limit: Annotated[int, typer.Option("--limit", min=1, max=100_000)] = 50,
) -> None:
    """Read Stage 3 copyability pools or watchlist rows without exposing addresses."""
    source_adapter = _source(source)
    repository = CopyabilitySelectionRepository(database)
    requested = pool.strip().upper()
    try:
        repository.initialize()
        if requested == SelectionStatus.WATCHLIST.value:
            rows = repository.current_status_rows(
                source_adapter.source_id,
                SelectionStatus.WATCHLIST,
                limit=limit,
            )
        else:
            rows = repository.current_pool(
                source_adapter.source_id,
                SelectionPoolId(requested),
                limit=limit,
            )
    except (CandidateStoreError, ValueError) as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": "copyability_selection_read_failed",
                    "message": "Copyability selection could not be read safely.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "count": len(rows),
                "pool": requested,
                "rows": [_selection_row_payload(row) for row in rows],
                "source_id": source_adapter.source_id,
                "status": "succeeded",
            },
            sort_keys=True,
        )
    )


def shadow_sync(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    mode: Annotated[str, typer.Option("--mode", help="HISTORICAL or FORWARD.")] = "HISTORICAL",
    lookback_hours: Annotated[int, typer.Option("--lookback-hours", min=1, max=720)] = 168,
    lookback_minutes: Annotated[
        int | None,
        typer.Option("--lookback-minutes", min=1, max=43_200),
    ] = None,
    fee_bps: Annotated[str, typer.Option("--fee-bps")] = "200",
    slippage_bps: Annotated[str, typer.Option("--historical-slippage-bps")] = "100",
    historical_delay_ms: Annotated[
        int, typer.Option("--historical-delay-ms", min=0, max=3_600_000)
    ] = 2_000,
    maximum_forward_delay_ms: Annotated[
        int,
        typer.Option("--maximum-forward-delay-ms", min=1, max=3_600_000),
    ] = 30_000,
    maximum_notional: Annotated[str, typer.Option("--maximum-notional")] = "5",
    modeled_liquidity_size: Annotated[
        str,
        typer.Option("--modeled-liquidity-size"),
    ] = "100",
    history_days: Annotated[int, typer.Option("--history-days", min=30, max=3650)] = 365,
) -> None:
    """Backfill or forward-simulate current Stage 3 pools without order authority."""
    source_adapter = _source(source)
    try:
        requested_mode = DynamicShadowMode(mode.strip().upper())
        config = DynamicShadowConfig(
            fee_bps=_decimal_option(fee_bps, "fee-bps"),
            historical_slippage_bps=_decimal_option(slippage_bps, "historical-slippage-bps"),
            historical_delay_ms=historical_delay_ms,
            maximum_forward_delay_ms=maximum_forward_delay_ms,
            maximum_notional=_decimal_option(maximum_notional, "maximum-notional"),
            modeled_liquidity_size=_decimal_option(
                modeled_liquidity_size,
                "modeled-liquidity-size",
            ),
        )
        repository = DynamicShadowRepository(database)
        service = DynamicShadowService(
            repository,
            CandidateIntelligenceRepository(database),
            lambda leaders: PolymarketCopyTradingSource(
                leaders,
                market_scope=PolymarketMarketScope.ALL_VERIFIED,
            ),
            quote_port=PolymarketPublicAdapter(),
            config=config,
        )
        outcome = asyncio.run(
            service.run(
                source_adapter.source_id,
                mode=requested_mode,
                lookback=(
                    timedelta(minutes=lookback_minutes)
                    if lookback_minutes is not None
                    else timedelta(hours=lookback_hours)
                ),
            )
        )
        repository.prune_history(cutoff=datetime.now(UTC) - timedelta(days=history_days))
    except (
        DynamicShadowError,
        DynamicShadowStoreError,
        CandidatePipelineBusyError,
        CandidateStoreError,
        ValueError,
    ) as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": getattr(error, "error_code", "dynamic_shadow_failed"),
                    "message": "Dynamic Shadow failed safely; no order was sent.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(outcome.to_dict(), sort_keys=True))


def shadow_results(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    mode: Annotated[str, typer.Option("--mode", help="HISTORICAL or FORWARD.")] = "FORWARD",
    limit: Annotated[int, typer.Option("--limit", min=1, max=100_000)] = 100,
) -> None:
    """Read current address-free per-wallet Shadow evidence."""
    source_adapter = _source(source)
    try:
        requested_mode = DynamicShadowMode(mode.strip().upper())
        repository = DynamicShadowRepository(database)
        repository.initialize()
        rows = repository.current_wallet_results(
            source_adapter.source_id,
            mode=requested_mode,
            limit=limit,
        )
    except (DynamicShadowStoreError, CandidateStoreError, ValueError) as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": "dynamic_shadow_read_failed",
                    "message": "Dynamic Shadow results could not be read safely.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "count": len(rows),
                "mode": requested_mode.value,
                "rows": [row.to_dict() for row in rows],
                "source_id": source_adapter.source_id,
                "status": "succeeded",
            },
            sort_keys=True,
        )
    )


def portfolio_start(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[
        Path, typer.Option("--source-database")
    ] = DEFAULT_DATABASE,
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    wallet_bankroll: Annotated[str, typer.Option("--wallet-bankroll")] = "100",
    follower_bankroll: Annotated[str, typer.Option("--follower-bankroll")] = "1000",
    maximum_event_notional: Annotated[
        str, typer.Option("--maximum-event-notional")
    ] = "5",
    wallet_maximum_exposure: Annotated[
        str, typer.Option("--wallet-maximum-exposure")
    ] = "100",
    follower_maximum_exposure: Annotated[
        str, typer.Option("--follower-maximum-exposure")
    ] = "500",
    follower_maximum_wallet_exposure: Annotated[
        str, typer.Option("--follower-maximum-wallet-exposure")
    ] = "25",
    follower_maximum_market_exposure: Annotated[
        str, typer.Option("--follower-maximum-market-exposure")
    ] = "100",
    follower_maximum_positions: Annotated[
        int, typer.Option("--follower-maximum-positions", min=1, max=10_000)
    ] = 100,
    maximum_forward_delay_ms: Annotated[
        int, typer.Option("--maximum-forward-delay-ms", min=1, max=3_600_000)
    ] = 300_000,
    maximum_quote_age_ms: Annotated[
        int, typer.Option("--maximum-quote-age-ms", min=1, max=300_000)
    ] = 30_000,
    initial_lookback_minutes: Annotated[
        int, typer.Option("--initial-lookback-minutes", min=1, max=1_440)
    ] = 15,
    overlap_seconds: Annotated[
        int, typer.Option("--overlap-seconds", min=0, max=300)
    ] = 30,
) -> None:
    """Start or idempotently reuse one versioned continuous Shadow experiment."""
    try:
        _require_continuous_shadow_safety()
        service = _continuous_shadow_service(
            source,
            source_database,
            database,
            config=_continuous_shadow_config(
                wallet_bankroll=wallet_bankroll,
                follower_bankroll=follower_bankroll,
                maximum_event_notional=maximum_event_notional,
                wallet_maximum_exposure=wallet_maximum_exposure,
                follower_maximum_exposure=follower_maximum_exposure,
                follower_maximum_wallet_exposure=follower_maximum_wallet_exposure,
                follower_maximum_market_exposure=follower_maximum_market_exposure,
                follower_maximum_positions=follower_maximum_positions,
                maximum_forward_delay_ms=maximum_forward_delay_ms,
                maximum_quote_age_ms=maximum_quote_age_ms,
                initial_lookback_minutes=initial_lookback_minutes,
                overlap_seconds=overlap_seconds,
            ),
        )
        experiment = service.start(_source(source).source_id)
    except (
        ContinuousShadowError,
        ContinuousShadowStoreError,
        CandidateStoreError,
        ValueError,
    ) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(
        json.dumps(
            {"experiment": experiment.to_dict(), "status": "succeeded"},
            sort_keys=True,
        )
    )


def portfolio_sync(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[
        Path, typer.Option("--source-database")
    ] = DEFAULT_DATABASE,
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    health_report: Annotated[
        Path,
        typer.Option("--health-report", help="Sanitized atomic Stage 4B health path."),
    ] = Path("reports/wallet-intelligence/continuous-shadow.json"),
    poll_interval_seconds: Annotated[
        int, typer.Option("--poll-interval-seconds", min=30, max=3_600)
    ] = 60,
    wallet_bankroll: Annotated[str, typer.Option("--wallet-bankroll")] = "100",
    follower_bankroll: Annotated[str, typer.Option("--follower-bankroll")] = "1000",
    maximum_event_notional: Annotated[
        str, typer.Option("--maximum-event-notional")
    ] = "5",
    wallet_maximum_exposure: Annotated[
        str, typer.Option("--wallet-maximum-exposure")
    ] = "100",
    follower_maximum_exposure: Annotated[
        str, typer.Option("--follower-maximum-exposure")
    ] = "500",
    follower_maximum_wallet_exposure: Annotated[
        str, typer.Option("--follower-maximum-wallet-exposure")
    ] = "25",
    follower_maximum_market_exposure: Annotated[
        str, typer.Option("--follower-maximum-market-exposure")
    ] = "100",
    follower_maximum_positions: Annotated[
        int, typer.Option("--follower-maximum-positions", min=1, max=10_000)
    ] = 100,
    maximum_forward_delay_ms: Annotated[
        int, typer.Option("--maximum-forward-delay-ms", min=1, max=3_600_000)
    ] = 300_000,
    maximum_quote_age_ms: Annotated[
        int, typer.Option("--maximum-quote-age-ms", min=1, max=300_000)
    ] = 30_000,
    initial_lookback_minutes: Annotated[
        int, typer.Option("--initial-lookback-minutes", min=1, max=1_440)
    ] = 15,
    overlap_seconds: Annotated[
        int, typer.Option("--overlap-seconds", min=0, max=300)
    ] = 30,
    maximum_selection_age_hours: Annotated[
        int, typer.Option("--maximum-selection-age-hours", min=1, max=168)
    ] = 36,
    loop: Annotated[
        bool,
        typer.Option(
            "--loop",
            help="Keep a fenced persistent worker alive between polls.",
        ),
    ] = False,
) -> None:
    """Poll new leader trades and atomically advance persistent Shadow portfolios."""
    try:
        _require_continuous_shadow_safety()
        service = _continuous_shadow_service(
            source,
            source_database,
            database,
            config=_continuous_shadow_config(
                wallet_bankroll=wallet_bankroll,
                follower_bankroll=follower_bankroll,
                maximum_event_notional=maximum_event_notional,
                wallet_maximum_exposure=wallet_maximum_exposure,
                follower_maximum_exposure=follower_maximum_exposure,
                follower_maximum_wallet_exposure=follower_maximum_wallet_exposure,
                follower_maximum_market_exposure=follower_maximum_market_exposure,
                follower_maximum_positions=follower_maximum_positions,
                maximum_forward_delay_ms=maximum_forward_delay_ms,
                maximum_quote_age_ms=maximum_quote_age_ms,
                initial_lookback_minutes=initial_lookback_minutes,
                overlap_seconds=overlap_seconds,
            ),
            maximum_selection_age=timedelta(hours=maximum_selection_age_hours),
        )
        source_id = _source(source).source_id
        if not loop:
            _emit_portfolio_poll(
                service,
                source_id,
                database,
                health_report,
                poll_interval_seconds,
            )
            return
        running = True

        def _stop(*_unused_signals: object) -> None:
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        while running:
            started = time.monotonic()
            wait_ns: int | None = None
            try:
                _emit_portfolio_poll(
                    service,
                    source_id,
                    database,
                    health_report,
                    poll_interval_seconds,
                )
            except (CandidatePipelineBusyError, CandidatePipelineLeaseLostError) as error:
                typer.echo(
                    json.dumps(
                        {
                            "error_code": getattr(error, "error_code", "lease_busy"),
                            "message": (
                                "Persistent Shadow worker skipped a busy poll; "
                                "no order was sent."
                            ),
                            "status": "skipped",
                        },
                        sort_keys=True,
                    )
                )
            except ContinuousShadowError as error:
                classified = classify_continuous_shadow_failure(
                    error,
                    stage=getattr(error, "processing_stage", "unexpected"),
                )
                if classified.category not in _RETRYABLE_PERSISTENT_SHADOW_FAILURES:
                    raise
                typer.echo(
                    json.dumps(
                        {
                            "error_code": classified.category,
                            "message": "Persistent Shadow worker skipped a transient "
                            "poll; durable prior state was kept and no order was sent.",
                            "processing_stage": classified.stage,
                            "status": "skipped",
                        },
                        sort_keys=True,
                    )
                )
            remaining = poll_interval_seconds - (time.monotonic() - started)
            remaining = _maybe_run_latency_probe(service, remaining)
            if running and remaining > 0:
                sleep_started = time.monotonic()
                time.sleep(remaining)
                wait_ns = int((time.monotonic() - sleep_started) * 1_000_000_000)
            _record_poll_wait(service, wait_ns)
    except (
        ContinuousShadowError,
        ContinuousShadowStoreError,
        CandidatePipelineBusyError,
        CandidatePipelineLeaseLostError,
        CandidateStoreError,
        ValueError,
    ) as error:
        _emit_continuous_shadow_failure(error)


def _emit_portfolio_poll(
    service: ContinuousShadowService,
    source_id: str,
    database: Path,
    health_report: Path,
    poll_interval_seconds: int,
) -> None:
    outcome = asyncio.run(service.poll(source_id))
    payload = outcome.to_dict()
    _flush_latency_telemetry(service, database, health_report)
    observed_at = datetime.now(UTC)
    try:
        report = ContinuousShadowRepository(database).health(
            source_id,
            now=observed_at,
            poll_interval_seconds=poll_interval_seconds,
        )
        health_payload = report.to_dict()
        health_payload["report_refresh"] = {
            "observed_at": observed_at.isoformat(),
            "status": "succeeded",
        }
        write_wallet_intelligence_health_payload(health_payload, health_report)
        payload["health"] = health_payload
        payload["health_refresh"] = health_payload["report_refresh"]
    except (
        sqlite3.DatabaseError,
        ContinuousShadowStoreError,
        WalletIntelligenceHealthReportError,
        OSError,
    ) as error:
        classified = classify_continuous_shadow_failure(
            error,
            stage=FAILURE_STAGE_REPORT_HEALTH,
        )
        refresh_failure: dict[str, object] = {
            "error_code": classified.category,
            "observed_at": observed_at.isoformat(),
            "processing_stage": classified.stage,
            "status": "failed",
        }
        payload["health_refresh"] = refresh_failure
        try:
            last_known_good = read_wallet_intelligence_health_payload(health_report)
        except WalletIntelligenceHealthReportError:
            last_known_good = None
        if last_known_good is not None:
            refresh_failure["artifact_status"] = "preserved_last_known_good"
            payload["health"] = last_known_good
        else:
            refresh_failure["artifact_status"] = "unavailable"
    typer.echo(json.dumps(payload, sort_keys=True))


def portfolio_health(
    health_report: Annotated[
        Path,
        typer.Option(
            "--health-report",
            help="Sanitized atomic Stage 4B health artifact; does not open SQLite.",
        ),
    ] = DEFAULT_CONTINUOUS_SHADOW_HEALTH,
) -> None:
    """Report current operator health from the atomic artifact, not the live database."""
    try:
        payload = read_wallet_intelligence_health_payload(health_report)
    except WalletIntelligenceHealthReportError as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps(payload, sort_keys=True))
    if payload.get("level") == "critical":
        raise typer.Exit(code=2)


def portfolio_results(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Verified snapshot or backup SQLite path; do not use the active worker file.",
        ),
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    experiment_id: Annotated[str | None, typer.Option("--experiment-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10_000)] = 100,
) -> None:
    """Read cumulative evidence from a snapshot without initializing or writing storage."""
    try:
        repository = ContinuousShadowRepository(database)
        if experiment_id is None:
            experiment = repository.active_experiment(_source(source).source_id)
            if experiment is None:
                raise ContinuousShadowStoreError(
                    "Continuous Shadow experiment is unavailable."
                )
            experiment_id = experiment.experiment_id
        payload = repository.results(experiment_id, limit=limit)
    except (
        ContinuousShadowStoreError,
        CandidateStoreError,
        ValueError,
        OSError,
        sqlite3.DatabaseError,
    ) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps(payload, sort_keys=True))


def portfolio_drain(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[
        Path, typer.Option("--source-database")
    ] = DEFAULT_DATABASE,
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
) -> None:
    """Block new entries while retaining exits, marks, and verified settlement."""
    try:
        _require_continuous_shadow_safety()
        experiment = _continuous_shadow_service(
            source, source_database, database, config=ContinuousShadowConfig()
        ).drain(_source(source).source_id)
    except (ContinuousShadowError, ContinuousShadowStoreError, CandidateStoreError) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps({"experiment": experiment.to_dict(), "status": "succeeded"}))


def portfolio_finalize(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[
        Path, typer.Option("--source-database")
    ] = DEFAULT_DATABASE,
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
) -> None:
    """Finalize a drained experiment only after every synthetic position is closed."""
    try:
        _require_continuous_shadow_safety()
        experiment = _continuous_shadow_service(
            source, source_database, database, config=ContinuousShadowConfig()
        ).finalize(_source(source).source_id)
    except (ContinuousShadowError, ContinuousShadowStoreError, CandidateStoreError) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps({"experiment": experiment.to_dict(), "status": "succeeded"}))


def portfolio_migrate(
    legacy_backup: Annotated[
        Path,
        typer.Option(
            "--legacy-backup",
            help="Stopped-worker schema-v4 wallet-intelligence backup to extract.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option("--database", help="New standalone Stage 4B SQLite path."),
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    maintenance: Annotated[
        bool,
        typer.Option(
            "--maintenance",
            help="Acknowledge that the Stage 4B worker is stopped for migration.",
        ),
    ] = False,
    maximum_selection_age_hours: Annotated[
        int, typer.Option("--maximum-selection-age-hours", min=1, max=168)
    ] = 36,
) -> None:
    """Atomically extract legacy Stage 4B state into its single-writer database."""

    try:
        _require_continuous_shadow_safety()
        if not maintenance:
            raise ContinuousShadowStoreError(
                "Continuous Shadow migration requires explicit maintenance mode."
            )
        result = migrate_continuous_shadow_database(
            legacy_backup,
            database,
            maximum_selection_age=timedelta(hours=maximum_selection_age_hours),
        )
    except (ContinuousShadowStoreError, CandidateStoreError, OSError, ValueError) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(
        json.dumps(
            {
                "experiment_id": result.experiment_id,
                "ledger_balanced": result.ledger_balanced,
                "schema_version": result.schema_version,
                "status": "succeeded",
                "table_counts": result.table_counts,
            },
            sort_keys=True,
        )
    )


def runtime_bank(
    source: Annotated[str, typer.Option("--source")] = "polycop",
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    candidate_file: Annotated[
        Path,
        typer.Option("--candidate-file", help="Protected Tiny Live Copy runtime input."),
    ] = Path("data/runtime/candidates.txt"),
    manifest_dir: Annotated[
        Path,
        typer.Option("--manifest-dir", help="Protected versioned handoff evidence directory."),
    ] = Path("data/runtime/candidate-banks"),
    minimum_simulated_events: Annotated[
        int,
        typer.Option("--minimum-simulated-events", min=1),
    ] = 1,
    maximum_unknown_ratio: Annotated[
        str,
        typer.Option("--maximum-unknown-ratio"),
    ] = "0.50",
    maximum_historical_age_days: Annotated[
        int,
        typer.Option("--maximum-historical-age-days", min=1, max=30),
    ] = 8,
) -> None:
    """Publish a protected dynamic bank for a later separately authorized dry-run."""

    try:
        settings = AppSettings()
        if (
            settings.trading_mode is not TradingMode.DATA_ONLY
            or settings.live_trading_enabled
            or settings.polymarket_live_token_allowlist
        ):
            raise DynamicLiveHandoffError(
                "handoff_requires_data_only",
                "Dynamic runtime-bank publication requires fail-closed DATA_ONLY settings.",
            )
        repository = DynamicShadowRepository(database)
        service = DynamicLiveHandoffService(
            repository,
            config=DynamicLiveHandoffConfig(
                minimum_simulated_events=minimum_simulated_events,
                maximum_unknown_ratio=_decimal_option(
                    maximum_unknown_ratio,
                    "maximum-unknown-ratio",
                ),
                maximum_historical_age=timedelta(days=maximum_historical_age_days),
            ),
        )
        outcome = service.prepare(
            _source(source).source_id,
            candidate_file=candidate_file,
            manifest_dir=manifest_dir,
        )
    except (
        DynamicLiveHandoffError,
        DynamicShadowStoreError,
        CandidateStoreError,
        ValueError,
    ) as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": getattr(error, "error_code", "dynamic_runtime_bank_failed"),
                    "message": "Dynamic runtime bank was not published; Live remains disabled.",
                    "status": "failed",
                    "values_redacted": True,
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(outcome.to_dict(), sort_keys=True))


def backup(
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    continuous_shadow_database: Annotated[
        Path,
        typer.Option(
            "--continuous-shadow-database",
            help="Standalone Stage 4B SQLite path; backed up when present.",
        ),
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    backup_dir: Annotated[Path, typer.Option("--backup-dir")] = DEFAULT_BACKUP_DIR,
    keep: Annotated[int, typer.Option("--keep", min=1, max=90)] = 14,
) -> None:
    """Create and verify a protected online backup."""
    try:
        financial, shadow, latency = backup_wallet_intelligence_state(
            database,
            backup_dir,
            continuous_shadow_path=continuous_shadow_database,
            keep=keep,
        )
    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": "backup_failed",
                    "message": "Wallet-intelligence backup failed.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    payload: dict[str, object] = {
        "backup": str(financial.backup_path),
        "sha256": financial.sha256,
        "status": "succeeded",
    }
    if latency is not None:
        payload["latency_backup"] = str(latency.backup_path)
        payload["latency_sha256"] = latency.sha256
    if shadow is not None:
        payload["continuous_shadow_backup"] = str(shadow.backup_path)
        payload["continuous_shadow_sha256"] = shadow.sha256
    typer.echo(json.dumps(payload, sort_keys=True))


def restore_check(
    backup_path: Annotated[Path, typer.Option("--backup", help="Backup to restore and inspect.")],
    working_directory: Annotated[
        Path | None,
        typer.Option(
            "--working-directory",
            help="Protected same-volume scratch directory; defaults beside the backup.",
        ),
    ] = None,
    latency_backup: Annotated[
        Path | None,
        typer.Option(
            "--latency-backup",
            help="Optional isolated latency telemetry backup to restore separately.",
        ),
    ] = None,
    continuous_shadow_backup: Annotated[
        Path | None,
        typer.Option(
            "--continuous-shadow-backup",
            help="Optional standalone Stage 4B backup to restore and verify separately.",
        ),
    ] = None,
) -> None:
    """Perform a non-destructive restore rehearsal into disposable state."""
    try:
        result = rehearse_wallet_intelligence_restore(
            backup_path,
            working_directory=working_directory,
        )
        latency_result = None
        if latency_backup is not None:
            latency_result = rehearse_latency_telemetry_restore(
                latency_backup,
                working_directory=working_directory,
            )
        shadow_result = None
        if continuous_shadow_backup is not None:
            shadow_result = rehearse_continuous_shadow_restore(
                continuous_shadow_backup,
                working_directory=working_directory,
            )
    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "error_code": "restore_check_failed",
                    "message": "Wallet-intelligence restore rehearsal failed.",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from error
    payload: dict[str, object] = {
        "restored_row_count": result.validation.row_count,
        "restored_snapshot_count": result.validation.snapshot_count,
        "candidate_intelligence_schema_version": (
            result.validation.candidate_intelligence_schema_version
        ),
        "copyability_selection_schema_version": (
            result.validation.copyability_selection_schema_version
        ),
        "restored_candidate_pool_count": result.validation.candidate_pool_count,
        "restored_candidate_run_count": result.validation.candidate_run_count,
        "restored_copyability_membership_count": (
            result.validation.copyability_membership_count
        ),
        "restored_copyability_run_count": result.validation.copyability_run_count,
        "dynamic_shadow_schema_version": result.validation.dynamic_shadow_schema_version,
        "restored_dynamic_shadow_run_count": result.validation.dynamic_shadow_run_count,
        "restored_dynamic_shadow_evaluation_count": (
            result.validation.dynamic_shadow_evaluation_count
        ),
        "continuous_shadow_schema_version": result.validation.continuous_shadow_schema_version,
        "restored_continuous_shadow_experiment_count": (
            result.validation.continuous_shadow_experiment_count
        ),
        "restored_continuous_shadow_poll_count": result.validation.continuous_shadow_poll_count,
        "restored_continuous_shadow_event_count": result.validation.continuous_shadow_event_count,
        "restored_continuous_shadow_ledger_count": (
            result.validation.continuous_shadow_ledger_count
        ),
        "schema_version": result.validation.schema_version,
        "sha256": result.sha256,
        "status": "succeeded",
    }
    if latency_result is not None:
        payload["latency_schema_version"] = latency_result.schema_version
        payload["latency_sha256"] = latency_result.sha256
        payload["restored_latency_span_count"] = latency_result.span_count
        payload["restored_latency_measurement_count"] = latency_result.measurement_count
    if shadow_result is not None:
        payload["continuous_shadow_schema_version"] = (
            shadow_result.validation.schema_version
        )
        payload["continuous_shadow_sha256"] = shadow_result.sha256
        payload["restored_continuous_shadow_experiment_count"] = (
            shadow_result.validation.experiment_count
        )
        payload["restored_continuous_shadow_poll_count"] = (
            shadow_result.validation.poll_count
        )
        payload["restored_continuous_shadow_event_count"] = (
            shadow_result.validation.event_count
        )
        payload["restored_continuous_shadow_ledger_count"] = (
            shadow_result.validation.ledger_count
        )
        payload["continuous_shadow_ledger_balanced"] = (
            shadow_result.validation.ledger_balanced
        )
    typer.echo(json.dumps(payload, sort_keys=True))


def _selection_row_payload(row: CopyabilityPoolRow) -> dict[str, object]:
    return {
        "activity_score": None if row.activity_score is None else format(row.activity_score, "f"),
        "alpha_score": None if row.alpha_score is None else format(row.alpha_score, "f"),
        "calculated_at": row.calculated_at.isoformat(),
        "confidence_score": None
        if row.confidence_score is None
        else format(row.confidence_score, "f"),
        "copyability_score": None
        if row.copyability_score is None
        else format(row.copyability_score, "f"),
        "effective_at": row.effective_at.isoformat(),
        "feature_set_version": row.feature_set_version,
        "hedging_risk_score": None
        if row.hedging_risk_score is None
        else format(row.hedging_risk_score, "f"),
        "performance_score": None
        if row.performance_score is None
        else format(row.performance_score, "f"),
        "policy_id": row.policy_id,
        "policy_version": row.policy_version,
        "pool_id": row.pool_id or None,
        "pool_rank": row.pool_rank,
        "ranking_version": row.ranking_version,
        "reasons": list(row.reasons),
        "recent_edge_score": None
        if row.recent_edge_score is None
        else format(row.recent_edge_score, "f"),
        "run_id": row.run_id,
        "stability_score": None
        if row.stability_score is None
        else format(row.stability_score, "f"),
        "status": row.status.value,
        "wallet_id": row.wallet_id,
    }


def _latency_telemetry_store(database: Path) -> LatencyTelemetryStore:
    destination = default_latency_telemetry_path(database)
    with suppress(Exception):
        copy_latency_telemetry_from_financial(database, destination)
    return LatencyTelemetryStore(destination)


def _continuous_shadow_service(
    source: str,
    source_database: Path,
    database: Path,
    *,
    config: ContinuousShadowConfig,
    maximum_selection_age: timedelta = timedelta(hours=36),
) -> ContinuousShadowService:
    _source(source)
    if source_database.resolve() == database.resolve():
        raise ValueError(
            "Continuous Shadow source and financial databases must be separate."
        )
    recorder = None
    if telemetry_enabled():
        recorder = LatencyRecorder(
            _latency_telemetry_store(source_database),
            load_runtime_identity(venue_id="polymarket"),
        )
    return ContinuousShadowService(
        ContinuousShadowRepository(database),
        DynamicShadowRepository(source_database),
        ContinuousShadowLeaseRepository(database),
        lambda leaders: PolymarketCopyTradingSource(
            leaders,
            market_scope=PolymarketMarketScope.ALL_VERIFIED,
        ),
        PolymarketPublicAdapter(),
        config=config,
        maximum_selection_age=maximum_selection_age,
        latency_recorder=recorder,
    )


_PROBE_INDEX = 0


def _flush_latency_telemetry(
    service: object,
    database: Path,
    health_report: Path,
) -> None:
    recorder = getattr(service, "latency_recorder", None)
    if recorder is None:
        return
    try:
        recorder.flush()
        store = getattr(recorder, "store", None)
        if store is None:
            store = _latency_telemetry_store(database)
        report = build_latency_performance_intelligence(store, health=recorder.health())
        write_wallet_intelligence_health_payload(
            report,
            health_report.parent / DEFAULT_LATENCY_REPORT.name,
        )
        try:
            store.mark_artifact_written(written_at=datetime.now(UTC))
        except Exception:
            return
    except Exception:
        try:
            write_wallet_intelligence_health_payload(
                insufficient_report(health=recorder.health()),
                health_report.parent / DEFAULT_LATENCY_REPORT.name,
            )
        except Exception:
            return


def _maybe_run_latency_probe(service: object, remaining: float) -> float:
    global _PROBE_INDEX
    recorder = getattr(service, "latency_recorder", None)
    policy = LatencyPolicy()
    if (
        recorder is None
        or not probes_enabled()
        or remaining < policy.probe_min_remaining_seconds
    ):
        return remaining
    started = time.monotonic()
    try:
        endpoint = POLYMARKET_READ_ENDPOINTS[_PROBE_INDEX % len(POLYMARKET_READ_ENDPOINTS)]
        _PROBE_INDEX += 1
        sample = probe_endpoint(endpoint, policy=policy)
        record_probe(recorder, sample)
        recorder.flush()
    except Exception:
        record_probe_failure = getattr(recorder, "record_probe_outcome", None)
        if record_probe_failure is not None:
            with suppress(Exception):
                record_probe_failure(success=False)
    return remaining - (time.monotonic() - started)


def _record_poll_wait(service: object, wait_ns: int | None) -> None:
    recorder = getattr(service, "latency_recorder", None)
    if recorder is None or wait_ns is None:
        return
    try:
        recorder.record_measurement(
            kind="poll_wait_component_ms",
            value_ns=wait_ns,
            started_at_utc=datetime.now(UTC),
        )
    except Exception:
        return


def _continuous_shadow_config(
    *,
    wallet_bankroll: str,
    follower_bankroll: str,
    maximum_event_notional: str,
    wallet_maximum_exposure: str,
    follower_maximum_exposure: str,
    follower_maximum_wallet_exposure: str,
    follower_maximum_market_exposure: str,
    follower_maximum_positions: int,
    maximum_forward_delay_ms: int,
    maximum_quote_age_ms: int,
    initial_lookback_minutes: int,
    overlap_seconds: int,
) -> ContinuousShadowConfig:
    return ContinuousShadowConfig(
        wallet_bankroll=_decimal_option(wallet_bankroll, "wallet-bankroll"),
        follower_bankroll=_decimal_option(follower_bankroll, "follower-bankroll"),
        maximum_event_notional=_decimal_option(
            maximum_event_notional, "maximum-event-notional"
        ),
        wallet_maximum_exposure=_decimal_option(
            wallet_maximum_exposure, "wallet-maximum-exposure"
        ),
        follower_maximum_exposure=_decimal_option(
            follower_maximum_exposure, "follower-maximum-exposure"
        ),
        follower_maximum_wallet_exposure=_decimal_option(
            follower_maximum_wallet_exposure,
            "follower-maximum-wallet-exposure",
        ),
        follower_maximum_market_exposure=_decimal_option(
            follower_maximum_market_exposure,
            "follower-maximum-market-exposure",
        ),
        follower_maximum_positions=follower_maximum_positions,
        maximum_forward_delay_ms=maximum_forward_delay_ms,
        maximum_quote_age_ms=maximum_quote_age_ms,
        initial_lookback_minutes=initial_lookback_minutes,
        overlap_seconds=overlap_seconds,
    )


def _require_continuous_shadow_safety() -> None:
    settings = AppSettings()
    if settings.trading_mode is not TradingMode.DATA_ONLY or settings.live_trading_enabled:
        raise ContinuousShadowError(
            "Continuous Shadow requires TRADING_MODE=DATA_ONLY and LIVE_TRADING_ENABLED=false."
        )


def _emit_continuous_shadow_failure(error: Exception) -> Never:
    classified = classify_continuous_shadow_failure(error, stage="unexpected")
    error_code = getattr(error, "error_code", None)
    if not isinstance(error_code, str) or not error_code:
        error_code = classified.category
    processing_stage = getattr(error, "processing_stage", None)
    if not isinstance(processing_stage, str) or not processing_stage:
        processing_stage = classified.stage
    typer.echo(
        json.dumps(
            {
                "error_code": error_code,
                "message": "Continuous Shadow failed safely; no order was sent.",
                "processing_stage": processing_stage,
                "status": "failed",
            },
            sort_keys=True,
        ),
        err=True,
    )
    raise typer.Exit(code=1)


def _source(source_id: str) -> PolyCopCandidateWalletSource:
    normalized = source_id.strip().lower()
    if normalized == "polycop":
        return PolyCopCandidateWalletSource()
    raise typer.BadParameter(f"Unsupported candidate-wallet source: {source_id}")


def _decimal_option(value: str, name: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise typer.BadParameter(f"{name} must be decimal") from error
    if not result.is_finite():
        raise typer.BadParameter(f"{name} must be finite")
    return result


def _schedule_date(value: str | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("scheduled-for must use YYYY-MM-DD") from error


def _emit_failed_sync(
    service: CandidateWalletSyncService,
    health_report: Path,
    error: Exception,
) -> Never:
    try:
        report = service.health()
        write_candidate_health_report(report, health_report)
        health_payload: dict[str, object] = report.to_dict()
    except Exception:
        health_payload = {"level": "unavailable", "reasons": ["health_check_failed"]}
    error_code = getattr(error, "error_code", "candidate_sync_failed")
    typer.echo(
        json.dumps(
            {
                "error_code": error_code,
                "health": health_payload,
                "message": str(error),
                "status": "failed",
            },
            sort_keys=True,
        ),
        err=True,
    )
    raise typer.Exit(code=1)


def _combined_health(
    source_adapter: PolyCopCandidateWalletSource,
    source_store: WalletIntelligenceRepository,
    intelligence_store: CandidateIntelligenceRepository,
    *,
    warning_after: timedelta,
    critical_after: timedelta,
) -> tuple[dict[str, object], int]:
    source_report = CandidateWalletSyncService(source_adapter, source_store).health(
        warning_after=warning_after,
        critical_after=critical_after,
    )
    intelligence_store.initialize()
    intelligence_state = intelligence_store.state(source_adapter.source_id)
    payload = source_report.to_dict()
    reasons = list(source_report.reasons)
    level = source_report.level.value
    current = intelligence_state.current_run
    if current is None:
        reasons.append("candidate_pool_unavailable")
        level = "critical"
        candidate_pool: dict[str, object] | None = None
    else:
        candidate_pool = {
            "evaluated_count": current.evaluated_count,
            "feature_set_version": current.key.feature_set_version,
            "ineligible_count": current.ineligible_count,
            "invalid_count": current.invalid_count,
            "last_error_code": intelligence_state.last_error_code,
            "last_run_id": intelligence_state.last_run_id,
            "last_run_status": intelligence_state.last_run_status,
            "partial_count": current.partial_count,
            "policy_id": current.key.policy_id,
            "policy_version": current.key.policy_version,
            "published_at": current.published_at.isoformat(),
            "ranking_version": current.key.ranking_version,
            "ready_count": current.ready_count,
            "run_id": current.run_id,
            "selected_count": current.selected_count,
            "source_snapshot_id": current.key.source_snapshot_id,
            "stale_count": current.stale_count,
            "unknown_count": current.unknown_count,
            "watchlist_count": current.watchlist_count,
        }
        if current.key.source_snapshot_id != source_report.state.current_snapshot_id:
            reasons.append("candidate_pool_behind_source")
            if level == "healthy":
                level = "warning"
        if intelligence_state.last_run_status == "failed":
            reasons.append("latest_candidate_run_failed")
            if level == "healthy":
                level = "warning"
        elif intelligence_state.last_run_status == "running":
            reasons.append("candidate_run_in_progress")
            if level == "healthy":
                level = "warning"
    payload["candidate_pool"] = candidate_pool
    selection_store = CopyabilitySelectionRepository(intelligence_store.path)
    selection_store.initialize()
    selection_state = selection_store.state(source_adapter.source_id)
    current_selection = selection_state.current_run
    if current is None:
        copyability_selection: dict[str, object] | None = None
    elif current_selection is None:
        reasons.append("copyability_selection_unavailable")
        if level == "healthy":
            level = "warning"
        copyability_selection = None
    else:
        copyability_selection = {
            "alpha_count": current_selection.alpha_count,
            "evaluated_count": current_selection.evaluated_count,
            "feature_set_version": current_selection.key.feature_set_version,
            "last_error_code": selection_state.last_error_code,
            "last_run_id": selection_state.last_run_id,
            "last_run_status": selection_state.last_run_status,
            "live_review_count": current_selection.live_review_count,
            "overlap_count": current_selection.overlap_count,
            "policy_id": current_selection.key.policy_id,
            "policy_version": current_selection.key.policy_version,
            "published_at": current_selection.published_at.isoformat(),
            "ranking_version": current_selection.key.ranking_version,
            "rejected_count": current_selection.rejected_count,
            "run_id": current_selection.run_id,
            "stage2_run_id": current_selection.key.stage2_run_id,
            "stress_count": current_selection.stress_count,
            "watchlist_count": current_selection.watchlist_count,
        }
        if current_selection.key.stage2_run_id != current.run_id:
            reasons.append("copyability_selection_behind_stage2")
            if level == "healthy":
                level = "warning"
        if selection_state.last_run_status == "failed":
            reasons.append("latest_copyability_selection_failed")
            if level == "healthy":
                level = "warning"
        if current_selection.live_review_count != 0:
            reasons.append("live_review_candidate_not_empty")
            if level == "healthy":
                level = "warning"
    payload["copyability_selection"] = copyability_selection
    shadow_store = DynamicShadowRepository(intelligence_store.path)
    shadow_store.initialize()
    shadow_health = shadow_store.health(source_adapter.source_id, now=datetime.now(UTC))
    current_shadow = shadow_health.current_run
    payload["dynamic_shadow"] = (
        None
        if current_shadow is None
        else {
            "candidate_count": current_shadow.candidate_count,
            "completed_at": None
            if current_shadow.completed_at is None
            else current_shadow.completed_at.isoformat(),
            "cost_model_version": current_shadow.cost_model_version,
            "event_count": current_shadow.event_count,
            "mode": current_shadow.mode.value,
            "policy_version": current_shadow.policy_version,
            "run_id": current_shadow.run_id,
            "selection_run_id": current_shadow.selection_run_id,
            "simulated_count": current_shadow.simulated_count,
            "unknown_count": current_shadow.unknown_count,
        }
    )
    if current_selection is not None:
        if current_shadow is None:
            reasons.append("dynamic_shadow_unavailable")
            if level == "healthy":
                level = "warning"
        elif current_shadow.selection_run_id != current_selection.run_id:
            reasons.append("dynamic_shadow_behind_selection")
            if level == "healthy":
                level = "warning"
    if current_selection is not None:
        reasons.extend(shadow_health.reasons)
        if shadow_health.level == "warning" and level == "healthy":
            level = "warning"
    payload["level"] = level
    payload["reasons"] = list(dict.fromkeys(reasons))
    return payload, int(level == "critical")


def _emit_failed_pipeline(
    source_adapter: PolyCopCandidateWalletSource,
    source_store: WalletIntelligenceRepository,
    intelligence_store: CandidateIntelligenceRepository,
    health_report: Path,
    error: Exception,
) -> Never:
    try:
        health_payload, _ = _combined_health(
            source_adapter,
            source_store,
            intelligence_store,
            warning_after=timedelta(hours=36),
            critical_after=timedelta(hours=72),
        )
        write_wallet_intelligence_health_payload(health_payload, health_report)
    except Exception:
        health_payload = {
            "level": "unavailable",
            "reasons": ["health_check_failed"],
        }
    if isinstance(error, CandidatePipelineBusyError):
        error_code = "pipeline_busy"
    elif isinstance(error, CandidatePipelineLeaseLostError):
        error_code = "pipeline_lease_lost"
    else:
        error_code = getattr(error, "error_code", "wallet_intelligence_pipeline_failed")
    typer.echo(
        json.dumps(
            {
                "error_code": error_code,
                "health": health_payload,
                "message": "Wallet-intelligence pipeline failed safely.",
                "status": "failed",
            },
            sort_keys=True,
        ),
        err=True,
    )
    raise typer.Exit(code=1)
