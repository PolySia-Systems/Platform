from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polysia.application.ports.candidate_intelligence import CandidatePipelineLeaseLostError
from polysia.domain.wallet_intelligence import (
    CandidatePipelineLease,
    CandidateStatus,
    DataReadinessStatus,
)
from polysia.domain.wallet_intelligence.copyability_selection import (
    CopyabilityEvidence,
    CopyabilityMembership,
    CopyabilityPoolRow,
    CopyabilityProcessingKey,
    CopyabilityScore,
    CopyabilitySelectionRun,
    CopyabilitySelectionState,
    SelectionPoolId,
    SelectionStatus,
)
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.wallet_intelligence import CandidateStoreError

COPYABILITY_SELECTION_SCHEMA_PATH = Path(__file__).with_name(
    "copyability_selection_schema.sql"
)
COPYABILITY_SELECTION_SCHEMA_VERSION = 1


class CopyabilitySelectionStoreError(CandidateStoreError):
    """Safe Stage 3 persistence or publication failure."""


class CopyabilitySelectionRepository:
    """SQLite owner for additive copyability-selection history and publication."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self, *, verify_integrity: bool = True) -> None:
        CandidateIntelligenceRepository(self._path).initialize(verify_integrity=False)
        connection = self._connect()
        try:
            connection.executescript(
                COPYABILITY_SELECTION_SCHEMA_PATH.read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT OR IGNORE INTO copyability_selection_metadata "
                "(schema_version, initialized_at) VALUES (?, ?)",
                (COPYABILITY_SELECTION_SCHEMA_VERSION, _iso(datetime.now(UTC))),
            )
            connection.commit()
            self._require_schema_version(connection)
            if verify_integrity:
                self._require_integrity(connection)
        finally:
            connection.close()
        _restrict_file(self._path)

    def load_evidence(
        self,
        source_id: str,
        stage2_run_id: str,
    ) -> tuple[CopyabilityEvidence, ...]:
        _require_identifier(source_id, field_name="source_id")
        _require_identifier(stage2_run_id, field_name="stage2_run_id")
        connection = self._connect(read_only=True)
        try:
            run = connection.execute(
                "SELECT run_id, source_id, source_snapshot_id FROM candidate_intelligence_runs "
                "WHERE run_id = ? AND status = 'succeeded'",
                (stage2_run_id,),
            ).fetchone()
            if run is None or str(run["source_id"]) != source_id:
                raise CopyabilitySelectionStoreError(
                    "Healthy Stage 2 run is unavailable for copyability selection."
                )
            rows = connection.execute(
                "SELECT f.wallet_id, f.source_rank, f.source_score, f.source_metrics_json, "
                "f.effective_at, f.observed_at, f.ingested_at, f.calculated_at, "
                "f.observation_count, f.observed_days, f.presence_ratio, "
                "f.rank_delta_7d, f.rank_delta_30d, f.score_delta_7d, f.score_delta_30d, "
                "f.rank_stability, f.score_stability, f.data_readiness_status, "
                "e.candidate_status "
                "FROM candidate_wallet_features f "
                "JOIN candidate_policy_evaluations e "
                "ON e.run_id = f.run_id AND e.wallet_id = f.wallet_id "
                "WHERE f.run_id = ? ORDER BY f.wallet_id",
                (stage2_run_id,),
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            raise CopyabilitySelectionStoreError(
                "Stage 2 run has no published wallet features."
            )
        return tuple(
            CopyabilityEvidence(
                wallet_id=str(row["wallet_id"]),
                stage2_run_id=stage2_run_id,
                source_id=source_id,
                source_snapshot_id=str(run["source_snapshot_id"]),
                source_rank=int(row["source_rank"]),
                source_score=_optional_decimal(row["source_score"]),
                source_metrics_json=str(row["source_metrics_json"]),
                effective_at=_parse_datetime(str(row["effective_at"])),
                observed_at=_parse_datetime(str(row["observed_at"])),
                ingested_at=_parse_datetime(str(row["ingested_at"])),
                stage2_calculated_at=_parse_datetime(str(row["calculated_at"])),
                observation_count=int(row["observation_count"]),
                observed_days=int(row["observed_days"]),
                presence_ratio=Decimal(str(row["presence_ratio"])),
                rank_delta_7d=_optional_int(row["rank_delta_7d"]),
                rank_delta_30d=_optional_int(row["rank_delta_30d"]),
                score_delta_7d=_optional_decimal(row["score_delta_7d"]),
                score_delta_30d=_optional_decimal(row["score_delta_30d"]),
                rank_stability=_optional_decimal(row["rank_stability"]),
                score_stability=_optional_decimal(row["score_stability"]),
                data_readiness_status=DataReadinessStatus(str(row["data_readiness_status"])),
                candidate_status=CandidateStatus(str(row["candidate_status"])),
            )
            for row in rows
        )

    def successful_run(self, key: CopyabilityProcessingKey) -> CopyabilitySelectionRun | None:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM copyability_selection_runs WHERE stage2_run_id = ? "
                "AND feature_set_version = ? AND policy_id = ? AND policy_version = ? "
                "AND ranking_version = ? AND status = 'succeeded' LIMIT 1",
                (
                    key.stage2_run_id,
                    key.feature_set_version,
                    key.policy_id,
                    key.policy_version,
                    key.ranking_version,
                ),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _selection_run(row)

    def start_run(
        self,
        key: CopyabilityProcessingKey,
        *,
        source_id: str,
        source_snapshot_id: str,
        started_at: datetime,
    ) -> str:
        _require_identifier(source_id, field_name="source_id")
        _require_identifier(source_snapshot_id, field_name="source_snapshot_id")
        started_at = _utc(started_at, field_name="started_at")
        run_id = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO copyability_selection_runs ("
                "run_id, source_id, source_snapshot_id, stage2_run_id, feature_set_version, "
                "policy_id, policy_version, ranking_version, status, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)",
                (
                    run_id,
                    source_id,
                    source_snapshot_id,
                    key.stage2_run_id,
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
                "UPDATE copyability_selection_runs SET status = 'failed', failed_at = ?, "
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
        scores: tuple[CopyabilityScore, ...],
        memberships: tuple[CopyabilityMembership, ...],
        published_at: datetime,
    ) -> CopyabilitySelectionRun:
        published_at = _utc(published_at, field_name="published_at")
        _validate_publication(scores, memberships)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_live_lease(connection, lease, at=published_at)
            run = connection.execute(
                "SELECT * FROM copyability_selection_runs "
                "WHERE run_id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if run is None:
                raise CopyabilitySelectionStoreError(
                    "Copyability selection run is not open for publication."
                )
            source_id = str(run["source_id"])
            for score in scores:
                connection.execute(
                    "INSERT INTO copyability_wallet_scores ("
                    "run_id, wallet_id, performance_score, recent_edge_score, activity_score, "
                    "copyability_score, hedging_risk_score, confidence_score, stability_score, "
                    "alpha_score, status, reasons_json, effective_at, observed_at, ingested_at, "
                    "calculated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        score.wallet_id,
                        _decimal_text(score.performance_score),
                        _decimal_text(score.recent_edge_score),
                        _decimal_text(score.activity_score),
                        _decimal_text(score.copyability_score),
                        _decimal_text(score.hedging_risk_score),
                        _decimal_text(score.confidence_score),
                        _decimal_text(score.stability_score),
                        _decimal_text(score.alpha_score),
                        score.status.value,
                        _json_array(score.reasons),
                        _iso(score.effective_at),
                        _iso(score.observed_at),
                        _iso(score.ingested_at),
                        _iso(score.calculated_at),
                    ),
                )
            for membership in memberships:
                connection.execute(
                    "INSERT INTO copyability_pool_memberships ("
                    "run_id, pool_id, wallet_id, pool_rank, reasons_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        run_id,
                        membership.pool_id.value,
                        membership.wallet_id,
                        membership.pool_rank,
                        _json_array(membership.reasons),
                    ),
                )
            alpha_count = sum(
                1 for item in memberships if item.pool_id is SelectionPoolId.SHADOW_ALPHA
            )
            stress_count = sum(
                1 for item in memberships if item.pool_id is SelectionPoolId.SHADOW_STRESS
            )
            rejected_count = sum(
                1 for item in memberships if item.pool_id is SelectionPoolId.REJECTED
            )
            alpha_ids = {
                item.wallet_id
                for item in memberships
                if item.pool_id is SelectionPoolId.SHADOW_ALPHA
            }
            stress_ids = {
                item.wallet_id
                for item in memberships
                if item.pool_id is SelectionPoolId.SHADOW_STRESS
            }
            overlap_count = len(alpha_ids & stress_ids)
            watchlist_count = sum(
                1 for item in scores if item.status is SelectionStatus.WATCHLIST
            )
            calculated_at = scores[0].calculated_at
            updated = connection.execute(
                "UPDATE copyability_selection_runs SET status = 'succeeded', "
                "calculated_at = ?, published_at = ?, evaluated_count = ?, alpha_count = ?, "
                "stress_count = ?, live_review_count = 0, rejected_count = ?, "
                "watchlist_count = ?, overlap_count = ? "
                "WHERE run_id = ? AND status = 'running'",
                (
                    _iso(calculated_at),
                    _iso(published_at),
                    len(scores),
                    alpha_count,
                    stress_count,
                    rejected_count,
                    watchlist_count,
                    overlap_count,
                    run_id,
                ),
            ).rowcount
            if updated != 1:
                raise CopyabilitySelectionStoreError(
                    "Copyability selection run completion was not recorded."
                )
            connection.execute(
                "INSERT INTO copyability_selection_current (source_id, run_id, published_at) "
                "VALUES (?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
                "run_id = excluded.run_id, published_at = excluded.published_at",
                (source_id, run_id, _iso(published_at)),
            )
            completed = connection.execute(
                "SELECT * FROM copyability_selection_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if completed is None:
            raise CopyabilitySelectionStoreError("Published copyability run is unavailable.")
        _restrict_file(self._path)
        return _selection_run(completed)

    def current_run(self, source_id: str) -> CopyabilitySelectionRun | None:
        _require_identifier(source_id, field_name="source_id")
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT r.* FROM copyability_selection_current c "
                "JOIN copyability_selection_runs r ON r.run_id = c.run_id "
                "WHERE c.source_id = ? AND r.status = 'succeeded'",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _selection_run(row)

    def state(self, source_id: str) -> CopyabilitySelectionState:
        _require_identifier(source_id, field_name="source_id")
        connection = self._connect(read_only=True)
        try:
            current = connection.execute(
                "SELECT r.* FROM copyability_selection_current c "
                "JOIN copyability_selection_runs r ON r.run_id = c.run_id "
                "WHERE c.source_id = ? AND r.status = 'succeeded'",
                (source_id,),
            ).fetchone()
            latest = connection.execute(
                "SELECT run_id, status, error_code FROM copyability_selection_runs "
                "WHERE source_id = ? ORDER BY started_at DESC, run_id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        return CopyabilitySelectionState(
            source_id=source_id,
            current_run=None if current is None else _selection_run(current),
            last_run_id=None if latest is None else str(latest["run_id"]),
            last_run_status=None if latest is None else str(latest["status"]),
            last_error_code=None
            if latest is None or latest["error_code"] is None
            else str(latest["error_code"]),
        )

    def current_pool(
        self,
        source_id: str,
        pool_id: SelectionPoolId,
        *,
        limit: int | None = None,
    ) -> tuple[CopyabilityPoolRow, ...]:
        _require_identifier(source_id, field_name="source_id")
        if limit is not None and not 1 <= limit <= 100_000:
            raise ValueError("limit must be between 1 and 100000")
        query = (
            "SELECT * FROM copyability_pools_current WHERE source_id = ? AND pool_id = ? "
            "ORDER BY pool_rank IS NULL, pool_rank, wallet_id"
        )
        parameters: list[object] = [source_id, pool_id.value]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
        return tuple(_pool_row(row) for row in rows)

    def current_status_rows(
        self,
        source_id: str,
        status: SelectionStatus,
        *,
        limit: int | None = None,
    ) -> tuple[CopyabilityPoolRow, ...]:
        _require_identifier(source_id, field_name="source_id")
        if limit is not None and not 1 <= limit <= 100_000:
            raise ValueError("limit must be between 1 and 100000")
        query = (
            "SELECT s.wallet_id, r.source_id, r.source_snapshot_id, r.stage2_run_id, "
            "'' AS pool_id, NULL AS pool_rank, s.status, s.alpha_score, s.copyability_score, "
            "s.performance_score, s.recent_edge_score, s.activity_score, s.hedging_risk_score, "
            "s.confidence_score, s.stability_score, s.reasons_json, s.effective_at, "
            "s.observed_at, s.ingested_at, s.calculated_at, r.feature_set_version, "
            "r.policy_id, r.policy_version, r.ranking_version, r.run_id "
            "FROM copyability_selection_current c "
            "JOIN copyability_selection_runs r ON r.run_id = c.run_id "
            "JOIN copyability_wallet_scores s ON s.run_id = r.run_id "
            "WHERE c.source_id = ? AND s.status = ? ORDER BY s.wallet_id"
        )
        parameters: list[object] = [source_id, status.value]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
        return tuple(_status_row(row) for row in rows)

    def prune_history(self, *, cutoff: datetime) -> None:
        cutoff = _utc(cutoff, field_name="cutoff")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM copyability_selection_runs WHERE "
                "COALESCE(published_at, failed_at, started_at) < ? "
                "AND run_id NOT IN (SELECT run_id FROM copyability_selection_current)",
                (_iso(cutoff),),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
                "Wallet-intelligence pipeline lease was lost before copyability publication."
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
            "SELECT schema_version FROM copyability_selection_metadata"
        ).fetchall()
        if len(rows) != 1 or int(rows[0][0]) != COPYABILITY_SELECTION_SCHEMA_VERSION:
            raise CopyabilitySelectionStoreError(
                "Copyability selection schema version is unsupported."
            )

    @staticmethod
    def _require_integrity(connection: sqlite3.Connection) -> None:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise CopyabilitySelectionStoreError(
                "Copyability selection SQLite integrity check failed."
            )


def _validate_publication(
    scores: tuple[CopyabilityScore, ...],
    memberships: tuple[CopyabilityMembership, ...],
) -> None:
    if not scores:
        raise CopyabilitySelectionStoreError("Copyability publication must be non-empty.")
    wallet_ids = [item.wallet_id for item in scores]
    if len(set(wallet_ids)) != len(wallet_ids):
        raise CopyabilitySelectionStoreError("Copyability scores contain duplicate wallets.")
    score_ids = set(wallet_ids)
    for membership in memberships:
        if membership.wallet_id not in score_ids:
            raise CopyabilitySelectionStoreError(
                "Copyability membership references an unknown wallet."
            )
    live_review = [
        item for item in memberships if item.pool_id is SelectionPoolId.LIVE_REVIEW_CANDIDATE
    ]
    if live_review:
        raise CopyabilitySelectionStoreError(
            "LIVE_REVIEW_CANDIDATE must remain empty until independent evidence exists."
        )
    calculated_times = {item.calculated_at for item in scores}
    if len(calculated_times) != 1:
        raise CopyabilitySelectionStoreError("Copyability scores must share one calculation time.")


def _selection_run(row: sqlite3.Row) -> CopyabilitySelectionRun:
    return CopyabilitySelectionRun(
        run_id=str(row["run_id"]),
        key=CopyabilityProcessingKey(
            stage2_run_id=str(row["stage2_run_id"]),
            feature_set_version=str(row["feature_set_version"]),
            policy_id=str(row["policy_id"]),
            policy_version=str(row["policy_version"]),
            ranking_version=str(row["ranking_version"]),
        ),
        source_id=str(row["source_id"]),
        source_snapshot_id=str(row["source_snapshot_id"]),
        calculated_at=_parse_datetime(str(row["calculated_at"])),
        published_at=_parse_datetime(str(row["published_at"])),
        evaluated_count=int(row["evaluated_count"]),
        alpha_count=int(row["alpha_count"]),
        stress_count=int(row["stress_count"]),
        live_review_count=int(row["live_review_count"]),
        rejected_count=int(row["rejected_count"]),
        watchlist_count=int(row["watchlist_count"]),
        overlap_count=int(row["overlap_count"]),
    )


def _pool_row(row: sqlite3.Row) -> CopyabilityPoolRow:
    return CopyabilityPoolRow(
        wallet_id=str(row["wallet_id"]),
        source_id=str(row["source_id"]),
        source_snapshot_id=str(row["source_snapshot_id"]),
        stage2_run_id=str(row["stage2_run_id"]),
        pool_id=str(row["pool_id"]),
        pool_rank=None if row["pool_rank"] is None else int(row["pool_rank"]),
        status=SelectionStatus(str(row["status"])),
        alpha_score=_optional_decimal(row["alpha_score"]),
        copyability_score=_optional_decimal(row["copyability_score"]),
        performance_score=_optional_decimal(row["performance_score"]),
        recent_edge_score=_optional_decimal(row["recent_edge_score"]),
        activity_score=_optional_decimal(row["activity_score"]),
        hedging_risk_score=_optional_decimal(row["hedging_risk_score"]),
        confidence_score=_optional_decimal(row["confidence_score"]),
        stability_score=_optional_decimal(row["stability_score"]),
        reasons=tuple(json.loads(str(row["reasons_json"]))),
        effective_at=_parse_datetime(str(row["effective_at"])),
        observed_at=_parse_datetime(str(row["observed_at"])),
        ingested_at=_parse_datetime(str(row["ingested_at"])),
        calculated_at=_parse_datetime(str(row["calculated_at"])),
        feature_set_version=str(row["feature_set_version"]),
        policy_id=str(row["policy_id"]),
        policy_version=str(row["policy_version"]),
        ranking_version=str(row["ranking_version"]),
        run_id=str(row["run_id"]),
    )


def _status_row(row: sqlite3.Row) -> CopyabilityPoolRow:
    return _pool_row(row)


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _safe_message(message: str) -> str:
    if "0x" in message.lower():
        return "Copyability selection failed; protected details were omitted."
    return message[:500]


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value or len(value) > 128 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
        for character in value
    ):
        raise ValueError(f"{field_name} is invalid")


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
