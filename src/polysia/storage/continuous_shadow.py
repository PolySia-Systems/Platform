from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.application.ports.continuous_shadow import (
    ContinuousLedgerRecord,
    ContinuousPollCompletion,
    ContinuousPollOutcome,
    ContinuousPositionMark,
    ContinuousShadowExperiment,
    ContinuousShadowHealth,
    FollowerAttribution,
)
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.domain.copytrading.continuous_shadow import (
    ContinuousPortfolio,
    ContinuousPortfolioKind,
    ContinuousPosition,
    ContinuousShadowConfig,
    ContinuousShadowLifecycle,
)
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.wallet_intelligence import CandidateStoreError

CONTINUOUS_SHADOW_SCHEMA_PATH = Path(__file__).with_name("continuous_shadow_schema.sql")
CONTINUOUS_SHADOW_SCHEMA_VERSION = 2
_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
_ABANDONED_POLL_AFTER = timedelta(minutes=30)
_ZERO = Decimal("0")


class ContinuousShadowStoreError(CandidateStoreError):
    """Safe Stage 4B persistence failure without protected identity values."""


class ContinuousShadowRepository:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        CopyabilitySelectionRepository(self._path).initialize()
        connection = self._connect()
        try:
            connection.executescript(
                CONTINUOUS_SHADOW_SCHEMA_PATH.read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT OR IGNORE INTO continuous_shadow_metadata "
                "(schema_version, initialized_at) VALUES (?, ?)",
                (CONTINUOUS_SHADOW_SCHEMA_VERSION, _iso(datetime.now(UTC))),
            )
            cutoff = _iso(datetime.now(UTC) - _ABANDONED_POLL_AFTER)
            connection.execute(
                "UPDATE continuous_shadow_poll_runs SET status = 'failed', failed_at = ?, "
                "last_error_code = 'abandoned_poll' "
                "WHERE status = 'running' AND started_at < ?",
                (_iso(datetime.now(UTC)), cutoff),
            )
            connection.commit()
            self._require_schema(connection)
            self._require_integrity(connection)
        finally:
            connection.close()
        _restrict_file(self._path)

    def start_experiment(
        self,
        *,
        source_id: str,
        selection_run_id: str,
        candidates: tuple[ProtectedShadowCandidate, ...],
        config: ContinuousShadowConfig,
        started_at: datetime,
    ) -> ContinuousShadowExperiment:
        if not candidates:
            raise ContinuousShadowStoreError("Continuous Shadow candidates are unavailable.")
        started_at = _utc(started_at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE source_id = ? "
                "AND lifecycle IN ('RUNNING', 'DRAINING')",
                (source_id,),
            ).fetchone()
            if active is not None:
                existing = _experiment(active)
                expected = (
                    config.policy_version,
                    config.cost_model_version,
                    config.bankroll_version,
                )
                actual = (
                    existing.policy_version,
                    existing.cost_model_version,
                    existing.bankroll_version,
                )
                if actual != expected or existing.config.to_dict() != config.to_dict():
                    raise ContinuousShadowStoreError(
                        "An active Continuous Shadow experiment uses different versions."
                    )
                connection.commit()
                return existing
            experiment_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO continuous_shadow_experiments "
                "(experiment_id, source_id, selection_run_id, policy_version, "
                "cost_model_version, bankroll_version, config_json, lifecycle, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?)",
                (
                    experiment_id,
                    source_id,
                    selection_run_id,
                    config.policy_version,
                    config.cost_model_version,
                    config.bankroll_version,
                    json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":")),
                    _iso(started_at),
                ),
            )
            self._upsert_candidates(
                connection,
                experiment_id=experiment_id,
                selection_run_id=selection_run_id,
                candidates=candidates,
                selected_at=started_at,
                reset_active=False,
                wallet_bankroll=config.wallet_bankroll,
            )
            connection.execute(
                "INSERT INTO continuous_shadow_portfolios "
                "(experiment_id, portfolio_id, kind, wallet_id, initial_cash, cash, "
                "realized_pnl, unrealized_pnl, fees, nav, high_water_nav, drawdown, "
                "exposure, updated_at) VALUES (?, 'follower', 'FOLLOWER', NULL, ?, ?, "
                "'0', '0', '0', ?, ?, '0', '0', ?)",
                (
                    experiment_id,
                    _decimal(config.follower_bankroll),
                    _decimal(config.follower_bankroll),
                    _decimal(config.follower_bankroll),
                    _decimal(config.follower_bankroll),
                    _iso(started_at),
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        assert row is not None
        return _experiment(row)

    def active_experiment(self, source_id: str) -> ContinuousShadowExperiment | None:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE source_id = ? "
                "AND lifecycle IN ('RUNNING', 'DRAINING') ORDER BY started_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _experiment(row)

    def transition(
        self,
        experiment_id: str,
        *,
        lifecycle: ContinuousShadowLifecycle,
        transitioned_at: datetime,
    ) -> ContinuousShadowExperiment:
        transitioned_at = _utc(transitioned_at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if row is None:
                raise ContinuousShadowStoreError("Continuous Shadow experiment is unavailable.")
            current = ContinuousShadowLifecycle(str(row["lifecycle"]))
            if current is lifecycle:
                connection.commit()
                return _experiment(row)
            allowed = (
                current is ContinuousShadowLifecycle.RUNNING
                and lifecycle is ContinuousShadowLifecycle.DRAINING
            ) or (
                current is ContinuousShadowLifecycle.DRAINING
                and lifecycle is ContinuousShadowLifecycle.FINALIZED
            )
            if not allowed:
                raise ContinuousShadowStoreError(
                    "Continuous Shadow lifecycle transition is invalid."
                )
            if lifecycle is ContinuousShadowLifecycle.FINALIZED:
                open_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM continuous_shadow_positions "
                        "WHERE experiment_id = ?",
                        (experiment_id,),
                    ).fetchone()[0]
                )
                if open_count:
                    raise ContinuousShadowStoreError(
                        "Continuous Shadow cannot finalize with open positions."
                    )
            column = (
                "draining_at"
                if lifecycle is ContinuousShadowLifecycle.DRAINING
                else "finalized_at"
            )
            connection.execute(
                f"UPDATE continuous_shadow_experiments SET lifecycle = ?, {column} = ? "
                "WHERE experiment_id = ?",
                (lifecycle.value, _iso(transitioned_at), experiment_id),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        assert updated is not None
        return _experiment(updated)

    def retained_candidates(
        self,
        experiment_id: str,
    ) -> tuple[ProtectedShadowCandidate, ...]:
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute(
                "SELECT c.wallet_id, c.pools_json, c.alpha_rank, c.stress_rank, "
                "w.normalized_address FROM continuous_shadow_candidates c "
                "JOIN canonical_wallets w ON w.wallet_id = c.wallet_id "
                "WHERE c.experiment_id = ? AND (c.active = 1 OR EXISTS ("
                "SELECT 1 FROM continuous_shadow_positions p "
                "JOIN continuous_shadow_portfolios pf ON pf.experiment_id = p.experiment_id "
                "AND pf.portfolio_id = p.portfolio_id "
                "WHERE p.experiment_id = c.experiment_id AND pf.wallet_id = c.wallet_id "
                ") OR EXISTS ("
                "SELECT 1 FROM continuous_shadow_follower_attribution a "
                "WHERE a.experiment_id = c.experiment_id AND a.wallet_id = c.wallet_id "
                ")) ORDER BY c.wallet_id",
                (experiment_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_candidate(row) for row in rows)

    def watermark(self, experiment_id: str) -> datetime | None:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT watermark FROM continuous_shadow_checkpoint WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _datetime(str(row[0]))

    def seen_event_ids(self, event_ids: tuple[str, ...]) -> set[str]:
        if not event_ids:
            return set()
        seen: set[str] = set()
        connection = self._connect(read_only=True)
        try:
            for start in range(0, len(event_ids), 500):
                chunk = event_ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"SELECT event_id FROM continuous_shadow_event_journal "
                    f"WHERE event_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                seen.update(str(row[0]) for row in rows)
        finally:
            connection.close()
        return seen

    def portfolios(self, experiment_id: str) -> tuple[ContinuousPortfolio, ...]:
        connection = self._connect(read_only=True)
        try:
            portfolio_rows = connection.execute(
                "SELECT * FROM continuous_shadow_portfolios WHERE experiment_id = ? "
                "ORDER BY kind, portfolio_id",
                (experiment_id,),
            ).fetchall()
            position_rows = connection.execute(
                "SELECT * FROM continuous_shadow_positions WHERE experiment_id = ? "
                "ORDER BY portfolio_id, market_reference, outcome_reference",
                (experiment_id,),
            ).fetchall()
        finally:
            connection.close()
        by_portfolio: dict[str, list[ContinuousPosition]] = {}
        for row in position_rows:
            position = _position(row)
            by_portfolio.setdefault(position.portfolio_id, []).append(position)
        return tuple(
            _portfolio(row, tuple(by_portfolio.get(str(row["portfolio_id"]), ())))
            for row in portfolio_rows
        )

    def attributions(self, experiment_id: str) -> tuple[FollowerAttribution, ...]:
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute(
                "SELECT * FROM continuous_shadow_follower_attribution "
                "WHERE experiment_id = ? ORDER BY wallet_id, market_reference, outcome_reference",
                (experiment_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            FollowerAttribution(
                wallet_id=str(row["wallet_id"]),
                market_reference=str(row["market_reference"]),
                outcome_reference=str(row["outcome_reference"]),
                quantity=Decimal(str(row["quantity"])),
                cost_basis=Decimal(str(row["cost_basis"])),
            )
            for row in rows
        )

    def start_poll(
        self,
        *,
        experiment_id: str,
        selection_run_id: str,
        window_start: datetime,
        window_end: datetime,
        started_at: datetime,
        candidate_count: int,
    ) -> str:
        if candidate_count < 1 or window_end <= window_start:
            raise ValueError("Continuous Shadow poll bounds are invalid")
        poll_run_id = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            running = connection.execute(
                "SELECT 1 FROM continuous_shadow_poll_runs WHERE experiment_id = ? "
                "AND status = 'running'",
                (experiment_id,),
            ).fetchone()
            if running is not None:
                raise ContinuousShadowStoreError("A Continuous Shadow poll is already running.")
            connection.execute(
                "INSERT INTO continuous_shadow_poll_runs "
                "(poll_run_id, experiment_id, selection_run_id, window_start, window_end, "
                "status, started_at, candidate_count) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
                (
                    poll_run_id,
                    experiment_id,
                    selection_run_id,
                    _iso(window_start),
                    _iso(window_end),
                    _iso(started_at),
                    candidate_count,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return poll_run_id

    def complete_poll(
        self,
        poll_run_id: str,
        *,
        experiment: ContinuousShadowExperiment,
        selection_run_id: str,
        current_candidates: tuple[ProtectedShadowCandidate, ...],
        completion: ContinuousPollCompletion,
        completed_at: datetime,
    ) -> ContinuousPollOutcome:
        completed_at = _utc(completed_at)
        _validate_completion(completion)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            poll = connection.execute(
                "SELECT * FROM continuous_shadow_poll_runs "
                "WHERE poll_run_id = ? AND status = 'running'",
                (poll_run_id,),
            ).fetchone()
            if poll is None or str(poll["experiment_id"]) != experiment.experiment_id:
                raise ContinuousShadowStoreError("Continuous Shadow poll is not publishable.")
            self._upsert_candidates(
                connection,
                experiment_id=experiment.experiment_id,
                selection_run_id=selection_run_id,
                candidates=current_candidates,
                selected_at=completed_at,
                reset_active=True,
                wallet_bankroll=next(
                    item.initial_cash
                    for item in completion.portfolios
                    if item.kind is ContinuousPortfolioKind.WALLET
                )
                if any(
                    item.kind is ContinuousPortfolioKind.WALLET
                    for item in completion.portfolios
                )
                else Decimal("100"),
            )
            for event, pools in completion.events:
                connection.execute(
                    "INSERT INTO continuous_shadow_event_journal "
                    "(event_id, source_id, wallet_id, market_reference, outcome_reference, "
                    "action, leader_price, leader_size, executed_at, observed_at, first_seen_at, "
                    "first_poll_run_id, external_evidence_reference, pools_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.source_id,
                        event.leader_id,
                        event.market_reference,
                        event.outcome_reference,
                        event.trade_action.value,
                        _decimal(event.executed_price),
                        _decimal(event.executed_size),
                        _iso(event.executed_at),
                        _iso(event.observed_at),
                        _iso(completed_at),
                        poll_run_id,
                        event.external_evidence_reference,
                        json.dumps(pools, separators=(",", ":")),
                    ),
                )
            for item in completion.evaluations:
                connection.execute(
                    "INSERT INTO continuous_shadow_evaluations "
                    "(experiment_id, poll_run_id, event_id, portfolio_id, wallet_id, "
                    "pool_class, status, reason, requested_size, filled_size, follower_price, "
                    "gross_notional, fee, fee_status, fee_source, fee_rate, fee_exponent, "
                    "realized_pnl, source_api_lag_ms, signal_delay_ms, price_movement, "
                    "spread_cost, depth_impact, liquidity_loss, available_liquidity, "
                    "quote_timestamp, evaluated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?, ?, ?, ?, ?)",
                    (
                        experiment.experiment_id,
                        poll_run_id,
                        item.event_id,
                        item.portfolio_id,
                        item.wallet_id,
                        item.pool_class,
                        item.status.value,
                        item.reason,
                        _decimal(item.requested_size),
                        _decimal(item.filled_size),
                        _optional_decimal(item.follower_price),
                        _optional_decimal(item.gross_notional),
                        _optional_decimal(item.fee),
                        item.fee_status,
                        item.fee_source,
                        _optional_decimal(item.fee_rate),
                        _optional_decimal(item.fee_exponent),
                        _optional_decimal(item.realized_pnl),
                        item.source_api_lag_ms,
                        item.signal_delay_ms,
                        _optional_decimal(item.price_movement),
                        _optional_decimal(item.spread_cost),
                        _optional_decimal(item.depth_impact),
                        _optional_decimal(item.liquidity_loss),
                        _optional_decimal(item.available_liquidity),
                        None if item.quote_timestamp is None else _iso(item.quote_timestamp),
                        _iso(item.evaluated_at),
                    ),
                )
                for price, size in item.consumed:
                    connection.execute(
                        "INSERT INTO continuous_shadow_liquidity_consumption "
                        "(experiment_id, poll_run_id, event_id, portfolio_id, "
                        "outcome_reference, price, consumed_size) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            experiment.experiment_id,
                            poll_run_id,
                            item.event_id,
                            item.portfolio_id,
                            _event_outcome(completion.events, item.event_id),
                            _decimal(price),
                            _decimal(size),
                        ),
                    )
            connection.execute(
                "DELETE FROM continuous_shadow_positions WHERE experiment_id = ?",
                (experiment.experiment_id,),
            )
            for portfolio in completion.portfolios:
                _write_portfolio(connection, experiment.experiment_id, portfolio, completed_at)
                for position in portfolio.positions:
                    if position.quantity <= _ZERO:
                        continue
                    connection.execute(
                        "INSERT INTO continuous_shadow_positions "
                        "(experiment_id, portfolio_id, market_reference, outcome_reference, "
                        "quantity, cost_basis, entry_fees, mark_price, marked_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            experiment.experiment_id,
                            portfolio.portfolio_id,
                            position.market_reference,
                            position.outcome_reference,
                            _decimal(position.quantity),
                            _decimal(position.cost_basis),
                            _decimal(position.entry_fees),
                            _optional_decimal(position.mark_price),
                            None if position.marked_at is None else _iso(position.marked_at),
                            _iso(completed_at),
                        ),
                    )
            connection.execute(
                "DELETE FROM continuous_shadow_follower_attribution WHERE experiment_id = ?",
                (experiment.experiment_id,),
            )
            for attribution_row in completion.attributions:
                if attribution_row.quantity <= _ZERO:
                    continue
                connection.execute(
                    "INSERT INTO continuous_shadow_follower_attribution "
                    "(experiment_id, wallet_id, market_reference, outcome_reference, "
                    "quantity, cost_basis) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        experiment.experiment_id,
                        attribution_row.wallet_id,
                        attribution_row.market_reference,
                        attribution_row.outcome_reference,
                        _decimal(attribution_row.quantity),
                        _decimal(attribution_row.cost_basis),
                    ),
                )
            for ledger_row in completion.ledger:
                _write_ledger(connection, experiment.experiment_id, poll_run_id, ledger_row)
            for mark_row in completion.marks:
                _write_mark(connection, experiment.experiment_id, poll_run_id, mark_row)

            simulated = sum(
                item.status.value == "SIMULATED" for item in completion.evaluations
            )
            unknown = sum(item.status.value == "UNKNOWN" for item in completion.evaluations)
            rejected = sum(item.status.value == "REJECTED" for item in completion.evaluations)
            realized_delta = sum(
                (
                    item.realized_pnl
                    for item in completion.evaluations
                    if item.realized_pnl is not None
                ),
                _ZERO,
            ) + sum(
                (item.realized_pnl_delta for item in completion.ledger if item.event_id is None),
                _ZERO,
            )
            fee_delta = sum(
                (item.fee for item in completion.evaluations if item.fee is not None),
                _ZERO,
            )
            max_api_lag = max(
                (item.source_api_lag_ms for item in completion.evaluations), default=0
            )
            max_signal_delay = max(
                (item.signal_delay_ms for item in completion.evaluations), default=0
            )
            connection.execute(
                "UPDATE continuous_shadow_poll_runs SET status = 'succeeded', completed_at = ?, "
                "raw_event_count = ?, new_event_count = ?, duplicate_count = ?, "
                "evaluation_count = ?, simulated_count = ?, unknown_count = ?, "
                "rejected_count = ?, settlement_count = ?, realized_pnl_delta = ?, "
                "fee_delta = ?, source_api_lag_max_ms = ?, signal_delay_max_ms = ?, "
                "request_telemetry_json = ? WHERE poll_run_id = ?",
                (
                    _iso(completed_at),
                    completion.raw_event_count,
                    len(completion.events),
                    completion.duplicate_count,
                    len(completion.evaluations),
                    simulated,
                    unknown,
                    rejected,
                    completion.settlement_count,
                    _decimal(realized_delta),
                    _decimal(fee_delta),
                    max_api_lag,
                    max_signal_delay,
                    json.dumps(completion.request_telemetry, sort_keys=True, default=str),
                    poll_run_id,
                ),
            )
            window_end = str(poll["window_end"])
            connection.execute(
                "INSERT INTO continuous_shadow_checkpoint "
                "(experiment_id, watermark, updated_at, last_poll_run_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(experiment_id) DO UPDATE SET watermark = excluded.watermark, "
                "updated_at = excluded.updated_at, last_poll_run_id = excluded.last_poll_run_id",
                (experiment.experiment_id, window_end, _iso(completed_at), poll_run_id),
            )
            connection.execute(
                "UPDATE continuous_shadow_experiments SET selection_run_id = ?, "
                "last_successful_poll_at = ?, last_error_code = NULL WHERE experiment_id = ?",
                (selection_run_id, _iso(completed_at), experiment.experiment_id),
            )
            connection.commit()
            updated_experiment_row = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE experiment_id = ?",
                (experiment.experiment_id,),
            ).fetchone()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        assert updated_experiment_row is not None
        updated_experiment = _experiment(updated_experiment_row)
        follower = next(
            item for item in completion.portfolios if item.kind is ContinuousPortfolioKind.FOLLOWER
        )
        return ContinuousPollOutcome(
            experiment=updated_experiment,
            poll_run_id=poll_run_id,
            window_start=_datetime(str(poll["window_start"])),
            window_end=_datetime(str(poll["window_end"])),
            candidate_count=int(poll["candidate_count"]),
            raw_event_count=completion.raw_event_count,
            new_event_count=len(completion.events),
            duplicate_count=completion.duplicate_count,
            evaluation_count=len(completion.evaluations),
            simulated_count=simulated,
            unknown_count=unknown,
            rejected_count=rejected,
            settlement_count=completion.settlement_count,
            realized_pnl_delta=realized_delta,
            fee_delta=fee_delta,
            follower_nav=follower.cash
            + sum(
                (
                    position.market_value
                    for position in follower.positions
                    if position.market_value is not None
                ),
                _ZERO,
            ),
            follower_cash=follower.cash,
            follower_exposure=follower.exposure,
            request_telemetry=completion.request_telemetry,
        )

    def fail_poll(
        self,
        poll_run_id: str,
        *,
        failed_at: datetime,
        error_code: str,
    ) -> None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT experiment_id FROM continuous_shadow_poll_runs WHERE poll_run_id = ?",
                (poll_run_id,),
            ).fetchone()
            connection.execute(
                "UPDATE continuous_shadow_poll_runs SET status = 'failed', failed_at = ?, "
                "last_error_code = ? WHERE poll_run_id = ? AND status = 'running'",
                (_iso(_utc(failed_at)), _safe_error_code(error_code), poll_run_id),
            )
            if row is not None:
                connection.execute(
                    "UPDATE continuous_shadow_experiments SET last_error_code = ? "
                    "WHERE experiment_id = ?",
                    (_safe_error_code(error_code), str(row["experiment_id"])),
                )
            connection.commit()
        finally:
            connection.close()

    def health(
        self,
        source_id: str,
        *,
        now: datetime,
        poll_interval_seconds: int,
    ) -> ContinuousShadowHealth:
        now = _utc(now)
        connection = self._connect(read_only=True)
        try:
            experiment_row = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE source_id = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if experiment_row is None:
                return ContinuousShadowHealth(
                    level="warning",
                    reasons=("continuous_shadow_experiment_unavailable",),
                    experiment=None,
                    last_poll_status=None,
                    last_poll_at=None,
                    poll_interval_seconds=poll_interval_seconds,
                    cumulative_events=0,
                    cumulative_evaluations=0,
                    duplicate_count=0,
                    unknown_ratio=None,
                    ledger_balanced=True,
                    unmarked_position_count=0,
                    unknown_fee_count=0,
                    open_position_count=0,
                )
            experiment = _experiment(experiment_row)
            poll = connection.execute(
                "SELECT * FROM continuous_shadow_poll_runs WHERE experiment_id = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (experiment.experiment_id,),
            ).fetchone()
            event_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_event_journal j "
                    "JOIN continuous_shadow_poll_runs p ON p.poll_run_id = j.first_poll_run_id "
                    "WHERE p.experiment_id = ?",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            evaluation_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_evaluations "
                    "WHERE experiment_id = ?",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            duplicate_count = int(
                connection.execute(
                    "SELECT COALESCE(SUM(duplicate_count), 0) "
                    "FROM continuous_shadow_poll_runs WHERE experiment_id = ?",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            unknown_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_evaluations "
                    "WHERE experiment_id = ? AND status = 'UNKNOWN'",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            unknown_fee_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_evaluations "
                    "WHERE experiment_id = ? AND fee_status = 'UNKNOWN'",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            open_position_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_positions "
                    "WHERE experiment_id = ?",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            unmarked = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_positions p "
                    "WHERE p.experiment_id = ? AND COALESCE(("
                    "SELECT m.mark_status FROM continuous_shadow_position_marks m "
                    "WHERE m.experiment_id = p.experiment_id "
                    "AND m.portfolio_id = p.portfolio_id "
                    "AND m.market_reference = p.market_reference "
                    "AND m.outcome_reference = p.outcome_reference "
                    "ORDER BY m.marked_at DESC, m.poll_run_id DESC LIMIT 1"
                    "), 'MISSING') <> 'VERIFIED_EXECUTABLE_BID'",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            ledger_balanced = _ledger_balanced(connection, experiment.experiment_id)
        finally:
            connection.close()
        reasons: list[str] = []
        level = "healthy"
        last_poll_at = None
        last_poll_status = None
        if poll is None:
            reasons.append("continuous_shadow_poll_unavailable")
            level = "warning"
        else:
            last_poll_status = str(poll["status"])
            raw_time = poll["completed_at"] or poll["failed_at"] or poll["started_at"]
            last_poll_at = _datetime(str(raw_time))
            age = now - last_poll_at
            if last_poll_status == "failed":
                reasons.append("latest_continuous_shadow_poll_failed")
                level = "warning"
            if age > timedelta(seconds=poll_interval_seconds * 10):
                reasons.append("continuous_shadow_poll_critical_stale")
                level = "critical"
            elif age > timedelta(seconds=poll_interval_seconds * 3):
                reasons.append("continuous_shadow_poll_stale")
                level = "warning"
        unknown_ratio = (
            None
            if evaluation_count == 0
            else Decimal(unknown_count) / Decimal(evaluation_count)
        )
        if unknown_ratio is not None and unknown_ratio > Decimal("0.5"):
            reasons.append("continuous_shadow_unknown_ratio_high")
            level = "warning" if level == "healthy" else level
        if unknown_fee_count:
            reasons.append("continuous_shadow_fee_provenance_unknown")
            level = "warning" if level == "healthy" else level
        if unmarked:
            reasons.append("continuous_shadow_positions_unmarked")
            level = "warning" if level == "healthy" else level
        if not ledger_balanced:
            reasons.append("continuous_shadow_ledger_unbalanced")
            level = "critical"
        if (
            experiment.lifecycle is ContinuousShadowLifecycle.FINALIZED
            and open_position_count
        ):
            reasons.append("finalized_continuous_shadow_has_open_positions")
            level = "critical"
        return ContinuousShadowHealth(
            level=level,
            reasons=tuple(reasons),
            experiment=experiment,
            last_poll_status=last_poll_status,
            last_poll_at=last_poll_at,
            poll_interval_seconds=poll_interval_seconds,
            cumulative_events=event_count,
            cumulative_evaluations=evaluation_count,
            duplicate_count=duplicate_count,
            unknown_ratio=unknown_ratio,
            ledger_balanced=ledger_balanced,
            unmarked_position_count=unmarked,
            unknown_fee_count=unknown_fee_count,
            open_position_count=open_position_count,
        )

    def results(self, experiment_id: str, *, limit: int) -> dict[str, object]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be within [1, 10000]")
        connection = self._connect(read_only=True)
        try:
            experiment_row = connection.execute(
                "SELECT * FROM continuous_shadow_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if experiment_row is None:
                raise ContinuousShadowStoreError("Continuous Shadow experiment is unavailable.")
            follower = connection.execute(
                "SELECT * FROM continuous_shadow_portfolios WHERE experiment_id = ? "
                "AND kind = 'FOLLOWER'",
                (experiment_id,),
            ).fetchone()
            status_rows = connection.execute(
                "SELECT pool_class, status, COUNT(*) AS count FROM continuous_shadow_evaluations "
                "WHERE experiment_id = ? GROUP BY pool_class, status "
                "ORDER BY pool_class, status",
                (experiment_id,),
            ).fetchall()
            wallets = connection.execute(
                "SELECT portfolio_id, wallet_id, cash, realized_pnl, unrealized_pnl, fees, "
                "nav, drawdown, exposure FROM continuous_shadow_portfolios "
                "WHERE experiment_id = ? AND kind = 'WALLET' "
                "ORDER BY wallet_id",
                (experiment_id,),
            ).fetchall()
            poll_totals = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(raw_event_count), 0), "
                "COALESCE(SUM(new_event_count), 0), COALESCE(SUM(duplicate_count), 0), "
                "COALESCE(SUM(settlement_count), 0) FROM continuous_shadow_poll_runs "
                "WHERE experiment_id = ? AND status = 'succeeded'",
                (experiment_id,),
            ).fetchone()
            open_positions = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_positions "
                    "WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchone()[0]
            )
            ledger_balanced = _ledger_balanced(connection, experiment_id)
        finally:
            connection.close()
        assert follower is not None
        initial = Decimal(str(follower["initial_cash"]))
        realized = Decimal(str(follower["realized_pnl"]))
        unrealized = Decimal(str(follower["unrealized_pnl"]))
        fees = Decimal(str(follower["fees"]))
        nav = Decimal(str(follower["nav"]))
        identity_delta = nav - (initial + realized + unrealized - fees)
        return {
            "accounting": {
                "identity": "NAV = initial_cash + realized_pnl + unrealized_pnl - fees",
                "identity_delta": format(identity_delta, "f"),
                "ledger_balanced": ledger_balanced,
            },
            "experiment": _experiment(experiment_row).to_dict(),
            "follower": {
                key: str(follower[key])
                for key in (
                    "cash",
                    "drawdown",
                    "exposure",
                    "fees",
                    "high_water_nav",
                    "initial_cash",
                    "nav",
                    "realized_pnl",
                    "unrealized_pnl",
                )
            },
            "open_position_count": open_positions,
            "pools": [
                {
                    "count": int(row["count"]),
                    "pool_class": str(row["pool_class"]),
                    "status": str(row["status"]),
                }
                for row in status_rows
            ],
            "polls": {
                "duplicate_count": int(poll_totals[3]),
                "new_event_count": int(poll_totals[2]),
                "raw_event_count": int(poll_totals[1]),
                "settlement_count": int(poll_totals[4]),
                "succeeded": int(poll_totals[0]),
            },
            "status": "succeeded",
            "wallets": [
                {
                    key: (str(row[key]) if row[key] is not None else None)
                    for key in (
                        "wallet_id",
                        "cash",
                        "realized_pnl",
                        "unrealized_pnl",
                        "fees",
                        "nav",
                        "drawdown",
                        "exposure",
                    )
                }
                for row in sorted(
                    wallets,
                    key=lambda value: (
                        -Decimal(str(value["nav"])),
                        str(value["wallet_id"]),
                    ),
                )[:limit]
            ],
        }

    def _upsert_candidates(
        self,
        connection: sqlite3.Connection,
        *,
        experiment_id: str,
        selection_run_id: str,
        candidates: tuple[ProtectedShadowCandidate, ...],
        selected_at: datetime,
        reset_active: bool,
        wallet_bankroll: Decimal,
    ) -> None:
        if reset_active:
            connection.execute(
                "UPDATE continuous_shadow_candidates SET active = 0 WHERE experiment_id = ?",
                (experiment_id,),
            )
        for candidate in candidates:
            connection.execute(
                "INSERT INTO continuous_shadow_candidates "
                "(experiment_id, wallet_id, pools_json, alpha_rank, stress_rank, "
                "selection_run_id, active, first_selected_at, last_selected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(experiment_id, wallet_id) DO UPDATE SET "
                "pools_json = excluded.pools_json, alpha_rank = excluded.alpha_rank, "
                "stress_rank = excluded.stress_rank, selection_run_id = excluded.selection_run_id, "
                "active = 1, last_selected_at = excluded.last_selected_at",
                (
                    experiment_id,
                    candidate.wallet_id,
                    json.dumps(candidate.pools, separators=(",", ":")),
                    candidate.alpha_rank,
                    candidate.stress_rank,
                    selection_run_id,
                    _iso(selected_at),
                    _iso(selected_at),
                ),
            )
            portfolio_id = f"wallet:{candidate.wallet_id}"
            connection.execute(
                "INSERT OR IGNORE INTO continuous_shadow_portfolios "
                "(experiment_id, portfolio_id, kind, wallet_id, initial_cash, cash, "
                "realized_pnl, unrealized_pnl, fees, nav, high_water_nav, drawdown, "
                "exposure, updated_at) VALUES (?, ?, 'WALLET', ?, ?, ?, '0', '0', '0', "
                "?, ?, '0', '0', ?)",
                (
                    experiment_id,
                    portfolio_id,
                    candidate.wallet_id,
                    _decimal(wallet_bankroll),
                    _decimal(wallet_bankroll),
                    _decimal(wallet_bankroll),
                    _decimal(wallet_bankroll),
                    _iso(selected_at),
                ),
            )

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                f"{self._path.resolve().as_uri()}?mode=ro", uri=True, timeout=10
            )
        else:
            connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchall()
        if len(rows) != 1 or int(rows[0][0]) != CONTINUOUS_SHADOW_SCHEMA_VERSION:
            raise ContinuousShadowStoreError("Continuous Shadow schema version is unsupported.")

    @staticmethod
    def _require_integrity(connection: sqlite3.Connection) -> None:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise ContinuousShadowStoreError("Continuous Shadow SQLite integrity check failed.")


