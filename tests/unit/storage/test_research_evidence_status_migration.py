from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from polysia.storage.research_evidence import ResearchEvidenceStore, ensure_research_evidence_schema

PRE_PR147_EXPERIMENTS_SQL = """
CREATE TABLE research_experiments (
    run_id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    collection_ends_at_utc TEXT NOT NULL,
    max_events INTEGER NOT NULL CHECK (max_events > 0),
    max_bytes INTEGER NOT NULL CHECK (max_bytes > 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'FINALIZED')),
    code_sha TEXT,
    configuration_digest TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    finalized_at_utc TEXT,
    bundle_path TEXT,
    bundle_sha256 TEXT,
    event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0)
)
"""


def test_pre_pr147_status_constraint_migrates_and_preserves_rows(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    started = datetime(2026, 9, 13, tzinfo=UTC).isoformat()
    ended = datetime(2026, 9, 13, 4, tzinfo=UTC).isoformat()
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(
            "CREATE TABLE research_evidence_metadata ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "schema_version TEXT NOT NULL, "
            "policy_version TEXT NOT NULL, "
            "created_at_utc TEXT NOT NULL"
            ");"
        )
        connection.execute(PRE_PR147_EXPERIMENTS_SQL)
        connection.execute(
            "INSERT INTO research_experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "active-run",
                started,
                ended,
                10,
                1_048_576,
                "ACTIVE",
                "a" * 40,
                "digest-a",
                "prospective-collector-v1",
                None,
                None,
                None,
                3,
            ),
        )
        connection.execute(
            "INSERT INTO research_experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "final-run",
                started,
                ended,
                10,
                1_048_576,
                "FINALIZED",
                "b" * 40,
                "digest-b",
                "prospective-collector-v1",
                ended,
                "bundle",
                "abc",
                4,
            ),
        )
        connection.commit()
        sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='research_experiments'"
            ).fetchone()[0]
        )
        assert "FAILURE_ARCHIVED" not in sql
        ensure_research_evidence_schema(connection, policy_version="prospective-collector-v1")
        migrated = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='research_experiments'"
            ).fetchone()[0]
        )
        assert "FAILURE_ARCHIVED" in migrated
        rows = {
            str(row["run_id"]): str(row["status"])
            for row in connection.execute(
                "SELECT run_id, status, event_count FROM research_experiments"
            )
        }
        counts = {
            str(row["run_id"]): int(row["event_count"])
            for row in connection.execute(
                "SELECT run_id, event_count FROM research_experiments"
            )
        }
        assert rows == {"active-run": "ACTIVE", "final-run": "FINALIZED"}
        assert counts == {"active-run": 3, "final-run": 4}
        connection.execute(
            "UPDATE research_experiments SET status='FAILURE_ARCHIVED' WHERE run_id='active-run'"
        )
        connection.commit()
        status = connection.execute(
            "SELECT status FROM research_experiments WHERE run_id='active-run'"
        ).fetchone()
        assert str(status[0]) == "FAILURE_ARCHIVED"
    finally:
        connection.close()
    store = ResearchEvidenceStore(database)
    store.initialize()
    loaded = store.load_experiment("final-run")
    assert loaded is not None
    assert loaded.status == "FINALIZED"
    assert loaded.event_count == 4
