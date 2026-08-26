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
from polysia.domain.copytrading import LeaderTradeAction
from polysia.domain.copytrading.continuous_shadow import (
    FOLLOWER_KIND_SPECS,
    ContinuousPortfolio,
    ContinuousPortfolioKind,
    ContinuousPosition,
    ContinuousShadowConfig,
    ContinuousShadowLifecycle,
)
from polysia.domain.copytrading.continuous_shadow_experiments import (
    RecordedShadowFill,
    walk_forward_policy_report,
)
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.wallet_intelligence import CandidateStoreError

CONTINUOUS_SHADOW_SCHEMA_PATH = Path(__file__).with_name("continuous_shadow_schema.sql")
CONTINUOUS_SHADOW_SCHEMA_VERSION = 4
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
            _migrate_schema(connection)
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
            for portfolio_id, kind, _accepted in FOLLOWER_KIND_SPECS:
                connection.execute(
                    "INSERT INTO continuous_shadow_portfolios "
                    "(experiment_id, portfolio_id, kind, wallet_id, initial_cash, cash, "
                    "realized_pnl, unrealized_pnl, fees, nav, high_water_nav, drawdown, "
                    "exposure, updated_at) VALUES (?, ?, ?, NULL, ?, ?, "
                    "'0', '0', '0', ?, ?, '0', '0', ?)",
                    (
                        experiment_id,
                        portfolio_id,
                        kind.value,
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
                portfolio_id=str(row["portfolio_id"]),
                pool_class=str(row["pool_class"]),
                last_event_id=(
                    None if row["last_event_id"] is None else str(row["last_event_id"])
                ),
            )
            for row in rows
        )

    def terminal_book_cache(
        self,
        token_ids: tuple[str, ...],
        *,
        now: datetime,
    ) -> dict[str, str]:
        if not token_ids:
            return {}
        now = _utc(now)
        cached: dict[str, str] = {}
        connection = self._connect()
        try:
            placeholders = ",".join("?" for _ in token_ids)
            rows = connection.execute(
                "SELECT token_id, reason, expires_at, hit_count "
                f"FROM continuous_shadow_terminal_book_cache "
                f"WHERE token_id IN ({placeholders}) AND expires_at > ?",
                (*token_ids, _iso(now)),
            ).fetchall()
            for row in rows:
                cached[str(row["token_id"])] = str(row["reason"])
                connection.execute(
                    "UPDATE continuous_shadow_terminal_book_cache "
                    "SET hit_count = hit_count + 1, last_seen_at = ? WHERE token_id = ?",
                    (_iso(now), str(row["token_id"])),
                )
            connection.commit()
        finally:
            connection.close()
        return cached

    def remember_terminal_books(
        self,
        entries: tuple[tuple[str, str], ...],
        *,
        now: datetime,
        ttl_seconds: int,
    ) -> None:
        if not entries:
            return
        now = _utc(now)
        expires_at = now + timedelta(seconds=ttl_seconds)
        connection = self._connect()
        try:
            for token_id, reason in entries:
                connection.execute(
                    "INSERT INTO continuous_shadow_terminal_book_cache "
                    "(token_id, reason, first_seen_at, last_seen_at, expires_at, hit_count) "
                    "VALUES (?, ?, ?, ?, ?, 1) "
                    "ON CONFLICT(token_id) DO UPDATE SET reason = excluded.reason, "
                    "last_seen_at = excluded.last_seen_at, expires_at = excluded.expires_at",
                    (token_id, reason, _iso(now), _iso(now), _iso(expires_at)),
                )
            connection.commit()
        finally:
            connection.close()

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
                    "first_poll_run_id, external_evidence_reference, pools_json, "
                    "processing_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROCESSED')",
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
                    "(experiment_id, portfolio_id, wallet_id, market_reference, "
                    "outcome_reference, quantity, cost_basis, pool_class, last_event_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        experiment.experiment_id,
                        attribution_row.portfolio_id,
                        attribution_row.wallet_id,
                        attribution_row.market_reference,
                        attribution_row.outcome_reference,
                        _decimal(attribution_row.quantity),
                        _decimal(attribution_row.cost_basis),
                        attribution_row.pool_class,
                        attribution_row.last_event_id,
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
                "rejected_count = ?, settlement_count = ?, settlement_backlog_count = ?, "
                "realized_pnl_delta = ?, fee_delta = ?, source_api_lag_max_ms = ?, "
                "signal_delay_max_ms = ?, "
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
                    completion.settlement_backlog_count,
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
            settlement_backlog_count=completion.settlement_backlog_count,
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
                    duplicate_processing_count=0,
                    unknown_ratio=None,
                    ledger_balanced=True,
                    unmarked_position_count=0,
                    unknown_fee_count=0,
                    open_position_count=0,
                    settlement_backlog_count=0,
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
            duplicate_processing_count = _duplicate_processing_count(
                connection, experiment.experiment_id
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
            settlement_backlog_row = connection.execute(
                "SELECT settlement_backlog_count FROM continuous_shadow_poll_runs "
                "WHERE experiment_id = ? AND status = 'succeeded' "
                "ORDER BY completed_at DESC LIMIT 1",
                (experiment.experiment_id,),
            ).fetchone()
            settlement_backlog_count = (
                0 if settlement_backlog_row is None else int(settlement_backlog_row[0])
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
            initialization_unknown_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_evaluations "
                    "WHERE experiment_id = ? AND status = 'UNKNOWN' "
                    "AND reason IN ("
                    "'source_and_signal_delay_exceeded', "
                    "'current_order_book_unavailable'"
                    ")",
                    (experiment.experiment_id,),
                ).fetchone()[0]
            )
            rolling_windows = _rolling_health_windows(
                connection,
                experiment.experiment_id,
                now=now,
            )
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
        rolling_1h = rolling_windows.get("1h")
        rolling_unknown = (
            rolling_1h.get("unknown_ratio") if isinstance(rolling_1h, dict) else None
        )
        if isinstance(rolling_unknown, str) and Decimal(rolling_unknown) > Decimal("0.5"):
            reasons.append("continuous_shadow_rolling_1h_unknown_ratio_high")
            level = "warning" if level == "healthy" else level
        elif unknown_ratio is not None and unknown_ratio > Decimal("0.5"):
            reasons.append("continuous_shadow_cumulative_unknown_includes_initialization_backlog")
        if unknown_fee_count:
            reasons.append("continuous_shadow_fee_provenance_unknown")
            level = "warning" if level == "healthy" else level
        if unmarked:
            reasons.append("continuous_shadow_positions_unmarked")
            level = "warning" if level == "healthy" else level
        if settlement_backlog_count:
            reasons.append("continuous_shadow_settlement_backlog")
            level = "warning" if level == "healthy" else level
        if duplicate_processing_count:
            reasons.append("continuous_shadow_duplicate_processing")
            level = "critical"
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
            duplicate_processing_count=duplicate_processing_count,
            unknown_ratio=unknown_ratio,
            ledger_balanced=ledger_balanced,
            unmarked_position_count=unmarked,
            unknown_fee_count=unknown_fee_count,
            open_position_count=open_position_count,
            settlement_backlog_count=settlement_backlog_count,
            rolling_windows=rolling_windows,
            initialization_unknown_count=initialization_unknown_count,
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
            followers = connection.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM continuous_shadow_positions x "
                "WHERE x.experiment_id = p.experiment_id "
                "AND x.portfolio_id = p.portfolio_id) AS open_position_count, "
                "(SELECT COUNT(*) FROM continuous_shadow_positions x "
                "WHERE x.experiment_id = p.experiment_id "
                "AND x.portfolio_id = p.portfolio_id AND COALESCE(("
                "SELECT m.mark_status FROM continuous_shadow_position_marks m "
                "WHERE m.experiment_id = x.experiment_id "
                "AND m.portfolio_id = x.portfolio_id "
                "AND m.market_reference = x.market_reference "
                "AND m.outcome_reference = x.outcome_reference "
                "ORDER BY m.marked_at DESC, m.poll_run_id DESC LIMIT 1"
                "), 'MISSING') <> 'VERIFIED_EXECUTABLE_BID') "
                "AS unmarked_position_count "
                "FROM continuous_shadow_portfolios p WHERE p.experiment_id = ? "
                "AND p.kind IN ('FOLLOWER', 'FOLLOWER_ALPHA', 'FOLLOWER_STRESS') "
                "ORDER BY p.kind",
                (experiment_id,),
            ).fetchall()
            follower = next(
                (row for row in followers if str(row["kind"]) == "FOLLOWER"),
                None,
            )
            status_rows = connection.execute(
                "SELECT pool_class, status, COUNT(*) AS count FROM continuous_shadow_evaluations "
                "WHERE experiment_id = ? GROUP BY pool_class, status "
                "ORDER BY pool_class, status",
                (experiment_id,),
            ).fetchall()
            wallets = connection.execute(
                "SELECT p.portfolio_id, p.wallet_id, p.initial_cash, p.cash, "
                "p.realized_pnl, p.unrealized_pnl, p.fees, p.nav, p.drawdown, p.exposure, "
                "(SELECT COUNT(*) FROM continuous_shadow_positions x "
                "WHERE x.experiment_id = p.experiment_id "
                "AND x.portfolio_id = p.portfolio_id) AS open_position_count, "
                "(SELECT COUNT(*) FROM continuous_shadow_positions x "
                "WHERE x.experiment_id = p.experiment_id "
                "AND x.portfolio_id = p.portfolio_id AND COALESCE(("
                "SELECT m.mark_status FROM continuous_shadow_position_marks m "
                "WHERE m.experiment_id = x.experiment_id "
                "AND m.portfolio_id = x.portfolio_id "
                "AND m.market_reference = x.market_reference "
                "AND m.outcome_reference = x.outcome_reference "
                "ORDER BY m.marked_at DESC, m.poll_run_id DESC LIMIT 1"
                "), 'MISSING') <> 'VERIFIED_EXECUTABLE_BID') "
                "AS unmarked_position_count "
                "FROM continuous_shadow_portfolios p "
                "WHERE p.experiment_id = ? AND p.kind = 'WALLET' "
                "ORDER BY p.wallet_id",
                (experiment_id,),
            ).fetchall()
            poll_totals = connection.execute(
                "SELECT COUNT(*) AS succeeded, "
                "COALESCE(SUM(raw_event_count), 0) AS raw_event_count, "
                "COALESCE(SUM(new_event_count), 0) AS new_event_count, "
                "COALESCE(SUM(duplicate_count), 0) AS duplicate_count, "
                "COALESCE(SUM(settlement_count), 0) AS settlement_count, "
                "COALESCE(MAX(settlement_backlog_count), 0) AS settlement_backlog_max, "
                "COALESCE(SUM(simulated_count), 0) AS simulated_count, "
                "COALESCE(SUM(unknown_count), 0) AS unknown_count, "
                "COALESCE(SUM(rejected_count), 0) AS rejected_count, "
                "MIN(completed_at) AS first_poll_at, MAX(completed_at) AS latest_poll_at "
                "FROM continuous_shadow_poll_runs "
                "WHERE experiment_id = ? AND status = 'succeeded'",
                (experiment_id,),
            ).fetchone()
            latest_backlog_row = connection.execute(
                "SELECT settlement_backlog_count FROM continuous_shadow_poll_runs "
                "WHERE experiment_id = ? AND status = 'succeeded' "
                "ORDER BY completed_at DESC LIMIT 1",
                (experiment_id,),
            ).fetchone()
            current_settlement_backlog = (
                0 if latest_backlog_row is None else int(latest_backlog_row[0])
            )
            event_window = connection.execute(
                "SELECT MIN(j.executed_at) AS first_source_event_at, "
                "MAX(j.executed_at) AS latest_source_event_at, "
                "MIN(j.first_seen_at) AS first_seen_at, "
                "MAX(j.first_seen_at) AS latest_seen_at, "
                "COUNT(*) AS unique_source_events, "
                "COUNT(DISTINCT j.wallet_id) AS active_wallets, "
                "COUNT(DISTINCT j.market_reference) AS active_markets "
                "FROM continuous_shadow_event_journal j "
                "JOIN continuous_shadow_poll_runs p ON p.poll_run_id = j.first_poll_run_id "
                "WHERE p.experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            processing_rows = connection.execute(
                "SELECT j.processing_status, COUNT(*) AS count "
                "FROM continuous_shadow_event_journal j "
                "JOIN continuous_shadow_poll_runs p ON p.poll_run_id = j.first_poll_run_id "
                "WHERE p.experiment_id = ? GROUP BY j.processing_status "
                "ORDER BY j.processing_status",
                (experiment_id,),
            ).fetchall()
            evaluation_rows = connection.execute(
                "SELECT e.*, j.market_reference, p.selection_run_id "
                "FROM continuous_shadow_evaluations e "
                "JOIN continuous_shadow_event_journal j ON j.event_id = e.event_id "
                "JOIN continuous_shadow_poll_runs p ON p.poll_run_id = e.poll_run_id "
                "WHERE e.experiment_id = ? "
                "ORDER BY e.evaluated_at, e.event_id, e.portfolio_id",
                (experiment_id,),
            ).fetchall()
            candidate_rows = connection.execute(
                "SELECT wallet_id, alpha_rank, stress_rank, active "
                "FROM continuous_shadow_candidates WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()
            close_rows = connection.execute(
                "SELECT l.portfolio_id, p.kind, p.wallet_id, l.entry_type, "
                "l.realized_pnl_delta, l.fee_delta, l.wallet_id AS ledger_wallet_id, "
                "l.pool_class AS ledger_pool_class, l.market_reference, e.pool_class "
                "FROM continuous_shadow_ledger l "
                "JOIN continuous_shadow_portfolios p ON p.experiment_id = l.experiment_id "
                "AND p.portfolio_id = l.portfolio_id "
                "LEFT JOIN continuous_shadow_evaluations e "
                "ON e.experiment_id = l.experiment_id AND e.event_id = l.event_id "
                "AND e.portfolio_id = l.portfolio_id "
                "WHERE l.experiment_id = ? AND l.entry_type IN ('CLOSE', 'SETTLEMENT') "
                "ORDER BY l.created_at, l.entry_id",
                (experiment_id,),
            ).fetchall()
            checkpoint = connection.execute(
                "SELECT watermark, updated_at, last_poll_run_id "
                "FROM continuous_shadow_checkpoint WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            open_positions = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuous_shadow_positions "
                    "WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchone()[0]
            )
            unmarked_position_rows = connection.execute(
                "SELECT portfolio_id, cost_basis FROM continuous_shadow_positions "
                "WHERE experiment_id = ? AND mark_price IS NULL",
                (experiment_id,),
            ).fetchall()
            untrusted_mark_count = int(
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
                    (experiment_id,),
                ).fetchone()[0]
            )
            ledger_balanced = _ledger_balanced(connection, experiment_id)
            duplicate_processing_count = _duplicate_processing_count(
                connection, experiment_id
            )
            pnl_decomposition_rows = connection.execute(
                "SELECT entry_type, realized_pnl_delta, fee_delta "
                "FROM continuous_shadow_ledger WHERE experiment_id = ? "
                "AND portfolio_id = 'follower'",
                (experiment_id,),
            ).fetchall()
            wallet_attribution_rows = connection.execute(
                "SELECT COALESCE(l.wallet_id, p.wallet_id) AS wallet_id, "
                "COALESCE(l.pool_class, e.pool_class) AS pool_class, "
                "l.entry_type, l.realized_pnl_delta, l.fee_delta, l.market_reference "
                "FROM continuous_shadow_ledger l "
                "JOIN continuous_shadow_portfolios p ON p.experiment_id = l.experiment_id "
                "AND p.portfolio_id = l.portfolio_id "
                "LEFT JOIN continuous_shadow_evaluations e "
                "ON e.experiment_id = l.experiment_id AND e.event_id = l.event_id "
                "AND e.portfolio_id = l.portfolio_id "
                "WHERE l.experiment_id = ? AND l.portfolio_id = 'follower' "
                "AND l.entry_type IN ('CLOSE', 'SETTLEMENT')",
                (experiment_id,),
            ).fetchall()
            poll_latency_rows = connection.execute(
                "SELECT started_at, completed_at FROM continuous_shadow_poll_runs "
                "WHERE experiment_id = ? AND status = 'succeeded' AND completed_at IS NOT NULL "
                "ORDER BY completed_at",
                (experiment_id,),
            ).fetchall()
            latest_marks = connection.execute(
                "SELECT p.portfolio_id, p.market_reference, p.outcome_reference, "
                "p.mark_price, p.marked_at, "
                "m.mark_status, m.source_timestamp, m.source_age_ms, m.freshness, m.marked_at "
                "AS mark_recorded_at "
                "FROM continuous_shadow_positions p "
                "LEFT JOIN continuous_shadow_position_marks m "
                "ON m.experiment_id = p.experiment_id AND m.portfolio_id = p.portfolio_id "
                "AND m.market_reference = p.market_reference "
                "AND m.outcome_reference = p.outcome_reference "
                "AND m.poll_run_id = ("
                "SELECT last_poll_run_id FROM continuous_shadow_checkpoint "
                "WHERE experiment_id = p.experiment_id) "
                "WHERE p.experiment_id = ? AND p.portfolio_id = 'follower'",
                (experiment_id,),
            ).fetchall()
            cache_hits = connection.execute(
                "SELECT reason, SUM(hit_count) AS hits, COUNT(*) AS tokens "
                "FROM continuous_shadow_terminal_book_cache GROUP BY reason"
            ).fetchall()
            fill_rows = connection.execute(
                "SELECT e.evaluated_at, e.wallet_id, e.pool_class, j.action, j.leader_price, "
                "e.follower_price, e.filled_size, e.gross_notional, e.fee, e.price_movement, "
                "e.spread_cost, e.depth_impact, e.realized_pnl, e.status "
                "FROM continuous_shadow_evaluations e "
                "JOIN continuous_shadow_event_journal j ON j.event_id = e.event_id "
                "WHERE e.experiment_id = ? AND e.portfolio_id = 'follower' "
                "ORDER BY e.evaluated_at, e.event_id",
                (experiment_id,),
            ).fetchall()
        finally:
            connection.close()
        assert follower is not None
        assert poll_totals is not None
        assert event_window is not None
        experiment = _experiment(experiment_row)
        initial = Decimal(str(follower["initial_cash"]))
        realized = Decimal(str(follower["realized_pnl"]))
        unrealized = Decimal(str(follower["unrealized_pnl"]))
        fees = Decimal(str(follower["fees"]))
        nav = Decimal(str(follower["nav"]))
        identity_delta = nav - (initial + realized + unrealized - fees)
        unmarked_cost_basis = sum(
            (Decimal(str(row["cost_basis"])) for row in unmarked_position_rows),
            _ZERO,
        )
        follower_unmarked_cost_basis = sum(
            (
                Decimal(str(row["cost_basis"]))
                for row in unmarked_position_rows
                if str(row["portfolio_id"]) == "follower"
            ),
            _ZERO,
        )
        follower_valuation_complete = int(follower["unmarked_position_count"]) == 0
        identity_status = (
            "VERIFIED"
            if follower_valuation_complete and identity_delta == _ZERO
            else "MISMATCH" if follower_valuation_complete else "INCOMPLETE_MARKS"
        )
        candidate_membership = {
            str(row["wallet_id"]): {
                "alpha": row["alpha_rank"] is not None,
                "stress": row["stress_rank"] is not None,
                "active": bool(row["active"]),
            }
            for row in candidate_rows
        }
        follower_ids = {"follower", "follower-alpha", "follower-stress"}
        wallet_evaluations = [
            row for row in evaluation_rows if str(row["portfolio_id"]) not in follower_ids
        ]
        follower_evaluations = [
            row for row in evaluation_rows if str(row["portfolio_id"]) == "follower"
        ]
        alpha_follower_evaluations = [
            row for row in evaluation_rows if str(row["portfolio_id"]) == "follower-alpha"
        ]
        stress_follower_evaluations = [
            row for row in evaluation_rows if str(row["portfolio_id"]) == "follower-stress"
        ]
        alpha_wallets = {
            wallet_id
            for wallet_id, membership in candidate_membership.items()
            if membership["alpha"]
        }
        stress_wallets = {
            wallet_id
            for wallet_id, membership in candidate_membership.items()
            if membership["stress"]
        }
        wallet_rows = list(wallets)
        alpha_portfolios = [
            row for row in wallet_rows if str(row["wallet_id"]) in alpha_wallets
        ]
        stress_portfolios = [
            row for row in wallet_rows if str(row["wallet_id"]) in stress_wallets
        ]
        alpha_evaluations = [
            row
            for row in wallet_evaluations
            if str(row["pool_class"]) in {"ALPHA", "ALPHA_STRESS"}
        ]
        stress_evaluations = [
            row
            for row in wallet_evaluations
            if str(row["pool_class"]) in {"STRESS", "ALPHA_STRESS"}
        ]
        follower_closes = [row for row in close_rows if str(row["kind"]) == "FOLLOWER"]
        wallet_closes = [row for row in close_rows if str(row["kind"]) == "WALLET"]
        alpha_follower_closes = [
            row for row in close_rows if str(row["kind"]) == "FOLLOWER_ALPHA"
        ]
        stress_follower_closes = [
            row for row in close_rows if str(row["kind"]) == "FOLLOWER_STRESS"
        ]
        alpha_closes = [
            row
            for row in wallet_closes
            if (
                _close_pool_class(row) in {"ALPHA", "ALPHA_STRESS"}
            )
            or (_close_pool_class(row) is None and str(row["wallet_id"]) in alpha_wallets)
        ]
        stress_closes = [
            row
            for row in wallet_closes
            if (
                _close_pool_class(row) in {"STRESS", "ALPHA_STRESS"}
            )
            or (_close_pool_class(row) is None and str(row["wallet_id"]) in stress_wallets)
        ]
        latest_poll_at = (
            None
            if poll_totals["latest_poll_at"] is None
            else _datetime(str(poll_totals["latest_poll_at"]))
        )
        observation_seconds = (
            0
            if latest_poll_at is None
            else max(0, int((latest_poll_at - experiment.started_at).total_seconds()))
        )
        all_evaluations = _evaluation_summary(evaluation_rows)
        follower_activity = _evaluation_summary(follower_evaluations)
        follower_close_summary = _close_summary(follower_closes)
        health = self.health(
            experiment.source_id,
            now=datetime.now(UTC),
            poll_interval_seconds=60,
        )
        limitations, confidence = _confidence(
            unique_events=int(event_window["unique_source_events"]),
            observation_seconds=observation_seconds,
            follower_activity=follower_activity,
            follower_closes=follower_close_summary,
            ledger_balanced=ledger_balanced,
            duplicate_processing_count=duplicate_processing_count,
            settlement_backlog_count=current_settlement_backlog,
            untrusted_mark_count=untrusted_mark_count,
        )
        alpha_row = next(
            (row for row in followers if str(row["kind"]) == "FOLLOWER_ALPHA"),
            None,
        )
        stress_row = next(
            (row for row in followers if str(row["kind"]) == "FOLLOWER_STRESS"),
            None,
        )
        pnl_decomposition = _pnl_decomposition(pnl_decomposition_rows)
        latency = _poll_latency(poll_latency_rows)
        mark_report = _mark_freshness_report(latest_marks)
        recorded_fills = tuple(
            RecordedShadowFill(
                evaluated_at=_datetime(str(row["evaluated_at"])),
                wallet_id=str(row["wallet_id"]),
                pool_class=str(row["pool_class"]),
                action=LeaderTradeAction(str(row["action"])),
                leader_price=Decimal(str(row["leader_price"])),
                follower_price=_optional_row_decimal(row["follower_price"]),
                filled_size=Decimal(str(row["filled_size"])),
                gross_notional=_optional_row_decimal(row["gross_notional"]),
                fee=_optional_row_decimal(row["fee"]),
                price_movement=_optional_row_decimal(row["price_movement"]),
                spread_cost=_optional_row_decimal(row["spread_cost"]),
                depth_impact=_optional_row_decimal(row["depth_impact"]),
                realized_pnl=_optional_row_decimal(row["realized_pnl"]),
                status=str(row["status"]),
            )
            for row in fill_rows
        )
        policy_experiments = walk_forward_policy_report(recorded_fills)
        decision_readiness = _decision_readiness(
            confidence=confidence,
            identity_status=identity_status,
            ledger_balanced=ledger_balanced,
            duplicate_processing_count=duplicate_processing_count,
            observation_seconds=observation_seconds,
            open_positions=open_positions,
        )
        rolling = health.rolling_windows or {}
        rolling_1h = rolling.get("1h")
        rolling_1h_unknown = (
            rolling_1h.get("unknown_ratio") if isinstance(rolling_1h, dict) else None
        )
        total_pnl = realized + unrealized - fees
        operator_summary = {
            "alpha_follower_total_pnl": _follower_total_pnl(alpha_row),
            "confidence": confidence,
            "decision_readiness": decision_readiness["status"],
            "follower_total_pnl": _decimal(total_pnl),
            "follower_valuation": (
                "CURRENTLY_MARKED"
                if int(follower["unmarked_position_count"]) == 0
                else "PARTIAL_OR_LAST_KNOWN_GOOD"
            ),
            "latency_p95_ms": latency["p95"],
            "open_position_count": open_positions,
            "real_orders": False,
            "rolling_1h_unknown_ratio": rolling_1h_unknown,
            "stress_follower_total_pnl": _follower_total_pnl(stress_row),
        }
        return {
            "accounting": {
                "identity": "NAV = initial_cash + realized_pnl + unrealized_pnl - fees",
                "identity_delta": format(identity_delta, "f"),
                "identity_status": identity_status,
                "ledger_balanced": ledger_balanced,
                "unmarked_adjusted_identity_delta": _decimal(
                    identity_delta + follower_unmarked_cost_basis
                ),
                "unmarked_cost_basis": _decimal(follower_unmarked_cost_basis),
                "valuation_complete": follower_valuation_complete,
            },
            "confidence": {
                "level": confidence,
                "limitations": limitations,
                "maximum_possible_level": "MODERATE",
                "observation_seconds": observation_seconds,
            },
            "decision_readiness": decision_readiness,
            "event_journal": {
                "active_markets": int(event_window["active_markets"]),
                "active_wallets": int(event_window["active_wallets"]),
                "duplicate_events_detected": int(poll_totals["duplicate_count"]),
                "duplicate_processing_count": duplicate_processing_count,
                "first_seen_at": event_window["first_seen_at"],
                "first_source_event_at": event_window["first_source_event_at"],
                "latest_seen_at": event_window["latest_seen_at"],
                "latest_source_event_at": event_window["latest_source_event_at"],
                "processing_status": {
                    str(row["processing_status"]): int(row["count"])
                    for row in processing_rows
                },
                "unique_source_events": int(event_window["unique_source_events"]),
            },
            "event_outcomes": all_evaluations["event_outcomes"],
            "experiment": experiment.to_dict(),
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
            }
            | {
                "gross_exposure": str(follower["exposure"]),
                "net_exposure": str(follower["exposure"]),
                "open_position_count": int(follower["open_position_count"]),
                "total_pnl": _decimal(realized + unrealized - fees),
                "total_pnl_status": (
                    "CURRENTLY_MARKED"
                    if int(follower["unmarked_position_count"]) == 0
                    else "PARTIAL_OR_LAST_KNOWN_GOOD"
                ),
                "unmarked_cost_basis": _decimal(follower_unmarked_cost_basis),
                "unmarked_position_count": int(follower["unmarked_position_count"]),
            },
            "follower_activity": follower_activity,
            "follower_closes": follower_close_summary,
            "follower_portfolios": {
                "MIXED_BASELINE": {
                    "label": "shared follower mixing Alpha and Stress; not a live book",
                    "portfolio": _follower_payload(follower),
                    "activity": follower_activity,
                    "closes": follower_close_summary,
                },
                "SHADOW_ALPHA": {
                    "label": "independent Alpha follower; started empty at schema v4",
                    "portfolio": _follower_payload(alpha_row),
                    "activity": _evaluation_summary(alpha_follower_evaluations),
                    "closes": _close_summary(alpha_follower_closes),
                },
                "SHADOW_STRESS": {
                    "label": "independent Stress follower; started empty at schema v4",
                    "portfolio": _follower_payload(stress_row),
                    "activity": _evaluation_summary(stress_follower_evaluations),
                    "closes": _close_summary(stress_follower_closes),
                },
            },
            "health": health.to_dict(),
            "latency": latency,
            "mark_freshness": mark_report,
            "off_host_backup": {
                "encrypted_destination_configured": False,
                "gap": "no_approved_encrypted_off_host_backup_destination",
            },
            "open_position_count": open_positions,
            "operator_summary": operator_summary,
            "all_portfolios_valuation_complete": untrusted_mark_count == 0,
            "unmarked_cost_basis_all_portfolios": _decimal(unmarked_cost_basis),
            "pnl_decomposition": pnl_decomposition,
            "pool_results": {
                "SHADOW_ALPHA": {
                    "activity": _evaluation_summary(alpha_evaluations),
                    "closes": _close_summary(alpha_closes),
                    "independent_follower": {
                        "activity": _evaluation_summary(alpha_follower_evaluations),
                        "closes": _close_summary(alpha_follower_closes),
                        "portfolio": _follower_payload(alpha_row),
                    },
                    "membership_count": len(alpha_wallets),
                    "portfolio": _portfolio_summary(alpha_portfolios),
                    "activity_scope": "event_time_membership",
                    "portfolio_scope": "current_membership_independent_wallet_portfolios",
                },
                "SHADOW_STRESS": {
                    "activity": _evaluation_summary(stress_evaluations),
                    "closes": _close_summary(stress_closes),
                    "independent_follower": {
                        "activity": _evaluation_summary(stress_follower_evaluations),
                        "closes": _close_summary(stress_follower_closes),
                        "portfolio": _follower_payload(stress_row),
                    },
                    "membership_count": len(stress_wallets),
                    "portfolio": _portfolio_summary(stress_portfolios),
                    "activity_scope": "event_time_membership",
                    "portfolio_scope": "current_membership_independent_wallet_portfolios",
                },
                "overlap_wallet_count": len(alpha_wallets & stress_wallets),
            },
            "policy_experiments": policy_experiments,
            "pools": [
                {
                    "count": int(row["count"]),
                    "pool_class": str(row["pool_class"]),
                    "status": str(row["status"]),
                }
                for row in status_rows
            ],
            "polls": {
                "duplicate_count": int(poll_totals["duplicate_count"]),
                "duplicate_events_detected": int(poll_totals["duplicate_count"]),
                "duplicate_processing_count": duplicate_processing_count,
                "first_poll_at": poll_totals["first_poll_at"],
                "latest_poll_at": poll_totals["latest_poll_at"],
                "new_event_count": int(poll_totals["new_event_count"]),
                "raw_event_count": int(poll_totals["raw_event_count"]),
                "rejected_count": int(poll_totals["rejected_count"]),
                "settlement_backlog_max": int(poll_totals["settlement_backlog_max"]),
                "settlement_backlog_current": current_settlement_backlog,
                "settlement_count": int(poll_totals["settlement_count"]),
                "simulated_count": int(poll_totals["simulated_count"]),
                "succeeded": int(poll_totals["succeeded"]),
                "unknown_count": int(poll_totals["unknown_count"]),
            },
            "processing": {
                "checkpoint": None
                if checkpoint is None
                else {
                    "last_poll_run_id": str(checkpoint["last_poll_run_id"]),
                    "updated_at": str(checkpoint["updated_at"]),
                    "watermark": str(checkpoint["watermark"]),
                },
                "semantics": (
                    "Journal publication, evaluations, ledger, portfolios, and checkpoint "
                    "commit atomically; overlap duplicates are detected but not processed."
                ),
            },
            "reporting_semantics": {
                "event_categories_may_overlap": True,
                "pool_overlap_is_included_in_each_selected_pool": True,
                "pool_portfolios_are_independent_counterfactuals": True,
                "real_orders": False,
                "alpha_stress_followers_not_backfilled": True,
            },
            "terminal_book_cache": {
                str(row["reason"]): {
                    "hits": int(row["hits"]),
                    "tokens": int(row["tokens"]),
                }
                for row in cache_hits
            },
            "wallet_market_attribution": _wallet_market_attribution(wallet_attribution_rows),
            "status": "succeeded",
            "wallets": [
                {
                    key: (
                        int(row[key])
                        if key in {"open_position_count", "unmarked_position_count"}
                        else str(row[key]) if row[key] is not None else None
                    )
                    for key in (
                        "wallet_id",
                        "cash",
                        "realized_pnl",
                        "unrealized_pnl",
                        "fees",
                        "nav",
                        "drawdown",
                        "exposure",
                        "open_position_count",
                        "unmarked_position_count",
                    )
                }
                for row in sorted(
                    wallet_rows,
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


def _close_pool_class(row: sqlite3.Row) -> str | None:
    for key in ("ledger_pool_class", "pool_class"):
        try:
            value = row[key]
        except (IndexError, KeyError):
            continue
        if value is not None:
            return str(value)
    return None


def _optional_row_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _follower_payload(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    realized = Decimal(str(row["realized_pnl"]))
    unrealized = Decimal(str(row["unrealized_pnl"]))
    fees = Decimal(str(row["fees"]))
    return {
        "cash": str(row["cash"]),
        "drawdown": str(row["drawdown"]),
        "exposure": str(row["exposure"]),
        "fees": str(row["fees"]),
        "initial_cash": str(row["initial_cash"]),
        "kind": str(row["kind"]),
        "nav": str(row["nav"]),
        "open_position_count": int(row["open_position_count"]),
        "portfolio_id": str(row["portfolio_id"]),
        "realized_pnl": str(row["realized_pnl"]),
        "total_pnl": _decimal(realized + unrealized - fees),
        "unmarked_position_count": int(row["unmarked_position_count"]),
        "unrealized_pnl": str(row["unrealized_pnl"]),
    }


def _follower_total_pnl(row: sqlite3.Row | None) -> str | None:
    payload = _follower_payload(row)
    return None if payload is None else str(payload["total_pnl"])


def _pnl_decomposition(rows: list[sqlite3.Row]) -> dict[str, object]:
    trading = _ZERO
    settlement = _ZERO
    fees = _ZERO
    for row in rows:
        realized = Decimal(str(row["realized_pnl_delta"]))
        fees += Decimal(str(row["fee_delta"]))
        entry_type = str(row["entry_type"])
        if entry_type in {"CLOSE", "REDUCE"}:
            trading += realized
        elif entry_type == "SETTLEMENT":
            settlement += realized
    return {
        "fees": _decimal(fees),
        "settlement_realized_pnl": _decimal(settlement),
        "stale_valuation_note": (
            "Unrealized P&L on LAST_KNOWN_GOOD or missing marks is excluded from "
            "realized totals and labelled separately in follower.total_pnl_status."
        ),
        "trading_close_realized_pnl": _decimal(trading),
    }


def _poll_latency(rows: list[sqlite3.Row]) -> dict[str, object]:
    samples: list[int] = []
    for row in rows:
        started = _datetime(str(row["started_at"]))
        completed = _datetime(str(row["completed_at"]))
        samples.append(max(0, int((completed - started).total_seconds() * 1000)))
    distribution = _integer_distribution(samples)
    return {
        **distribution,
        "median": distribution["p50"],
        "unit": "ms",
        "scope": "in_process_poll_excluding_container_start",
    }


def _mark_freshness_report(rows: list[sqlite3.Row]) -> dict[str, object]:
    marks = []
    for row in rows:
        marks.append(
            {
                "freshness": None if row["freshness"] is None else str(row["freshness"]),
                "mark_price": None if row["mark_price"] is None else str(row["mark_price"]),
                "mark_status": None if row["mark_status"] is None else str(row["mark_status"]),
                "market_reference": str(row["market_reference"]),
                "outcome_reference": str(row["outcome_reference"]),
                "source_age_ms": (
                    None if row["source_age_ms"] is None else int(row["source_age_ms"])
                ),
                "source_timestamp": (
                    None if row["source_timestamp"] is None else str(row["source_timestamp"])
                ),
            }
        )
    return {
        "count": len(marks),
        "positions": marks,
        "stale_or_missing_count": sum(
            1
            for item in marks
            if item["freshness"] not in {"FRESH", "VERIFIED_SETTLEMENT"}
        ),
    }


def _wallet_market_attribution(rows: list[sqlite3.Row]) -> dict[str, object]:
    by_wallet: dict[str, Decimal] = {}
    by_market: dict[str, Decimal] = {}
    by_pool: dict[str, Decimal] = {}
    unattributed = _ZERO
    for row in rows:
        net = Decimal(str(row["realized_pnl_delta"])) - Decimal(str(row["fee_delta"]))
        wallet_id = row["wallet_id"]
        market = row["market_reference"]
        pool = row["pool_class"]
        if wallet_id is None:
            unattributed += net
        else:
            key = str(wallet_id)
            by_wallet[key] = by_wallet.get(key, _ZERO) + net
        if market is None:
            unattributed += _ZERO
        else:
            market_key = str(market)
            by_market[market_key] = by_market.get(market_key, _ZERO) + net
        if pool is not None:
            pool_key = str(pool)
            by_pool[pool_key] = by_pool.get(pool_key, _ZERO) + net
    return {
        "markets": {
            key: _decimal(value)
            for key, value in sorted(by_market.items(), key=lambda item: item[0])
        },
        "pools": {key: _decimal(value) for key, value in sorted(by_pool.items())},
        "unattributed_net": _decimal(unattributed),
        "wallets": {
            key: _decimal(value)
            for key, value in sorted(by_wallet.items(), key=lambda item: item[0])
        },
    }


def _decision_readiness(
    *,
    confidence: str,
    identity_status: str,
    ledger_balanced: bool,
    duplicate_processing_count: int,
    observation_seconds: int,
    open_positions: int,
) -> dict[str, object]:
    if not ledger_balanced or duplicate_processing_count:
        status = "NOT_DECISION_READY"
        reason = "accounting_or_duplicate_processing_failure"
    elif confidence in {"UNTRUSTWORTHY", "INSUFFICIENT", "LOW"}:
        status = "NOT_DECISION_READY"
        reason = "confidence_below_research_threshold"
    elif open_positions:
        status = "OBSERVE_ONLY"
        reason = "open_synthetic_exposure_remains"
    elif observation_seconds < 86_400:
        status = "OBSERVE_ONLY"
        reason = "less_than_24_hours_observation"
    elif identity_status != "VERIFIED":
        status = "OBSERVE_ONLY"
        reason = "valuation_incomplete"
    else:
        status = "RESEARCH_ONLY"
        reason = "synthetic_shadow_not_live_authority"
    return {
        "live_promotion": False,
        "real_orders": False,
        "reason": reason,
        "status": status,
    }


def _evaluation_summary(rows: list[sqlite3.Row]) -> dict[str, object]:
    status_counts = {"SIMULATED": 0, "UNKNOWN": 0, "REJECTED": 0}
    status_events: dict[str, set[str]] = {
        "SIMULATED": set(),
        "UNKNOWN": set(),
        "REJECTED": set(),
    }
    event_ids: set[str] = set()
    partial_events: set[str] = set()
    active_wallets: set[str] = set()
    active_markets: set[str] = set()
    pool_classes: set[str] = set()
    selection_run_ids: set[str] = set()
    reasons: dict[str, int] = {}
    requested = _ZERO
    filled = _ZERO
    partial_evaluations = 0
    unknown_fee_count = 0
    source_lags: list[int] = []
    signal_delays: list[int] = []
    cost_values: dict[str, list[Decimal]] = {
        "price_movement": [],
        "spread_cost": [],
        "depth_impact": [],
        "fee": [],
        "liquidity_loss": [],
    }
    financial_values: dict[str, list[Decimal]] = {
        "gross_notional": [],
        "realized_pnl": [],
    }
    for row in rows:
        event_id = str(row["event_id"])
        status = str(row["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        status_events.setdefault(status, set()).add(event_id)
        event_ids.add(event_id)
        active_wallets.add(str(row["wallet_id"]))
        active_markets.add(str(row["market_reference"]))
        pool_classes.add(str(row["pool_class"]))
        selection_run_ids.add(str(row["selection_run_id"]))
        reason = str(row["reason"])
        reasons[reason] = reasons.get(reason, 0) + 1
        requested_size = Decimal(str(row["requested_size"]))
        filled_size = Decimal(str(row["filled_size"]))
        requested += requested_size
        filled += filled_size
        if _ZERO < filled_size < requested_size:
            partial_evaluations += 1
            partial_events.add(event_id)
        if str(row["fee_status"]) == "UNKNOWN":
            unknown_fee_count += 1
        source_lags.append(int(row["source_api_lag_ms"]))
        signal_delays.append(int(row["signal_delay_ms"]))
        for name in cost_values:
            value = row[name]
            if value is not None:
                cost_values[name].append(Decimal(str(value)))
        for name in financial_values:
            value = row[name]
            if value is not None:
                financial_values[name].append(Decimal(str(value)))
    return {
        "active_markets": len(active_markets),
        "active_wallets": len(active_wallets),
        "cost_distribution": {
            name: _decimal_distribution(values)
            for name, values in cost_values.items()
        },
        "delay_distribution_ms": {
            "signal_delay": _integer_distribution(signal_delays),
            "source_api_observation_lag": _integer_distribution(source_lags),
        },
        "evaluation_count": len(rows),
        "evaluation_status": status_counts,
        "event_outcomes": {
            "partial": len(partial_events),
            "rejected": len(status_events["REJECTED"]),
            "simulated": len(status_events["SIMULATED"]),
            "unique_evaluated": len(event_ids),
            "unknown": len(status_events["UNKNOWN"]),
        },
        "filled_size": _decimal(filled),
        "financial_distribution": {
            name: _decimal_distribution(values)
            for name, values in financial_values.items()
        },
        "partial_fill_evaluations": partial_evaluations,
        "pool_classes": sorted(pool_classes),
        "reasons": dict(sorted(reasons.items())),
        "requested_size": _decimal(requested),
        "selection_run_ids": sorted(selection_run_ids),
        "unknown_fee_count": unknown_fee_count,
    }


def _decimal_distribution(values: list[Decimal]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "maximum": None,
            "mean": None,
            "minimum": None,
            "nonzero_count": 0,
            "total": "0",
        }
    total = sum(values, _ZERO)
    return {
        "count": len(values),
        "maximum": _decimal(max(values)),
        "mean": _decimal(total / Decimal(len(values))),
        "minimum": _decimal(min(values)),
        "nonzero_count": sum(value != _ZERO for value in values),
        "total": _decimal(total),
    }


def _integer_distribution(values: list[int]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "maximum": None,
            "mean": None,
            "minimum": None,
            "p50": None,
            "p95": None,
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "maximum": ordered[-1],
        "mean": _decimal(Decimal(sum(ordered)) / Decimal(len(ordered))),
        "minimum": ordered[0],
        "p50": ordered[max(0, (len(ordered) * 50 + 99) // 100 - 1)],
        "p95": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
    }


def _portfolio_summary(rows: list[sqlite3.Row]) -> dict[str, object]:
    fields = (
        "initial_cash",
        "cash",
        "realized_pnl",
        "unrealized_pnl",
        "fees",
        "nav",
        "exposure",
    )
    totals = {
        field: sum((Decimal(str(row[field])) for row in rows), _ZERO)
        for field in fields
    }
    unmarked_position_count = sum(int(row["unmarked_position_count"]) for row in rows)
    return {
        **{field: _decimal(value) for field, value in totals.items()},
        "gross_exposure": _decimal(totals["exposure"]),
        "maximum_drawdown": _decimal(
            max((Decimal(str(row["drawdown"])) for row in rows), default=_ZERO)
        ),
        "net_exposure": _decimal(totals["exposure"]),
        "open_position_count": sum(int(row["open_position_count"]) for row in rows),
        "portfolio_count": len(rows),
        "total_pnl": _decimal(totals["nav"] - totals["initial_cash"]),
        "total_pnl_status": (
            "COMPLETE_PERSISTED_MARKS"
            if unmarked_position_count == 0
            else "PARTIAL_MISSING_MARKS"
        ),
        "unmarked_position_count": unmarked_position_count,
    }


def _close_summary(rows: list[sqlite3.Row]) -> dict[str, int]:
    winning = 0
    losing = 0
    breakeven = 0
    settlements = 0
    for row in rows:
        net = Decimal(str(row["realized_pnl_delta"])) - Decimal(str(row["fee_delta"]))
        if net > _ZERO:
            winning += 1
        elif net < _ZERO:
            losing += 1
        else:
            breakeven += 1
        if str(row["entry_type"]) == "SETTLEMENT":
            settlements += 1
    return {
        "breakeven": breakeven,
        "closed_positions": len(rows),
        "losing": losing,
        "settlements": settlements,
        "winning": winning,
    }


def _confidence(
    *,
    unique_events: int,
    observation_seconds: int,
    follower_activity: dict[str, object],
    follower_closes: dict[str, int],
    ledger_balanced: bool,
    duplicate_processing_count: int,
    settlement_backlog_count: int,
    untrusted_mark_count: int,
) -> tuple[list[str], str]:
    limitations = ["synthetic_shadow_only", "no_real_fill_or_account_mutation_evidence"]
    event_outcomes = follower_activity["event_outcomes"]
    assert isinstance(event_outcomes, dict)
    unknown_events = int(event_outcomes["unknown"])
    if observation_seconds < 86_400:
        limitations.append("less_than_24_hours_observation")
    if follower_closes["closed_positions"] == 0:
        limitations.append("no_closed_follower_positions")
    if unknown_events:
        limitations.append("unknown_event_evidence_present")
    unknown_fee_count = follower_activity["unknown_fee_count"]
    assert isinstance(unknown_fee_count, int)
    if unknown_fee_count:
        limitations.append("unknown_fee_evidence_present")
    if settlement_backlog_count:
        limitations.append("verified_closed_market_settlement_backlog")
    if untrusted_mark_count:
        limitations.append("portfolio_valuation_not_fully_current")
    if unique_events == 0:
        return limitations + ["no_source_events_observed"], "INSUFFICIENT"
    if not ledger_balanced or duplicate_processing_count:
        return limitations, "UNTRUSTWORTHY"
    evaluated = int(event_outcomes["unique_evaluated"])
    if untrusted_mark_count:
        return limitations, "LOW"
    if evaluated and Decimal(unknown_events) / Decimal(evaluated) > Decimal("0.5"):
        return limitations, "LOW"
    if observation_seconds < 86_400 or follower_closes["closed_positions"] == 0:
        return limitations, "PRELIMINARY"
    return limitations, "MODERATE"


def _migrate_schema(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'continuous_shadow_metadata'"
    ).fetchone()
    if table is None:
        return
    rows = connection.execute(
        "SELECT schema_version FROM continuous_shadow_metadata"
    ).fetchall()
    if len(rows) != 1:
        raise ContinuousShadowStoreError("Continuous Shadow schema version is invalid.")
    version = int(rows[0][0])
    if version == CONTINUOUS_SHADOW_SCHEMA_VERSION:
        return
    if version == 2:
        _migrate_v2_to_v3(connection)
        version = 3
    if version != 3:
        raise ContinuousShadowStoreError("Continuous Shadow schema version is unsupported.")
    _migrate_v3_to_v4(connection)


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        journal_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_event_journal)"
            ).fetchall()
        }
        if "processing_status" not in journal_columns:
            connection.execute(
                "ALTER TABLE continuous_shadow_event_journal "
                "ADD COLUMN processing_status TEXT NOT NULL DEFAULT 'PROCESSED' "
                "CHECK(processing_status = 'PROCESSED')"
            )
        poll_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(continuous_shadow_poll_runs)"
            ).fetchall()
        }
        if "settlement_backlog_count" not in poll_columns:
            connection.execute(
                "ALTER TABLE continuous_shadow_poll_runs "
                "ADD COLUMN settlement_backlog_count INTEGER NOT NULL DEFAULT 0 "
                "CHECK(settlement_backlog_count >= 0)"
            )
        _replace_metadata_version(connection, version=3)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        _rebuild_portfolios_table(connection)
        _rebuild_attribution_table(connection)
        _add_column_if_missing(
            connection,
            "continuous_shadow_ledger",
            "wallet_id",
            "TEXT",
        )
        _add_column_if_missing(
            connection,
            "continuous_shadow_ledger",
            "pool_class",
            "TEXT",
        )
        _add_column_if_missing(
            connection,
            "continuous_shadow_position_marks",
            "source_timestamp",
            "TEXT",
        )
        _add_column_if_missing(
            connection,
            "continuous_shadow_position_marks",
            "source_age_ms",
            "INTEGER",
        )
        _add_column_if_missing(
            connection,
            "continuous_shadow_position_marks",
            "freshness",
            "TEXT NOT NULL DEFAULT 'MISSING'",
        )
        _backfill_ledger_attribution(connection)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS continuous_shadow_terminal_book_cache ("
            "token_id TEXT PRIMARY KEY, "
            "reason TEXT NOT NULL CHECK(reason IN ('TERMINAL_404', 'MARKET_CLOSED')), "
            "first_seen_at TEXT NOT NULL, "
            "last_seen_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL, "
            "hit_count INTEGER NOT NULL DEFAULT 1 CHECK(hit_count >= 1))"
        )
        connection.execute("DROP INDEX IF EXISTS idx_continuous_shadow_one_follower")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_continuous_shadow_one_follower_kind "
            "ON continuous_shadow_portfolios(experiment_id, kind) "
            "WHERE kind IN ('FOLLOWER', 'FOLLOWER_ALPHA', 'FOLLOWER_STRESS')"
        )
        _patch_experiment_configs(connection)
        _ensure_specialized_followers(connection)
        _replace_metadata_version(connection, version=4)
        connection.execute("PRAGMA foreign_key_check")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _replace_metadata_version(connection: sqlite3.Connection, *, version: int) -> None:
    initialized_at = str(
        connection.execute(
            "SELECT initialized_at FROM continuous_shadow_metadata"
        ).fetchone()[0]
    )
    connection.execute(
        "ALTER TABLE continuous_shadow_metadata RENAME TO continuous_shadow_metadata_old"
    )
    connection.execute(
        "CREATE TABLE continuous_shadow_metadata ("
        f"schema_version INTEGER PRIMARY KEY CHECK(schema_version = {int(version)}), "
        "initialized_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO continuous_shadow_metadata (schema_version, initialized_at) "
        "VALUES (?, ?)",
        (version, initialized_at),
    )
    connection.execute("DROP TABLE continuous_shadow_metadata_old")


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_ledger_attribution(connection: sqlite3.Connection) -> None:
    connection.execute(
        "UPDATE continuous_shadow_ledger SET "
        "wallet_id = ("
        "SELECT e.wallet_id FROM continuous_shadow_evaluations AS e "
        "WHERE e.experiment_id = continuous_shadow_ledger.experiment_id "
        "AND e.event_id = continuous_shadow_ledger.event_id "
        "AND e.portfolio_id = continuous_shadow_ledger.portfolio_id LIMIT 1"
        "), "
        "pool_class = ("
        "SELECT e.pool_class FROM continuous_shadow_evaluations AS e "
        "WHERE e.experiment_id = continuous_shadow_ledger.experiment_id "
        "AND e.event_id = continuous_shadow_ledger.event_id "
        "AND e.portfolio_id = continuous_shadow_ledger.portfolio_id LIMIT 1"
        ") "
        "WHERE wallet_id IS NULL AND event_id IS NOT NULL"
    )


def _rebuild_portfolios_table(connection: sqlite3.Connection) -> None:
    sql = str(
        connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'continuous_shadow_portfolios'"
        ).fetchone()[0]
    )
    if "FOLLOWER_ALPHA" in sql:
        return
    connection.execute("DROP VIEW IF EXISTS continuous_shadow_portfolio_current")
    connection.execute(
        "CREATE TABLE continuous_shadow_portfolios_v4 ("
        "experiment_id TEXT NOT NULL, "
        "portfolio_id TEXT NOT NULL, "
        "kind TEXT NOT NULL CHECK("
        "kind IN ('WALLET', 'FOLLOWER', 'FOLLOWER_ALPHA', 'FOLLOWER_STRESS')), "
        "wallet_id TEXT, "
        "initial_cash TEXT NOT NULL, "
        "cash TEXT NOT NULL, "
        "realized_pnl TEXT NOT NULL DEFAULT '0', "
        "unrealized_pnl TEXT NOT NULL DEFAULT '0', "
        "fees TEXT NOT NULL DEFAULT '0', "
        "nav TEXT NOT NULL, "
        "high_water_nav TEXT NOT NULL, "
        "drawdown TEXT NOT NULL DEFAULT '0', "
        "exposure TEXT NOT NULL DEFAULT '0', "
        "updated_at TEXT NOT NULL, "
        "PRIMARY KEY(experiment_id, portfolio_id), "
        "UNIQUE(experiment_id, wallet_id), "
        "FOREIGN KEY(experiment_id) REFERENCES continuous_shadow_experiments(experiment_id), "
        "FOREIGN KEY(wallet_id) REFERENCES canonical_wallets(wallet_id))"
    )
    connection.execute(
        "INSERT INTO continuous_shadow_portfolios_v4 SELECT * FROM continuous_shadow_portfolios"
    )
    connection.execute("DROP TABLE continuous_shadow_portfolios")
    connection.execute(
        "ALTER TABLE continuous_shadow_portfolios_v4 RENAME TO continuous_shadow_portfolios"
    )
    _recreate_portfolio_current_view(connection)


