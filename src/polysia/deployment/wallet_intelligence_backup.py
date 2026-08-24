from __future__ import annotations

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
from polysia.storage.wallet_intelligence import (
    WalletIntelligenceDatabaseValidation,
    WalletIntelligenceRepository,
)

WALLET_INTELLIGENCE_BACKUP_PREFIX = "wallet-intelligence-"


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
