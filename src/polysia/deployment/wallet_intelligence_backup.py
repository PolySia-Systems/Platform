from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from polysia.deployment.recovery_bundle import (
    RecoveryDatabaseRecord,
    assemble_recovery_bundle,
)
from polysia.deployment.sqlite_backup import (
    BackupResult,
    backup_sqlite_database,
    restore_sqlite_backup,
    verify_sqlite_backup,
)
from polysia.storage.continuous_shadow import (
    CONTINUOUS_SHADOW_SCHEMA_VERSION,
    ContinuousShadowRepository,
    ContinuousShadowStoreError,
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
CONTINUOUS_SHADOW_BACKUP_PREFIX = "continuous-shadow-"


@dataclass(frozen=True, slots=True)
class WalletIntelligenceRestoreCheck:
    sha256: str
    validation: WalletIntelligenceDatabaseValidation


@dataclass(frozen=True, slots=True)
class ContinuousShadowDatabaseValidation:
    schema_version: int
    experiment_count: int
    poll_count: int
    event_count: int
    ledger_count: int
    ledger_balanced: bool


@dataclass(frozen=True, slots=True)
class ContinuousShadowRestoreCheck:
    sha256: str
    validation: ContinuousShadowDatabaseValidation


def backup_wallet_intelligence_database(
    database_path: Path,
    backup_dir: Path,
    *,
    keep: int = 3,
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
    keep: int = 3,
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


def backup_continuous_shadow_database(
    database_path: Path,
    backup_dir: Path,
    *,
    keep: int = 3,
    now: datetime | None = None,
) -> BackupResult:
    """Validate and back up the Stage 4B single-writer financial database."""

    _validate_continuous_shadow_database(database_path)
    result = backup_sqlite_database(
        database_path,
        backup_dir,
        keep=keep,
        now=now,
        prefix=CONTINUOUS_SHADOW_BACKUP_PREFIX,
    )
    verify_sqlite_backup(result.backup_path)
    _validate_continuous_shadow_database(result.backup_path)
    return result


def backup_wallet_intelligence_state(
    database_path: Path,
    backup_dir: Path,
    *,
    continuous_shadow_path: Path | None = None,
    keep: int = 3,
    now: datetime | None = None,
) -> tuple[BackupResult, BackupResult | None, BackupResult | None]:
    """Back up intelligence, Stage 4B state, and optional telemetry sidecar."""

    financial = backup_wallet_intelligence_database(
        database_path,
        backup_dir,
        keep=keep,
        now=now,
    )
    shadow = None
    if continuous_shadow_path is not None and continuous_shadow_path.is_file():
        shadow = backup_continuous_shadow_database(
            continuous_shadow_path,
            backup_dir,
            keep=keep,
            now=now,
        )
    latency_path = default_latency_telemetry_path(database_path)
    if not latency_path.is_file():
        _write_recovery_bundle(
            backup_dir,
            created_at=now,
            financial=financial,
            shadow=shadow,
            latency=None,
            keep=keep,
        )
        return financial, shadow, None
    latency = backup_latency_telemetry_database(
        latency_path,
        backup_dir,
        keep=keep,
        now=now,
    )
    _write_recovery_bundle(
        backup_dir,
        created_at=now,
        financial=financial,
        shadow=shadow,
        latency=latency,
        keep=keep,
    )
    return financial, shadow, latency


def _write_recovery_bundle(
    backup_dir: Path,
    *,
    created_at: datetime | None,
    financial: BackupResult,
    shadow: BackupResult | None,
    latency: BackupResult | None,
    keep: int,
) -> Path:
    stamp = created_at or datetime.now(UTC)
    records: list[RecoveryDatabaseRecord] = []
    sources: dict[str, Path] = {}
    experiment_id: str | None = None
    watermark: str | None = None

    def add(
        role: str,
        result: BackupResult,
        schema_version: int | None = None,
        counts: dict[str, object] | None = None,
    ) -> None:
        record = RecoveryDatabaseRecord(
            role=role,
            filename=result.backup_path.name,
            sha256=result.sha256,
            schema_version=schema_version,
            integrity="ok",
            created_at=stamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            size_bytes=result.backup_path.stat().st_size,
            counts=dict(counts or {}),
        )
        records.append(record)
        sources[record.filename] = result.backup_path

    add("wallet-intelligence", financial)
    if shadow is not None:
        schema_version, experiment_id, watermark, counts = _shadow_manifest_fields(
            shadow.backup_path
        )
        add(
            "continuous-shadow",
            shadow,
            schema_version=schema_version,
            counts=counts,
        )
    if latency is not None:
        add("latency-telemetry", latency)
    return assemble_recovery_bundle(
        backup_dir,
        created_at=stamp,
        databases=tuple(records),
        source_files=sources,
        keep=keep,
        experiment_id=experiment_id,
        watermark=watermark,
    )


def _shadow_manifest_fields(
    path: Path,
) -> tuple[int | None, str | None, str | None, dict[str, object]]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=0)
    try:
        schema = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()
        experiment = connection.execute(
            "SELECT experiment_id FROM continuous_shadow_experiments "
            "WHERE lifecycle IN ('RUNNING', 'DRAINING') ORDER BY started_at LIMIT 1"
        ).fetchone()
        checkpoint = connection.execute(
            "SELECT watermark FROM continuous_shadow_checkpoint "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        counts: dict[str, object] = {
            "experiment_count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_experiments"
                ).fetchone()[0]
            ),
            "ledger_count": int(
                connection.execute("SELECT COUNT(*) FROM continuous_shadow_ledger").fetchone()[0]
            ),
            "poll_count": int(
                connection.execute("SELECT COUNT(*) FROM continuous_shadow_poll_runs").fetchone()[0]
            ),
        }
    finally:
        connection.close()
    return (
        None if schema is None else int(schema[0]),
        None if experiment is None else str(experiment[0]),
        None if checkpoint is None else str(checkpoint[0]),
        counts,
    )


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