def _validate_completion(completion: ContinuousPollCompletion) -> None:
    event_ids = [event.event_id for event, _ in completion.events]
    if len(event_ids) != len(set(event_ids)):
        raise ContinuousShadowStoreError("Continuous Shadow journal events are duplicated.")
    known = set(event_ids)
    if any(item.event_id not in known for item in completion.evaluations):
        raise ContinuousShadowStoreError("Continuous Shadow evaluation lacks journal evidence.")
    evaluation_keys = [
        (item.event_id, item.portfolio_id) for item in completion.evaluations
    ]
    if len(evaluation_keys) != len(set(evaluation_keys)):
        raise ContinuousShadowStoreError("Continuous Shadow evaluations are duplicated.")
    portfolio_ids = {item.portfolio_id for item in completion.portfolios}
    if "follower" not in portfolio_ids:
        raise ContinuousShadowStoreError("Continuous Shadow follower portfolio is missing.")
    if any(item.portfolio_id not in portfolio_ids for item in completion.evaluations):
        raise ContinuousShadowStoreError("Continuous Shadow evaluation portfolio is unknown.")
    for portfolio in completion.portfolios:
        if min(
            portfolio.initial_cash,
            portfolio.cash,
            portfolio.fees,
            portfolio.high_water_nav,
            portfolio.drawdown,
        ) < _ZERO:
            raise ContinuousShadowStoreError("Continuous Shadow portfolio values are invalid.")
        if any(
            position.quantity <= _ZERO
            or position.cost_basis < _ZERO
            or position.entry_fees < _ZERO
            for position in portfolio.positions
        ):
            raise ContinuousShadowStoreError("Continuous Shadow position values are invalid.")


