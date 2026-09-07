"""Read-only SQLite access for immutable historical evidence.

Never checkpoint, compact, migrate, or write the opened file. Hash the bytes
on disk; do not ask SQLite to rewrite the database.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_HASH_CHUNK = 1024 * 1024


class ImmutableSqliteError(RuntimeError):
    """Raised when an immutable historical database cannot be opened safely."""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file without modifying it."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_immutable_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro&immutable=1"


def connect_immutable_sqlite(path: Path) -> sqlite3.Connection:
    """Open SQLite with ``mode=ro&immutable=1`` and ``query_only``."""

    if not path.is_file():
        raise ImmutableSqliteError(f"immutable sqlite file is missing: {path}")
    try:
        connection = sqlite3.connect(sqlite_immutable_uri(path), uri=True)
    except sqlite3.Error as error:
        raise ImmutableSqliteError(
            f"immutable sqlite open failed for {path}: {error}"
        ) from error
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def verify_file_digest(path: Path, expected_sha256: str) -> str:
    digest = sha256_file(path)
    if digest.casefold() != expected_sha256.casefold():
        raise ImmutableSqliteError(
            f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, got {digest}"
        )
    return digest


@contextmanager
def open_immutable_sqlite(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a query-only connection and re-check the digest on close."""

    before = sha256_file(path) if expected_sha256 is None else verify_file_digest(
        path, expected_sha256
    )
    connection = connect_immutable_sqlite(path)
    try:
        yield connection
    finally:
        connection.close()
        after = sha256_file(path)
        if after != before:
            raise ImmutableSqliteError(
                f"immutable sqlite digest changed after read-only use: {path.name}"
            )


__all__ = [
    "ImmutableSqliteError",
    "connect_immutable_sqlite",
    "open_immutable_sqlite",
    "sha256_file",
    "sqlite_immutable_uri",
    "verify_file_digest",
]