def rehearse_continuous_shadow_restore(
    backup_path: Path,
    *,
    working_directory: Path | None = None,
) -> ContinuousShadowRestoreCheck:
    """Restore Stage 4B into disposable state and verify ledger and schema."""

    scratch_root = working_directory or backup_path.parent
    scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with TemporaryDirectory(
        prefix="polysia-shadow-restore-",
        dir=scratch_root,
    ) as temporary_directory:
        restored_path = Path(temporary_directory) / "continuous-shadow.sqlite3"
        sha256 = restore_sqlite_backup(backup_path, restored_path)
        validation = _validate_continuous_shadow_database(restored_path)
    return ContinuousShadowRestoreCheck(sha256=sha256, validation=validation)


@dataclass(frozen=True, slots=True)
class LatencyTelemetryRestoreCheck:
    sha256: str
    schema_version: int
    span_count: int
    measurement_count: int


def _validate_continuous_shadow_database(
    database_path: Path,
) -> ContinuousShadowDatabaseValidation:
    if not database_path.is_file():
        raise FileNotFoundError("Continuous Shadow database is unavailable.")
    connection = sqlite3.connect(
        f"{database_path.resolve().as_uri()}?mode=ro",
        uri=True,
        timeout=0,
    )
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ContinuousShadowStoreError(
                "Continuous Shadow SQLite integrity check failed."
            )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ContinuousShadowStoreError(
                "Continuous Shadow foreign-key check failed."
            )
        metadata = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchall()
        if len(metadata) != 1 or int(metadata[0][0]) not in {5, CONTINUOUS_SHADOW_SCHEMA_VERSION}:
            raise ContinuousShadowStoreError(
                "Continuous Shadow schema version is unsupported."
            )
        schema_version = int(metadata[0][0])
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "continuous_shadow_experiments",
                "continuous_shadow_poll_runs",
                "continuous_shadow_event_journal",
                "continuous_shadow_ledger",
            )
        }
        experiments = [
            str(row[0])
            for row in connection.execute(
                "SELECT experiment_id FROM continuous_shadow_experiments"
            ).fetchall()
        ]
    finally:
        connection.close()
    ledger_balanced = True
    if schema_version == CONTINUOUS_SHADOW_SCHEMA_VERSION:
        repository = ContinuousShadowRepository(database_path)
        for experiment_id in experiments:
            accounting = cast(
                dict[str, object],
                repository.results(experiment_id, limit=1)["accounting"],
            )
            ledger_balanced = ledger_balanced and bool(accounting["ledger_balanced"])
    else:
        legacy = sqlite3.connect(
            f"{database_path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=0,
        )
        legacy.row_factory = sqlite3.Row
        try:
            from polysia.storage.continuous_shadow import _ledger_balanced

            for experiment_id in experiments:
                ledger_balanced = ledger_balanced and _ledger_balanced(
                    legacy, experiment_id
                )
        finally:
            legacy.close()
    if not ledger_balanced:
        raise ContinuousShadowStoreError("Continuous Shadow ledger identity is unbalanced.")
    return ContinuousShadowDatabaseValidation(
        schema_version=schema_version,
        experiment_count=counts["continuous_shadow_experiments"],
        poll_count=counts["continuous_shadow_poll_runs"],
        event_count=counts["continuous_shadow_event_journal"],
        ledger_count=counts["continuous_shadow_ledger"],
        ledger_balanced=ledger_balanced,
    )


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