def _recreate_portfolio_current_view(connection: sqlite3.Connection) -> None:
    connection.execute("DROP VIEW IF EXISTS continuous_shadow_portfolio_current")
    connection.execute(
        "CREATE VIEW continuous_shadow_portfolio_current AS "
        "SELECT e.source_id, e.experiment_id, e.lifecycle, e.policy_version, "
        "e.cost_model_version, e.bankroll_version, e.started_at, "
        "e.last_successful_poll_at, p.portfolio_id, p.kind, p.wallet_id, "
        "p.initial_cash, p.cash, p.realized_pnl, p.unrealized_pnl, p.fees, "
        "p.nav, p.high_water_nav, p.drawdown, p.exposure, p.updated_at "
        "FROM continuous_shadow_experiments e "
        "JOIN continuous_shadow_portfolios p ON p.experiment_id = e.experiment_id"
    )


def _rebuild_attribution_table(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(continuous_shadow_follower_attribution)"
        ).fetchall()
    }
    if "portfolio_id" in columns and "pool_class" in columns:
        return
    connection.execute(
        "CREATE TABLE continuous_shadow_follower_attribution_v4 ("
        "experiment_id TEXT NOT NULL, "
        "portfolio_id TEXT NOT NULL, "
        "wallet_id TEXT NOT NULL, "
        "market_reference TEXT NOT NULL, "
        "outcome_reference TEXT NOT NULL, "
        "quantity TEXT NOT NULL, "
        "cost_basis TEXT NOT NULL, "
        "pool_class TEXT NOT NULL, "
        "last_event_id TEXT, "
        "PRIMARY KEY("
        "experiment_id, portfolio_id, wallet_id, market_reference, outcome_reference), "
        "FOREIGN KEY(experiment_id, wallet_id) "
        "REFERENCES continuous_shadow_candidates(experiment_id, wallet_id) ON DELETE CASCADE, "
        "FOREIGN KEY(experiment_id, portfolio_id) "
        "REFERENCES continuous_shadow_portfolios(experiment_id, portfolio_id) ON DELETE CASCADE)"
    )
    connection.execute(
        "INSERT INTO continuous_shadow_follower_attribution_v4 "
        "(experiment_id, portfolio_id, wallet_id, market_reference, outcome_reference, "
        "quantity, cost_basis, pool_class, last_event_id) "
        "SELECT experiment_id, 'follower', wallet_id, market_reference, outcome_reference, "
        "quantity, cost_basis, 'UNKNOWN', NULL "
        "FROM continuous_shadow_follower_attribution"
    )
    connection.execute("DROP TABLE continuous_shadow_follower_attribution")
    connection.execute(
        "ALTER TABLE continuous_shadow_follower_attribution_v4 "
        "RENAME TO continuous_shadow_follower_attribution"
    )