def _write_portfolio(
    connection: sqlite3.Connection,
    experiment_id: str,
    portfolio: ContinuousPortfolio,
    completed_at: datetime,
) -> None:
    market_value = sum(
        (
            position.market_value
            for position in portfolio.positions
            if position.market_value is not None
        ),
        _ZERO,
    )
    marked_cost = sum(
        (
            position.cost_basis
            for position in portfolio.positions
            if position.market_value is not None
        ),
        _ZERO,
    )
    unrealized = market_value - marked_cost
    nav = portfolio.cash + market_value
    high_water = max(portfolio.high_water_nav, nav)
    drawdown = _ZERO if high_water == _ZERO else (high_water - nav) / high_water
    connection.execute(
        "INSERT INTO continuous_shadow_portfolios "
        "(experiment_id, portfolio_id, kind, wallet_id, initial_cash, cash, "
        "realized_pnl, unrealized_pnl, fees, nav, high_water_nav, drawdown, exposure, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(experiment_id, portfolio_id) DO UPDATE SET cash = excluded.cash, "
        "realized_pnl = excluded.realized_pnl, unrealized_pnl = excluded.unrealized_pnl, "
        "fees = excluded.fees, nav = excluded.nav, high_water_nav = excluded.high_water_nav, "
        "drawdown = excluded.drawdown, exposure = excluded.exposure, "
        "updated_at = excluded.updated_at",
        (
            experiment_id,
            portfolio.portfolio_id,
            portfolio.kind.value,
            portfolio.wallet_id,
            _decimal(portfolio.initial_cash),
            _decimal(portfolio.cash),
            _decimal(portfolio.realized_pnl),
            _decimal(unrealized),
            _decimal(portfolio.fees),
            _decimal(nav),
            _decimal(high_water),
            _decimal(drawdown),
            _decimal(portfolio.exposure),
            _iso(completed_at),
        ),
    )


