from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from polysia.application.ports.candidate_intelligence import (
    CandidatePipelineBusyError,
    CandidatePipelineLeaseLostError,
)
from polysia.domain.wallet_intelligence import (
    CandidateIntelligenceState,
    CandidatePipelineLease,
    CandidatePolicyEvaluation,
    CandidatePoolRow,
    CandidatePoolRun,
    CandidateProcessingKey,
    CandidateSourceHistory,
    CandidateSourceObservation,
    CandidateSourceSnapshot,
    CandidateStatus,
    CandidateWalletFeature,
    DataReadinessStatus,
)
from polysia.storage.wallet_intelligence import (
    CandidateStoreError,
    WalletIntelligenceRepository,
)

CANDIDATE_INTELLIGENCE_SCHEMA_PATH = Path(__file__).with_name(
    "candidate_intelligence_schema.sql"
)
CANDIDATE_INTELLIGENCE_SCHEMA_VERSION = 1
MAX_WALLET_HISTORY_BATCH_SIZE = 64


class CandidateIntelligenceStoreError(CandidateStoreError):
    """Safe Stage 2 persistence or publication failure."""


class CandidateIntelligenceRepository:
    """SQLite owner for additive Candidate Intelligence history and publication."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        WalletIntelligenceRepository(self._path).initialize()
        connection = self._connect()
        try:
            connection.executescript(
                CANDIDATE_INTELLIGENCE_SCHEMA_PATH.read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT OR IGNORE INTO candidate_intelligence_metadata "
                "(schema_version, initialized_at) VALUES (?, ?)",
                (CANDIDATE_INTELLIGENCE_SCHEMA_VERSION, _iso(datetime.now(UTC))),
            )
            connection.commit()
            self._require_schema_version(connection)
            self._require_integrity(connection)
        finally:
            connection.close()
        _restrict_file(self._path)

    def acquire_lease(
        self,
        resource: str,
        *,
        owner_id: str,
        acquired_at: datetime,
        lease_duration: timedelta,
    ) -> CandidatePipelineLease:
        _require_identifier(resource, field_name="resource")
        _require_identifier(owner_id, field_name="owner_id")
        acquired_at = _utc(acquired_at, field_name="acquired_at")
        _require_lease_duration(lease_duration)
        expires_at = acquired_at + lease_duration
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_id, fencing_token, acquired_at, lease_expires_at "
                "FROM candidate_pipeline_leases WHERE resource = ?",
                (resource,),
            ).fetchone()
            if row is None:
                fencing_token = 1
                original_acquired_at = acquired_at
                connection.execute(
                    "INSERT INTO candidate_pipeline_leases "
                    "(resource, owner_id, fencing_token, acquired_at, heartbeat_at, "
                    "lease_expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        resource,
                        owner_id,
                        fencing_token,
                        _iso(acquired_at),
                        _iso(acquired_at),
                        _iso(expires_at),
                    ),
                )
            else:
                existing_expiry = _parse_datetime(str(row["lease_expires_at"]))
                existing_owner = str(row["owner_id"])
                if existing_expiry > acquired_at and existing_owner != owner_id:
                    raise CandidatePipelineBusyError(
                        "Wallet-intelligence pipeline is already running."
                    )
                if existing_expiry > acquired_at:
                    fencing_token = int(row["fencing_token"])
                    original_acquired_at = _parse_datetime(str(row["acquired_at"]))
                else:
                    fencing_token = int(row["fencing_token"]) + 1
                    original_acquired_at = acquired_at
                connection.execute(
                    "UPDATE candidate_pipeline_leases SET owner_id = ?, fencing_token = ?, "
                    "acquired_at = ?, heartbeat_at = ?, lease_expires_at = ? "
                    "WHERE resource = ?",
                    (
                        owner_id,
                        fencing_token,
                        _iso(original_acquired_at),
                        _iso(acquired_at),
                        _iso(expires_at),
                        resource,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return CandidatePipelineLease(
            resource=resource,
            owner_id=owner_id,
            fencing_token=fencing_token,
            acquired_at=original_acquired_at,
            heartbeat_at=acquired_at,
            lease_expires_at=expires_at,
        )

    def renew_lease(
        self,
        lease: CandidatePipelineLease,
        *,
        renewed_at: datetime,
        lease_duration: timedelta,
    ) -> CandidatePipelineLease:
        renewed_at = _utc(renewed_at, field_name="renewed_at")
        _require_lease_duration(lease_duration)
        expires_at = renewed_at + lease_duration
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE candidate_pipeline_leases SET heartbeat_at = ?, lease_expires_at = ? "
                "WHERE resource = ? AND owner_id = ? AND fencing_token = ? "
                "AND lease_expires_at > ?",
                (
                    _iso(renewed_at),
                    _iso(expires_at),
                    lease.resource,
                    lease.owner_id,
                    lease.fencing_token,
                    _iso(renewed_at),
                ),
            ).rowcount
            if updated != 1:
                raise CandidatePipelineLeaseLostError(
                    "Wallet-intelligence pipeline lease was lost before renewal."
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return CandidatePipelineLease(
            resource=lease.resource,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            acquired_at=lease.acquired_at,
            heartbeat_at=renewed_at,
            lease_expires_at=expires_at,
        )

    def release_lease(self, lease: CandidatePipelineLease) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE candidate_pipeline_leases SET lease_expires_at = heartbeat_at "
                "WHERE resource = ? AND owner_id = ? AND fencing_token = ?",
                (lease.resource, lease.owner_id, lease.fencing_token),
            )
            connection.commit()
        finally:
            connection.close()

    def load_source_history(
        self,
        source_id: str,
        source_snapshot_id: str,
    ) -> CandidateSourceHistory:
        _require_identifier(source_id, field_name="source_id")
        _require_identifier(source_snapshot_id, field_name="source_snapshot_id")
        connection = self._connect(read_only=True)
        try:
            current = connection.execute(
                "SELECT snapshot_id, source_id, accepted_at FROM candidate_wallet_snapshots "
                "WHERE snapshot_id = ?",
                (source_snapshot_id,),
            ).fetchone()
            if current is None or str(current["source_id"]) != source_id:
                raise CandidateIntelligenceStoreError(
                    "Requested healthy source snapshot is unavailable."
                )
            accepted_at = str(current["accepted_at"])
            snapshot_rows = connection.execute(
                "SELECT snapshot_id, captured_at, accepted_at "
                "FROM candidate_wallet_snapshots WHERE source_id = ? AND accepted_at <= ? "
                "ORDER BY accepted_at, snapshot_id",
                (source_id, accepted_at),
            ).fetchall()
            observation_rows = connection.execute(
                "SELECT s.snapshot_id, s.captured_at, s.accepted_at, r.wallet_key, "
                "i.external_wallet_id, r.source_rank, r.metrics_json "
                "FROM candidate_wallet_snapshots s "
                "JOIN candidate_wallet_snapshot_rows r ON r.snapshot_id = s.snapshot_id "
                "JOIN candidate_wallet_identities i ON i.wallet_key = r.wallet_key "
                "WHERE s.snapshot_id = ? AND s.source_id = ? AND i.source_id = ? "
                "ORDER BY r.source_rank, r.wallet_key",
                (source_snapshot_id, source_id, source_id),
            ).fetchall()
        finally:
            connection.close()
        snapshots = tuple(
            CandidateSourceSnapshot(
                snapshot_id=str(row["snapshot_id"]),
                captured_at=_parse_datetime(str(row["captured_at"])),
                accepted_at=_parse_datetime(str(row["accepted_at"])),
            )
            for row in snapshot_rows
        )
        if not snapshots or snapshots[-1].snapshot_id != source_snapshot_id:
            raise CandidateIntelligenceStoreError(
                "Source history did not end at the requested snapshot."
            )
        current_observations = tuple(_source_observation(row) for row in observation_rows)
        if not current_observations:
            raise CandidateIntelligenceStoreError("Source snapshot contains no wallet rows.")
        return CandidateSourceHistory(
            source_id=source_id,
            current_snapshot_id=source_snapshot_id,
            snapshots=snapshots,
            current_observations=current_observations,
        )

    def load_wallet_histories(
        self,
        source_id: str,
        source_snapshot_id: str,
        wallet_keys: tuple[str, ...],
    ) -> dict[str, tuple[CandidateSourceObservation, ...]]:
        _require_identifier(source_id, field_name="source_id")
        _require_identifier(source_snapshot_id, field_name="source_snapshot_id")
        if not wallet_keys or len(wallet_keys) > MAX_WALLET_HISTORY_BATCH_SIZE:
            raise ValueError(
                f"wallet_keys must contain 1 to {MAX_WALLET_HISTORY_BATCH_SIZE} values"
            )
        if len(set(wallet_keys)) != len(wallet_keys):
            raise ValueError("wallet_keys must be unique")
        for wallet_key in wallet_keys:
            _require_identifier(wallet_key, field_name="wallet_key")
        connection = self._connect(read_only=True)
        try:
            current = connection.execute(
                "SELECT source_id, accepted_at FROM candidate_wallet_snapshots "
                "WHERE snapshot_id = ?",
                (source_snapshot_id,),
            ).fetchone()
            if current is None or str(current["source_id"]) != source_id:
                raise CandidateIntelligenceStoreError(
                    "Requested healthy source snapshot is unavailable."
                )
            placeholders = ",".join("?" for _ in wallet_keys)
            rows = connection.execute(
                "SELECT s.snapshot_id, s.captured_at, s.accepted_at, r.wallet_key, "
                "i.external_wallet_id, r.source_rank, r.metrics_json "
                "FROM candidate_wallet_snapshots s "
                "JOIN candidate_wallet_snapshot_rows r ON r.snapshot_id = s.snapshot_id "
                "JOIN candidate_wallet_identities i ON i.wallet_key = r.wallet_key "
                "WHERE s.source_id = ? AND i.source_id = ? AND s.accepted_at <= ? "
                f"AND r.wallet_key IN ({placeholders}) "
                "ORDER BY r.wallet_key, s.accepted_at, s.snapshot_id",
                (
                    source_id,
                    source_id,
                    str(current["accepted_at"]),
                    *wallet_keys,
                ),
            ).fetchall()
        finally:
            connection.close()
        histories: dict[str, list[CandidateSourceObservation]] = {
            wallet_key: [] for wallet_key in wallet_keys
        }
        for row in rows:
            histories[str(row["wallet_key"])].append(_source_observation(row))
        result = {wallet_key: tuple(histories[wallet_key]) for wallet_key in wallet_keys}
        if any(
            not observations or observations[-1].snapshot_id != source_snapshot_id
            for observations in result.values()
        ):
            raise CandidateIntelligenceStoreError(
                "Current wallet history did not reconcile with the source snapshot."
            )
        return result

    def successful_run(self, key: CandidateProcessingKey) -> CandidatePoolRun | None:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM candidate_intelligence_runs WHERE source_snapshot_id = ? "
                "AND feature_set_version = ? AND policy_id = ? AND policy_version = ? "
                "AND ranking_version = ? AND status = 'succeeded' LIMIT 1",
                (
                    key.source_snapshot_id,
                    key.feature_set_version,
                    key.policy_id,
                    key.policy_version,
                    key.ranking_version,
                ),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _pool_run(row)

    def start_run(
        self,
        key: CandidateProcessingKey,
        *,
        source_id: str,
        started_at: datetime,
    ) -> str:
        _require_identifier(source_id, field_name="source_id")
        started_at = _utc(started_at, field_name="started_at")
        run_id = str(uuid.uuid4())
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO candidate_intelligence_runs "
                "(run_id, source_id, source_snapshot_id, feature_set_version, policy_id, "
                "policy_version, ranking_version, status, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)",
                (
                    run_id,
                    source_id,
                    key.source_snapshot_id,
                    key.feature_set_version,
                    key.policy_id,
                    key.policy_version,
                    key.ranking_version,
                    _iso(started_at),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return run_id

    def fail_run(
        self,
        run_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        failed_at = _utc(failed_at, field_name="failed_at")
        _require_identifier(error_code, field_name="error_code")
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE candidate_intelligence_runs SET status = 'failed', failed_at = ?, "
                "error_code = ?, error_message = ? WHERE run_id = ? AND status = 'running'",
                (_iso(failed_at), error_code, _safe_message(error_message), run_id),
            )
            connection.commit()
        finally:
            connection.close()

    def publish_run(
        self,
        run_id: str,
        *,
        lease: CandidatePipelineLease,
        features: tuple[CandidateWalletFeature, ...],
        evaluations: tuple[CandidatePolicyEvaluation, ...],
        published_at: datetime,
    ) -> CandidatePoolRun:
        published_at = _utc(published_at, field_name="published_at")
        _validate_publication(features, evaluations)
        feature_by_wallet = {feature.wallet_id: feature for feature in features}
        status_counts = Counter(evaluation.candidate_status for evaluation in evaluations)
        readiness_counts = Counter(
            feature.data_readiness_status for feature in features
        )
        calculated_at = features[0].calculated_at
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_live_lease(connection, lease, at=published_at)
            run = connection.execute(
                "SELECT * FROM candidate_intelligence_runs "
                "WHERE run_id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if run is None:
                raise CandidateIntelligenceStoreError(
                    "Candidate Intelligence run is not open for publication."
                )
            source_id = str(run["source_id"])
            for feature in features:
                connection.execute(
                    "INSERT INTO canonical_wallets "
                    "(wallet_id, chain, normalized_address, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(wallet_id) DO UPDATE SET "
                    "updated_at = excluded.updated_at",
                    (
                        feature.wallet_id,
                        feature.chain,
                        feature.normalized_address,
                        _iso(feature.first_seen_at),
                        _iso(feature.last_seen_at),
                    ),
                )
                canonical = connection.execute(
                    "SELECT chain, normalized_address FROM canonical_wallets "
                    "WHERE wallet_id = ?",
                    (feature.wallet_id,),
                ).fetchone()
                if canonical is None or (
                    str(canonical["chain"]), str(canonical["normalized_address"])
                ) != (feature.chain, feature.normalized_address):
                    raise CandidateIntelligenceStoreError(
                        "Canonical wallet identity did not reconcile."
                    )
                connection.execute(
                    "INSERT INTO wallet_source_links "
                    "(source_id, source_wallet_key, wallet_id, linked_at, last_seen_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_id, source_wallet_key) "
                    "DO UPDATE SET last_seen_at = excluded.last_seen_at",
                    (
                        source_id,
                        feature.source_wallet_key,
                        feature.wallet_id,
                        _iso(feature.first_seen_at),
                        _iso(feature.last_seen_at),
                    ),
                )
                link = connection.execute(
                    "SELECT wallet_id FROM wallet_source_links "
                    "WHERE source_id = ? AND source_wallet_key = ?",
                    (source_id, feature.source_wallet_key),
                ).fetchone()
                if link is None or str(link["wallet_id"]) != feature.wallet_id:
                    raise CandidateIntelligenceStoreError(
                        "Source wallet link did not reconcile."
                    )
                self._insert_feature(connection, run_id, feature)
            for evaluation in evaluations:
                connection.execute(
                    "INSERT INTO candidate_policy_evaluations "
                    "(run_id, wallet_id, candidate_status, candidate_rank, "
                    "policy_reasons_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        run_id,
                        evaluation.wallet_id,
                        evaluation.candidate_status.value,
                        evaluation.candidate_rank,
                        _json_array(evaluation.policy_reasons),
                    ),
                )
            if set(feature_by_wallet) != {item.wallet_id for item in evaluations}:
                raise CandidateIntelligenceStoreError(
                    "Feature and policy wallet sets did not reconcile."
                )
            counts = (
                len(features),
                status_counts[CandidateStatus.SELECTED],
                status_counts[CandidateStatus.WATCHLIST],
                status_counts[CandidateStatus.INELIGIBLE],
                readiness_counts[DataReadinessStatus.READY],
                readiness_counts[DataReadinessStatus.PARTIAL],
                readiness_counts[DataReadinessStatus.STALE],
                readiness_counts[DataReadinessStatus.INVALID],
                readiness_counts[DataReadinessStatus.UNKNOWN],
            )
            if sum(counts[1:4]) != counts[0] or sum(counts[4:]) != counts[0]:
                raise CandidateIntelligenceStoreError(
                    "Candidate Intelligence publication counts did not reconcile."
                )
            updated = connection.execute(
                "UPDATE candidate_intelligence_runs SET status = 'succeeded', "
                "calculated_at = ?, published_at = ?, evaluated_count = ?, "
                "selected_count = ?, watchlist_count = ?, ineligible_count = ?, "
                "ready_count = ?, partial_count = ?, stale_count = ?, invalid_count = ?, "
                "unknown_count = ? WHERE run_id = ? AND status = 'running'",
                (_iso(calculated_at), _iso(published_at), *counts, run_id),
            ).rowcount
            if updated != 1:
                raise CandidateIntelligenceStoreError(
                    "Candidate Intelligence run completion was not recorded."
                )
            connection.execute(
                "INSERT INTO candidate_intelligence_current (source_id, run_id, published_at) "
                "VALUES (?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
                "run_id = excluded.run_id, published_at = excluded.published_at",
                (source_id, run_id, _iso(published_at)),
            )
            completed = connection.execute(
                "SELECT * FROM candidate_intelligence_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if completed is None:
            raise CandidateIntelligenceStoreError("Published run is unavailable.")
        _restrict_file(self._path)
        return _pool_run(completed)

    def current_run(self, source_id: str) -> CandidatePoolRun | None:
        _require_identifier(source_id, field_name="source_id")
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT r.* FROM candidate_intelligence_current c "
                "JOIN candidate_intelligence_runs r ON r.run_id = c.run_id "
                "WHERE c.source_id = ? AND r.status = 'succeeded'",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _pool_run(row)

    def state(self, source_id: str) -> CandidateIntelligenceState:
        _require_identifier(source_id, field_name="source_id")
        connection = self._connect(read_only=True)
        try:
            current = connection.execute(
                "SELECT r.* FROM candidate_intelligence_current c "
                "JOIN candidate_intelligence_runs r ON r.run_id = c.run_id "
                "WHERE c.source_id = ? AND r.status = 'succeeded'",
                (source_id,),
            ).fetchone()
            latest = connection.execute(
                "SELECT run_id, status, error_code FROM candidate_intelligence_runs "
                "WHERE source_id = ? ORDER BY started_at DESC, run_id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        return CandidateIntelligenceState(
            source_id=source_id,
            current_run=None if current is None else _pool_run(current),
            last_run_id=None if latest is None else str(latest["run_id"]),
            last_run_status=None if latest is None else str(latest["status"]),
            last_error_code=None
            if latest is None or latest["error_code"] is None
            else str(latest["error_code"]),
        )

    def current_pool(
        self,
        source_id: str,
        *,
        limit: int | None = None,
        selected_only: bool = False,
    ) -> tuple[CandidatePoolRow, ...]:
        _require_identifier(source_id, field_name="source_id")
        if limit is not None and not 1 <= limit <= 100_000:
            raise ValueError("limit must be between 1 and 100000")
        query = "SELECT * FROM candidate_trading_pool_current WHERE source_id = ?"
        parameters: list[object] = [source_id]
        if selected_only:
            query += " AND candidate_status = 'SELECTED'"
        query += (
            " ORDER BY CASE candidate_status WHEN 'SELECTED' THEN 0 "
            "WHEN 'WATCHLIST' THEN 1 ELSE 2 END, "
            "candidate_rank IS NULL, candidate_rank, source_rank, wallet_id"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
        return tuple(_pool_row(row) for row in rows)

    def prune_history(self, *, cutoff: datetime) -> None:
        cutoff = _utc(cutoff, field_name="cutoff")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM candidate_intelligence_runs WHERE "
                "COALESCE(published_at, failed_at, started_at) < ? "
                "AND run_id NOT IN (SELECT run_id FROM candidate_intelligence_current)",
                (_iso(cutoff),),
            )
            connection.execute(
                "DELETE FROM canonical_wallets WHERE wallet_id NOT IN "
                "(SELECT wallet_id FROM wallet_source_links) AND wallet_id NOT IN "
                "(SELECT wallet_id FROM candidate_wallet_features)"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def validate_integrity(self) -> None:
        connection = self._connect(read_only=True)
        try:
            self._require_integrity(connection)
            self._require_schema_version(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise CandidateIntelligenceStoreError(
                    "Candidate Intelligence foreign-key check failed."
                )
        finally:
            connection.close()

    @staticmethod
    def _insert_feature(
        connection: sqlite3.Connection,
        run_id: str,
        feature: CandidateWalletFeature,
    ) -> None:
        connection.execute(
            "INSERT INTO candidate_wallet_features ("
            "run_id, wallet_id, source_wallet_key, source_rank, source_score, "
            "source_metrics_json, effective_at, observed_at, ingested_at, calculated_at, "
            "first_seen_at, last_seen_at, observation_count, observed_days, "
            "eligible_snapshot_count, presence_ratio, data_age_seconds, "
            "stale_after_seconds, is_stale, "
            "previous_rank, rank_delta_previous, rank_delta_1d, rank_delta_7d, "
            "rank_delta_30d, best_rank, worst_rank, rank_volatility, rank_stability, "
            "score_delta_previous, score_delta_1d, score_delta_7d, score_delta_30d, "
            "score_volatility, score_stability, data_readiness_status, "
            "readiness_reasons_json) VALUES ("
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                feature.wallet_id,
                feature.source_wallet_key,
                feature.source_rank,
                _decimal_text(feature.source_score),
                feature.source_metrics_json,
                _iso(feature.effective_at),
                _iso(feature.observed_at),
                _iso(feature.ingested_at),
                _iso(feature.calculated_at),
                _iso(feature.first_seen_at),
                _iso(feature.last_seen_at),
                feature.observation_count,
                feature.observed_days,
                feature.eligible_snapshot_count,
                _decimal_text(feature.presence_ratio),
                feature.data_age_seconds,
                feature.stale_after_seconds,
                int(feature.is_stale),
                feature.previous_rank,
                feature.rank_delta_previous,
                feature.rank_delta_1d,
                feature.rank_delta_7d,
                feature.rank_delta_30d,
                feature.best_rank,
                feature.worst_rank,
                _decimal_text(feature.rank_volatility),
                _decimal_text(feature.rank_stability),
                _decimal_text(feature.score_delta_previous),
                _decimal_text(feature.score_delta_1d),
                _decimal_text(feature.score_delta_7d),
                _decimal_text(feature.score_delta_30d),
                _decimal_text(feature.score_volatility),
                _decimal_text(feature.score_stability),
                feature.data_readiness_status.value,
                _json_array(feature.readiness_reasons),
            ),
        )

    @staticmethod
    def _assert_live_lease(
        connection: sqlite3.Connection,
        lease: CandidatePipelineLease,
        *,
        at: datetime,
    ) -> None:
        row = connection.execute(
            "SELECT 1 FROM candidate_pipeline_leases WHERE resource = ? AND owner_id = ? "
            "AND fencing_token = ? AND lease_expires_at > ?",
            (lease.resource, lease.owner_id, lease.fencing_token, _iso(at)),
        ).fetchone()
        if row is None:
            raise CandidatePipelineLeaseLostError(
                "Wallet-intelligence pipeline lease was lost before publication."
            )

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                f"{self._path.resolve().as_uri()}?mode=ro",
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
    def _require_schema_version(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT schema_version FROM candidate_intelligence_metadata"
        ).fetchall()
        if len(rows) != 1 or int(rows[0][0]) != CANDIDATE_INTELLIGENCE_SCHEMA_VERSION:
            raise CandidateIntelligenceStoreError(
                "Candidate Intelligence schema version is unsupported."
            )

    @staticmethod
    def _require_integrity(connection: sqlite3.Connection) -> None:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise CandidateIntelligenceStoreError(
                "Candidate Intelligence SQLite integrity check failed."
            )


def _source_score(metrics_json: str) -> Decimal | None:
    try:
        metrics = json.loads(metrics_json)
        value = metrics.get("score")
        if value is None or isinstance(value, bool):
            return None
        score = Decimal(str(value))
    except (AttributeError, InvalidOperation, TypeError, ValueError) as error:
        raise CandidateIntelligenceStoreError("Stored source score is invalid.") from error
    return score if score.is_finite() else None


def _source_observation(row: sqlite3.Row) -> CandidateSourceObservation:
    return CandidateSourceObservation(
        snapshot_id=str(row["snapshot_id"]),
        wallet_key=str(row["wallet_key"]),
        external_wallet_id=str(row["external_wallet_id"]),
        source_rank=int(row["source_rank"]),
        source_score=_source_score(str(row["metrics_json"])),
        source_metrics_json=str(row["metrics_json"]),
        captured_at=_parse_datetime(str(row["captured_at"])),
        accepted_at=_parse_datetime(str(row["accepted_at"])),
    )


def _validate_publication(
    features: tuple[CandidateWalletFeature, ...],
    evaluations: tuple[CandidatePolicyEvaluation, ...],
) -> None:
    if not features or len(features) != len(evaluations):
        raise CandidateIntelligenceStoreError(
            "Candidate Intelligence publication must be complete and non-empty."
        )
    feature_ids = [feature.wallet_id for feature in features]
    evaluation_ids = [evaluation.wallet_id for evaluation in evaluations]
    if len(set(feature_ids)) != len(feature_ids) or set(feature_ids) != set(evaluation_ids):
        raise CandidateIntelligenceStoreError(
            "Candidate Intelligence publication contains duplicate or mismatched wallets."
        )
    selected = tuple(
        evaluation
        for evaluation in evaluations
        if evaluation.candidate_status is CandidateStatus.SELECTED
    )
    if any(evaluation.candidate_rank is None for evaluation in selected):
        raise CandidateIntelligenceStoreError(
            "Every selected candidate must have a candidate rank."
        )
    selected_ranks = sorted(
        evaluation.candidate_rank
        for evaluation in selected
        if evaluation.candidate_rank is not None
    )
    if any(
        evaluation.candidate_rank is not None
        for evaluation in evaluations
        if evaluation.candidate_status is not CandidateStatus.SELECTED
    ) or selected_ranks != list(range(1, len(selected_ranks) + 1)):
        raise CandidateIntelligenceStoreError(
            "Selected candidate ranks must be complete, contiguous, and exclusive."
        )
    calculated_times = {feature.calculated_at for feature in features}
    if len(calculated_times) != 1:
        raise CandidateIntelligenceStoreError(
            "Candidate features must share one calculation time."
        )


def _pool_run(row: sqlite3.Row) -> CandidatePoolRun:
    required_counts = (
        "evaluated_count",
        "selected_count",
        "watchlist_count",
        "ineligible_count",
        "ready_count",
        "partial_count",
        "stale_count",
        "invalid_count",
        "unknown_count",
    )
    if any(row[name] is None for name in required_counts):
        raise CandidateIntelligenceStoreError("Successful candidate run has incomplete counts.")
    return CandidatePoolRun(
        run_id=str(row["run_id"]),
        key=CandidateProcessingKey(
            source_snapshot_id=str(row["source_snapshot_id"]),
            feature_set_version=str(row["feature_set_version"]),
            policy_id=str(row["policy_id"]),
            policy_version=str(row["policy_version"]),
            ranking_version=str(row["ranking_version"]),
        ),
        source_id=str(row["source_id"]),
        calculated_at=_parse_datetime(str(row["calculated_at"])),
        published_at=_parse_datetime(str(row["published_at"])),
        evaluated_count=int(row["evaluated_count"]),
        selected_count=int(row["selected_count"]),
        watchlist_count=int(row["watchlist_count"]),
        ineligible_count=int(row["ineligible_count"]),
        ready_count=int(row["ready_count"]),
        partial_count=int(row["partial_count"]),
        stale_count=int(row["stale_count"]),
        invalid_count=int(row["invalid_count"]),
        unknown_count=int(row["unknown_count"]),
    )


def _pool_row(row: sqlite3.Row) -> CandidatePoolRow:
    score = None if row["source_score"] is None else Decimal(str(row["source_score"]))
    return CandidatePoolRow(
        wallet_id=str(row["wallet_id"]),
        chain=str(row["chain"]),
        source_id=str(row["source_id"]),
        source_snapshot_id=str(row["source_snapshot_id"]),
        source_rank=int(row["source_rank"]),
        source_score=score,
        presence_ratio=Decimal(str(row["presence_ratio"])),
        data_age_seconds=int(row["data_age_seconds"]),
        data_readiness_status=DataReadinessStatus(str(row["data_readiness_status"])),
        candidate_status=CandidateStatus(str(row["candidate_status"])),
        candidate_rank=None
        if row["candidate_rank"] is None
        else int(row["candidate_rank"]),
        effective_at=_parse_datetime(str(row["effective_at"])),
        ingested_at=_parse_datetime(str(row["ingested_at"])),
        calculated_at=_parse_datetime(str(row["calculated_at"])),
        feature_set_version=str(row["feature_set_version"]),
        policy_id=str(row["policy_id"]),
        policy_version=str(row["policy_version"]),
        ranking_version=str(row["ranking_version"]),
    )


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _safe_message(message: str) -> str:
    if "0x" in message.lower():
        return "Candidate Intelligence failed; protected details were omitted."
    return message[:500]


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value or len(value) > 128 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
        for character in value
    ):
        raise ValueError(f"{field_name} is invalid")


def _require_lease_duration(value: timedelta) -> None:
    if value < timedelta(seconds=10) or value > timedelta(hours=24):
        raise ValueError("lease_duration must be between 10 seconds and 24 hours")


def _utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value, field_name="datetime").isoformat(timespec="microseconds")


def _parse_datetime(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value), field_name="stored datetime")


def _restrict_file(path: Path) -> None:
    if os.name != "nt" and path.exists():
        path.chmod(0o600)