def _patch_experiment_configs(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT experiment_id, config_json FROM continuous_shadow_experiments"
    ).fetchall()
    for row in rows:
        payload = json.loads(str(row["config_json"]))
        if not isinstance(payload, dict):
            raise ContinuousShadowStoreError("Continuous Shadow config is invalid.")
        payload.setdefault("price_drift_max_ratio", None)
        payload.setdefault("negative_cache_ttl_seconds", 21_600)
        connection.execute(
            "UPDATE continuous_shadow_experiments SET config_json = ? "
            "WHERE experiment_id = ?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                str(row["experiment_id"]),
            ),
        )


def _ensure_specialized_followers(connection: sqlite3.Connection) -> None:
    experiments = connection.execute(
        "SELECT experiment_id, updated_at, initial_cash FROM continuous_shadow_portfolios "
        "WHERE kind = 'FOLLOWER'"
    ).fetchall()
    for row in experiments:
        for portfolio_id, kind, _accepted in FOLLOWER_KIND_SPECS:
            if kind is ContinuousPortfolioKind.FOLLOWER:
                continue
            connection.execute(
                "INSERT OR IGNORE INTO continuous_shadow_portfolios "
                "(experiment_id, portfolio_id, kind, wallet_id, initial_cash, cash, "
                "realized_pnl, unrealized_pnl, fees, nav, high_water_nav, drawdown, "
                "exposure, updated_at) VALUES (?, ?, ?, NULL, ?, ?, '0', '0', '0', ?, ?, "
                "'0', '0', ?)",
                (
                    str(row["experiment_id"]),
                    portfolio_id,
                    kind.value,
                    str(row["initial_cash"]),
                    str(row["initial_cash"]),
                    str(row["initial_cash"]),
                    str(row["initial_cash"]),
                    str(row["updated_at"]),
                ),
            )


