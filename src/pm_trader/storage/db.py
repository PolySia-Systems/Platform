from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schemas.sql")


def connect_sqlite(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Open a SQLite connection configured for repository use."""
    if path != ":memory:":
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(db_path))
    else:
        connection = sqlite3.connect(":memory:")

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(
    connection: sqlite3.Connection,
    *,
    schema_path: Path = SCHEMA_PATH,
) -> None:
    """Create all storage tables if they do not already exist."""
    connection.executescript(schema_path.read_text(encoding="utf-8"))
    connection.commit()


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Wrap writes in a commit/rollback transaction."""
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


class SQLiteDatabase:
    """Small owner for a SQLite connection and schema lifecycle."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = path
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = connect_sqlite(self._path)
        return self._connection

    def initialize(self) -> None:
        initialize_database(self.connection)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> SQLiteDatabase:
        self.initialize()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
