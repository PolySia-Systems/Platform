from __future__ import annotations

from pm_trader.storage.db import SQLiteDatabase, connect_sqlite, initialize_database


def test_initialize_database_creates_expected_tables() -> None:
    connection = connect_sqlite()
    initialize_database(connection)

    rows = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
        """
    ).fetchall()

    table_names = {str(row["name"]) for row in rows}
    assert {
        "decisions",
        "fills",
        "market_events",
        "markets",
        "orderbook_snapshots",
        "orders",
        "positions",
    }.issubset(table_names)


def test_sqlite_database_context_initializes_and_closes(tmp_path) -> None:
    db_path = tmp_path / "pm_trader.sqlite3"

    with SQLiteDatabase(db_path) as database:
        database.connection.execute("SELECT 1").fetchone()

    assert db_path.exists()
