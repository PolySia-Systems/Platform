from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from polysia.deployment.sqlite_backup import (
    BackupResult,
    backup_sqlite_database,
    restore_sqlite_backup,
    verify_sqlite_backup,
)
from polysia.storage.latency_telemetry import (
    LatencyTelemetryStore,
    default_latency_telemetry_path,
)
from polysia.storage.wallet_intelligence import (
    WalletIntelligenceDatabaseValidation,
    WalletIntelligenceRepository,
)

WALLET_INTELLIGENCE_BACKUP_PREFIX = "wallet-intelligence-"
LATENCY_TELEMETRY_BACKUP_PREFIX = "wallet-intelligence-latency-"


@dataclass(frozen=True, slots=True)
class WalletIntelligenceRestoreCheck:
    sha256: str
    validation: WalletIntelligenceDatabaseValidation


def backup_wallet_intelligence_database(
    database_path: Path,
    backup_dir: Path,
    *,
    keep: int = 14,
    now: datetime | None = None,
) -> BackupResult:
    """Validate and back up the protected wallet-intelligence database."""
    WalletIntelligenceRepository(database_path).validate_integrity()
    result = backup_sqlite_database(
        database_path,
        backup_dir,
        keep=keep,
        now=now,
        prefix=WALLET_INTELLIGENCE_BACKUP_PREFIX,
    )
    verify_sqlite_backup(result.backup_path)
    return result


def backup_latency_telemetry_database(
    database_path: Path,
    backup_dir: Path,
    *,
    keep: int = 14,
    now: datetime | None = None,
) -> BackupResult:
    """Back up the isolated latency telemetry database without rewriting it."""

    result = backup_sqlite_database(
        database_path,
        backup_dir,
        keep=keep,
        now=now,
        prefix=LATENCY_TELEMETRY_BACKUP_PREFIX,
    )
    verify_sqlite_backup(result.backup_path)
    return result


def backup_wallet_intelligence_state(
    database_path: Path,
    backup_dir: Path,
    *,
    keep: int = 14,
    now: datetime | None = None,
) -> tuple[BackupResult, BackupResult | None]:
    """Back up the financial database and, when present, the telemetry sidecar."""

    financial = backup_wallet_intelligence_database(
        database_path,
        backup_dir,
        keep=keep,
        now=now,
    )
    latency_path = default_latency_telemetry_path(database_path)
    if not latency_path.is_file():
        return financial, None
    latency = backup_latency_telemetry_database(
        latency_path,
        backup_dir,
        keep=keep,
        now=now,
    )
    return financial, latency


def rehearse_wallet_intelligence_restore(
    backup_path: Path,
    *,
    working_directory: Path | None = None,
) -> WalletIntelligenceRestoreCheck:
    """Restore one backup into disposable state and validate its actual contents."""
    scratch_root = working_directory or backup_path.parent
    scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with TemporaryDirectory(
        prefix="polysia-wallet-restore-",
        dir=scratch_root,
    ) as temporary_directory:
        restored_path = Path(temporary_directory) / "wallet-intelligence.sqlite3"
        sha256 = restore_sqlite_backup(backup_path, restored_path)
        validation = WalletIntelligenceRepository(restored_path).validate_integrity()
    return WalletIntelligenceRestoreCheck(sha256=sha256, validation=validation)


@dataclass(frozen=True, slots=True)
class LatencyTelemetryRestoreCheck:
    sha256: str
    schema_version: int
    span_count: int
    measurement_count: int


def rehearse_latency_telemetry_restore(
    backup_path: Path,
    *,
    working_directory: Path | None = None,
) -> LatencyTelemetryRestoreCheck:
    """Restore one telemetry backup into disposable state and inspect schema."""

    scratch_root = working_directory or backup_path.parent
    scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with TemporaryDirectory(
        prefix="polysia-latency-restore-",
        dir=scratch_root,
    ) as temporary_directory:
        restored_path = Path(temporary_directory) / "wallet-intelligence-latency.sqlite3"
        sha256 = restore_sqlite_backup(backup_path, restored_path)
        store = LatencyTelemetryStore(restored_path)
        span_count = len(store.load_spans(limit=10_000_000))
        measurement_count = len(store.load_measurements(limit=10_000_000))
        connection = sqlite3.connect(restored_path)
        try:
            schema_version = int(
                connection.execute(
                    "SELECT schema_version FROM latency_telemetry_metadata"
                ).fetchone()[0]
            )
        finally:
            connection.close()
    return LatencyTelemetryRestoreCheck(
        sha256=sha256,
        schema_version=schema_version,
        span_count=span_count,
        measurement_count=measurement_count,
    )
