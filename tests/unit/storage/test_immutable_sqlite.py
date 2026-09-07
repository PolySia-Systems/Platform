from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from polysia.storage.immutable_sqlite import (
    ImmutableSqliteError,
    open_immutable_sqlite,
    sha256_file,
    verify_file_digest,
)


def _write_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO items(name) VALUES ('alpha')")
    connection.commit()
    connection.close()


def test_immutable_open_leaves_sha256_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    _write_sqlite(path)
    before = sha256_file(path)

    with open_immutable_sqlite(path, expected_sha256=before) as connection:
        row = connection.execute("SELECT COUNT(*) FROM items").fetchone()
        assert int(row[0]) == 1
        with pytest.raises(sqlite3.Error):
            connection.execute("INSERT INTO items(name) VALUES ('write')")

    assert sha256_file(path) == before


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    _write_sqlite(path)

    with pytest.raises(ImmutableSqliteError, match="SHA-256 mismatch"):
        verify_file_digest(path, "0" * 64)
