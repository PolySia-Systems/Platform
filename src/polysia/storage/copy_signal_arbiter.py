from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from decimal import Decimal

from polysia.domain.copytrading.signal_arbiter import (
    ClosedSignalOutcome,
    ConcentrationCause,
    ConcentrationEvent,
    FollowerExecutionOutcome,
    SignalContext,
)

_WALLET_FRAGMENT = re.compile(r"(?<![0-9a-fA-F])0x[a-fA-F0-9]{40}(?![0-9a-fA-F])")


class CopySignalArbiterRepository:
    """Additive persistence for research outcomes and concentration evidence."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record_wallet_outcome_if_new(
        self,
        outcome: ClosedSignalOutcome,
        *,
        labeling_version: str,
        created_at: datetime,
    ) -> bool:
        _require_text("labeling_version", labeling_version)
        _require_utc("created_at", created_at)
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO copytrading_wallet_signal_outcomes (
                    outcome_id, leader_key, market_type, timeframe_seconds,
                    opened_at, closed_at, net_return, maximum_drawdown,
                    labeling_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.outcome_id,
                    outcome.leader_key,
                    outcome.context.market_type,
                    outcome.context.timeframe_seconds,
                    _datetime_text(outcome.opened_at),
                    _datetime_text(outcome.closed_at),
                    str(outcome.net_return),
                    str(outcome.maximum_drawdown),
                    labeling_version,
                    _datetime_text(created_at),
                ),
            )
        return cursor.rowcount == 1

    def wallet_outcomes(
        self,
        *,
        labeling_version: str,
        closed_at_or_before: datetime | None = None,
    ) -> tuple[ClosedSignalOutcome, ...]:
        _require_text("labeling_version", labeling_version)
        parameters: tuple[str, ...] = (labeling_version,)
        condition = "WHERE labeling_version = ?"
        if closed_at_or_before is not None:
            _require_utc("closed_at_or_before", closed_at_or_before)
            condition += " AND closed_at <= ?"
            parameters += (_datetime_text(closed_at_or_before),)
        rows = self._connection.execute(
            f"""
            SELECT outcome_id, leader_key, market_type, timeframe_seconds,
                   opened_at, closed_at, net_return, maximum_drawdown
            FROM copytrading_wallet_signal_outcomes
            {condition}
            ORDER BY closed_at, outcome_id
            """,  # noqa: S608 - condition is selected from fixed local literals.
            parameters,
        ).fetchall()
        return tuple(
            ClosedSignalOutcome(
                outcome_id=str(row["outcome_id"]),
                leader_key=str(row["leader_key"]),
                context=SignalContext(
                    market_type=str(row["market_type"]),
                    timeframe_seconds=int(row["timeframe_seconds"]),
                ),
                opened_at=datetime.fromisoformat(str(row["opened_at"])),
                closed_at=datetime.fromisoformat(str(row["closed_at"])),
                net_return=Decimal(str(row["net_return"])),
                maximum_drawdown=Decimal(str(row["maximum_drawdown"])),
            )
            for row in rows
        )

    def record_follower_outcome_if_new(
        self,
        outcome: FollowerExecutionOutcome,
        *,
        created_at: datetime,
    ) -> bool:
        _require_utc("created_at", created_at)
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO copytrading_follower_execution_outcomes (
                    execution_id, leader_key, market_type, timeframe_seconds,
                    closed_at, filled, completed_cycle, net_pnl, execution_cost,
                    slippage, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.execution_id,
                    outcome.leader_key,
                    outcome.context.market_type,
                    outcome.context.timeframe_seconds,
                    _datetime_text(outcome.closed_at),
                    int(outcome.filled),
                    int(outcome.completed_cycle),
                    _optional_decimal(outcome.net_pnl),
                    _optional_decimal(outcome.execution_cost),
                    _optional_decimal(outcome.slippage),
                    _datetime_text(created_at),
                ),
            )
        return cursor.rowcount == 1

    def follower_outcomes(
        self,
        *,
        closed_at_or_before: datetime | None = None,
    ) -> tuple[FollowerExecutionOutcome, ...]:
        parameters: tuple[str, ...] = ()
        condition = ""
        if closed_at_or_before is not None:
            _require_utc("closed_at_or_before", closed_at_or_before)
            condition = "WHERE closed_at <= ?"
            parameters = (_datetime_text(closed_at_or_before),)
        rows = self._connection.execute(
            f"""
            SELECT execution_id, leader_key, market_type, timeframe_seconds,
                   closed_at, filled, completed_cycle, net_pnl, execution_cost,
                   slippage
            FROM copytrading_follower_execution_outcomes
            {condition}
            ORDER BY closed_at, execution_id
            """,  # noqa: S608 - condition is selected from fixed local literals.
            parameters,
        ).fetchall()
        return tuple(
            FollowerExecutionOutcome(
                execution_id=str(row["execution_id"]),
                leader_key=str(row["leader_key"]),
                context=SignalContext(
                    market_type=str(row["market_type"]),
                    timeframe_seconds=int(row["timeframe_seconds"]),
                ),
                closed_at=datetime.fromisoformat(str(row["closed_at"])),
                filled=bool(row["filled"]),
                completed_cycle=bool(row["completed_cycle"]),
                net_pnl=_decimal_or_none(row["net_pnl"]),
                execution_cost=_decimal_or_none(row["execution_cost"]),
                slippage=_decimal_or_none(row["slippage"]),
            )
            for row in rows
        )

    def record_concentration_event_if_new(
        self,
        event: ConcentrationEvent,
        *,
        created_at: datetime,
    ) -> bool:
        _require_utc("created_at", created_at)
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO copytrading_concentration_events (
                    event_id, leader_key, cause, occurred_at, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.leader_key,
                    event.cause.value,
                    _datetime_text(event.occurred_at),
                    _datetime_text(created_at),
                ),
            )
        return cursor.rowcount == 1

    def concentration_events(
        self,
        *,
        occurred_at_or_before: datetime | None = None,
    ) -> tuple[ConcentrationEvent, ...]:
        parameters: tuple[str, ...] = ()
        condition = ""
        if occurred_at_or_before is not None:
            _require_utc("occurred_at_or_before", occurred_at_or_before)
            condition = "WHERE occurred_at <= ?"
            parameters = (_datetime_text(occurred_at_or_before),)
        rows = self._connection.execute(
            f"""
            SELECT event_id, leader_key, cause, occurred_at
            FROM copytrading_concentration_events
            {condition}
            ORDER BY occurred_at, event_id
            """,  # noqa: S608 - condition is selected from fixed local literals.
            parameters,
        ).fetchall()
        return tuple(
            ConcentrationEvent(
                event_id=str(row["event_id"]),
                leader_key=str(row["leader_key"]),
                cause=ConcentrationCause(str(row["cause"])),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            )
            for row in rows
        )


def _datetime_text(value: datetime) -> str:
    _require_utc("datetime", value)
    return value.isoformat()


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _require_text(name: str, value: str) -> None:
    if not value or len(value) > 100:
        raise ValueError(f"{name} must be a non-empty bounded value")
    if _WALLET_FRAGMENT.search(value):
        raise ValueError(f"{name} must not contain a wallet address")


def _require_utc(name: str, value: datetime) -> None:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = ["CopySignalArbiterRepository"]