def _write_ledger(
    connection: sqlite3.Connection,
    experiment_id: str,
    poll_run_id: str,
    item: ContinuousLedgerRecord,
) -> None:
    connection.execute(
        "INSERT INTO continuous_shadow_ledger "
        "(experiment_id, entry_id, poll_run_id, portfolio_id, event_id, entry_type, "
        "market_reference, outcome_reference, quantity_delta, cash_delta, cost_basis_delta, "
        "realized_pnl_delta, fee_delta, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            experiment_id,
            item.entry_id,
            poll_run_id,
            item.portfolio_id,
            item.event_id,
            item.entry_type,
            item.market_reference,
            item.outcome_reference,
            _decimal(item.quantity_delta),
            _decimal(item.cash_delta),
            _decimal(item.cost_basis_delta),
            _decimal(item.realized_pnl_delta),
            _decimal(item.fee_delta),
            _iso(item.created_at),
        ),
    )


def _write_mark(
    connection: sqlite3.Connection,
    experiment_id: str,
    poll_run_id: str,
    item: ContinuousPositionMark,
) -> None:
    connection.execute(
        "INSERT INTO continuous_shadow_position_marks "
        "(experiment_id, poll_run_id, portfolio_id, market_reference, outcome_reference, "
        "quantity, mark_price, market_value, unrealized_pnl, mark_status, marked_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            experiment_id,
            poll_run_id,
            item.portfolio_id,
            item.market_reference,
            item.outcome_reference,
            _decimal(item.quantity),
            _optional_decimal(item.mark_price),
            _optional_decimal(item.market_value),
            _optional_decimal(item.unrealized_pnl),
            item.mark_status,
            _iso(item.marked_at),
        ),
    )