def _rolling_health_windows(
    connection: sqlite3.Connection,
    experiment_id: str,
    *,
    now: datetime,
) -> dict[str, object]:
    windows: dict[str, object] = {}
    for label, hours in (("1h", 1), ("6h", 6), ("24h", 24)):
        start = _iso(now - timedelta(hours=hours))
        row = connection.execute(
            "SELECT COUNT(*) AS polls, "
            "COALESCE(SUM(evaluation_count), 0) AS evaluations, "
            "COALESCE(SUM(unknown_count), 0) AS unknown_count, "
            "COALESCE(SUM(simulated_count), 0) AS simulated_count, "
            "COALESCE(SUM(rejected_count), 0) AS rejected_count "
            "FROM continuous_shadow_poll_runs "
            "WHERE experiment_id = ? AND status = 'succeeded' AND completed_at >= ?",
            (experiment_id, start),
        ).fetchone()
        assert row is not None
        evaluations = int(row["evaluations"])
        unknown_count = int(row["unknown_count"])
        windows[label] = {
            "evaluation_count": evaluations,
            "poll_count": int(row["polls"]),
            "rejected_count": int(row["rejected_count"]),
            "simulated_count": int(row["simulated_count"]),
            "unknown_count": unknown_count,
            "unknown_ratio": (
                None
                if evaluations == 0
                else format(Decimal(unknown_count) / Decimal(evaluations), "f")
            ),
        }
    return windows


