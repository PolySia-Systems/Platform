from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Never

import typer

from polysia.adapters.polycop import PolyCopCandidateWalletSource
from polysia.application.services.candidate_wallet_sync import (
    CandidateWalletSyncError,
    CandidateWalletSyncService,
)
from polysia.deployment.wallet_intelligence_backup import (
    backup_wallet_intelligence_database,
    rehearse_wallet_intelligence_restore,
)
from polysia.monitoring.wallet_intelligence_health import write_candidate_health_report
from polysia.storage.wallet_intelligence import CandidateStoreError, WalletIntelligenceRepository

DEFAULT_DATABASE = Path("data/wallet-intelligence.sqlite3")
DEFAULT_BACKUP_DIR = Path("backups/wallet-intelligence")
DEFAULT_HEALTH_REPORT = Path("reports/wallet-intelligence/latest.json")


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
    schedule_date = _schedule_date(scheduled_for)
    try:
        outcome = asyncio.run(
            service.sync(
                scheduled_for=schedule_date,
                force_new=force_new,
                history_days=history_days,
                quarantine_days=quarantine_days,
            )
        )
    except (CandidateWalletSyncError, CandidateStoreError, ValueError) as error:
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
    service = CandidateWalletSyncService(
        _source(source),
        WalletIntelligenceRepository(database),
    )
    try:
        report = service.health(
            warning_after=timedelta(hours=warning_hours),
            critical_after=timedelta(hours=critical_hours),
        )
        write_candidate_health_report(report, health_report)
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
    typer.echo(json.dumps(report.to_dict(), sort_keys=True))
    if report.exit_code:
        raise typer.Exit(code=report.exit_code)


def backup(
    database: Annotated[Path, typer.Option("--database")] = DEFAULT_DATABASE,
    backup_dir: Annotated[Path, typer.Option("--backup-dir")] = DEFAULT_BACKUP_DIR,
    keep: Annotated[int, typer.Option("--keep", min=1, max=90)] = 14,
) -> None:
    """Create and verify a protected online backup."""
    try:
        result = backup_wallet_intelligence_database(database, backup_dir, keep=keep)
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
    typer.echo(
        json.dumps(
            {"backup": str(result.backup_path), "sha256": result.sha256, "status": "succeeded"},
            sort_keys=True,
        )
    )


def restore_check(
    backup_path: Annotated[Path, typer.Option("--backup", help="Backup to restore and inspect.")],
) -> None:
    """Perform a non-destructive restore rehearsal into disposable state."""
    try:
        result = rehearse_wallet_intelligence_restore(backup_path)
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
    typer.echo(
        json.dumps(
            {
                "restored_row_count": result.validation.row_count,
                "restored_snapshot_count": result.validation.snapshot_count,
                "schema_version": result.validation.schema_version,
                "sha256": result.sha256,
                "status": "succeeded",
            },
            sort_keys=True,
        )
    )


def _source(source_id: str) -> PolyCopCandidateWalletSource:
    normalized = source_id.strip().lower()
    if normalized == "polycop":
        return PolyCopCandidateWalletSource()
    raise typer.BadParameter(f"Unsupported candidate-wallet source: {source_id}")


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
