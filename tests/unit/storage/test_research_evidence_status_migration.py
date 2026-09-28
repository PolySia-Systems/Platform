from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from polysia.domain.research_evidence.models import (
    PREVIOUS_RESEARCH_EVIDENCE_SCHEMA_VERSION,
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    IntervalValidity,
    ObservationKind,
    ResearchInterval,
)
from polysia.domain.research_evidence.replay import replay_same_observations
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


def test_v2_bundle_stays_readable_and_writable_migration_adds_nullable_admission(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v2.sqlite3"
    store = ResearchEvidenceStore(database)
    store.initialize()
    observed = datetime(2026, 9, 13, tzinfo=UTC)
    store.persist_interval(ResearchInterval(
        interval_id="legacy-window", started_at=observed, ended_at=None,
        validity=IntervalValidity.OPEN, reason="open", code_sha=None,
        configuration_digest=None, policy_version="test-v1",
    ))
    store.persist_event(CanonicalResearchEvent(
        evidence_id="e" * 64, schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="legacy-trades", event_kind=ObservationKind.WALLET_TRADE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference="market", outcome_reference="token", side="BUY",
        price=Decimal("0.4"), size=Decimal("1"), source_time=observed,
        observed_time=observed, receive_monotonic_ns=1, normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.WALLET_ALIASED, leader_alias="pub-legacy",
        confirmation=ConfirmationStatus.CONFIRMED, payload_digest="f" * 64,
        provenance={}, source_event_id="trade-1", run_id="legacy-run",
    ), interval_id="legacy-window")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE research_evidence_metadata SET schema_version = ?",
            (PREVIOUS_RESEARCH_EVIDENCE_SCHEMA_VERSION,),
        )
        connection.execute("ALTER TABLE research_events DROP COLUMN admission_time_utc")
        connection.execute(
            "UPDATE research_events SET schema_version = ?",
            (PREVIOUS_RESEARCH_EVIDENCE_SCHEMA_VERSION,),
        )
    before_read = database.read_bytes()
    old = ResearchEvidenceStore(database, read_only=True)
    old.verify_integrity()
    legacy_event = old.load_events(run_id="legacy-run")[0]
    assert legacy_event.admission_time is None
    assert dict(replay_same_observations((legacy_event,)).unknown_by_cause) == {
        "missing_admission_time": 1
    }
    assert database.read_bytes() == before_read

    store.initialize()
    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM research_evidence_metadata WHERE singleton = 1"
        ).fetchone()
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(research_events)")
        }
    assert version == (RESEARCH_EVIDENCE_SCHEMA_VERSION,)
    assert "admission_time_utc" in columns


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