def _duplicate_processing_count(
    connection: sqlite3.Connection,
    experiment_id: str,
) -> int:
    journal = connection.execute(
        "SELECT COALESCE(SUM(row_count - 1), 0) FROM ("
        "SELECT j.event_id, COUNT(*) AS row_count "
        "FROM continuous_shadow_event_journal j "
        "JOIN continuous_shadow_poll_runs p ON p.poll_run_id = j.first_poll_run_id "
        "WHERE p.experiment_id = ? GROUP BY j.event_id HAVING COUNT(*) > 1)",
        (experiment_id,),
    ).fetchone()
    evaluations = connection.execute(
        "SELECT COALESCE(SUM(row_count - 1), 0) FROM ("
        "SELECT event_id, portfolio_id, COUNT(*) AS row_count "
        "FROM continuous_shadow_evaluations WHERE experiment_id = ? "
        "GROUP BY event_id, portfolio_id HAVING COUNT(*) > 1)",
        (experiment_id,),
    ).fetchone()
    return int(journal[0]) + int(evaluations[0])


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
        "realized_pnl_delta, fee_delta, created_at, wallet_id, pool_class) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            item.wallet_id,
            item.pool_class,
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
        "quantity, mark_price, market_value, unrealized_pnl, mark_status, marked_at, "
        "source_timestamp, source_age_ms, freshness) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            None if item.source_timestamp is None else _iso(item.source_timestamp),
            item.source_age_ms,
            item.freshness,
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
            price_drift_max_ratio=(
                None
                if value.get("price_drift_max_ratio") is None
                else Decimal(str(value["price_drift_max_ratio"]))
            ),
            negative_cache_ttl_seconds=int(value.get("negative_cache_ttl_seconds", 21_600)),
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
