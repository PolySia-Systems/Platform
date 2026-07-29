from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from polysia.domain.copytrading.live_experiment import (
    MAXIMUM_COMPLETED_LIVE_CYCLES,
    MAXIMUM_EXPERIMENT_ENTRY_COST,
    MAXIMUM_TOTAL_ENTRY_ATTEMPTS,
    CopyExperimentSnapshot,
    CopyExperimentState,
)

ACTIVE_DISCOVERY_COUNT = 48
DISCOVERY_ROTATION_STEP = 34
DISCOVERY_ORDERING_VERSION = "prior-signal-aliases-first-v1"


@dataclass(frozen=True, slots=True)
class CopyDiscoveryState:
    ordering_version: str
    ordered_aliases: tuple[str, ...]
    cursor: int
    active_aliases: tuple[str, ...]
    subset_digest: str
    rotated_at: datetime
    outage_started_at: datetime | None
    next_probe_at: datetime | None
    cooldown_attempt: int
    last_source_success_at: datetime | None


@dataclass(frozen=True, slots=True)
class CopyReadCheckpoint:
    leader_alias: str
    window_start: datetime
    window_end: datetime
    checkpoint_value: str | None
    last_successful_at: datetime | None


class CopyExperimentRepository:
    """Atomic durable state for the single bounded Copy Trading experiment."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        run_id: str,
        authorization_id: str,
        started_at: datetime,
        signal_window_end: datetime,
        payload: dict[str, object],
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO copytrading_live_runs (
                    run_id, authorization_id, state, started_at, signal_window_end,
                    payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    authorization_id,
                    CopyExperimentState.PREFLIGHT.value,
                    _datetime_text(started_at),
                    _datetime_text(signal_window_end),
                    _json(payload),
                    _datetime_text(started_at),
                ),
            )

    def get(self, run_id: str) -> CopyExperimentSnapshot | None:
        row = self._connection.execute(
            "SELECT * FROM copytrading_live_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return None if row is None else _snapshot(row)

    def signal_window_end(self, run_id: str) -> datetime:
        row = self._required_run(run_id)
        return datetime.fromisoformat(str(row["signal_window_end"]))

    def set_state(
        self,
        run_id: str,
        state: CopyExperimentState,
        *,
        updated_at: datetime,
        signal_acceptance_open: bool | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        fields = ["state = ?", "updated_at = ?"]
        values: list[object] = [state.value, _datetime_text(updated_at)]
        if signal_acceptance_open is not None:
            fields.append("signal_acceptance_open = ?")
            values.append(int(signal_acceptance_open))
        if payload is not None:
            fields.append("payload_json = ?")
            values.append(_json(payload))
        values.append(run_id)
        with self._connection:
            cursor = self._connection.execute(
                f"UPDATE copytrading_live_runs SET {', '.join(fields)} WHERE run_id = ?",
                values,
            )
        if cursor.rowcount != 1:
            raise KeyError(f"unknown Copy Trading run {run_id}")

    def claim_entry_attempt(
        self,
        *,
        run_id: str,
        leader_alias: str,
        event_id: str,
        market_id: str,
        market_slug: str,
        token_id: str,
        entry_price: Decimal,
        entry_quantity: Decimal,
        entry_debit: Decimal,
        entry_fee: Decimal,
        entry_cancel_at: datetime,
        leader_latency_ms: int,
        leader_price_difference: Decimal,
        claimed_at: datetime,
    ) -> int | None:
        """Atomically consume one venue-attempt slot immediately before submission."""

        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._required_run(run_id)
            attempts = int(row["total_entry_attempts"])
            cycles = int(row["completed_live_cycles"])
            cumulative_entry_cost = self.cumulative_entry_cost(run_id)
            allowed = (
                bool(row["signal_acceptance_open"])
                and str(row["state"]) == CopyExperimentState.MONITORING.value
                and attempts < MAXIMUM_TOTAL_ENTRY_ATTEMPTS
                and cycles < MAXIMUM_COMPLETED_LIVE_CYCLES
                and cumulative_entry_cost + entry_debit <= MAXIMUM_EXPERIMENT_ENTRY_COST
                and row["entry_order_id"] is None
                and Decimal(str(row["position_size"])) == 0
            )
            if not allowed:
                connection.rollback()
                return None
            attempt_number = attempts + 1
            connection.execute(
                """
                INSERT INTO copytrading_live_attempts (
                    run_id, attempt_number, leader_alias, event_id, market_id,
                    state, entry_quantity, entry_debit, entry_fee,
                    leader_latency_ms, leader_price_difference, claimed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    attempt_number,
                    leader_alias,
                    event_id,
                    market_id,
                    "CLAIMED_BEFORE_SUBMIT",
                    str(entry_quantity),
                    str(entry_debit),
                    str(entry_fee),
                    leader_latency_ms,
                    str(leader_price_difference),
                    _datetime_text(claimed_at),
                    _datetime_text(claimed_at),
                ),
            )
            acceptance_open = attempt_number < MAXIMUM_TOTAL_ENTRY_ATTEMPTS
            connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, total_entry_attempts = ?, signal_acceptance_open = ?,
                    active_leader_alias = ?, active_event_id = ?,
                    active_market_id = ?, active_market_slug = ?,
                    active_token_id = ?, entry_price = ?,
                    entry_quantity = ?, entry_fee = ?, entry_cancel_at = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    CopyExperimentState.ENTRY_SUBMITTING.value,
                    attempt_number,
                    int(acceptance_open),
                    leader_alias,
                    event_id,
                    market_id,
                    market_slug,
                    token_id,
                    str(entry_price),
                    str(entry_quantity),
                    str(entry_fee),
                    _datetime_text(entry_cancel_at),
                    _datetime_text(claimed_at),
                    run_id,
                ),
            )
            connection.commit()
            return attempt_number
        except sqlite3.IntegrityError:
            connection.rollback()
            return None
        except Exception:
            connection.rollback()
            raise

    def record_entry_submission(
        self,
        *,
        run_id: str,
        attempt_number: int,
        venue_order_id: str | None,
        state: str,
        updated_at: datetime,
    ) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE copytrading_live_attempts
                SET state = ?, venue_order_id = ?, updated_at = ?
                WHERE run_id = ? AND attempt_number = ?
                """,
                (
                    state,
                    venue_order_id,
                    _datetime_text(updated_at),
                    run_id,
                    attempt_number,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("unknown Copy Trading entry attempt")
            next_state = (
                CopyExperimentState.ENTRY_PENDING.value
                if venue_order_id is not None
                else CopyExperimentState.MONITORING.value
            )
            self._connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, entry_order_id = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (next_state, venue_order_id, _datetime_text(updated_at), run_id),
            )

    def record_no_fill(
        self,
        *,
        run_id: str,
        attempt_number: int,
        updated_at: datetime,
        signal_window_open: bool,
    ) -> CopyExperimentSnapshot:
        with self._connection:
            self._connection.execute(
                """
                UPDATE copytrading_live_attempts
                SET state = 'UNFILLED_CANCELLED_RECONCILED', updated_at = ?
                WHERE run_id = ? AND attempt_number = ?
                """,
                (_datetime_text(updated_at), run_id, attempt_number),
            )
            row = self._required_run(run_id)
            acceptance_open = (
                signal_window_open
                and int(row["total_entry_attempts"]) < MAXIMUM_TOTAL_ENTRY_ATTEMPTS
                and int(row["completed_live_cycles"]) < MAXIMUM_COMPLETED_LIVE_CYCLES
            )
            next_state = (
                CopyExperimentState.MONITORING if acceptance_open else CopyExperimentState.FINALIZED
            )
            self._connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, signal_acceptance_open = ?, entry_order_id = NULL,
                    active_leader_alias = NULL, active_event_id = NULL,
                    active_market_id = NULL, active_token_id = NULL,
                    active_market_slug = NULL,
                    entry_price = NULL, entry_quantity = NULL,
                    entry_fee = '0', entry_cancel_at = NULL,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    next_state.value,
                    int(acceptance_open),
                    _datetime_text(updated_at),
                    run_id,
                ),
            )
        snapshot = self.get(run_id)
        assert snapshot is not None
        return snapshot

    def record_fill(
        self,
        *,
        run_id: str,
        attempt_number: int,
        position_size: Decimal,
        fill_price: Decimal,
        entry_fee: Decimal,
        updated_at: datetime,
    ) -> CopyExperimentSnapshot:
        if position_size <= 0:
            raise ValueError("confirmed position size must be positive")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE copytrading_live_attempts SET state = 'FILLED', updated_at = ?,
                    fill_size = ?, fill_price = ?, entry_fee = ?
                WHERE run_id = ? AND attempt_number = ?
                  AND state != 'FILLED'
                """,
                (
                    _datetime_text(updated_at),
                    str(position_size),
                    str(fill_price),
                    str(entry_fee),
                    run_id,
                    attempt_number,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("attempt was already filled or is unknown")
            self._connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, entry_order_id = NULL, position_size = ?,
                    fill_price = ?, entry_fee = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    CopyExperimentState.POSITION_OPEN.value,
                    str(position_size),
                    str(fill_price),
                    str(entry_fee),
                    _datetime_text(updated_at),
                    run_id,
                ),
            )
        snapshot = self.get(run_id)
        assert snapshot is not None
        return snapshot

    def record_exit_order(
        self,
        *,
        run_id: str,
        order_id: str,
        exit_price: Decimal,
        exit_fee: Decimal,
        updated_at: datetime,
    ) -> CopyExperimentSnapshot:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, exit_order_id = ?, updated_at = ?
                WHERE run_id = ? AND CAST(position_size AS REAL) > 0
                  AND exit_order_id IS NULL
                """,
                (
                    CopyExperimentState.EXIT_PENDING.value,
                    order_id,
                    _datetime_text(updated_at),
                    run_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError("one-position/one-related-exit invariant blocked the exit")
        with self._connection:
            self._connection.execute(
                """
                UPDATE copytrading_live_attempts
                SET exit_price = ?, exit_fee = ?, updated_at = ?
                WHERE run_id = ? AND attempt_number = (
                    SELECT MAX(attempt_number) FROM copytrading_live_attempts
                    WHERE run_id = ?
                )
                """,
                (
                    str(exit_price),
                    str(exit_fee),
                    _datetime_text(updated_at),
                    run_id,
                    run_id,
                ),
            )
        snapshot = self.get(run_id)
        assert snapshot is not None
        return snapshot

    def clear_exit_order(
        self,
        *,
        run_id: str,
        state: CopyExperimentState,
        updated_at: datetime,
    ) -> None:
        if state not in {
            CopyExperimentState.POSITION_OPEN,
            CopyExperimentState.AWAITING_RESOLUTION,
        }:
            raise ValueError("invalid post-cancellation position state")
        with self._connection:
            self._connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, exit_order_id = NULL, updated_at = ?
                WHERE run_id = ?
                """,
                (state.value, _datetime_text(updated_at), run_id),
            )

    def complete_cycle(
        self,
        *,
        run_id: str,
        updated_at: datetime,
        signal_window_open: bool,
    ) -> CopyExperimentSnapshot:
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._required_run(run_id)
            if Decimal(str(row["position_size"])) <= 0:
                raise ValueError("no active filled cycle to complete")
            completed = int(row["completed_live_cycles"]) + 1
            if completed > MAXIMUM_COMPLETED_LIVE_CYCLES:
                raise ValueError("completed-cycle limit violated")
            acceptance_open = (
                signal_window_open
                and completed < MAXIMUM_COMPLETED_LIVE_CYCLES
                and int(row["total_entry_attempts"]) < MAXIMUM_TOTAL_ENTRY_ATTEMPTS
            )
            next_state = (
                CopyExperimentState.MONITORING if acceptance_open else CopyExperimentState.FINALIZED
            )
            connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, completed_live_cycles = ?, signal_acceptance_open = ?,
                    active_leader_alias = NULL, active_event_id = NULL,
                    active_market_id = NULL, active_token_id = NULL,
                    active_market_slug = NULL,
                    entry_order_id = NULL, exit_order_id = NULL, position_size = '0',
                    entry_price = NULL, entry_quantity = NULL,
                    entry_fee = '0', entry_cancel_at = NULL,
                    fill_price = NULL,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    next_state.value,
                    completed,
                    int(acceptance_open),
                    _datetime_text(updated_at),
                    run_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        snapshot = self.get(run_id)
        assert snapshot is not None
        return snapshot

    def record_terminal_pnl(
        self,
        *,
        run_id: str,
        exit_price: Decimal,
        exit_fee: Decimal,
        gross_pnl: Decimal,
        net_pnl: Decimal,
        terminal_reason: str,
        updated_at: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE copytrading_live_attempts
                SET state = 'CLOSED', exit_price = ?, exit_fee = ?,
                    gross_pnl = ?, net_pnl = ?, terminal_reason = ?, updated_at = ?
                WHERE run_id = ? AND attempt_number = (
                    SELECT MAX(attempt_number) FROM copytrading_live_attempts
                    WHERE run_id = ?
                )
                """,
                (
                    str(exit_price),
                    str(exit_fee),
                    str(gross_pnl),
                    str(net_pnl),
                    terminal_reason,
                    _datetime_text(updated_at),
                    run_id,
                    run_id,
                ),
            )

    def complete_redeemable_cycle(
        self,
        *,
        run_id: str,
        updated_at: datetime,
    ) -> CopyExperimentSnapshot:
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._required_run(run_id)
            if Decimal(str(row["position_size"])) <= 0:
                raise ValueError("no winning position is available for redemption")
            completed = int(row["completed_live_cycles"]) + 1
            if completed > MAXIMUM_COMPLETED_LIVE_CYCLES:
                raise ValueError("completed-cycle limit violated")
            connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, completed_live_cycles = ?,
                    signal_acceptance_open = 0, exit_order_id = NULL, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    CopyExperimentState.REDEEMABLE.value,
                    completed,
                    _datetime_text(updated_at),
                    run_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        snapshot = self.get(run_id)
        assert snapshot is not None
        return snapshot

    def record_emergency_cancellation(
        self,
        *,
        run_id: str,
        remaining_position: Decimal,
        updated_at: datetime,
    ) -> None:
        if remaining_position < 0:
            raise ValueError("remaining emergency position must not be negative")
        with self._connection:
            self._connection.execute(
                """
                UPDATE copytrading_live_runs
                SET state = ?, signal_acceptance_open = 0,
                    entry_order_id = NULL, exit_order_id = NULL,
                    position_size = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    CopyExperimentState.FAILED_SAFE.value,
                    str(remaining_position),
                    _datetime_text(updated_at),
                    run_id,
                ),
            )

    def mark_seen(
        self,
        *,
        run_id: str,
        event_id: str,
        leader_alias: str,
        observed_at: datetime,
    ) -> bool:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO copytrading_seen_events (
                        run_id, event_id, leader_alias, observed_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (run_id, event_id, leader_alias, _datetime_text(observed_at)),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def apply_event_if_unseen(
        self,
        *,
        run_id: str,
        event_id: str,
        leader_alias: str,
        observed_at: datetime,
        market_reference: str,
        outcome_reference: str,
        next_size: Decimal,
    ) -> bool:
        if next_size < 0:
            raise ValueError("leader inventory must not be negative")
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO copytrading_seen_events (
                        run_id, event_id, leader_alias, observed_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        event_id,
                        leader_alias,
                        _datetime_text(observed_at),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO copytrading_leader_inventory (
                        run_id, leader_alias, market_reference, outcome_reference,
                        size, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                        run_id, leader_alias, market_reference, outcome_reference
                    ) DO UPDATE SET
                        size = excluded.size, updated_at = excluded.updated_at
                    """,
                    (
                        run_id,
                        leader_alias,
                        market_reference,
                        outcome_reference,
                        str(next_size),
                        _datetime_text(observed_at),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def aliases_with_seen_events(self, run_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            """
            SELECT DISTINCT leader_alias FROM copytrading_seen_events
            WHERE run_id = ? ORDER BY leader_alias
            """,
            (run_id,),
        ).fetchall()
        return tuple(str(row["leader_alias"]) for row in rows)

    def initialize_discovery(
        self,
        *,
        run_id: str,
        ordered_aliases: tuple[str, ...],
        initialized_at: datetime,
    ) -> CopyDiscoveryState:
        if len(ordered_aliases) != 102 or len(set(ordered_aliases)) != 102:
            raise ValueError("discovery ordering must contain exactly 102 unique aliases")
        active_aliases = ordered_aliases[:ACTIVE_DISCOVERY_COUNT]
        digest = _alias_digest(active_aliases)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO copytrading_discovery_state (
                    run_id, ordering_version, ordered_aliases_json, cursor,
                    active_aliases_json, subset_digest, rotated_at, updated_at
                ) VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (
                    run_id,
                    DISCOVERY_ORDERING_VERSION,
                    json.dumps(ordered_aliases, separators=(",", ":")),
                    json.dumps(active_aliases, separators=(",", ":")),
                    digest,
                    _datetime_text(initialized_at),
                    _datetime_text(initialized_at),
                ),
            )
        state = self.discovery_state(run_id)
        if (
            state.ordering_version != DISCOVERY_ORDERING_VERSION
            or state.ordered_aliases != ordered_aliases
        ):
            raise ValueError("durable discovery ordering does not match runtime aliases")
        return state

    def discovery_state(self, run_id: str) -> CopyDiscoveryState:
        row = self._connection.execute(
            "SELECT * FROM copytrading_discovery_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"missing discovery state for {run_id}")
        return _discovery_state(row)

    def rotate_discovery(
        self,
        *,
        run_id: str,
        rotated_at: datetime,
    ) -> CopyDiscoveryState:
        state = self.discovery_state(run_id)
        cursor = (state.cursor + DISCOVERY_ROTATION_STEP) % len(state.ordered_aliases)
        active_aliases = tuple(
            state.ordered_aliases[(cursor + offset) % len(state.ordered_aliases)]
            for offset in range(ACTIVE_DISCOVERY_COUNT)
        )
        digest = _alias_digest(active_aliases)
        with self._connection:
            self._connection.execute(
                """
                UPDATE copytrading_discovery_state
                SET cursor = ?, active_aliases_json = ?, subset_digest = ?,
                    rotated_at = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    cursor,
                    json.dumps(active_aliases, separators=(",", ":")),
                    digest,
                    _datetime_text(rotated_at),
                    _datetime_text(rotated_at),
                    run_id,
                ),
            )
        return self.discovery_state(run_id)

    def set_discovery_cooldown(
        self,
        *,
        run_id: str,
        outage_started_at: datetime,
        next_probe_at: datetime,
        cooldown_attempt: int,
        updated_at: datetime,
    ) -> None:
        if cooldown_attempt < 1:
            raise ValueError("cooldown_attempt must be positive")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE copytrading_discovery_state
                SET outage_started_at = ?, next_probe_at = ?,
                    cooldown_attempt = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    _datetime_text(outage_started_at),
                    _datetime_text(next_probe_at),
                    cooldown_attempt,
                    _datetime_text(updated_at),
                    run_id,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"missing discovery state for {run_id}")

    def clear_discovery_cooldown(
        self,
        *,
        run_id: str,
        successful_at: datetime,
    ) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE copytrading_discovery_state
                SET outage_started_at = NULL, next_probe_at = NULL,
                    cooldown_attempt = 0, last_source_success_at = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    _datetime_text(successful_at),
                    _datetime_text(successful_at),
                    run_id,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"missing discovery state for {run_id}")

    def read_checkpoint(
        self,
        *,
        run_id: str,
        leader_alias: str,
    ) -> CopyReadCheckpoint | None:
        row = self._connection.execute(
            """
            SELECT * FROM copytrading_read_checkpoints
            WHERE run_id = ? AND leader_alias = ?
            """,
            (run_id, leader_alias),
        ).fetchone()
        if row is None:
            return None
        return CopyReadCheckpoint(
            leader_alias=str(row["leader_alias"]),
            window_start=datetime.fromisoformat(str(row["window_start"])),
            window_end=datetime.fromisoformat(str(row["window_end"])),
            checkpoint_value=_optional(row["checkpoint_value"]),
            last_successful_at=_optional_datetime(row["last_successful_at"]),
        )

    def save_read_checkpoint(
        self,
        *,
        run_id: str,
        leader_alias: str,
        window_start: datetime,
        window_end: datetime,
        checkpoint_value: str | None,
        last_successful_at: datetime | None,
        updated_at: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO copytrading_read_checkpoints (
                    run_id, leader_alias, window_start, window_end,
                    checkpoint_value, last_successful_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, leader_alias) DO UPDATE SET
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    checkpoint_value = excluded.checkpoint_value,
                    last_successful_at = excluded.last_successful_at,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    leader_alias,
                    _datetime_text(window_start),
                    _datetime_text(window_end),
                    checkpoint_value,
                    (None if last_successful_at is None else _datetime_text(last_successful_at)),
                    _datetime_text(updated_at),
                ),
            )

    def stage_read_page(
        self,
        *,
        run_id: str,
        leader_alias: str,
        window_start: datetime,
        window_end: datetime,
        checkpoint_value: str | None,
        last_successful_at: datetime | None,
        event_payloads: tuple[dict[str, object], ...],
        staged_at: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO copytrading_read_checkpoints (
                    run_id, leader_alias, window_start, window_end,
                    checkpoint_value, last_successful_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, leader_alias) DO UPDATE SET
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    checkpoint_value = excluded.checkpoint_value,
                    last_successful_at = excluded.last_successful_at,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    leader_alias,
                    _datetime_text(window_start),
                    _datetime_text(window_end),
                    checkpoint_value,
                    (None if last_successful_at is None else _datetime_text(last_successful_at)),
                    _datetime_text(staged_at),
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO copytrading_pending_read_events (
                    run_id, leader_alias, event_id, payload_json, staged_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, event_id) DO NOTHING
                """,
                (
                    (
                        run_id,
                        leader_alias,
                        str(payload["event_id"]),
                        json.dumps(payload, sort_keys=True, separators=(",", ":")),
                        _datetime_text(staged_at),
                    )
                    for payload in event_payloads
                ),
            )

    def pending_read_events(
        self,
        *,
        run_id: str,
        leader_alias: str,
    ) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            """
            SELECT payload_json FROM copytrading_pending_read_events
            WHERE run_id = ? AND leader_alias = ? ORDER BY staged_at, event_id
            """,
            (run_id, leader_alias),
        ).fetchall()
        return tuple(json.loads(str(row["payload_json"])) for row in rows)

    def clear_pending_read_events(
        self,
        *,
        run_id: str,
        event_ids: tuple[str, ...],
    ) -> None:
        if not event_ids:
            return
        with self._connection:
            self._connection.executemany(
                """
                DELETE FROM copytrading_pending_read_events
                WHERE run_id = ? AND event_id = ?
                """,
                ((run_id, event_id) for event_id in event_ids),
            )

    def set_inventory(
        self,
        *,
        run_id: str,
        leader_alias: str,
        market_reference: str,
        outcome_reference: str,
        size: Decimal,
        updated_at: datetime,
    ) -> None:
        if size < 0:
            raise ValueError("leader inventory must not be negative")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO copytrading_leader_inventory (
                    run_id, leader_alias, market_reference, outcome_reference,
                    size, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, leader_alias, market_reference, outcome_reference)
                DO UPDATE SET size = excluded.size, updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    leader_alias,
                    market_reference,
                    outcome_reference,
                    str(size),
                    _datetime_text(updated_at),
                ),
            )

    def mark_baselined(
        self,
        *,
        run_id: str,
        leader_alias: str,
        baseline_digest: str,
        baselined_at: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO copytrading_baselined_leaders (
                    run_id, leader_alias, baseline_digest, baselined_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, leader_alias) DO UPDATE SET
                    baseline_digest = excluded.baseline_digest,
                    baselined_at = excluded.baselined_at
                """,
                (
                    run_id,
                    leader_alias,
                    baseline_digest,
                    _datetime_text(baselined_at),
                ),
            )

    def is_baselined(self, *, run_id: str, leader_alias: str) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM copytrading_baselined_leaders
            WHERE run_id = ? AND leader_alias = ?
            """,
            (run_id, leader_alias),
        ).fetchone()
        return row is not None

    def baselined_count(self, run_id: str) -> int:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS count FROM copytrading_baselined_leaders
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        assert row is not None
        return int(row["count"])

    def inventory(
        self,
        *,
        run_id: str,
        leader_alias: str,
        market_reference: str,
        outcome_reference: str,
    ) -> Decimal | None:
        row = self._connection.execute(
            """
            SELECT size FROM copytrading_leader_inventory
            WHERE run_id = ? AND leader_alias = ?
              AND market_reference = ? AND outcome_reference = ?
            """,
            (run_id, leader_alias, market_reference, outcome_reference),
        ).fetchone()
        return None if row is None else Decimal(str(row["size"]))

    def used_leaders(self, run_id: str) -> frozenset[str]:
        rows = self._connection.execute(
            "SELECT leader_alias FROM copytrading_live_attempts WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return frozenset(str(row["leader_alias"]) for row in rows)

    def attempts(self, run_id: str) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            """
            SELECT attempt_number, leader_alias, event_id, market_id, state,
                   venue_order_id, entry_quantity, entry_debit, entry_fee,
                   fill_size, fill_price, exit_price, exit_fee, gross_pnl,
                   net_pnl, terminal_reason, leader_latency_ms,
                   leader_price_difference, claimed_at, updated_at
            FROM copytrading_live_attempts
            WHERE run_id = ? ORDER BY attempt_number
            """,
            (run_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def cumulative_entry_cost(self, run_id: str) -> Decimal:
        rows = self._connection.execute(
            """
            SELECT fill_size, fill_price, entry_fee
            FROM copytrading_live_attempts
            WHERE run_id = ? AND fill_size IS NOT NULL AND fill_price IS NOT NULL
            """,
            (run_id,),
        ).fetchall()
        return sum(
            (
                Decimal(str(row["fill_size"])) * Decimal(str(row["fill_price"]))
                + Decimal(str(row["entry_fee"] or "0"))
                for row in rows
            ),
            Decimal("0"),
        )

    def _required_run(self, run_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM copytrading_live_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Copy Trading run {run_id}")
        return row


def _snapshot(row: sqlite3.Row) -> CopyExperimentSnapshot:
    return CopyExperimentSnapshot(
        state=CopyExperimentState(str(row["state"])),
        total_entry_attempts=int(row["total_entry_attempts"]),
        completed_live_cycles=int(row["completed_live_cycles"]),
        signal_acceptance_open=bool(row["signal_acceptance_open"]),
        active_leader_alias=_optional(row["active_leader_alias"]),
        active_event_id=_optional(row["active_event_id"]),
        active_market_id=_optional(row["active_market_id"]),
        active_market_slug=_optional(row["active_market_slug"]),
        active_token_id=_optional(row["active_token_id"]),
        entry_order_id=_optional(row["entry_order_id"]),
        exit_order_id=_optional(row["exit_order_id"]),
        entry_price=_optional_decimal(row["entry_price"]),
        entry_quantity=_optional_decimal(row["entry_quantity"]),
        entry_fee=Decimal(str(row["entry_fee"])),
        entry_cancel_at=_optional_datetime(row["entry_cancel_at"]),
        fill_price=_optional_decimal(row["fill_price"]),
        position_size=Decimal(str(row["position_size"])),
    )


def _discovery_state(row: sqlite3.Row) -> CopyDiscoveryState:
    ordered = tuple(str(value) for value in json.loads(str(row["ordered_aliases_json"])))
    active = tuple(str(value) for value in json.loads(str(row["active_aliases_json"])))
    if len(ordered) != 102 or len(active) != ACTIVE_DISCOVERY_COUNT:
        raise ValueError("durable discovery state has invalid alias counts")
    return CopyDiscoveryState(
        ordering_version=str(row["ordering_version"]),
        ordered_aliases=ordered,
        cursor=int(row["cursor"]),
        active_aliases=active,
        subset_digest=str(row["subset_digest"]),
        rotated_at=datetime.fromisoformat(str(row["rotated_at"])),
        outage_started_at=_optional_datetime(row["outage_started_at"]),
        next_probe_at=_optional_datetime(row["next_probe_at"]),
        cooldown_attempt=int(row["cooldown_attempt"]),
        last_source_success_at=_optional_datetime(row["last_source_success_at"]),
    )


def _alias_digest(aliases: tuple[str, ...]) -> str:
    return "sha256:" + hashlib.sha256("\n".join(aliases).encode()).hexdigest()


def _optional(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _optional_datetime(value: Any) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "ACTIVE_DISCOVERY_COUNT",
    "DISCOVERY_ORDERING_VERSION",
    "DISCOVERY_ROTATION_STEP",
    "CopyDiscoveryState",
    "CopyExperimentRepository",
    "CopyReadCheckpoint",
]
