from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.storage.continuous_shadow import (
    CONTINUOUS_SHADOW_SCHEMA_VERSION,
    ContinuousShadowRepository,
    ContinuousShadowStoreError,
    _backfill_current_valuation,
)

_SOURCE_SCHEMA_VERSION = 4
_COPY_TABLES = (
    "continuous_shadow_experiments",
    "continuous_shadow_candidates",
    "continuous_shadow_event_journal",
    "continuous_shadow_portfolios",
    "continuous_shadow_positions",
    "continuous_shadow_follower_attribution",
    "continuous_shadow_evaluations",
    "continuous_shadow_liquidity_consumption",
    "continuous_shadow_ledger",
    "continuous_shadow_position_marks",
    "continuous_shadow_terminal_book_cache",
)


@dataclass(frozen=True, slots=True)
class ContinuousShadowMigrationResult:
    source: Path
    destination: Path
    schema_version: int
    table_counts: dict[str, int]
    experiment_id: str | None
    ledger_balanced: bool | None


def migrate_continuous_shadow_database(
    source: Path,
    destination: Path,
    *,
    migrated_at: datetime | None = None,
    maximum_selection_age: timedelta = timedelta(hours=36),
) -> ContinuousShadowMigrationResult:
    """Atomically extract Stage 4B from a verified legacy combined SQLite file."""
    if source.resolve() == destination.resolve():
        raise ValueError("Continuous Shadow migration requires separate database paths.")
    if destination.exists():
        raise FileExistsError("Continuous Shadow migration destination already exists.")
    if not source.is_file():
        raise FileNotFoundError("Continuous Shadow migration source is unavailable.")
    observed_at = _utc(migrated_at or datetime.now(UTC))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        source_connection = _read_only_connection(source)
        try:
            _require_source(source_connection)
            ContinuousShadowRepository(temporary).initialize()
            destination_connection = sqlite3.connect(temporary, timeout=30)
            destination_connection.row_factory = sqlite3.Row
            destination_connection.execute("PRAGMA foreign_keys = ON")
            try:
                destination_connection.execute("BEGIN IMMEDIATE")
                snapshots = _selection_snapshots(source_connection)
                _insert_snapshots(destination_connection, snapshots, recorded_at=observed_at)
                for table in _COPY_TABLES[:2]:
                    _copy_matching_table(source_connection, destination_connection, table)
                _copy_poll_runs(
                    source_connection,
                    destination_connection,
                    snapshots=snapshots,
                    maximum_selection_age=maximum_selection_age,
                )
                _copy_matching_table(
                    source_connection,
                    destination_connection,
                    "continuous_shadow_checkpoint",
                )
                for table in _COPY_TABLES[2:]:
                    _copy_matching_table(source_connection, destination_connection, table)
                _backfill_current_valuation(destination_connection)
                violations = destination_connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if violations:
                    raise ContinuousShadowStoreError(
                        "Continuous Shadow migration produced foreign-key violations."
                    )
                destination_connection.commit()
            except Exception:
                destination_connection.rollback()
                raise
            finally:
                destination_connection.close()
            _require_equal_counts(source_connection, temporary)
        finally:
            source_connection.close()
        repository = ContinuousShadowRepository(temporary)
        experiment = repository.active_experiment("polycop")
        ledger_balanced: bool | None = None
        if experiment is not None:
            result = repository.results(experiment.experiment_id, limit=1)
            accounting = cast(dict[str, object], result["accounting"])
            ledger_balanced = bool(accounting["ledger_balanced"])
            if not ledger_balanced:
                raise ContinuousShadowStoreError(
                    "Continuous Shadow migration did not preserve ledger identity."
                )
        table_counts = _table_counts(temporary)
        os.replace(temporary, destination)
        if os.name != "nt":
            destination.chmod(0o600)
        return ContinuousShadowMigrationResult(
            source=source,
            destination=destination,
            schema_version=CONTINUOUS_SHADOW_SCHEMA_VERSION,
            table_counts=table_counts,
            experiment_id=None if experiment is None else experiment.experiment_id,
            ledger_balanced=ledger_balanced,
        )
    finally:
        temporary.unlink(missing_ok=True)


