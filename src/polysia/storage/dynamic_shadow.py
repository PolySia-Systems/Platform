from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.application.ports.dynamic_shadow import (
    DynamicShadowHealth,
    DynamicShadowRunRecord,
    DynamicShadowWalletResult,
    ProtectedShadowCandidate,
)
from polysia.domain.copytrading.dynamic_shadow import (
    DynamicShadowMode,
    ShadowEventEvaluation,
    ShadowWalletSummary,
)
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.wallet_intelligence import CandidateStoreError

DYNAMIC_SHADOW_SCHEMA_PATH = Path(__file__).with_name("dynamic_shadow_schema.sql")
DYNAMIC_SHADOW_SCHEMA_VERSION = 1
_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


class DynamicShadowStoreError(CandidateStoreError):
    """Safe Stage 4 persistence failure without protected identities."""


class DynamicShadowRepository:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        CopyabilitySelectionRepository(self._path).initialize()
        connection = self._connect()
        try:
            connection.executescript(DYNAMIC_SHADOW_SCHEMA_PATH.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT OR IGNORE INTO dynamic_shadow_metadata "
                "(schema_version, initialized_at) VALUES (?, ?)",
                (DYNAMIC_SHADOW_SCHEMA_VERSION, _iso(datetime.now(UTC))),
            )
            connection.commit()
            self._require_schema(connection)
            self._require_integrity(connection)
        finally:
            connection.close()
        _restrict_file(self._path)

    def current_candidates(
        self,
        source_id: str,
    ) -> tuple[str, tuple[ProtectedShadowCandidate, ...]]:
        connection = self._connect(read_only=True)
        try:
            current = connection.execute(
                "SELECT r.run_id FROM copyability_selection_current c "
                "JOIN copyability_selection_runs r ON r.run_id = c.run_id "
                "WHERE c.source_id = ? AND r.status = 'succeeded'",
                (source_id,),
            ).fetchone()
            if current is None:
                raise DynamicShadowStoreError("Current Stage 3 selection is unavailable.")
            selection_run_id = str(current["run_id"])
            rows = connection.execute(
                "SELECT m.wallet_id, m.pool_id, m.pool_rank, w.normalized_address "
                "FROM copyability_pool_memberships m "
                "JOIN canonical_wallets w ON w.wallet_id = m.wallet_id "
                "WHERE m.run_id = ? AND m.pool_id IN ('SHADOW_ALPHA', 'SHADOW_STRESS') "
                "ORDER BY m.wallet_id, m.pool_id",
                (selection_run_id,),
            ).fetchall()
        finally:
            connection.close()
        by_wallet: dict[str, dict[str, Any]] = {}
        for row in rows:
            wallet_id = str(row["wallet_id"])
            address = str(row["normalized_address"])
            if _WALLET_PATTERN.fullmatch(address) is None:
                raise DynamicShadowStoreError("Protected candidate address is invalid.")
            item = by_wallet.setdefault(
                wallet_id,
                {"address": address, "pools": [], "alpha_rank": None, "stress_rank": None},
            )
            if item["address"] != address:
                raise DynamicShadowStoreError("Canonical candidate identity is inconsistent.")
            pool_id = str(row["pool_id"])
            pools = item["pools"]
            assert isinstance(pools, list)
            pools.append(pool_id)
            if pool_id == "SHADOW_ALPHA":
                item["alpha_rank"] = int(row["pool_rank"])
            else:
                item["stress_rank"] = int(row["pool_rank"])
        candidates = tuple(
            ProtectedShadowCandidate(
                wallet_id=wallet_id,
                address=str(item["address"]),
                pools=tuple(str(value) for value in item["pools"]),
                alpha_rank=_optional_int(item["alpha_rank"]),
                stress_rank=_optional_int(item["stress_rank"]),
            )
            for wallet_id, item in sorted(by_wallet.items())
        )
        if not candidates:
            raise DynamicShadowStoreError("Current Stage 3 selection has no Shadow candidates.")
        return selection_run_id, candidates

    def successful_run(
        self,
        *,
        selection_run_id: str,
        mode: DynamicShadowMode,
        policy_version: str,
        cost_model_version: str,
        window_start: datetime,
        window_end: datetime,
    ) -> DynamicShadowRunRecord | None:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM dynamic_shadow_runs WHERE selection_run_id = ? AND mode = ? "
                "AND policy_version = ? AND cost_model_version = ? AND window_start = ? "
                "AND window_end = ? AND status = 'succeeded' LIMIT 1",
                (
                    selection_run_id,
                    mode.value,
                    policy_version,
                    cost_model_version,
                    _iso(window_start),
                    _iso(window_end),
                ),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _run(row)

    def start_run(
        self,
        *,
        source_id: str,
        selection_run_id: str,
        mode: DynamicShadowMode,
        policy_version: str,
        cost_model_version: str,
        window_start: datetime,
        window_end: datetime,
        started_at: datetime,
        candidate_count: int,
    ) -> str:
        if candidate_count < 1 or window_end <= window_start:
            raise ValueError("dynamic Shadow run bounds are invalid")
        run_id = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO dynamic_shadow_runs (run_id, source_id, selection_run_id, "
                "mode, policy_version, cost_model_version, window_start, window_end, status, "
                "started_at, candidate_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)",
                (
                    run_id,
                    source_id,
                    selection_run_id,
                    mode.value,
                    policy_version,
                    cost_model_version,
                    _iso(window_start),
                    _iso(window_end),
                    _iso(started_at),
                    candidate_count,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return run_id

    def complete_run(
        self,
        run_id: str,
        *,
        candidates: tuple[ProtectedShadowCandidate, ...],
        evaluations: tuple[ShadowEventEvaluation, ...],
        summaries: tuple[ShadowWalletSummary, ...],
        completed_at: datetime,
    ) -> DynamicShadowRunRecord:
        _validate_completion(candidates, evaluations, summaries)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM dynamic_shadow_runs WHERE run_id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if row is None:
                raise DynamicShadowStoreError("Dynamic Shadow run is not publishable.")
            if int(row["candidate_count"]) != len(candidates):
                raise DynamicShadowStoreError("Dynamic Shadow candidate count changed.")
            for candidate in candidates:
                connection.execute(
                    "INSERT INTO dynamic_shadow_candidates "
                    "(run_id, wallet_id, pools_json, alpha_rank, stress_rank) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        run_id,
                        candidate.wallet_id,
                        json.dumps(candidate.pools, separators=(",", ":")),
                        candidate.alpha_rank,
                        candidate.stress_rank,
                    ),
                )
            for item in evaluations:
                connection.execute(
                    "INSERT INTO dynamic_shadow_evaluations (run_id, event_id, wallet_id, "
                    "market_reference, outcome_reference, action, evaluation_status, reason, "
                    "mode, leader_price, requested_size, filled_size, follower_price, "
                    "gross_notional, fee, slippage, delay_ms, available_liquidity, "
                    "realized_pnl, quote_source, executed_at, evaluated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        item.event_id,
                        item.wallet_id,
                        item.market_reference,
                        item.outcome_reference,
                        item.action.value,
                        item.status.value,
                        item.reason,
                        item.mode.value,
                        _decimal(item.leader_price),
                        _decimal(item.requested_size),
                        _decimal(item.filled_size),
                        _optional_decimal(item.follower_price),
                        _optional_decimal(item.gross_notional),
                        _optional_decimal(item.fee),
                        _optional_decimal(item.slippage),
                        item.delay_ms,
                        _optional_decimal(item.available_liquidity),
                        _optional_decimal(item.realized_pnl),
                        item.quote_source,
                        _iso(item.executed_at),
                        _iso(item.evaluated_at),
                    ),
                )
            for summary in summaries:
                connection.execute(
                    "INSERT INTO dynamic_shadow_wallet_summaries (run_id, wallet_id, "
                    "event_count, simulated_count, unknown_count, rejected_count, buy_count, "
                    "sell_count, realized_pnl, fees, slippage, open_notional) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        summary.wallet_id,
                        summary.event_count,
                        summary.simulated_count,
                        summary.unknown_count,
                        summary.rejected_count,
                        summary.buy_count,
                        summary.sell_count,
                        _decimal(summary.realized_pnl),
                        _decimal(summary.fees),
                        _decimal(summary.slippage),
                        _decimal(summary.open_notional),
                    ),
                )
            simulated_count = sum(item.simulated_count for item in summaries)
            unknown_count = sum(item.unknown_count for item in summaries)
            rejected_count = sum(item.rejected_count for item in summaries)
            realized_pnl = sum((item.realized_pnl for item in summaries), start=Decimal("0"))
            fees = sum((item.fees for item in summaries), start=Decimal("0"))
            slippage = sum((item.slippage for item in summaries), start=Decimal("0"))
            connection.execute(
                "UPDATE dynamic_shadow_runs SET status = 'succeeded', completed_at = ?, "
                "event_count = ?, simulated_count = ?, unknown_count = ?, rejected_count = ?, "
                "realized_pnl = ?, fees = ?, slippage = ? "
                "WHERE run_id = ?",
                (
                    _iso(completed_at),
                    len(evaluations),
                    simulated_count,
                    unknown_count,
                    rejected_count,
                    _decimal(realized_pnl),
                    _decimal(fees),
                    _decimal(slippage),
                    run_id,
                ),
            )
            connection.execute(
                "INSERT INTO dynamic_shadow_current (source_id, mode, run_id, published_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(source_id, mode) DO UPDATE SET "
                "run_id = excluded.run_id, published_at = excluded.published_at",
                (str(row["source_id"]), str(row["mode"]), run_id, _iso(completed_at)),
            )
            connection.commit()
            published = connection.execute(
                "SELECT * FROM dynamic_shadow_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        assert published is not None
        return _run(published)

    def fail_run(
        self,
        run_id: str,
        *,
        failed_at: datetime,
        error_code: str,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE dynamic_shadow_runs SET status = 'failed', failed_at = ?, "
                "last_error_code = ? WHERE run_id = ? AND status = 'running'",
                (_iso(failed_at), _safe_error_code(error_code), run_id),
            )
            connection.commit()
        finally:
            connection.close()

    def health(self, source_id: str, *, now: datetime) -> DynamicShadowHealth:
        connection = self._connect(read_only=True)
        try:
            current_row = connection.execute(
                "SELECT r.* FROM dynamic_shadow_current c JOIN dynamic_shadow_runs r "
                "ON r.run_id = c.run_id WHERE c.source_id = ? "
                "ORDER BY CASE r.mode WHEN 'FORWARD' THEN 0 ELSE 1 END LIMIT 1",
                (source_id,),
            ).fetchone()
            last_row = connection.execute(
                "SELECT * FROM dynamic_shadow_runs WHERE source_id = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        current = None if current_row is None else _run(current_row)
        last = None if last_row is None else _run(last_row)
        reasons: list[str] = []
        level = "healthy"
        if current is None:
            level = "warning"
            reasons.append("dynamic_shadow_unavailable")
        elif current.completed_at is not None and now - current.completed_at > timedelta(hours=36):
            level = "warning"
            reasons.append("dynamic_shadow_stale")
        if last is not None and last.status == "failed":
            level = "warning"
            reasons.append("latest_dynamic_shadow_failed")
        if current is not None and current.event_count == 0:
            level = "warning"
            reasons.append("dynamic_shadow_no_events")
        return DynamicShadowHealth(
            current_run=current,
            last_run=last,
            level=level,
            reasons=tuple(reasons),
        )

    def current_wallet_results(
        self,
        source_id: str,
        *,
        mode: DynamicShadowMode,
        limit: int = 100,
    ) -> tuple[DynamicShadowWalletResult, ...]:
        if not 1 <= limit <= 100_000:
            raise ValueError("limit must be within [1, 100000]")
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute(
                "SELECT * FROM dynamic_shadow_wallets_current "
                "WHERE source_id = ? AND mode = ? "
                "ORDER BY event_count DESC, simulated_count DESC, "
                "COALESCE(alpha_rank, 2147483647), "
                "COALESCE(stress_rank, 2147483647), wallet_id LIMIT ?",
                (source_id, mode.value, limit),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_wallet_result(row) for row in rows)

    def prune_history(self, *, cutoff: datetime) -> int:
        cutoff_value = _iso(cutoff)
        connection = self._connect()
        try:
            deleted = connection.execute(
                "DELETE FROM dynamic_shadow_runs WHERE status != 'running' "
                "AND started_at < ? AND run_id NOT IN "
                "(SELECT run_id FROM dynamic_shadow_current)",
                (cutoff_value,),
            ).rowcount
            connection.commit()
        finally:
            connection.close()
        return int(deleted)

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                f"{self._path.resolve().as_uri()}?mode=ro", uri=True, timeout=5
            )
        else:
            connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT schema_version FROM dynamic_shadow_metadata").fetchall()
        if len(rows) != 1 or int(rows[0][0]) != DYNAMIC_SHADOW_SCHEMA_VERSION:
            raise DynamicShadowStoreError("Dynamic Shadow schema version is unsupported.")

    @staticmethod
    def _require_integrity(connection: sqlite3.Connection) -> None:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise DynamicShadowStoreError("Dynamic Shadow SQLite integrity check failed.")


def _validate_completion(
    candidates: tuple[ProtectedShadowCandidate, ...],
    evaluations: tuple[ShadowEventEvaluation, ...],
    summaries: tuple[ShadowWalletSummary, ...],
) -> None:
    candidate_ids = {item.wallet_id for item in candidates}
    if not candidates or len(candidate_ids) != len(candidates):
        raise DynamicShadowStoreError("Dynamic Shadow candidates are empty or duplicated.")
    if {item.wallet_id for item in summaries} != candidate_ids:
        raise DynamicShadowStoreError("Dynamic Shadow summaries are incomplete.")
    if any(item.wallet_id not in candidate_ids for item in evaluations):
        raise DynamicShadowStoreError("Dynamic Shadow evaluation references an unknown wallet.")
    event_ids = [item.event_id for item in evaluations]
    if len(set(event_ids)) != len(event_ids):
        raise DynamicShadowStoreError("Dynamic Shadow events are duplicated across candidates.")
    for summary in summaries:
        rows = tuple(item for item in evaluations if item.wallet_id == summary.wallet_id)
        simulated = tuple(item for item in rows if item.status.value == "SIMULATED")
        expected = (
            len(rows),
            len(simulated),
            sum(item.status.value == "UNKNOWN" for item in rows),
            sum(item.status.value == "REJECTED" for item in rows),
            sum(item.action.value == "BUY" for item in simulated),
            sum(item.action.value == "SELL" for item in simulated),
            sum(
                (item.realized_pnl for item in simulated if item.realized_pnl is not None),
                Decimal("0"),
            ),
            sum((item.fee for item in simulated if item.fee is not None), Decimal("0")),
            sum(
                (item.slippage for item in simulated if item.slippage is not None),
                Decimal("0"),
            ),
        )
        actual = (
            summary.event_count,
            summary.simulated_count,
            summary.unknown_count,
            summary.rejected_count,
            summary.buy_count,
            summary.sell_count,
            summary.realized_pnl,
            summary.fees,
            summary.slippage,
        )
        if actual != expected:
            raise DynamicShadowStoreError("Dynamic Shadow wallet summary is inconsistent.")


def _run(row: sqlite3.Row) -> DynamicShadowRunRecord:
    return DynamicShadowRunRecord(
        run_id=str(row["run_id"]),
        source_id=str(row["source_id"]),
        selection_run_id=str(row["selection_run_id"]),
        mode=DynamicShadowMode(str(row["mode"])),
        policy_version=str(row["policy_version"]),
        cost_model_version=str(row["cost_model_version"]),
        window_start=_datetime(str(row["window_start"])),
        window_end=_datetime(str(row["window_end"])),
        started_at=_datetime(str(row["started_at"])),
        completed_at=None if row["completed_at"] is None else _datetime(str(row["completed_at"])),
        status=str(row["status"]),
        candidate_count=int(row["candidate_count"]),
        event_count=int(row["event_count"]),
        simulated_count=int(row["simulated_count"]),
        unknown_count=int(row["unknown_count"]),
        rejected_count=int(row["rejected_count"]),
        realized_pnl=Decimal(str(row["realized_pnl"])),
        fees=Decimal(str(row["fees"])),
        slippage=Decimal(str(row["slippage"])),
        last_error_code=None if row["last_error_code"] is None else str(row["last_error_code"]),
    )


def _wallet_result(row: sqlite3.Row) -> DynamicShadowWalletResult:
    raw_pools = json.loads(str(row["pools_json"]))
    if not isinstance(raw_pools, list) or not all(isinstance(item, str) for item in raw_pools):
        raise DynamicShadowStoreError("Dynamic Shadow pool evidence is invalid.")
    return DynamicShadowWalletResult(
        run_id=str(row["run_id"]),
        wallet_id=str(row["wallet_id"]),
        mode=DynamicShadowMode(str(row["mode"])),
        pools=tuple(str(item) for item in raw_pools),
        alpha_rank=_optional_int(row["alpha_rank"]),
        stress_rank=_optional_int(row["stress_rank"]),
        event_count=int(row["event_count"]),
        simulated_count=int(row["simulated_count"]),
        unknown_count=int(row["unknown_count"]),
        rejected_count=int(row["rejected_count"]),
        buy_count=int(row["buy_count"]),
        sell_count=int(row["sell_count"]),
        realized_pnl=Decimal(str(row["realized_pnl"])),
        fees=Decimal(str(row["fees"])),
        slippage=Decimal(str(row["slippage"])),
        open_notional=Decimal(str(row["open_notional"])),
        policy_version=str(row["policy_version"]),
        cost_model_version=str(row["cost_model_version"]),
        window_start=_datetime(str(row["window_start"])),
        window_end=_datetime(str(row["window_end"])),
    )


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be timezone-aware UTC")
    return value.isoformat().replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _decimal(value: object) -> str:
    return format(value, "f")


def _optional_decimal(value: object | None) -> str | None:
    return None if value is None else _decimal(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _safe_error_code(value: str) -> str:
    normalized = value[:128]
    return normalized if re.fullmatch(r"[a-zA-Z0-9_.-]+", normalized) else "dynamic_shadow_failed"


def _restrict_file(path: Path) -> None:
    if path.exists() and os.name != "nt":
        path.chmod(0o600)