def _ledger_balanced(connection: sqlite3.Connection, experiment_id: str) -> bool:
    portfolio_rows = connection.execute(
        "SELECT portfolio_id, initial_cash, cash, realized_pnl, fees "
        "FROM continuous_shadow_portfolios WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()
    ledger_rows = connection.execute(
        "SELECT portfolio_id, market_reference, outcome_reference, quantity_delta, "
        "cash_delta, cost_basis_delta, realized_pnl_delta, fee_delta "
        "FROM continuous_shadow_ledger WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()
    portfolio_totals: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    position_totals: dict[tuple[str, str, str], tuple[Decimal, Decimal]] = {}
    for ledger_row in ledger_rows:
        portfolio_id = str(ledger_row["portfolio_id"])
        cash, realized, fees = portfolio_totals.get(
            portfolio_id, (_ZERO, _ZERO, _ZERO)
        )
        portfolio_totals[portfolio_id] = (
            cash + Decimal(str(ledger_row["cash_delta"])),
            realized + Decimal(str(ledger_row["realized_pnl_delta"])),
            fees + Decimal(str(ledger_row["fee_delta"])),
        )
        if (
            ledger_row["market_reference"] is not None
            and ledger_row["outcome_reference"] is not None
        ):
            key = (
                portfolio_id,
                str(ledger_row["market_reference"]),
                str(ledger_row["outcome_reference"]),
            )
            quantity, cost_basis = position_totals.get(key, (_ZERO, _ZERO))
            position_totals[key] = (
                quantity + Decimal(str(ledger_row["quantity_delta"])),
                cost_basis + Decimal(str(ledger_row["cost_basis_delta"])),
            )
    for row in portfolio_rows:
        totals = portfolio_totals.get(str(row["portfolio_id"]), (_ZERO, _ZERO, _ZERO))
        expected_cash = Decimal(str(row["initial_cash"])) + totals[0]
        if abs(expected_cash - Decimal(str(row["cash"]))) > Decimal("0.000001"):
            return False
        if abs(totals[1] - Decimal(str(row["realized_pnl"]))) > Decimal(
            "0.000001"
        ):
            return False
        if abs(totals[2] - Decimal(str(row["fees"]))) > Decimal("0.000001"):
            return False
    position_rows = connection.execute(
        "SELECT portfolio_id, market_reference, outcome_reference, quantity, cost_basis "
        "FROM continuous_shadow_positions WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()
    current_position_keys: set[tuple[str, str, str]] = set()
    for row in position_rows:
        key = (
            str(row["portfolio_id"]),
            str(row["market_reference"]),
            str(row["outcome_reference"]),
        )
        current_position_keys.add(key)
        position_total = position_totals.get(key, (_ZERO, _ZERO))
        if abs(position_total[0] - Decimal(str(row["quantity"]))) > Decimal(
            "0.000001"
        ):
            return False
        if abs(position_total[1] - Decimal(str(row["cost_basis"]))) > Decimal(
            "0.000001"
        ):
            return False
    for key, (quantity, cost_basis) in position_totals.items():
        if key not in current_position_keys and (
            abs(quantity) > Decimal("0.000001")
            or abs(cost_basis) > Decimal("0.000001")
        ):
            return False
    return True


def _experiment(row: sqlite3.Row) -> ContinuousShadowExperiment:
    config = _config(json.loads(str(row["config_json"])))
    return ContinuousShadowExperiment(
        experiment_id=str(row["experiment_id"]),
        source_id=str(row["source_id"]),
        selection_run_id=str(row["selection_run_id"]),
        policy_version=str(row["policy_version"]),
        cost_model_version=str(row["cost_model_version"]),
        bankroll_version=str(row["bankroll_version"]),
        config=config,
        lifecycle=ContinuousShadowLifecycle(str(row["lifecycle"])),
        started_at=_datetime(str(row["started_at"])),
        draining_at=(
            None if row["draining_at"] is None else _datetime(str(row["draining_at"]))
        ),
        finalized_at=(
            None if row["finalized_at"] is None else _datetime(str(row["finalized_at"]))
        ),
        last_successful_poll_at=(
            None
            if row["last_successful_poll_at"] is None
            else _datetime(str(row["last_successful_poll_at"]))
        ),
        last_error_code=(
            None if row["last_error_code"] is None else str(row["last_error_code"])
        ),
    )


def _config(value: object) -> ContinuousShadowConfig:
    if not isinstance(value, dict):
        raise ContinuousShadowStoreError("Continuous Shadow config is invalid.")
    try:
        return ContinuousShadowConfig(
            wallet_bankroll=Decimal(str(value["wallet_bankroll"])),
            follower_bankroll=Decimal(str(value["follower_bankroll"])),
            maximum_event_notional=Decimal(str(value["maximum_event_notional"])),
            wallet_maximum_exposure=Decimal(str(value["wallet_maximum_exposure"])),
            follower_maximum_exposure=Decimal(str(value["follower_maximum_exposure"])),
            follower_maximum_wallet_exposure=Decimal(
                str(value["follower_maximum_wallet_exposure"])
            ),
            follower_maximum_market_exposure=Decimal(
                str(value["follower_maximum_market_exposure"])
            ),
            follower_maximum_positions=int(value["follower_maximum_positions"]),
            maximum_forward_delay_ms=int(value["maximum_forward_delay_ms"]),
            maximum_quote_age_ms=int(value["maximum_quote_age_ms"]),
            initial_lookback_minutes=int(value["initial_lookback_minutes"]),
            overlap_seconds=int(value["overlap_seconds"]),
            policy_version=str(value["policy_version"]),
            cost_model_version=str(value["cost_model_version"]),
            bankroll_version=str(value["bankroll_version"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ContinuousShadowStoreError("Continuous Shadow config is invalid.") from error


def _candidate(row: sqlite3.Row) -> ProtectedShadowCandidate:
    address = str(row["normalized_address"])
    if _WALLET_PATTERN.fullmatch(address) is None:
        raise ContinuousShadowStoreError("Protected candidate address is invalid.")
    pools = json.loads(str(row["pools_json"]))
    if not isinstance(pools, list) or any(not isinstance(value, str) for value in pools):
        raise ContinuousShadowStoreError("Continuous Shadow candidate pools are invalid.")
    return ProtectedShadowCandidate(
        wallet_id=str(row["wallet_id"]),
        address=address,
        pools=tuple(pools),
        alpha_rank=None if row["alpha_rank"] is None else int(row["alpha_rank"]),
        stress_rank=None if row["stress_rank"] is None else int(row["stress_rank"]),
    )


def _portfolio(
    row: sqlite3.Row,
    positions: tuple[ContinuousPosition, ...],
) -> ContinuousPortfolio:
    return ContinuousPortfolio(
        portfolio_id=str(row["portfolio_id"]),
        kind=ContinuousPortfolioKind(str(row["kind"])),
        wallet_id=None if row["wallet_id"] is None else str(row["wallet_id"]),
        initial_cash=Decimal(str(row["initial_cash"])),
        cash=Decimal(str(row["cash"])),
        realized_pnl=Decimal(str(row["realized_pnl"])),
        fees=Decimal(str(row["fees"])),
        high_water_nav=Decimal(str(row["high_water_nav"])),
        drawdown=Decimal(str(row["drawdown"])),
        positions=positions,
    )


def _position(row: sqlite3.Row) -> ContinuousPosition:
    return ContinuousPosition(
        portfolio_id=str(row["portfolio_id"]),
        market_reference=str(row["market_reference"]),
        outcome_reference=str(row["outcome_reference"]),
        quantity=Decimal(str(row["quantity"])),
        cost_basis=Decimal(str(row["cost_basis"])),
        entry_fees=Decimal(str(row["entry_fees"])),
        mark_price=None if row["mark_price"] is None else Decimal(str(row["mark_price"])),
        marked_at=None if row["marked_at"] is None else _datetime(str(row["marked_at"])),
    )


def _event_outcome(
    events: tuple[tuple[Any, tuple[str, ...]], ...], event_id: str
) -> str:
    for event, _ in events:
        if event.event_id == event_id:
            return str(event.outcome_reference)
    raise ContinuousShadowStoreError("Continuous Shadow event evidence is unavailable.")


def _safe_error_code(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    return normalized[:80] or "continuous_shadow_failed"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be timezone-aware UTC")
    return value


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc(parsed)


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("decimal must be finite")
    return format(value, "f")


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else _decimal(value)


def _restrict_file(path: Path) -> None:
    with suppress(OSError):
        os.chmod(path, 0o600)


__all__ = [
    "CONTINUOUS_SHADOW_SCHEMA_VERSION",
    "ContinuousShadowRepository",
    "ContinuousShadowStoreError",
]