def _selection_snapshots(
    connection: sqlite3.Connection,
) -> dict[str, ContinuousSelectionSnapshot]:
    rows = connection.execute(
        "SELECT selection_run_id FROM continuous_shadow_experiments "
        "UNION SELECT selection_run_id FROM continuous_shadow_candidates "
        "UNION SELECT selection_run_id FROM continuous_shadow_poll_runs "
        "ORDER BY selection_run_id"
    ).fetchall()
    snapshots: dict[str, ContinuousSelectionSnapshot] = {}
    for selection_run_id in (str(row[0]) for row in rows):
        run = connection.execute(
            "SELECT source_id, source_snapshot_id, feature_set_version, policy_id, "
            "policy_version, ranking_version, published_at "
            "FROM copyability_selection_runs WHERE run_id = ? AND status = 'succeeded'",
            (selection_run_id,),
        ).fetchone()
        if run is None or run["published_at"] is None:
            raise ContinuousShadowStoreError(
                "Continuous Shadow migration selection provenance is unavailable."
            )
        memberships = connection.execute(
            "SELECT m.wallet_id, m.pool_id, m.pool_rank, w.normalized_address "
            "FROM copyability_pool_memberships m "
            "JOIN canonical_wallets w ON w.wallet_id = m.wallet_id "
            "WHERE m.run_id = ? AND m.pool_id IN ('SHADOW_ALPHA', 'SHADOW_STRESS') "
            "ORDER BY m.wallet_id, m.pool_id",
            (selection_run_id,),
        ).fetchall()
        candidates = _candidates(memberships)
        if not candidates:
            raise ContinuousShadowStoreError(
                "Continuous Shadow migration selection candidates are unavailable."
            )
        snapshots[selection_run_id] = ContinuousSelectionSnapshot.create(
            source_id=str(run["source_id"]),
            selection_run_id=selection_run_id,
            source_snapshot_id=str(run["source_snapshot_id"]),
            feature_set_version=str(run["feature_set_version"]),
            policy_id=str(run["policy_id"]),
            policy_version=str(run["policy_version"]),
            ranking_version=str(run["ranking_version"]),
            published_at=_datetime(str(run["published_at"])),
            candidates=candidates,
        )
    return snapshots


def _insert_snapshots(
    connection: sqlite3.Connection,
    snapshots: dict[str, ContinuousSelectionSnapshot],
    *,
    recorded_at: datetime,
) -> None:
    for snapshot in snapshots.values():
        connection.execute(
            "INSERT INTO continuous_shadow_selection_snapshots "
            "(selection_run_id, source_id, source_snapshot_id, feature_set_version, "
            "policy_id, policy_version, ranking_version, published_at, candidate_count, "
            "digest, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.selection_run_id,
                snapshot.source_id,
                snapshot.source_snapshot_id,
                snapshot.feature_set_version,
                snapshot.policy_id,
                snapshot.policy_version,
                snapshot.ranking_version,
                _iso(snapshot.published_at),
                len(snapshot.candidates),
                snapshot.digest,
                _iso(recorded_at),
            ),
        )
        for candidate in snapshot.candidates:
            connection.execute(
                "INSERT INTO continuous_shadow_wallets "
                "(wallet_id, normalized_address, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(wallet_id) DO UPDATE SET "
                "last_seen_at = excluded.last_seen_at",
                (
                    candidate.wallet_id,
                    candidate.address,
                    _iso(recorded_at),
                    _iso(recorded_at),
                ),
            )
            connection.execute(
                "INSERT INTO continuous_shadow_selection_memberships "
                "(selection_run_id, wallet_id, pools_json, alpha_rank, stress_rank) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.selection_run_id,
                    candidate.wallet_id,
                    _json(candidate.pools),
                    candidate.alpha_rank,
                    candidate.stress_rank,
                ),
            )


def _copy_matching_table(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
    table: str,
) -> None:
    destination_columns = [
        str(row[1])
        for row in destination.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    source_columns = {
        str(row[1]) for row in source.execute(f"PRAGMA table_info({table})").fetchall()
    }
    columns = [column for column in destination_columns if column in source_columns]
    rows = source.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    destination.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(row[column] for column in columns) for row in rows],
    )


