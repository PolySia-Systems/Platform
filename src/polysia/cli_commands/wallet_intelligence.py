from __future__ import annotations

import asyncio
import hashlib
import json
import signal
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
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
from polysia.application.ports.continuous_shadow import ContinuousSelectionUnavailableError
from polysia.application.services.candidate_intelligence import (
    CandidateIntelligenceError,
    WalletIntelligencePipelineService,
)
from polysia.application.services.candidate_wallet_sync import (
    CandidateWalletSyncError,
    CandidateWalletSyncService,
)
from polysia.application.services.continuous_shadow import (
    CONTINUOUS_SHADOW_LEASE_RESOURCE,
    ContinuousShadowError,
    ContinuousShadowService,
)
from polysia.application.services.continuous_shadow_failures import (
    FAILURE_CATEGORY_ACCOUNTING_BLOCKED,
    FAILURE_CATEGORY_DUPLICATE_PROCESSING,
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
    WalletBackupError,
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


def _sqlite_storage_bytes(path: Path) -> int:
    return sum(
        item.stat().st_size for item in (path, Path(str(path) + "-wal"))
        if item.exists()
    )


def _linux_process_peak_rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmHWM:"):
                parts = line.split()
                if len(parts) == 3 and parts[2] == "kB":
                    return int(parts[1]) * 1024
    except OSError:
        return None
    return None
_RETRYABLE_PERSISTENT_SHADOW_FAILURES = frozenset(
    {
        FAILURE_CATEGORY_MARKET_READ_FAILED,
        FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
        FAILURE_CATEGORY_SQLITE_BUSY,
    }
)
_ACCOUNTING_STOP_FAILURES = frozenset(
    {
        FAILURE_CATEGORY_ACCOUNTING_BLOCKED,
        FAILURE_CATEGORY_DUPLICATE_PROCESSING,
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
    backup_keep: Annotated[int, typer.Option("--backup-keep", min=1, max=90)] = 3,
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
    backup_keep: Annotated[int, typer.Option("--backup-keep", min=1, max=90)] = 3,
    history_days: Annotated[int, typer.Option("--history-days", min=30)] = 365,
    quarantine_days: Annotated[int, typer.Option("--quarantine-days", min=7)] = 30,
    intelligence_history_days: Annotated[
        int, typer.Option("--intelligence-history-days", min=365)
    ] = 365,
    fresh_hours: Annotated[int, typer.Option("--fresh-hours", min=1)] = 20,
    stale_hours: Annotated[int, typer.Option("--stale-hours", min=2)] = 36,
    alpha_pool_size: Annotated[
        int, typer.Option("--alpha-pool-size", min=1, max=500)
    ] = 50,
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
        alpha_size=alpha_pool_size,
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
            financial, shadow, latency = backup_wallet_intelligence_state(
                database,
                backup_dir,
                continuous_shadow_path=continuous_shadow_database,
                keep=backup_keep,
            )
            backup_payload = {
                "path": str(financial.backup_path),
                "sha256": financial.sha256,
                "verified": True,
            }
            if shadow is not None:
                backup_payload["continuous_shadow_path"] = str(shadow.backup_path)
                backup_payload["continuous_shadow_sha256"] = shadow.sha256
            if latency is not None:
                backup_payload["latency_path"] = str(latency.backup_path)
                backup_payload["latency_sha256"] = latency.sha256
        health_payload, _ = _combined_health(
            source_adapter,
            source_store,
            intelligence_store,
            warning_after=timedelta(hours=stale_hours),
            critical_after=timedelta(hours=max(72, stale_hours + 1)),
            refresh_after=timedelta(hours=fresh_hours),
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
    except Exception as error:
        _emit_failed_pipeline(
            source_adapter,
            source_store,
            intelligence_store,
            health_report,
            CandidateIntelligenceError(
                error.error_code if isinstance(error, WalletBackupError)
                else "wallet_intelligence_pipeline_failed",
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


def portfolio_preflight(
    wallet_count: Annotated[int, typer.Option("--wallet-count", min=1, max=40)],
    code_sha: Annotated[str, typer.Option("--code-sha")],
    source_database: Annotated[
        Path, typer.Option("--source-database")
    ] = DEFAULT_DATABASE,
    capacity_evidence_file: Annotated[
        Path | None, typer.Option("--capacity-evidence-file")
    ] = None,
) -> None:
    """Preview recent-active Shadow selection and its evidence before a period."""

    from polysia.adapters.polymarket.copytrading_source import UrllibJsonGetTransport
    from polysia.application.services.active_wallet_selection import select_active_shadow_alpha
    from polysia.cli_commands.research_evidence_cli import (
        _measure_recent_alpha_activity,
        measure_latest_market_availability,
    )
    from polysia.deployment.research_wallet_selection import load_current_polycop_snapshot
    from polysia.domain.copytrading.wallet_capacity import capacity_status, workload_digest

    try:
        _require_continuous_shadow_safety()
        if load_runtime_identity(venue_id="polymarket").deploy_sha != code_sha:
            raise ValueError("Shadow preflight code SHA does not match the running image")
        observed = datetime.now(UTC)
        snapshot = load_current_polycop_snapshot(source_database)
        transport = UrllibJsonGetTransport()
        counts, evidence = asyncio.run(_measure_recent_alpha_activity(
            snapshot.candidates, transport=transport, observed=observed,
            minimum_candidates=wallet_count,
            market_evidence_reader=lambda tokens: measure_latest_market_availability(
                transport, tokens
            ),
        ))
        selected = select_active_shadow_alpha(
            snapshot.candidates, counts, count=wallet_count
        )
        capacity_evidence = None
        if capacity_evidence_file is not None:
            loaded = json.loads(capacity_evidence_file.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("capacity evidence must be a JSON object")
            capacity_evidence = loaded
        config = ContinuousShadowConfig(
            runtime_version="continuous-shadow-runtime-v2",
            code_sha=code_sha, wallet_count=wallet_count,
            selection_policy="shadow-alpha-active-v2",
            selection_activity_counts=counts,
            selection_observed_at=observed,
            selection_preflight_digest=str(evidence["digest"]),
            capacity_evidence=capacity_evidence,
        )
        capacity = capacity_status(
            wallet_count, code_sha=code_sha,
            workload_digest=workload_digest("continuous-shadow", config.capacity_workload()),
            evidence=capacity_evidence,
        )
        typer.echo(json.dumps({
            "version": "shadow-preflight-v1",
            "status": "READY_FOR_PERIOD" if capacity["operational_status"] == "measured"
            else "PENDING_CAPACITY",
            "observed_at": observed.isoformat(),
            "requested_count": wallet_count,
            "selected_count": len(selected),
            "selected_wallet_ids": [item.wallet_id for item in selected],
            "activity_and_market_evidence": evidence,
            "capacity": capacity,
            "proposed_runtime_spec": {
                "runtime_version": config.runtime_version,
                "source_mode": "per-wallet-v2",
                "code_sha": code_sha,
                "wallet_count": wallet_count,
                "selection_policy": config.selection_policy,
                "selection_activity_counts": counts,
                "selection_observed_at": observed.isoformat(),
                "selection_preflight_digest": evidence["digest"],
                "capacity_evidence": capacity_evidence,
            },
        }, sort_keys=True, default=str))
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(json.dumps({
            "version": "shadow-preflight-v1",
            "status": "FAILED",
            "reason": str(error),
        }, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error


def portfolio_prepare(
    preparation_spec: Annotated[Path, typer.Option("--preparation-spec")],
    code_sha: Annotated[str, typer.Option("--code-sha")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    backup_dir: Annotated[Path, typer.Option("--backup-dir")] = DEFAULT_BACKUP_DIR,
    base_runtime_spec: Annotated[
        Path | None, typer.Option("--base-runtime-spec")
    ] = None,
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[Path, typer.Option("--source-database")] = DEFAULT_DATABASE,
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
) -> None:
    """Refresh and screen a bounded cohort before the next DATA_ONLY period."""

    from dataclasses import fields

    from polysia.adapters.polymarket.copytrading_source import UrllibJsonGetTransport
    from polysia.application.services.wallet_preparation import (
        WalletPreparationConfig,
        choose_prepared_cohort,
    )
    from polysia.cli_commands.research_evidence_cli import (
        _measure_recent_alpha_activity,
        measure_latest_market_availability,
    )

    attempts = 0
    preparation_lease = None
    preparation_lease_store = CandidateIntelligenceRepository(source_database)
    try:
        _require_continuous_shadow_safety()
        if load_runtime_identity(venue_id="polymarket").deploy_sha != code_sha:
            raise ValueError("preparation code SHA does not match the running image")
        raw = json.loads(preparation_spec.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) - {item.name for item in fields(
            WalletPreparationConfig
        )}:
            raise ValueError("preparation Spec has unsupported fields")
        policy = WalletPreparationConfig(**raw)
        preparation_lease_store.initialize()
        preparation_lease = preparation_lease_store.acquire_lease(
            "wallet-preparation", owner_id=f"prepare-{uuid.uuid4().hex}",
            acquired_at=datetime.now(UTC), lease_duration=timedelta(minutes=20),
        )
        prior_cached: dict[str, object] = {}
        if output is not None and output.exists():
            with suppress(WalletIntelligenceHealthReportError):
                prior_cached = read_wallet_intelligence_health_payload(output)
        if output is not None:
            write_wallet_intelligence_health_payload({
                "version": "wallet-preparation-v1", "status": "REQUESTED",
                "requested_count": policy.maximum_wallets,
                "next_action": "wait_for_bounded_preparation",
            }, output)
        source_storage_before = _sqlite_storage_bytes(source_database)
        source_adapter = _source(source)
        source_store = WalletIntelligenceRepository(source_database)
        pipeline = WalletIntelligencePipelineService(
            source_adapter, source_store,
            CandidateIntelligenceRepository(source_database),
            chain="polygon",
            selection_store=CopyabilitySelectionRepository(source_database),
            alpha_size=policy.candidate_pool_size,
        )
        while True:
            attempts += 1
            try:
                pipeline_result = asyncio.run(pipeline.ensure(
                    scheduled_for=datetime.now(UTC).date(),
                    fresh_after=timedelta(hours=policy.refresh_hours),
                ))
                break
            except (OSError, ValueError, RuntimeError):
                if attempts >= policy.maximum_attempts:
                    raise
                time.sleep(min(2, attempts))
        if pipeline_result.source_refreshed:
            backup_wallet_intelligence_state(
                source_database, backup_dir,
                continuous_shadow_path=database, keep=3,
            )
        snapshot = DynamicShadowRepository(source_database).current_snapshot(
            source_adapter.source_id
        )
        observed = datetime.now(UTC)
        if observed - snapshot.published_at > timedelta(hours=36):
            raise ValueError("candidate snapshot is stale after preparation")
        repository = ContinuousShadowRepository(database)
        current = (
            repository.active_experiment(source_adapter.source_id)
            if database.exists() else None
        )
        base = current.config if current is not None else ContinuousShadowConfig(
            runtime_version="continuous-shadow-runtime-v2", code_sha=code_sha,
            wallet_count=policy.maximum_wallets, selection_policy="shadow-alpha-ranked-v2",
        )
        if base_runtime_spec is not None:
            base = _load_continuous_shadow_runtime_spec(base_runtime_spec, base)
        base = replace(base, code_sha=code_sha)
        latest = (
            repository.latest_experiment(source_adapter.source_id)
            if database.exists() else None
        )
        expected_latest_id = "none" if latest is None else latest.experiment_id
        cache_identity = hashlib.sha256(json.dumps({
            "policy": raw, "runtime": base.to_dict(),
            "snapshot_digest": snapshot.digest,
            "expected_latest_experiment_id": expected_latest_id,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if output is not None:
            cached = prior_cached
            cached_at = cached.get("observed_at")
            expires_at = cached.get("expires_at")
            if (
                cached.get("cache_identity") == cache_identity
                and cached.get("status") == "PREPARED"
                and isinstance(cached_at, str)
                and isinstance(expires_at, str)
                and datetime.fromisoformat(expires_at) > observed
                and timedelta(0) <= observed - datetime.fromisoformat(cached_at)
                <= timedelta(minutes=30)
            ):
                write_wallet_intelligence_health_payload(cached, output)
                typer.echo(json.dumps(cached, sort_keys=True))
                return
        transport = UrllibJsonGetTransport()
        while True:
            try:
                counts, evidence = asyncio.run(_measure_recent_alpha_activity(
                    snapshot.candidates, transport=transport, observed=observed,
                    candidate_limit=policy.candidate_scan_limit,
                    minimum_candidates=1,
                    market_limit_per_wallet=policy.markets_per_wallet,
                    max_pages_per_wallet=policy.pages_per_wallet,
                    max_requests_per_wallet=policy.requests_per_wallet,
                    max_total_data_requests=policy.total_data_requests,
                    max_total_market_tokens=policy.total_market_tokens,
                    time_budget_seconds=policy.time_budget_seconds,
                    market_evidence_reader=lambda tokens: measure_latest_market_availability(
                        transport, tokens
                    ),
                ))
                break
            except (OSError, ValueError, RuntimeError):
                if attempts >= policy.maximum_attempts:
                    raise
                attempts += 1
                time.sleep(min(2, attempts - 1))
        result = choose_prepared_cohort(
            policy, snapshot, counts, evidence, base, observed_at=observed
        )
        storage_growth = max(0, _sqlite_storage_bytes(source_database) - source_storage_before)
        peak_rss = _linux_process_peak_rss_bytes()
        if storage_growth > policy.maximum_source_storage_growth_mb * 1_048_576:
            raise ValueError("source storage growth budget exceeded")
        if peak_rss is None or peak_rss > policy.maximum_process_rss_mb * 1_048_576:
            raise ValueError("preparation process RSS budget unavailable or exceeded")
        result["source_storage_growth_bytes"] = storage_growth
        result["process_peak_rss_bytes"] = peak_rss
        result["cache_identity"] = cache_identity
        result["preparation_attempts"] = attempts
        result["snapshot_digest"] = snapshot.digest
        result["prepared_for_experiment_id"] = expected_latest_id
        result["expires_at"] = (
            observed + timedelta(minutes=policy.evidence_expiry_minutes)
        ).isoformat()
        if result["status"] == "PREPARED":
            frozen = {
                "snapshot_digest": snapshot.digest,
                "prepared_for_experiment_id": expected_latest_id,
                "proposed_runtime_spec": result["proposed_runtime_spec"],
            }
            result["command_id"] = "prepare-" + hashlib.sha256(json.dumps(
                frozen, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()[:32]
        result["source_last_read_at"] = pipeline_result.snapshot.captured_at.isoformat()
        result["source_accepted_at"] = pipeline_result.snapshot.accepted_at.isoformat()
        result["source_fetched_at"] = pipeline_result.snapshot.captured_at.isoformat()
        result["upstream_data_as_of"] = None
        result["next_source_refresh_at"] = (
            pipeline_result.snapshot.accepted_at + timedelta(hours=policy.refresh_hours)
        ).isoformat()
        result["snapshot_age_seconds"] = max(
            0, int((observed - snapshot.published_at).total_seconds())
        )
        result["progress"] = {
            "source": "complete", "candidate_admission": "complete",
            "activity_screening": "complete",
            "persistence": "prepared_artifact_only",
            "post_t0_executable_evidence": "not_started",
        }
        result["source_refreshed"] = pipeline_result.source_refreshed
        result["source_snapshot_id"] = pipeline_result.snapshot.snapshot_id
        result["source_dataset_digest"] = pipeline_result.snapshot.dataset_digest
        if output is not None:
            write_wallet_intelligence_health_payload(result, output)
    except (OSError, ValueError, RuntimeError) as error:
        blocked = {
            "version": "wallet-preparation-v1", "status": "BLOCKED",
            "reason": str(error), "preparation_attempts": attempts,
            "next_action": "inspect_reason_then_retry_with_bounded_policy",
        }
        if output is not None and preparation_lease is not None:
            write_wallet_intelligence_health_payload(blocked, output)
        typer.echo(json.dumps(blocked, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error
    finally:
        if preparation_lease is not None:
            preparation_lease_store.release_lease(preparation_lease)
    typer.echo(json.dumps(result, sort_keys=True))


def portfolio_capacity_probe(
    preparation_file: Annotated[Path, typer.Option("--preparation-file")],
    duration_seconds: Annotated[
        int, typer.Option("--duration-seconds", min=30, max=180)
    ] = 90,
    poll_interval_seconds: Annotated[
        int, typer.Option("--poll-interval-seconds", min=5, max=60)
    ] = 30,
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[Path, typer.Option("--source-database")] = DEFAULT_DATABASE,
) -> None:
    """Measure the real DATA_ONLY Shadow writer in a disposable store, without admission."""

    from polysia.deployment.shadow_capacity_probe import (
        CountingMarketRead,
        probe_shadow_path,
    )

    try:
        _require_continuous_shadow_safety()
        prepared = read_wallet_intelligence_health_payload(preparation_file)
        if prepared.get("status") not in {
            "PENDING_CAPACITY", "BLOCKED_CAPACITY_ENVELOPE", "LOW_OBSERVABLE_RATE",
            "PREPARED",
        }:
            raise ValueError("capacity probe requires a screened cohort proposal")
        payload = prepared.get("proposed_runtime_spec")
        base = ContinuousShadowConfig(
            runtime_version="continuous-shadow-runtime-v2",
            code_sha=load_runtime_identity(venue_id="polymarket").deploy_sha,
            wallet_count=1, selection_policy="shadow-alpha-ranked-v2",
        )
        config = _parse_continuous_shadow_runtime_spec(payload, base)
        _verify_continuous_shadow_code(config)
        market = CountingMarketRead(PolymarketPublicAdapter())

        def service_factory(path: Path) -> ContinuousShadowService:
            return ContinuousShadowService(
                ContinuousShadowRepository(path),
                DynamicShadowRepository(source_database),
                ContinuousShadowLeaseRepository(path),
                lambda leaders: PolymarketCopyTradingSource(
                    leaders, market_scope=PolymarketMarketScope.ALL_VERIFIED,
                    max_pages=config.source_max_pages,
                    max_requests=config.source_max_requests,
                    max_elapsed_seconds=config.source_timeout_seconds,
                ),
                market,
                config=config,
                maximum_pages_per_wallet=config.maximum_pages_per_wallet,
                maximum_selection_age=timedelta(hours=config.maximum_selection_age_hours),
                automatic_rollover=False,
            )

        result = asyncio.run(probe_shadow_path(
            _source(source).source_id, service_factory,
            config=config, duration_seconds=duration_seconds,
            poll_interval_seconds=poll_interval_seconds,
        ))
        result["market_reads"] = {
            "book_requests": market.book_requests,
            "book_tokens": market.book_tokens,
            "market_requests": market.market_requests,
            "fee_schedule_reads": market.fee_schedule_reads,
        }
        result["code_sha"] = config.code_sha
        from polysia.domain.copytrading.wallet_capacity import workload_digest
        result["workload_digest"] = workload_digest(
            "continuous-shadow", config.capacity_workload()
        )
    except (OSError, ValueError, RuntimeError) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps(result, sort_keys=True))


def portfolio_capabilities() -> None:
    """Expose stable software support without claiming host capacity."""

    from polysia.domain.copytrading.wallet_capacity import (
        CAPACITY_CONTRACT_VERSION,
        SOFTWARE_WALLET_LIMIT,
    )

    typer.echo(json.dumps({
        "version": "shadow-capabilities-v1",
        "software_wallet_limit": SOFTWARE_WALLET_LIMIT,
        "legacy_operational_wallet_limit": 3,
        "capacity_evidence_version": CAPACITY_CONTRACT_VERSION,
        "policies": ["shadow-alpha-ranked-v2", "shadow-alpha-active-v2"],
        "runtime_version": "continuous-shadow-runtime-v2",
        "operational_status": "requires_matching_measured_evidence",
        "trading_mode": "DATA_ONLY",
    }, sort_keys=True))


def portfolio_preview(
    runtime_spec: Annotated[Path, typer.Option("--runtime-spec")],
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[Path, typer.Option("--source-database")] = DEFAULT_DATABASE,
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
) -> None:
    """Preview a versioned config against actual period and candidate state."""

    try:
        _require_continuous_shadow_safety()
        config = _load_continuous_shadow_runtime_spec(runtime_spec, ContinuousShadowConfig())
        _verify_continuous_shadow_code(config)
        service = _continuous_shadow_service(
            source, source_database, database, config=config,
            maximum_selection_age=timedelta(hours=config.maximum_selection_age_hours),
        )
        payload = service.preview_configuration(_source(source).source_id)
    except (OSError, ValueError, ContinuousShadowError, CandidateStoreError) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps(payload, sort_keys=True))


def portfolio_apply(
    runtime_spec: Annotated[Path, typer.Option("--runtime-spec")],
    command_id: Annotated[str, typer.Option("--command-id")],
    expected_latest_experiment_id: Annotated[
        str, typer.Option("--expected-latest-experiment-id")
    ],
    source: Annotated[str, typer.Option("--source")] = "polycop",
    source_database: Annotated[Path, typer.Option("--source-database")] = DEFAULT_DATABASE,
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
) -> None:
    """Apply a reviewed v2 config with durable idempotent receipt and conflict check."""

    try:
        _require_continuous_shadow_safety()
        config = _load_continuous_shadow_runtime_spec(runtime_spec, ContinuousShadowConfig())
        if config.runtime_version != "continuous-shadow-runtime-v2":
            raise ValueError("portfolio-apply requires v2 Shadow runtime")
        _verify_continuous_shadow_code(config)
        service = _continuous_shadow_service(
            source, source_database, database, config=config,
            maximum_selection_age=timedelta(hours=config.maximum_selection_age_hours),
        )
        receipt = service.apply_configuration(
            _source(source).source_id, command_id=command_id,
            expected_latest_experiment_id=expected_latest_experiment_id,
        )
    except (
        OSError, ValueError, ContinuousShadowError, ContinuousShadowStoreError,
        CandidateStoreError,
    ) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps(receipt, sort_keys=True))
    if receipt["disposition"] in {"FAILED", "CONFLICT"}:
        raise typer.Exit(code=1)


def portfolio_command_receipt(
    command_id: Annotated[str, typer.Option("--command-id")],
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
) -> None:
    """Read a durable configuration receipt without touching the active worker."""

    try:
        receipt = ContinuousShadowRepository(database).config_receipt(command_id)
        if receipt is None:
            raise ValueError("Shadow configuration command was not found")
    except (OSError, ValueError, ContinuousShadowStoreError) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps(receipt, sort_keys=True))


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
    runtime_spec: Annotated[
        Path | None,
        typer.Option("--runtime-spec", help="Versioned Shadow period configuration JSON."),
    ] = None,
) -> None:
    """Start or idempotently reuse one versioned continuous Shadow experiment."""
    try:
        _require_continuous_shadow_safety()
        config = _continuous_shadow_config(
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
        )
        if runtime_spec is not None:
            config = _load_continuous_shadow_runtime_spec(runtime_spec, config)
        _verify_continuous_shadow_code(config)
        service = _continuous_shadow_service(
            source,
            source_database,
            database,
            config=config,
            maximum_selection_age=timedelta(hours=config.maximum_selection_age_hours),
        )
        experiment = service.start(_source(source).source_id)
    except (
        ContinuousShadowError,
        ContinuousShadowStoreError,
        ContinuousSelectionUnavailableError,
        CandidateStoreError,
        ValueError,
        OSError,
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
    runtime_spec: Annotated[
        Path | None,
        typer.Option("--runtime-spec", help="Versioned Shadow period configuration JSON."),
    ] = None,
    preparation_file: Annotated[
        Path | None,
        typer.Option("--preparation-file", help="Atomic prepared next-period artifact."),
    ] = None,
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
        config = _continuous_shadow_config(
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
            poll_interval_seconds=poll_interval_seconds,
            maximum_selection_age_hours=maximum_selection_age_hours,
        )
        if runtime_spec is not None:
            config = _load_continuous_shadow_runtime_spec(runtime_spec, config)
        _verify_continuous_shadow_code(config)
        poll_interval_seconds = config.poll_interval_seconds
        service = _continuous_shadow_service(
            source,
            source_database,
            database,
            config=config,
            maximum_selection_age=timedelta(hours=config.maximum_selection_age_hours),
        )
        source_id = _source(source).source_id
        if not loop:
            if preparation_file is None:
                _emit_portfolio_poll(
                    service, source_id, database, health_report, poll_interval_seconds,
                )
            else:
                _emit_coordinated_portfolio_tick(
                    source, source_id, source_database, database, health_report,
                    preparation_file, config,
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
                if preparation_file is None:
                    _emit_portfolio_poll(
                        service, source_id, database, health_report, poll_interval_seconds,
                    )
                else:
                    _emit_coordinated_portfolio_tick(
                        source, source_id, source_database, database, health_report,
                        preparation_file, config,
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
                if classified.category in _ACCOUNTING_STOP_FAILURES:
                    _emit_accounting_invariant_stop(
                        error,
                        classified,
                        service=service,
                        source_id=source_id,
                        database=database,
                        health_report=health_report,
                        poll_interval_seconds=poll_interval_seconds,
                    )
                    return
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
        ContinuousSelectionUnavailableError,
        CandidatePipelineBusyError,
        CandidatePipelineLeaseLostError,
        CandidateStoreError,
        ValueError,
        OSError,
    ) as error:
        if isinstance(error, ContinuousShadowError):
            classified = classify_continuous_shadow_failure(
                error,
                stage=getattr(error, "processing_stage", "unexpected"),
            )
            if classified.category in _ACCOUNTING_STOP_FAILURES:
                _emit_accounting_invariant_stop(
                    error,
                    classified,
                    service=service,
                    source_id=source_id,
                    database=database,
                    health_report=health_report,
                    poll_interval_seconds=poll_interval_seconds,
                )
                return
        _emit_continuous_shadow_failure(error)


def _emit_coordinated_portfolio_tick(
    source: str,
    source_id: str,
    source_database: Path,
    database: Path,
    health_report: Path,
    preparation_file: Path,
    fallback_config: ContinuousShadowConfig,
    *,
    clock: Callable[[], datetime] | None = None,
) -> None:
    from polysia.application.services.continuous_shadow_transition import (
        ContinuousShadowTransition,
        PreparedShadowPeriod,
    )

    store = ContinuousShadowRepository(database)
    store.initialize()
    active = store.active_experiment(source_id)
    if active is not None and active.config.runtime_version == "continuous-shadow-runtime-v2":
        try:
            _verify_continuous_shadow_code(active.config)
        except ValueError:
            payload: dict[str, object] = {
                "status": "BLOCKED_CODE_IDENTITY",
                "experiment_id": active.experiment_id,
                "reason": "active_period_code_sha_differs_from_running_image",
                "next_action": "continue_on_pinned_image_or_close_at_safe_boundary",
            }
            health = store.health(
                source_id, now=datetime.now(UTC),
                poll_interval_seconds=active.config.poll_interval_seconds,
            ).to_dict()
            health["next_transition"] = payload
            write_wallet_intelligence_health_payload(health, health_report)
            typer.echo(json.dumps(payload, sort_keys=True))
            return
    base = fallback_config if active is None else active.config
    plan = None
    preparation_status = "UNAVAILABLE"
    preparation_reason: str | None = None
    if preparation_file.exists():
        try:
            prepared = read_wallet_intelligence_health_payload(preparation_file)
            preparation_status = str(prepared.get("status", "INVALID"))
            preparation_reason = str(prepared.get("reason")) if prepared.get("reason") else None
            if preparation_status == "PREPARED":
                runtime_payload = prepared.get("proposed_runtime_spec")
                plan_config = _parse_continuous_shadow_runtime_spec(runtime_payload, base)
                _verify_continuous_shadow_code(plan_config)
                required = (
                    "command_id", "prepared_for_experiment_id", "snapshot_digest",
                    "expires_at",
                )
                if any(not isinstance(prepared.get(key), str) or not prepared[key]
                       for key in required):
                    raise ValueError("prepared period identity or expiry is missing")
                plan = PreparedShadowPeriod(
                    command_id=str(prepared["command_id"]),
                    expected_latest_experiment_id=str(prepared["prepared_for_experiment_id"]),
                    snapshot_digest=str(prepared["snapshot_digest"]),
                    expires_at=datetime.fromisoformat(str(prepared["expires_at"])),
                    config=plan_config,
                )
        except (WalletIntelligenceHealthReportError, ValueError, TypeError) as error:
            preparation_status = "INVALID"
            preparation_reason = str(error)
    coordinator = ContinuousShadowTransition(
        store, DynamicShadowRepository(source_database),
        lambda effective: _continuous_shadow_service(
            source, source_database, database, config=effective,
            maximum_selection_age=timedelta(hours=effective.maximum_selection_age_hours),
            automatic_rollover=False,
        ),
        **({"clock": clock} if clock is not None else {}),
    )
    payload = asyncio.run(coordinator.tick(source_id, plan))
    payload["preparation_status"] = preparation_status
    if preparation_reason is not None:
        payload["preparation_reason"] = preparation_reason
    observed_at = datetime.now(UTC)
    try:
        report = store.health(
            source_id, now=observed_at,
            poll_interval_seconds=base.poll_interval_seconds,
        )
        health_payload = report.to_dict()
        health_payload["next_transition"] = {
            "status": payload["status"],
            "reason": payload.get("reason"),
            "preparation_status": preparation_status,
            "preparation_reason": preparation_reason,
        }
        write_wallet_intelligence_health_payload(health_payload, health_report)
        payload["health"] = health_payload
    except (sqlite3.DatabaseError, ContinuousShadowStoreError, OSError) as error:
        payload["health_refresh"] = {
            "status": "failed", "error_code": type(error).__name__,
        }
    typer.echo(json.dumps(payload, sort_keys=True))


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


def _emit_accounting_invariant_stop(
    error: ContinuousShadowError,
    classified: object,
    *,
    service: ContinuousShadowService,
    source_id: str,
    database: Path,
    health_report: Path,
    poll_interval_seconds: int,
) -> None:
    _flush_latency_telemetry(service, database, health_report)
    error_code = getattr(error, "error_code", None)
    if not isinstance(error_code, str) or not error_code:
        error_code = getattr(classified, "category", "accounting_blocked")
    processing_stage = getattr(error, "processing_stage", None)
    if not isinstance(processing_stage, str) or not processing_stage:
        processing_stage = getattr(classified, "stage", "pre_poll")
    payload: dict[str, object] = {
        "error_code": error_code,
        "message": (
            "Continuous Shadow stopped after an accounting or publication "
            "invariant failure; durable prior state was kept and no order was sent."
        ),
        "processing_stage": processing_stage,
        "status": "blocked",
    }
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
    except (
        sqlite3.DatabaseError,
        ContinuousShadowStoreError,
        WalletIntelligenceHealthReportError,
        OSError,
    ):
        payload["health_refresh"] = {
            "observed_at": observed_at.isoformat(),
            "status": "failed",
        }
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
    prospective: Annotated[
        bool,
        typer.Option("--prospective", help="Replay durable opportunities on this snapshot."),
    ] = False,
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
        if prospective:
            payload["prospective"] = repository.opportunity_report(experiment_id)
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
    keep: Annotated[int, typer.Option("--keep", min=1, max=90)] = 3,
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
                    "error_code": error.error_code if isinstance(error, WalletBackupError)
                    else "backup_failed",
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


def portfolio_prune_history(
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    maintenance: Annotated[
        bool,
        typer.Option(
            "--maintenance",
            help="Acknowledge that the Stage 4B worker is stopped for history pruning.",
        ),
    ] = False,
    deduplicate: Annotated[bool, typer.Option("--deduplicate/--no-deduplicate")] = True,
) -> None:
    """Prune unchanged and expired mark history through the Stage 4B writer lease."""

    try:
        _require_continuous_shadow_safety()
        if not maintenance:
            raise ContinuousShadowStoreError(
                "Continuous Shadow history pruning requires explicit maintenance mode."
            )
        store = ContinuousShadowRepository(database)
        store.initialize()
        leases = ContinuousShadowLeaseRepository(database)
        leases.initialize()
        lease = leases.acquire_lease(
            CONTINUOUS_SHADOW_LEASE_RESOURCE,
            owner_id="continuous-shadow-maintenance",
            acquired_at=datetime.now(UTC),
            lease_duration=timedelta(minutes=30),
        )
        try:
            result = store.prune_mark_history(now=datetime.now(UTC), deduplicate=deduplicate)
        finally:
            leases.release_lease(lease)
    except (
        ContinuousShadowError,
        ContinuousShadowStoreError,
        CandidatePipelineBusyError,
        CandidateStoreError,
    ) as error:
        _emit_continuous_shadow_failure(error)
    typer.echo(json.dumps({"status": "succeeded", **result}, sort_keys=True))


def capacity(
    database: Annotated[
        Path, typer.Option("--database")
    ] = DEFAULT_CONTINUOUS_SHADOW_DATABASE,
    intelligence_database: Annotated[
        Path, typer.Option("--intelligence-database")
    ] = DEFAULT_DATABASE,
    backup_dir: Annotated[Path, typer.Option("--backup-dir")] = DEFAULT_BACKUP_DIR,
    disk_free_bytes: Annotated[
        int | None,
        typer.Option("--disk-free-bytes", help="Host free bytes from df; optional."),
    ] = None,
) -> None:
    """Report Stage 4B capacity outside the trading critical path."""

    from polysia.deployment.recovery_bundle import capacity_payload
    from polysia.storage.lifecycle_policy import DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY

    _require_continuous_shadow_safety()
    shadow = ContinuousShadowRepository(database)
    if database.is_file():
        shadow.initialize()
        databases = {"continuous-shadow": shadow.capacity_report()}
    else:
        databases = {}
    backup_files = [
        path for path in backup_dir.rglob("*.sqlite3")
        if path.is_file() and not any(
            part.startswith(".bundle-staging-") for part in path.relative_to(backup_dir).parts
        )
    ] if backup_dir.is_dir() else []
    payload = capacity_payload(
        databases=databases,
        backup_count=len(backup_files),
        backup_bytes=sum(path.stat().st_size for path in backup_files),
        disk_free_bytes=disk_free_bytes,
        policy=DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY,
    )
    if intelligence_database.is_file():
        payload["intelligence_bytes"] = intelligence_database.stat().st_size
    typer.echo(json.dumps(payload, sort_keys=True))


def compact_backup(
    source: Annotated[Path, typer.Option("--source", help="Offline SQLite copy to compact.")],
    destination: Annotated[Path, typer.Option("--destination")],
) -> None:
    """VACUUM INTO an offline copy. Never compact the active writer in place."""

    from polysia.deployment.sqlite_backup import compact_sqlite_database

    _require_continuous_shadow_safety()
    if source.resolve() == destination.resolve():
        raise typer.BadParameter("compact-backup requires a separate destination")
    path = compact_sqlite_database(source, destination)
    typer.echo(
        json.dumps({"destination": str(path), "status": "succeeded"}, sort_keys=True)
    )


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
    automatic_rollover: bool = True,
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
            max_pages=config.source_max_pages,
            max_requests=config.source_max_requests,
            max_elapsed_seconds=config.source_timeout_seconds,
        ),
        PolymarketPublicAdapter(),
        config=config,
        maximum_pages_per_wallet=config.maximum_pages_per_wallet,
        maximum_selection_age=maximum_selection_age,
        latency_recorder=recorder,
        automatic_rollover=automatic_rollover,
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
    poll_interval_seconds: int = 60,
    maximum_selection_age_hours: int = 36,
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
        poll_interval_seconds=poll_interval_seconds,
        maximum_selection_age_hours=maximum_selection_age_hours,
    )


def _load_continuous_shadow_runtime_spec(
    path: Path, base: ContinuousShadowConfig
) -> ContinuousShadowConfig:
    """Apply one validated period override; the effective config is persisted at start."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return _parse_continuous_shadow_runtime_spec(payload, base)


def _parse_continuous_shadow_runtime_spec(
    payload: object, base: ContinuousShadowConfig
) -> ContinuousShadowConfig:
    if not isinstance(payload, dict):
        raise ValueError("Continuous Shadow runtime Spec must be a JSON object")
    allowed = {
        "runtime_version", "source_mode", "code_sha", "wallet_count",
        "poll_interval_seconds", "maximum_pages_per_wallet",
        "maximum_selection_age_hours", "period_duration_seconds",
        "period_max_events", "period_max_storage_bytes", "policy_version",
        "source_page_size", "source_max_pages", "source_max_requests",
        "source_timeout_seconds",
        "cost_model_version", "bankroll_version",
    }
    version = payload.get("runtime_version")
    if version == "continuous-shadow-runtime-v2":
        allowed |= {
            "selection_policy", "selection_activity_counts",
            "selection_observed_at", "selection_preflight_digest", "capacity_evidence",
            "wallet_bankroll", "follower_bankroll", "maximum_event_notional",
            "wallet_maximum_exposure", "follower_maximum_exposure",
            "follower_maximum_wallet_exposure", "follower_maximum_market_exposure",
            "follower_maximum_positions", "maximum_forward_delay_ms",
            "maximum_quote_age_ms", "initial_lookback_minutes", "overlap_seconds",
            "negative_cache_ttl_seconds", "price_drift_max_ratio",
        }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            "Unsupported Continuous Shadow runtime field: " + ", ".join(sorted(unknown))
        )
    if version not in {"continuous-shadow-runtime-v1", "continuous-shadow-runtime-v2"}:
        raise ValueError("Continuous Shadow runtime Spec version is unsupported")
    if payload.get("source_mode") != "per-wallet-v2":
        raise ValueError("Only per-wallet-v2 is an admitted Shadow source mode")
    if "code_sha" not in payload:
        raise ValueError("Continuous Shadow runtime Spec requires the running code SHA")
    for field in ("policy_version", "cost_model_version", "bankroll_version"):
        if field in payload and payload[field] != getattr(base, field):
            raise ValueError(f"Continuous Shadow {field} is not a supported policy")
    numeric = (
        "wallet_count", "poll_interval_seconds", "maximum_pages_per_wallet",
        "maximum_selection_age_hours", "period_duration_seconds",
        "period_max_events", "period_max_storage_bytes",
        "source_page_size", "source_max_pages", "source_max_requests",
        "source_timeout_seconds",
    )
    for field in numeric:
        if field in payload and (
            isinstance(payload[field], bool) or not isinstance(payload[field], int)
        ):
            raise ValueError(f"Continuous Shadow {field} must be an integer")
    options = {field: payload[field] for field in numeric if field in payload}
    options["runtime_version"] = version
    if version == "continuous-shadow-runtime-v2":
        if not isinstance(payload.get("selection_policy"), str):
            raise ValueError("v2 Shadow runtime requires selection_policy")
        options["selection_policy"] = payload["selection_policy"]
        counts = payload.get("selection_activity_counts")
        if counts is not None:
            if not isinstance(counts, dict):
                raise ValueError("selection_activity_counts must be an object")
            options["selection_activity_counts"] = dict(counts)
        observed = payload.get("selection_observed_at")
        if observed is not None:
            if not isinstance(observed, str):
                raise ValueError("selection_observed_at must be a UTC timestamp")
            options["selection_observed_at"] = datetime.fromisoformat(
                observed.replace("Z", "+00:00")
            )
        preflight_digest = payload.get("selection_preflight_digest")
        if preflight_digest is not None:
            if not isinstance(preflight_digest, str):
                raise ValueError("selection_preflight_digest must be a SHA-256 string")
            options["selection_preflight_digest"] = preflight_digest
        evidence = payload.get("capacity_evidence")
        if evidence is not None:
            if not isinstance(evidence, dict):
                raise ValueError("capacity_evidence must be an object")
            options["capacity_evidence"] = dict(evidence)
        financial = (
            "wallet_bankroll", "follower_bankroll", "maximum_event_notional",
            "wallet_maximum_exposure", "follower_maximum_exposure",
            "follower_maximum_wallet_exposure", "follower_maximum_market_exposure",
        )
        for field in financial:
            if field in payload:
                if isinstance(payload[field], bool) or not isinstance(
                    payload[field], (str, int)
                ):
                    raise ValueError(f"Continuous Shadow {field} must be decimal text")
                options[field] = Decimal(str(payload[field]))
        for field in (
            "follower_maximum_positions", "maximum_forward_delay_ms",
            "maximum_quote_age_ms", "initial_lookback_minutes", "overlap_seconds",
            "negative_cache_ttl_seconds",
        ):
            if field in payload:
                if isinstance(payload[field], bool) or not isinstance(payload[field], int):
                    raise ValueError(f"Continuous Shadow {field} must be an integer")
                options[field] = payload[field]
        drift = payload.get("price_drift_max_ratio")
        if drift is not None:
            if isinstance(drift, bool) or not isinstance(drift, (str, int)):
                raise ValueError("price_drift_max_ratio must be decimal text")
            options["price_drift_max_ratio"] = Decimal(str(drift))
    if "code_sha" in payload:
        if not isinstance(payload["code_sha"], str):
            raise ValueError("Continuous Shadow code_sha must be a Git SHA string")
        options["code_sha"] = payload["code_sha"]
    return replace(base, **options)


def _verify_continuous_shadow_code(config: ContinuousShadowConfig) -> None:
    if config.code_sha is None:
        return
    actual = load_runtime_identity(venue_id="polymarket").deploy_sha
    if actual != config.code_sha:
        raise ValueError(
            "Continuous Shadow runtime code SHA does not match the running image."
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
    refresh_after: timedelta = timedelta(hours=20),
) -> tuple[dict[str, object], int]:
    source_report = CandidateWalletSyncService(source_adapter, source_store).health(
        warning_after=warning_after,
        critical_after=critical_after,
        refresh_after=refresh_after,
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
