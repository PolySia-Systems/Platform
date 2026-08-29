from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from polysia.storage.db import connect_sqlite, initialize_database

BACKUP_PREFIX = "polysia-"
BACKUP_SUFFIX = ".sqlite3"


@dataclass(frozen=True, slots=True)
class BackupResult:
    backup_path: Path
    checksum_path: Path
    sha256: str


def initialize_sqlite_database(database_path: Path) -> None:
    """Create the current PolySia schema without replacing existing state."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_sqlite(database_path)
    try:
        initialize_database(connection)
        _require_integrity(connection)
    finally:
        connection.close()
    _restrict_permissions(database_path)


def backup_sqlite_database(
    database_path: Path,
    backup_dir: Path,
    *,
    keep: int = 14,
    now: datetime | None = None,
    prefix: str = BACKUP_PREFIX,
) -> BackupResult:
    """Create an online, integrity-checked, checksummed SQLite backup."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}-", prefix) is None:
        raise ValueError("backup prefix is invalid")
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        backup_dir.chmod(0o700)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{prefix}{timestamp}{BACKUP_SUFFIX}"

    temporary_path = _temporary_path(backup_dir)
    try:
        source = sqlite3.connect(_read_only_uri(database_path), uri=True)
        destination = sqlite3.connect(temporary_path)
        try:
            source.backup(destination)
            _require_integrity(destination)
        finally:
            destination.close()
            source.close()
        os.replace(temporary_path, backup_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    _restrict_permissions(backup_path)
    sha256 = _sha256(backup_path)
    checksum_path = backup_path.with_suffix(f"{backup_path.suffix}.sha256")
    checksum_path.write_text(f"{sha256}  {backup_path.name}\n", encoding="ascii")
    _restrict_permissions(checksum_path)
    _prune_backups(backup_dir, keep=keep, prefix=prefix)
    return BackupResult(backup_path=backup_path, checksum_path=checksum_path, sha256=sha256)


def verify_sqlite_backup(backup_path: Path) -> str:
    """Verify checksum and SQLite integrity for one backup."""
    checksum_path = backup_path.with_suffix(f"{backup_path.suffix}.sha256")
    expected = _read_checksum(checksum_path, expected_name=backup_path.name)
    actual = _sha256(backup_path)
    if actual != expected:
        raise ValueError("SQLite backup checksum does not match")

    connection = sqlite3.connect(_read_only_uri(backup_path), uri=True)
    try:
        _require_integrity(connection)
    finally:
        connection.close()
    return actual


def restore_sqlite_backup(
    backup_path: Path,
    database_path: Path,
    *,
    overwrite: bool = False,
) -> str:
    """Restore a verified backup atomically; existing state is protected by default."""
    sha256 = verify_sqlite_backup(backup_path)
    if database_path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to replace existing database: {database_path}")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_path(database_path.parent)
    try:
        source = sqlite3.connect(_read_only_uri(backup_path), uri=True)
        destination = sqlite3.connect(temporary_path)
        try:
            source.backup(destination)
            _require_integrity(destination)
        finally:
            destination.close()
            source.close()
        os.replace(temporary_path, database_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    _restrict_permissions(database_path)
    return sha256


def _temporary_path(directory: Path) -> Path:
    with NamedTemporaryFile(
        dir=directory,
        prefix=".polysia-sqlite-",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        return Path(temporary.name)


def _require_integrity(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise ValueError("SQLite integrity check failed")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _read_checksum(checksum_path: Path, *, expected_name: str) -> str:
    line = checksum_path.read_text(encoding="ascii").strip()
    parts = line.split(maxsplit=1)
    if len(parts) != 2 or parts[1].strip() != expected_name:
        raise ValueError("SQLite backup checksum file is invalid")
    checksum = parts[0].lower()
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        raise ValueError("SQLite backup checksum file is invalid")
    return checksum


def _restrict_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def _prune_backups(backup_dir: Path, *, keep: int, prefix: str = BACKUP_PREFIX) -> None:
    exact_name = re.compile(
        rf"^{re.escape(prefix)}\d{{8}}T\d{{12}}Z{re.escape(BACKUP_SUFFIX)}$"
    )
    backups = sorted(
        (
            path
            for path in backup_dir.glob(f"{prefix}*{BACKUP_SUFFIX}")
            if exact_name.fullmatch(path.name) is not None
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink()
        old_backup.with_suffix(f"{old_backup.suffix}.sha256").unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage PolySia SQLite backups.")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="Initialize the current SQLite schema.")
    initialize.add_argument("--database", required=True, type=Path)

    backup = commands.add_parser("backup", help="Create and verify an online backup.")
    backup.add_argument("--database", required=True, type=Path)
    backup.add_argument("--backup-dir", required=True, type=Path)
    backup.add_argument("--keep", default=14, type=int)

    verify = commands.add_parser("verify", help="Verify one backup and its checksum.")
    verify.add_argument("--backup", required=True, type=Path)

    restore = commands.add_parser("restore", help="Restore a verified backup.")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--database", required=True, type=Path)
    restore.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "init":
        initialize_sqlite_database(arguments.database)
        print(f"initialized={arguments.database}")
        return 0
    if arguments.command == "backup":
        result = backup_sqlite_database(
            arguments.database,
            arguments.backup_dir,
            keep=arguments.keep,
        )
        print(f"backup={result.backup_path}")
        print(f"sha256={result.sha256}")
        return 0
    if arguments.command == "verify":
        print(f"sha256={verify_sqlite_backup(arguments.backup)}")
        return 0
    if arguments.command == "restore":
        checksum = restore_sqlite_backup(
            arguments.backup,
            arguments.database,
            overwrite=arguments.overwrite,
        )
        print(f"sha256={checksum}")
        return 0
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
