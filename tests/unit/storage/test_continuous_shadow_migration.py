from __future__ import annotations

import sqlite3
from pathlib import Path

from polysia.storage.continuous_shadow import (
    CONTINUOUS_SHADOW_SCHEMA_PATH,
    ContinuousShadowRepository,
)
from polysia.storage.dynamic_shadow import DynamicShadowRepository


def test_stage4b_schema_is_additive_and_keeps_stage4a_schema_v1(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()

    ContinuousShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()

    connection = sqlite3.connect(database)
    try:
        dynamic_version = connection.execute(
            "SELECT schema_version FROM dynamic_shadow_metadata"
        ).fetchone()[0]
        continuous_version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
        dynamic_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'dynamic_shadow_evaluations'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert dynamic_version == 1
    assert continuous_version == 3
    assert "evaluation_status" in dynamic_sql


def test_stage4b_v2_migrates_atomically_and_idempotently_to_v3(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()
    current_schema = CONTINUOUS_SHADOW_SCHEMA_PATH.read_text(encoding="utf-8")
    legacy_schema = current_schema.replace(
        "schema_version INTEGER PRIMARY KEY CHECK(schema_version = 3)",
        "schema_version INTEGER PRIMARY KEY CHECK(schema_version = 2)",
    ).replace(
        "    settlement_backlog_count INTEGER NOT NULL DEFAULT 0 "
        "CHECK(settlement_backlog_count >= 0),\n",
        "",
    ).replace(
        "    processing_status TEXT NOT NULL DEFAULT 'PROCESSED'\n"
        "        CHECK(processing_status = 'PROCESSED'),\n",
        "",
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(legacy_schema)
        connection.execute(
            "INSERT INTO continuous_shadow_metadata (schema_version, initialized_at) "
            "VALUES (2, '2026-08-25T00:00:00+00:00')"
        )

    repository = ContinuousShadowRepository(database)
    repository.initialize()
    repository.initialize()

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
        journal_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_event_journal)"
            ).fetchall()
        }
        poll_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_poll_runs)"
            ).fetchall()
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert version == 3
    assert "processing_status" in journal_columns
    assert "settlement_backlog_count" in poll_columns
    assert integrity == "ok"
