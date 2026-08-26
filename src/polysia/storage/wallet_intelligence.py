from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.application.ports.candidate_wallets import (
    CandidateRunStart,
    CandidateSourceState,
    CandidateStoredSnapshot,
)
from polysia.domain.wallet_intelligence import CandidateWalletDataset

WALLET_INTELLIGENCE_SCHEMA_PATH = Path(__file__).with_name("wallet_intelligence_schema.sql")
WALLET_INTELLIGENCE_SCHEMA_VERSION = 1
_ABANDONED_RUN_AFTER = timedelta(hours=2)


class CandidateStoreError(RuntimeError):
    """Safe candidate-wallet persistence failure."""


class CandidateRunInProgressError(CandidateStoreError):
    """A non-stale run already owns this source."""


class CandidateRunIdConflictError(CandidateStoreError):
    """A supplied run id cannot be reused for a different attempt."""


@dataclass(frozen=True, slots=True)
class WalletIntelligenceDatabaseValidation:
    schema_version: int
    candidate_intelligence_schema_version: int | None
    candidate_run_count: int
    candidate_pool_count: int
    source_count: int
    snapshot_count: int
    row_count: int
    copyability_selection_schema_version: int | None = None
    copyability_run_count: int = 0
    copyability_membership_count: int = 0
    dynamic_shadow_schema_version: int | None = None
    dynamic_shadow_run_count: int = 0
    dynamic_shadow_evaluation_count: int = 0
    continuous_shadow_schema_version: int | None = None
    continuous_shadow_experiment_count: int = 0
    continuous_shadow_poll_count: int = 0
    continuous_shadow_event_count: int = 0
    continuous_shadow_ledger_count: int = 0


