from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysia.deployment.sqlite_backup import (
    backup_sqlite_database,
    initialize_sqlite_database,
    restore_sqlite_backup,
    verify_sqlite_backup,
)


def test_backup_and_restore_preserve_valid_database(tmp_path: Path) -> None:
    database = tmp_path / "data" / "polysia.sqlite3"
    initialize_sqlite_database(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO market_events "
            "(source, event_type, token_id, received_at, payload_json, raw_payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test", "quote", "token-1", "2026-07-28T00:00:00+00:00", "{}", "{}"),
        )
        connection.commit()
    finally:
        connection.close()

    result = backup_sqlite_database(
        database,
        tmp_path / "backups",
        now=datetime(2026, 7, 28, tzinfo=UTC),
    )
    restored = tmp_path / "restored" / "polysia.sqlite3"

    assert verify_sqlite_backup(result.backup_path) == result.sha256
    assert restore_sqlite_backup(result.backup_path, restored) == result.sha256
    restored_connection = sqlite3.connect(restored)
    try:
        assert restored_connection.execute("SELECT COUNT(*) FROM market_events").fetchone() == (
            1,
        )
    finally:
        restored_connection.close()


def test_restore_refuses_to_replace_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "polysia.sqlite3"
    initialize_sqlite_database(database)
    result = backup_sqlite_database(database, tmp_path / "backups")

    with pytest.raises(FileExistsError, match="Refusing to replace"):
        restore_sqlite_backup(result.backup_path, database)


def test_verification_rejects_tampered_backup(tmp_path: Path) -> None:
    database = tmp_path / "polysia.sqlite3"
    initialize_sqlite_database(database)
    result = backup_sqlite_database(database, tmp_path / "backups")
    result.backup_path.write_bytes(result.backup_path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="checksum"):
        verify_sqlite_backup(result.backup_path)


def test_backup_retention_prunes_oldest_copy_and_checksum(tmp_path: Path) -> None:
    database = tmp_path / "polysia.sqlite3"
    initialize_sqlite_database(database)
    backup_dir = tmp_path / "backups"
    start = datetime(2026, 7, 28, tzinfo=UTC)

    first = backup_sqlite_database(database, backup_dir, keep=2, now=start)
    second = backup_sqlite_database(database, backup_dir, keep=2, now=start + timedelta(seconds=1))
    third = backup_sqlite_database(database, backup_dir, keep=2, now=start + timedelta(seconds=2))

    assert not first.backup_path.exists()
    assert not first.checksum_path.exists()
    assert second.backup_path.exists()
    assert third.backup_path.exists()