def _copy_poll_runs(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
    *,
    snapshots: dict[str, ContinuousSelectionSnapshot],
    maximum_selection_age: timedelta,
) -> None:
    source_columns = [
        str(row[1])
        for row in source.execute("PRAGMA table_info(continuous_shadow_poll_runs)").fetchall()
    ]
    rows = source.execute("SELECT * FROM continuous_shadow_poll_runs").fetchall()
    destination_columns = source_columns + [
        "selection_snapshot_digest",
        "selection_published_at",
        "selection_fresh",
    ]
    placeholders = ", ".join("?" for _ in destination_columns)
    values: list[tuple[object, ...]] = []
    for row in rows:
        snapshot = snapshots[str(row["selection_run_id"])]
        started_at = _datetime(str(row["started_at"]))
        fresh = (
            snapshot.published_at <= started_at
            and started_at - snapshot.published_at <= maximum_selection_age
        )
        values.append(
            tuple(row[column] for column in source_columns)
            + (snapshot.digest, _iso(snapshot.published_at), int(fresh))
        )
    if values:
        destination.executemany(
            f"INSERT INTO continuous_shadow_poll_runs "
            f"({', '.join(destination_columns)}) VALUES ({placeholders})",
            values,
        )


def _candidates(rows: list[sqlite3.Row]) -> tuple[ProtectedShadowCandidate, ...]:
    by_wallet: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = by_wallet.setdefault(
            str(row["wallet_id"]),
            {
                "address": str(row["normalized_address"]),
                "pools": [],
                "alpha_rank": None,
                "stress_rank": None,
            },
        )
        pool = str(row["pool_id"])
        item["pools"].append(pool)
        item["alpha_rank" if pool == "SHADOW_ALPHA" else "stress_rank"] = int(
            row["pool_rank"]
        )
    return tuple(
        ProtectedShadowCandidate(
            wallet_id=wallet_id,
            address=str(item["address"]),
            pools=tuple(str(pool) for pool in item["pools"]),
            alpha_rank=None if item["alpha_rank"] is None else int(item["alpha_rank"]),
            stress_rank=None if item["stress_rank"] is None else int(item["stress_rank"]),
        )
        for wallet_id, item in sorted(by_wallet.items())
    )


def _require_source(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT schema_version FROM continuous_shadow_metadata"
    ).fetchone()
    if row is None or int(row[0]) != _SOURCE_SCHEMA_VERSION:
        raise ContinuousShadowStoreError(
            "Continuous Shadow migration source schema is unsupported."
        )
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ContinuousShadowStoreError("Continuous Shadow migration source is corrupt.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ContinuousShadowStoreError(
            "Continuous Shadow migration source has foreign-key violations."
        )
    running_polls = int(
        connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_poll_runs WHERE status = 'running'"
        ).fetchone()[0]
    )
    if running_polls:
        raise ContinuousShadowStoreError(
            "Continuous Shadow migration source contains an unfinished poll."
        )


def _require_equal_counts(source: sqlite3.Connection, destination: Path) -> None:
    target = sqlite3.connect(destination)
    try:
        for table in (
            "continuous_shadow_poll_runs",
            "continuous_shadow_checkpoint",
        ) + _COPY_TABLES:
            source_count = int(source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            target_count = int(target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if source_count != target_count:
                raise ContinuousShadowStoreError(
                    f"Continuous Shadow migration count mismatch for {table}."
                )
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ContinuousShadowStoreError(
                "Continuous Shadow migration destination is corrupt."
            )
    finally:
        target.close()


def _table_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "continuous_shadow_poll_runs",
                "continuous_shadow_checkpoint",
            )
            + _COPY_TABLES
        }
    finally:
        connection.close()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be timezone-aware UTC")
    return value


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _json(value: tuple[str, ...]) -> str:
    return json.dumps(value, separators=(",", ":"))


__all__ = ["ContinuousShadowMigrationResult", "migrate_continuous_shadow_database"]