class WalletIntelligenceRepository:
    """Owner of the separate protected candidate-wallet SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _restrict_directory(self._path.parent)
        connection = self._connect()
        try:
            connection.executescript(
                WALLET_INTELLIGENCE_SCHEMA_PATH.read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT OR IGNORE INTO wallet_intelligence_metadata "
                "(schema_version, initialized_at) VALUES (?, ?)",
                (WALLET_INTELLIGENCE_SCHEMA_VERSION, _iso(datetime.now(UTC))),
            )
            connection.commit()
            self._require_integrity(connection)
            self._require_schema_version(connection)
        finally:
            connection.close()
        _restrict_file(self._path)

    def start_run(
        self,
        source_id: str,
        *,
        scheduled_for: date,
        started_at: datetime,
        force_new: bool = False,
        run_id: str | None = None,
    ) -> CandidateRunStart:
        _require_source_id(source_id)
        started_at = _utc(started_at, field_name="started_at")
        supplied_run_id = run_id
        run_id = run_id or str(uuid.uuid4())
        _require_safe_identifier(run_id, field_name="run_id")
        snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"polysia:candidate:{run_id}"))
        schedule_text = scheduled_for.isoformat()

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_id = connection.execute(
                "SELECT run_id, snapshot_id, source_id, scheduled_for, status "
                "FROM candidate_source_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing_id is not None:
                if (
                    existing_id["status"] == "succeeded"
                    and existing_id["source_id"] == source_id
                    and existing_id["scheduled_for"] == schedule_text
                ):
                    connection.commit()
                    return CandidateRunStart(
                        run_id=str(existing_id["run_id"]),
                        snapshot_id=str(existing_id["snapshot_id"]),
                        already_succeeded=True,
                    )
                raise CandidateRunIdConflictError("run_id already belongs to another attempt")

            if not force_new and supplied_run_id is None:
                completed = connection.execute(
                    "SELECT run_id, snapshot_id FROM candidate_source_runs "
                    "WHERE source_id = ? AND scheduled_for = ? AND status = 'succeeded' "
                    "ORDER BY completed_at DESC LIMIT 1",
                    (source_id, schedule_text),
                ).fetchone()
                if completed is not None:
                    connection.commit()
                    return CandidateRunStart(
                        run_id=str(completed["run_id"]),
                        snapshot_id=str(completed["snapshot_id"]),
                        already_succeeded=True,
                    )

            running = connection.execute(
                "SELECT run_id, started_at FROM candidate_source_runs "
                "WHERE source_id = ? AND status = 'running'",
                (source_id,),
            ).fetchone()
            if running is not None:
                running_started_at = _parse_datetime(str(running["started_at"]))
                if started_at - running_started_at <= _ABANDONED_RUN_AFTER:
                    raise CandidateRunInProgressError(
                        "A candidate-wallet source run is already in progress."
                    )
                connection.execute(
                    "UPDATE candidate_source_runs SET status = 'failed', completed_at = ?, "
                    "error_code = 'abandoned_run', "
                    "error_message = 'Previous run exceeded the two-hour ownership window.' "
                    "WHERE run_id = ? AND status = 'running'",
                    (_iso(started_at), str(running["run_id"])),
                )

            connection.execute(
                "INSERT INTO candidate_source_runs "
                "(run_id, snapshot_id, source_id, scheduled_for, status, started_at) "
                "VALUES (?, ?, ?, ?, 'running', ?)",
                (run_id, snapshot_id, source_id, schedule_text, _iso(started_at)),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return CandidateRunStart(run_id=run_id, snapshot_id=snapshot_id, already_succeeded=False)

    def complete_run(
        self,
        start: CandidateRunStart,
        dataset: CandidateWalletDataset,
        *,
        accepted_at: datetime,
    ) -> CandidateStoredSnapshot:
        accepted_at = _utc(accepted_at, field_name="accepted_at")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT source_id, status, snapshot_id FROM candidate_source_runs "
                "WHERE run_id = ?",
                (start.run_id,),
            ).fetchone()
            if run is None or run["status"] != "running":
                raise CandidateStoreError("Candidate-wallet run is not open for completion.")
            if run["source_id"] != dataset.source_id or run["snapshot_id"] != start.snapshot_id:
                raise CandidateStoreError(
                    "Candidate-wallet run identity does not match the dataset."
                )

            warning_code = _record_count_warning(
                connection,
                source_id=dataset.source_id,
                record_count=len(dataset.records),
            )
            connection.execute(
                "INSERT INTO candidate_wallet_snapshots "
                "(snapshot_id, run_id, source_id, captured_at, accepted_at, schema_version, "
                "source_total_pages, record_count, dataset_digest) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    start.snapshot_id,
                    start.run_id,
                    dataset.source_id,
                    _iso(dataset.fetched_at),
                    _iso(accepted_at),
                    dataset.schema_version,
                    dataset.source_total_pages,
                    len(dataset.records),
                    dataset.dataset_digest,
                ),
            )
            for record in dataset.records:
                wallet_key = _wallet_key(dataset.source_id, record.external_wallet_id)
                connection.execute(
                    "INSERT INTO candidate_wallet_identities "
                    "(wallet_key, source_id, external_wallet_id, first_seen_at, last_seen_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(wallet_key) DO UPDATE SET last_seen_at = excluded.last_seen_at",
                    (
                        wallet_key,
                        dataset.source_id,
                        record.external_wallet_id,
                        _iso(accepted_at),
                        _iso(accepted_at),
                    ),
                )
                identity = connection.execute(
                    "SELECT source_id, external_wallet_id FROM candidate_wallet_identities "
                    "WHERE wallet_key = ?",
                    (wallet_key,),
                ).fetchone()
                if (
                    identity is None
                    or identity["source_id"] != dataset.source_id
                    or identity["external_wallet_id"] != record.external_wallet_id
                ):
                    raise CandidateStoreError("Protected wallet identity did not reconcile.")
                connection.execute(
                    "INSERT INTO candidate_wallet_snapshot_rows "
                    "(snapshot_id, wallet_key, source_rank, source_page, metrics_json, row_digest) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        start.snapshot_id,
                        wallet_key,
                        record.source_rank,
                        record.source_page,
                        _metrics_json(record.metrics),
                        record.row_digest,
                    ),
                )

            stored_count = connection.execute(
                "SELECT COUNT(*) FROM candidate_wallet_snapshot_rows WHERE snapshot_id = ?",
                (start.snapshot_id,),
            ).fetchone()[0]
            if stored_count != len(dataset.records):
                raise CandidateStoreError("Candidate-wallet snapshot row count did not reconcile.")

            connection.execute(
                "INSERT INTO candidate_current_snapshots (source_id, snapshot_id, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
                "snapshot_id = excluded.snapshot_id, updated_at = excluded.updated_at",
                (dataset.source_id, start.snapshot_id, _iso(accepted_at)),
            )
            updated = connection.execute(
                "UPDATE candidate_source_runs SET status = 'succeeded', completed_at = ?, "
                "source_total_pages = ?, record_count = ?, schema_version = ?, "
                "dataset_digest = ?, warning_code = ? "
                "WHERE run_id = ? AND status = 'running'",
                (
                    _iso(accepted_at),
                    dataset.source_total_pages,
                    len(dataset.records),
                    dataset.schema_version,
                    dataset.dataset_digest,
                    warning_code,
                    start.run_id,
                ),
            ).rowcount
            if updated != 1:
                raise CandidateStoreError("Candidate-wallet run completion was not recorded.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        _restrict_file(self._path)
        return CandidateStoredSnapshot(
            run_id=start.run_id,
            snapshot_id=start.snapshot_id,
            source_id=dataset.source_id,
            accepted_at=accepted_at,
            source_total_pages=dataset.source_total_pages,
            record_count=len(dataset.records),
            dataset_digest=dataset.dataset_digest,
            warning_code=warning_code,
        )

    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
        completed_at: datetime,
    ) -> None:
        completed_at = _utc(completed_at, field_name="completed_at")
        _require_safe_identifier(error_code, field_name="error_code")
        safe_message = _safe_error_message(error_message)
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE candidate_source_runs SET status = 'failed', completed_at = ?, "
                "error_code = ?, error_message = ? WHERE run_id = ? AND status = 'running'",
                (_iso(completed_at), error_code, safe_message, run_id),
            )
            connection.commit()
        finally:
            connection.close()

    def quarantine_run(
        self,
        run_id: str,
        *,
        reason_code: str,
        schema_fingerprint: str,
        sample_gzip: bytes,
        sample_sha256: str,
        completed_at: datetime,
    ) -> None:
        completed_at = _utc(completed_at, field_name="completed_at")
        _require_safe_identifier(reason_code, field_name="reason_code")
        if len(sample_gzip) > 65_536:
            raise ValueError("compressed quarantine sample exceeds 65536 bytes")
        if hashlib.sha256(sample_gzip).hexdigest() != sample_sha256:
            raise ValueError("quarantine sample checksum does not match")
        quarantine_id = str(uuid.uuid4())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT source_id FROM candidate_source_runs "
                "WHERE run_id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if run is None:
                raise CandidateStoreError("Candidate-wallet run is not open for quarantine.")
            connection.execute(
                "INSERT INTO candidate_source_quarantines "
                "(quarantine_id, run_id, source_id, reason_code, schema_fingerprint, "
                "sample_gzip, sample_sha256, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    quarantine_id,
                    run_id,
                    str(run["source_id"]),
                    reason_code,
                    schema_fingerprint,
                    sample_gzip,
                    sample_sha256,
                    _iso(completed_at),
                ),
            )
            connection.execute(
                "UPDATE candidate_source_runs SET status = 'quarantined', completed_at = ?, "
                "error_code = ?, "
                "error_message = 'External schema changed; inspect protected quarantine evidence.' "
                "WHERE run_id = ? AND status = 'running'",
                (_iso(completed_at), reason_code, run_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def source_state(self, source_id: str) -> CandidateSourceState:
        _require_source_id(source_id)
        connection = self._connect()
        try:
            current = connection.execute(
                "SELECT s.snapshot_id, s.run_id, s.accepted_at, s.record_count, "
                "s.source_total_pages, "
                "r.warning_code AS current_warning_code "
                "FROM candidate_current_snapshots c "
                "JOIN candidate_wallet_snapshots s ON s.snapshot_id = c.snapshot_id "
                "JOIN candidate_source_runs r ON r.run_id = s.run_id "
                "WHERE c.source_id = ?",
                (source_id,),
            ).fetchone()
            last_run = connection.execute(
                "SELECT run_id, status, error_code FROM candidate_source_runs "
                "WHERE source_id = ? ORDER BY started_at DESC, run_id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        return CandidateSourceState(
            source_id=source_id,
            current_snapshot_id=None if current is None else str(current["snapshot_id"]),
            current_run_id=None if current is None else str(current["run_id"]),
            last_success_at=None
            if current is None
            else _parse_datetime(str(current["accepted_at"])),
            current_record_count=None if current is None else int(current["record_count"]),
            current_page_count=None
            if current is None
            else int(current["source_total_pages"]),
            last_run_id=None if last_run is None else str(last_run["run_id"]),
            last_run_status=None if last_run is None else str(last_run["status"]),
            last_error_code=None
            if last_run is None or last_run["error_code"] is None
            else str(last_run["error_code"]),
            last_warning_code=None
            if current is None or current["current_warning_code"] is None
            else str(current["current_warning_code"]),
        )

    def stored_snapshot(self, run_id: str) -> CandidateStoredSnapshot:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT r.run_id, r.snapshot_id, r.source_id, r.warning_code, "
                "s.accepted_at, s.source_total_pages, s.record_count, s.dataset_digest "
                "FROM candidate_source_runs r JOIN candidate_wallet_snapshots s "
                "ON s.snapshot_id = r.snapshot_id WHERE r.run_id = ? AND r.status = 'succeeded'",
                (run_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise CandidateStoreError("Completed candidate-wallet snapshot is unavailable.")
        return CandidateStoredSnapshot(
            run_id=str(row["run_id"]),
            snapshot_id=str(row["snapshot_id"]),
            source_id=str(row["source_id"]),
            accepted_at=_parse_datetime(str(row["accepted_at"])),
            source_total_pages=int(row["source_total_pages"]),
            record_count=int(row["record_count"]),
            dataset_digest=str(row["dataset_digest"]),
            warning_code=None if row["warning_code"] is None else str(row["warning_code"]),
        )

    def prune_history(
        self,
        *,
        snapshot_cutoff: datetime,
        quarantine_cutoff: datetime,
    ) -> None:
        snapshot_cutoff = _utc(snapshot_cutoff, field_name="snapshot_cutoff")
        quarantine_cutoff = _utc(quarantine_cutoff, field_name="quarantine_cutoff")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM candidate_wallet_snapshots WHERE accepted_at < ? "
                "AND snapshot_id NOT IN (SELECT snapshot_id FROM candidate_current_snapshots)",
                (_iso(snapshot_cutoff),),
            )
            connection.execute(
                "DELETE FROM candidate_wallet_identities WHERE wallet_key NOT IN "
                "(SELECT wallet_key FROM candidate_wallet_snapshot_rows)"
            )
            connection.execute(
                "DELETE FROM candidate_source_quarantines WHERE captured_at < ?",
                (_iso(quarantine_cutoff),),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def validate_integrity(self) -> WalletIntelligenceDatabaseValidation:
        connection = self._connect(read_only=True)
        try:
            self._require_integrity(connection)
            self._require_schema_version(connection)
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise CandidateStoreError("Wallet-intelligence foreign-key check failed.")
            source_count = int(
                connection.execute("SELECT COUNT(*) FROM candidate_current_snapshots").fetchone()[0]
            )
            snapshot_count = int(
                connection.execute("SELECT COUNT(*) FROM candidate_wallet_snapshots").fetchone()[0]
            )
            row_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM candidate_wallet_snapshot_rows"
                ).fetchone()[0]
            )
            candidate_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'candidate_intelligence_metadata'"
            ).fetchone()
            candidate_schema_version: int | None = None
            candidate_run_count = 0
            candidate_pool_count = 0
            copyability_schema_version: int | None = None
            copyability_run_count = 0
            copyability_membership_count = 0
            dynamic_shadow_schema_version: int | None = None
            dynamic_shadow_run_count = 0
            dynamic_shadow_evaluation_count = 0
            continuous_shadow_schema_version: int | None = None
            continuous_shadow_experiment_count = 0
            continuous_shadow_poll_count = 0
            continuous_shadow_event_count = 0
            continuous_shadow_ledger_count = 0
            if candidate_table is not None:
                candidate_rows = connection.execute(
                    "SELECT schema_version FROM candidate_intelligence_metadata"
                ).fetchall()
                if len(candidate_rows) != 1 or int(candidate_rows[0][0]) != 1:
                    raise CandidateStoreError(
                        "Candidate Intelligence schema version is unsupported."
                    )
                candidate_schema_version = int(candidate_rows[0][0])
                candidate_run_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM candidate_intelligence_runs "
                        "WHERE status = 'succeeded'"
                    ).fetchone()[0]
                )
                candidate_pool_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM candidate_trading_pool_current"
                    ).fetchone()[0]
                )
            copyability_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'copyability_selection_metadata'"
            ).fetchone()
            if copyability_table is not None:
                copyability_rows = connection.execute(
                    "SELECT schema_version FROM copyability_selection_metadata"
                ).fetchall()
                if len(copyability_rows) != 1 or int(copyability_rows[0][0]) != 1:
                    raise CandidateStoreError(
                        "Copyability selection schema version is unsupported."
                    )
                copyability_schema_version = int(copyability_rows[0][0])
                copyability_run_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM copyability_selection_runs "
                        "WHERE status = 'succeeded'"
                    ).fetchone()[0]
                )
                copyability_membership_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM copyability_pools_current"
                    ).fetchone()[0]
                )
            dynamic_shadow_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'dynamic_shadow_metadata'"
            ).fetchone()
            if dynamic_shadow_table is not None:
                dynamic_shadow_rows = connection.execute(
                    "SELECT schema_version FROM dynamic_shadow_metadata"
                ).fetchall()
                if len(dynamic_shadow_rows) != 1 or int(dynamic_shadow_rows[0][0]) != 1:
                    raise CandidateStoreError("Dynamic Shadow schema version is unsupported.")
                dynamic_shadow_schema_version = int(dynamic_shadow_rows[0][0])
                dynamic_shadow_run_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM dynamic_shadow_runs WHERE status = 'succeeded'"
                    ).fetchone()[0]
                )
                dynamic_shadow_evaluation_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM dynamic_shadow_evaluations"
                    ).fetchone()[0]
                )
            continuous_shadow_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'continuous_shadow_metadata'"
            ).fetchone()
            if continuous_shadow_table is not None:
                continuous_rows = connection.execute(
                    "SELECT schema_version FROM continuous_shadow_metadata"
                ).fetchall()
                if len(continuous_rows) != 1 or int(continuous_rows[0][0]) != 4:
                    raise CandidateStoreError(
                        "Continuous Shadow schema version is unsupported."
                    )
                continuous_shadow_schema_version = int(continuous_rows[0][0])
                continuous_shadow_experiment_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM continuous_shadow_experiments"
                    ).fetchone()[0]
                )
                continuous_shadow_poll_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM continuous_shadow_poll_runs "
                        "WHERE status = 'succeeded'"
                    ).fetchone()[0]
                )
                continuous_shadow_event_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM continuous_shadow_event_journal"
                    ).fetchone()[0]
                )
                continuous_shadow_ledger_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM continuous_shadow_ledger"
                    ).fetchone()[0]
                )
        finally:
            connection.close()
        return WalletIntelligenceDatabaseValidation(
            schema_version=WALLET_INTELLIGENCE_SCHEMA_VERSION,
            candidate_intelligence_schema_version=candidate_schema_version,
            candidate_run_count=candidate_run_count,
            candidate_pool_count=candidate_pool_count,
            copyability_membership_count=copyability_membership_count,
            copyability_run_count=copyability_run_count,
            copyability_selection_schema_version=copyability_schema_version,
            dynamic_shadow_schema_version=dynamic_shadow_schema_version,
            dynamic_shadow_run_count=dynamic_shadow_run_count,
            dynamic_shadow_evaluation_count=dynamic_shadow_evaluation_count,
            continuous_shadow_schema_version=continuous_shadow_schema_version,
            continuous_shadow_experiment_count=continuous_shadow_experiment_count,
            continuous_shadow_poll_count=continuous_shadow_poll_count,
            continuous_shadow_event_count=continuous_shadow_event_count,
            continuous_shadow_ledger_count=continuous_shadow_ledger_count,
            source_count=source_count,
            snapshot_count=snapshot_count,
            row_count=row_count,
        )

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                _read_only_uri(self._path),
                uri=True,
                timeout=5,
            )
        else:
            connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _require_integrity(connection: sqlite3.Connection) -> None:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise CandidateStoreError("Wallet-intelligence SQLite integrity check failed.")

    @staticmethod
    def _require_schema_version(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT schema_version FROM wallet_intelligence_metadata"
        ).fetchall()
        if len(rows) != 1 or int(rows[0][0]) != WALLET_INTELLIGENCE_SCHEMA_VERSION:
            raise CandidateStoreError("Wallet-intelligence schema version is unsupported.")


def _record_count_warning(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    record_count: int,
) -> str | None:
    rows = connection.execute(
        "SELECT record_count FROM candidate_wallet_snapshots WHERE source_id = ? "
        "ORDER BY accepted_at DESC LIMIT 30",
        (source_id,),
    ).fetchall()
    if len(rows) < 7:
        return None
    baseline = Decimal(str(statistics.median(int(row[0]) for row in rows)))
    if Decimal(record_count) < baseline * Decimal("0.5"):
        return "record_count_below_baseline"
    if Decimal(record_count) > baseline * Decimal("2"):
        return "record_count_above_baseline"
    return None


def _wallet_key(source_id: str, external_wallet_id: str) -> str:
    return hashlib.sha256(f"{source_id}\0{external_wallet_id}".encode()).hexdigest()


def _metrics_json(metrics: dict[str, Any]) -> str:
    return json.dumps(
        metrics,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _safe_error_message(message: str) -> str:
    if "0x" in message.lower():
        return "Candidate-wallet operation failed; protected details were omitted."
    return message[:500]


def _require_source_id(source_id: str) -> None:
    _require_safe_identifier(source_id, field_name="source_id")


def _require_safe_identifier(value: str, *, field_name: str) -> None:
    if not value or len(value) > 128 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
        for character in value
    ):
        raise ValueError(f"{field_name} is invalid")


def _utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    converted = value.astimezone(UTC)
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return converted


def _iso(value: datetime) -> str:
    return _utc(value, field_name="datetime").isoformat(timespec="microseconds")


def _parse_datetime(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value), field_name="stored datetime")


def _restrict_directory(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700)


def _restrict_file(path: Path) -> None:
    if os.name != "nt" and path.exists():
        path.chmod(0o600)
