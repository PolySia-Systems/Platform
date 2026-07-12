from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from polysia.bus.events import MarketDataEvent, market_data_event_to_dict
from polysia.domain.ledger import LedgerEvent
from polysia.domain.market import MarketSummary
from polysia.domain.strategy import (
    StrategyDefinition,
    StrategyLifecycleStatus,
    StrategyPerformanceSummary,
    StrategyRun,
)
from polysia.orderbook.book import LocalOrderBook
from polysia.storage.db import transaction

OrderSide = Literal["BUY", "SELL"]


@dataclass(frozen=True, slots=True)
class StoredMarketEvent:
    id: int
    event: MarketDataEvent


@dataclass(frozen=True, slots=True)
class StoredMarket:
    market_id: str
    slug: str | None
    question: str | None
    category: str | None
    active: bool | None
    closed: bool | None
    accepting_orders: bool | None
    end_date: datetime | None
    liquidity: Decimal | None
    volume: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    outcomes: list[dict[str, Any]]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredOrderBookSnapshot:
    id: int
    token_id: str
    captured_at: datetime
    snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredDecision:
    id: int
    strategy_id: str
    token_id: str
    decision_type: str
    reason: str
    approved: bool | None
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredOrder:
    order_id: str
    broker: str
    strategy_id: str | None
    token_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    status: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredFill:
    fill_id: str
    order_id: str
    token_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    fee: Decimal | None
    liquidity_role: str | None
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredPosition:
    token_id: str
    market_id: str | None
    size: Decimal
    avg_price: Decimal
    realized_pnl: Decimal
    payload: dict[str, Any]
    updated_at: datetime


class EventRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, event: MarketDataEvent) -> int:
        safe_event = market_data_event_to_dict(event)
        with transaction(self._connection) as connection:
            cursor = connection.execute(
                """
                INSERT INTO market_events (
                    source, event_type, token_id, received_at, exchange_ts,
                    payload_json, raw_payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.source,
                    event.event_type,
                    event.token_id,
                    _datetime_to_text(event.received_at),
                    _optional_datetime_to_text(event.exchange_ts),
                    _json_dumps(safe_event["payload"]),
                    _json_dumps(safe_event["raw_payload"]),
                ),
            )
        return _lastrowid(cursor)

    def list_recent(
        self,
        *,
        token_id: str | None = None,
        limit: int = 100,
    ) -> list[StoredMarketEvent]:
        if limit <= 0:
            raise ValueError("limit must be positive")

        if token_id is None:
            rows = self._connection.execute(
                "SELECT * FROM market_events ORDER BY received_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM market_events
                WHERE token_id = ?
                ORDER BY received_at DESC, id DESC
                LIMIT ?
                """,
                (token_id, limit),
            ).fetchall()
        return [_row_to_event(row) for row in rows]


class MarketRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, market: MarketSummary, *, updated_at: datetime | None = None) -> None:
        timestamp = updated_at or datetime.now(UTC)
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO markets (
                    market_id, slug, question, category, active, closed,
                    accepting_orders, end_date, liquidity, volume, best_bid,
                    best_ask, outcomes_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_id) DO UPDATE SET
                    slug = excluded.slug,
                    question = excluded.question,
                    category = excluded.category,
                    active = excluded.active,
                    closed = excluded.closed,
                    accepting_orders = excluded.accepting_orders,
                    end_date = excluded.end_date,
                    liquidity = excluded.liquidity,
                    volume = excluded.volume,
                    best_bid = excluded.best_bid,
                    best_ask = excluded.best_ask,
                    outcomes_json = excluded.outcomes_json,
                    updated_at = excluded.updated_at
                """,
                (
                    market.id,
                    market.slug,
                    market.question,
                    market.category,
                    _optional_bool_to_int(market.active),
                    _optional_bool_to_int(market.closed),
                    _optional_bool_to_int(market.accepting_orders),
                    _optional_datetime_to_text(market.end_date),
                    _optional_decimal_to_text(market.liquidity),
                    _optional_decimal_to_text(market.volume),
                    _optional_decimal_to_text(market.best_bid),
                    _optional_decimal_to_text(market.best_ask),
                    _json_dumps([item.model_dump(mode="json") for item in market.outcomes]),
                    _datetime_to_text(timestamp),
                ),
            )

    def get(self, market_id: str) -> StoredMarket | None:
        row = self._connection.execute(
            "SELECT * FROM markets WHERE market_id = ?",
            (market_id,),
        ).fetchone()
        return _row_to_market(row) if row is not None else None

    def list_active(self, *, limit: int = 100) -> list[StoredMarket]:
        rows = self._connection.execute(
            """
            SELECT * FROM markets
            WHERE active = 1 AND closed = 0
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_market(row) for row in rows]


class OrderBookSnapshotRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, book: LocalOrderBook, *, captured_at: datetime | None = None) -> int:
        timestamp = captured_at or datetime.now(UTC)
        snapshot = book.snapshot()
        with transaction(self._connection) as connection:
            cursor = connection.execute(
                """
                INSERT INTO orderbook_snapshots (
                    token_id, captured_at, best_bid, best_ask, mid, spread,
                    bid_depth, ask_depth, imbalance, microprice,
                    bids_json, asks_json, snapshot_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book.token_id,
                    _datetime_to_text(timestamp),
                    snapshot["best_bid"],
                    snapshot["best_ask"],
                    snapshot["mid"],
                    snapshot["spread"],
                    snapshot["bid_depth"],
                    snapshot["ask_depth"],
                    snapshot["imbalance"],
                    snapshot["microprice"],
                    _json_dumps(snapshot["bids"]),
                    _json_dumps(snapshot["asks"]),
                    _json_dumps(snapshot),
                ),
            )
        return _lastrowid(cursor)

    def latest(self, token_id: str) -> StoredOrderBookSnapshot | None:
        row = self._connection.execute(
            """
            SELECT * FROM orderbook_snapshots
            WHERE token_id = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            (token_id,),
        ).fetchone()
        return _row_to_orderbook_snapshot(row) if row is not None else None


class DecisionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        *,
        strategy_id: str,
        token_id: str,
        decision_type: str,
        reason: str,
        approved: bool | None,
        payload: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> int:
        timestamp = created_at or datetime.now(UTC)
        with transaction(self._connection) as connection:
            cursor = connection.execute(
                """
                INSERT INTO decisions (
                    strategy_id, token_id, decision_type, reason, approved,
                    payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    token_id,
                    decision_type,
                    reason,
                    _optional_bool_to_int(approved),
                    _json_dumps(dict(payload or {})),
                    _datetime_to_text(timestamp),
                ),
            )
        return _lastrowid(cursor)

    def get(self, decision_id: int) -> StoredDecision | None:
        row = self._connection.execute(
            "SELECT * FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        return _row_to_decision(row) if row is not None else None


class OrderRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(
        self,
        *,
        order_id: str,
        broker: str,
        token_id: str,
        side: OrderSide,
        price: Decimal,
        size: Decimal,
        status: str,
        strategy_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        active_timestamp = timestamp or datetime.now(UTC)
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO orders (
                    order_id, broker, strategy_id, token_id, side, price, size,
                    status, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    broker = excluded.broker,
                    strategy_id = excluded.strategy_id,
                    token_id = excluded.token_id,
                    side = excluded.side,
                    price = excluded.price,
                    size = excluded.size,
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    broker,
                    strategy_id,
                    token_id,
                    side,
                    str(price),
                    str(size),
                    status,
                    _json_dumps(dict(payload or {})),
                    _datetime_to_text(active_timestamp),
                    _datetime_to_text(active_timestamp),
                ),
            )

    def get(self, order_id: str) -> StoredOrder | None:
        row = self._connection.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        return _row_to_order(row) if row is not None else None


class FillRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        *,
        fill_id: str,
        order_id: str,
        token_id: str,
        side: OrderSide,
        price: Decimal,
        size: Decimal,
        fee: Decimal | None = None,
        liquidity_role: str | None = None,
        payload: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        timestamp = created_at or datetime.now(UTC)
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO fills (
                    fill_id, order_id, token_id, side, price, size, fee,
                    liquidity_role, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill_id,
                    order_id,
                    token_id,
                    side,
                    str(price),
                    str(size),
                    _optional_decimal_to_text(fee),
                    liquidity_role,
                    _json_dumps(dict(payload or {})),
                    _datetime_to_text(timestamp),
                ),
            )

    def get(self, fill_id: str) -> StoredFill | None:
        row = self._connection.execute(
            "SELECT * FROM fills WHERE fill_id = ?",
            (fill_id,),
        ).fetchone()
        return _row_to_fill(row) if row is not None else None


class PositionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(
        self,
        *,
        token_id: str,
        size: Decimal,
        avg_price: Decimal,
        realized_pnl: Decimal,
        market_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        timestamp = updated_at or datetime.now(UTC)
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO positions (
                    token_id, market_id, size, avg_price, realized_pnl,
                    payload_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
                    market_id = excluded.market_id,
                    size = excluded.size,
                    avg_price = excluded.avg_price,
                    realized_pnl = excluded.realized_pnl,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    token_id,
                    market_id,
                    str(size),
                    str(avg_price),
                    str(realized_pnl),
                    _json_dumps(dict(payload or {})),
                    _datetime_to_text(timestamp),
                ),
            )

    def get(self, token_id: str) -> StoredPosition | None:
        row = self._connection.execute(
            "SELECT * FROM positions WHERE token_id = ?",
            (token_id,),
        ).fetchone()
        return _row_to_position(row) if row is not None else None


class StrategyRegistryRepository:
    """SQLite serialization for strategy definitions, runs, and evaluations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_definition(self, definition: StrategyDefinition) -> None:
        timestamp = datetime.now(UTC)
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO strategy_definitions (
                    strategy_id, version, lifecycle_status, definition_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.strategy_id,
                    definition.version,
                    definition.lifecycle_status.value,
                    _json_dumps(definition.model_dump(mode="json")),
                    _datetime_to_text(definition.created_at),
                    _datetime_to_text(timestamp),
                ),
            )

    def get_definition(self, strategy_id: str, version: str) -> StrategyDefinition | None:
        row = self._connection.execute(
            """
            SELECT definition_json FROM strategy_definitions
            WHERE strategy_id = ? AND version = ?
            """,
            (strategy_id, version),
        ).fetchone()
        if row is None:
            return None
        return StrategyDefinition.model_validate_json(str(row["definition_json"]))

    def list_definitions(self) -> list[StrategyDefinition]:
        rows = self._connection.execute(
            """
            SELECT definition_json FROM strategy_definitions
            ORDER BY strategy_id, version
            """
        ).fetchall()
        return [
            StrategyDefinition.model_validate_json(str(row["definition_json"]))
            for row in rows
        ]

    def update_lifecycle(
        self,
        strategy_id: str,
        version: str,
        status: StrategyLifecycleStatus,
    ) -> StrategyDefinition:
        definition = self.get_definition(strategy_id, version)
        if definition is None:
            raise KeyError(f"strategy {strategy_id}@{version} is not registered")
        updated = definition.model_copy(update={"lifecycle_status": status})
        timestamp = datetime.now(UTC)
        with transaction(self._connection) as connection:
            connection.execute(
                """
                UPDATE strategy_definitions
                SET lifecycle_status = ?, definition_json = ?, updated_at = ?
                WHERE strategy_id = ? AND version = ?
                """,
                (
                    status.value,
                    _json_dumps(updated.model_dump(mode="json")),
                    _datetime_to_text(timestamp),
                    strategy_id,
                    version,
                ),
            )
        return updated

    def add_run(self, run: StrategyRun) -> None:
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO strategy_runs (
                    run_id, strategy_id, strategy_version, runtime_mode, venue,
                    market, started_at, ended_at, run_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.strategy_id,
                    run.strategy_version,
                    run.runtime_mode,
                    run.venue,
                    run.market,
                    _datetime_to_text(run.started_at),
                    _optional_datetime_to_text(run.ended_at),
                    _json_dumps(run.model_dump(mode="json")),
                ),
            )

    def list_runs(self, strategy_id: str, version: str) -> list[StrategyRun]:
        rows = self._connection.execute(
            """
            SELECT run_json FROM strategy_runs
            WHERE strategy_id = ? AND strategy_version = ?
            ORDER BY started_at, run_id
            """,
            (strategy_id, version),
        ).fetchall()
        return [StrategyRun.model_validate_json(str(row["run_json"])) for row in rows]

    def upsert_performance(self, summary: StrategyPerformanceSummary) -> None:
        timestamp = datetime.now(UTC)
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO strategy_performance (
                    strategy_id, strategy_version, summary_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(strategy_id, strategy_version) DO UPDATE SET
                    summary_json = excluded.summary_json,
                    updated_at = excluded.updated_at
                """,
                (
                    summary.strategy_id,
                    summary.strategy_version,
                    _json_dumps(summary.model_dump(mode="json")),
                    _datetime_to_text(timestamp),
                ),
            )

    def get_performance(
        self,
        strategy_id: str,
        version: str,
    ) -> StrategyPerformanceSummary | None:
        row = self._connection.execute(
            """
            SELECT summary_json FROM strategy_performance
            WHERE strategy_id = ? AND strategy_version = ?
            """,
            (strategy_id, version),
        ).fetchone()
        if row is None:
            return None
        return StrategyPerformanceSummary.model_validate_json(str(row["summary_json"]))


class LiveEntryAttemptRepository:
    """Persistent one-attempt claim for an owner authorization identifier."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def claim(
        self,
        *,
        authorization_id: str,
        run_id: str,
        strategy_id: str,
        market_id: str,
        attempted_at: datetime,
    ) -> bool:
        try:
            with transaction(self._connection) as connection:
                connection.execute(
                    """
                    INSERT INTO live_entry_attempts (
                        authorization_id, run_id, strategy_id, market_id, state,
                        attempted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        authorization_id,
                        run_id,
                        strategy_id,
                        market_id,
                        "CLAIMED_BEFORE_SUBMIT",
                        _datetime_to_text(attempted_at),
                        _datetime_to_text(attempted_at),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def update_state(self, authorization_id: str, state: str, *, updated_at: datetime) -> None:
        with transaction(self._connection) as connection:
            cursor = connection.execute(
                """
                UPDATE live_entry_attempts SET state = ?, updated_at = ?
                WHERE authorization_id = ?
                """,
                (state, _datetime_to_text(updated_at), authorization_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"live authorization {authorization_id} has no attempt claim")

    def get(self, authorization_id: str) -> dict[str, str] | None:
        row = self._connection.execute(
            "SELECT * FROM live_entry_attempts WHERE authorization_id = ?",
            (authorization_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "authorization_id": str(row["authorization_id"]),
            "run_id": str(row["run_id"]),
            "strategy_id": str(row["strategy_id"]),
            "market_id": str(row["market_id"]),
            "state": str(row["state"]),
            "attempted_at": str(row["attempted_at"]),
            "updated_at": str(row["updated_at"]),
        }


class LedgerEventRepository:
    """Append-only persistence for run-scoped canonical ledger events."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        *,
        run_id: str,
        event: LedgerEvent,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO ledger_events (
                    event_id, run_id, event_type, instrument_id, amount,
                    currency, order_id, fill_id, payload_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    run_id,
                    event.event_type,
                    event.instrument_id,
                    str(event.amount),
                    event.currency,
                    event.order_id,
                    event.fill_id,
                    _json_dumps(dict(payload or {})),
                    _datetime_to_text(event.occurred_at),
                ),
            )

    def list_for_run(self, run_id: str) -> list[LedgerEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM ledger_events
            WHERE run_id = ? ORDER BY occurred_at, event_id
            """,
            (run_id,),
        ).fetchall()
        return [
            LedgerEvent(
                event_id=str(row["event_id"]),
                event_type=str(row["event_type"]),
                instrument_id=_optional_str(row["instrument_id"]),
                amount=Decimal(str(row["amount"])),
                currency=str(row["currency"]),
                occurred_at=_text_to_datetime(str(row["occurred_at"])),
                order_id=_optional_str(row["order_id"]),
                fill_id=_optional_str(row["fill_id"]),
            )
            for row in rows
        ]


class LiveOrderCheckpointRepository:
    """Durable transition checkpoints written before the next external step."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(
        self,
        *,
        run_id: str,
        phase: str,
        client_order_id: str,
        venue_order_id: str | None,
        payload: Mapping[str, Any],
        persisted_at: datetime,
    ) -> None:
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO live_order_checkpoints (
                    run_id, phase, client_order_id, venue_order_id,
                    payload_json, persisted_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, phase) DO UPDATE SET
                    client_order_id = excluded.client_order_id,
                    venue_order_id = excluded.venue_order_id,
                    payload_json = excluded.payload_json,
                    persisted_at = excluded.persisted_at
                """,
                (
                    run_id,
                    phase,
                    client_order_id,
                    venue_order_id,
                    _json_dumps(dict(payload)),
                    _datetime_to_text(persisted_at),
                ),
            )

    def list_for_run(self, run_id: str) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT * FROM live_order_checkpoints
            WHERE run_id = ? ORDER BY persisted_at, phase
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "client_order_id": str(row["client_order_id"]),
                "payload": _json_loads(str(row["payload_json"])),
                "persisted_at": str(row["persisted_at"]),
                "phase": str(row["phase"]),
                "run_id": str(row["run_id"]),
                "venue_order_id": _optional_str(row["venue_order_id"]),
            }
            for row in rows
        ]


def _row_to_event(row: sqlite3.Row) -> StoredMarketEvent:
    event = MarketDataEvent(
        source="polymarket",
        event_type=str(row["event_type"]),
        token_id=str(row["token_id"]),
        received_at=_text_to_datetime(str(row["received_at"])),
        exchange_ts=_optional_text_to_datetime(row["exchange_ts"]),
        payload=_json_loads(str(row["payload_json"])),
        raw_payload=_json_loads(str(row["raw_payload_json"])),
    )
    return StoredMarketEvent(id=int(row["id"]), event=event)


def _row_to_market(row: sqlite3.Row) -> StoredMarket:
    return StoredMarket(
        market_id=str(row["market_id"]),
        slug=_optional_str(row["slug"]),
        question=_optional_str(row["question"]),
        category=_optional_str(row["category"]),
        active=_optional_int_to_bool(row["active"]),
        closed=_optional_int_to_bool(row["closed"]),
        accepting_orders=_optional_int_to_bool(row["accepting_orders"]),
        end_date=_optional_text_to_datetime(row["end_date"]),
        liquidity=_optional_text_to_decimal(row["liquidity"]),
        volume=_optional_text_to_decimal(row["volume"]),
        best_bid=_optional_text_to_decimal(row["best_bid"]),
        best_ask=_optional_text_to_decimal(row["best_ask"]),
        outcomes=_json_loads_list(str(row["outcomes_json"])),
        updated_at=_text_to_datetime(str(row["updated_at"])),
    )


def _row_to_orderbook_snapshot(row: sqlite3.Row) -> StoredOrderBookSnapshot:
    return StoredOrderBookSnapshot(
        id=int(row["id"]),
        token_id=str(row["token_id"]),
        captured_at=_text_to_datetime(str(row["captured_at"])),
        snapshot=_json_loads(str(row["snapshot_json"])),
    )


def _row_to_decision(row: sqlite3.Row) -> StoredDecision:
    return StoredDecision(
        id=int(row["id"]),
        strategy_id=str(row["strategy_id"]),
        token_id=str(row["token_id"]),
        decision_type=str(row["decision_type"]),
        reason=str(row["reason"]),
        approved=_optional_int_to_bool(row["approved"]),
        payload=_json_loads(str(row["payload_json"])),
        created_at=_text_to_datetime(str(row["created_at"])),
    )


def _row_to_order(row: sqlite3.Row) -> StoredOrder:
    return StoredOrder(
        order_id=str(row["order_id"]),
        broker=str(row["broker"]),
        strategy_id=_optional_str(row["strategy_id"]),
        token_id=str(row["token_id"]),
        side=_row_side(row),
        price=Decimal(str(row["price"])),
        size=Decimal(str(row["size"])),
        status=str(row["status"]),
        payload=_json_loads(str(row["payload_json"])),
        created_at=_text_to_datetime(str(row["created_at"])),
        updated_at=_text_to_datetime(str(row["updated_at"])),
    )


def _row_to_fill(row: sqlite3.Row) -> StoredFill:
    return StoredFill(
        fill_id=str(row["fill_id"]),
        order_id=str(row["order_id"]),
        token_id=str(row["token_id"]),
        side=_row_side(row),
        price=Decimal(str(row["price"])),
        size=Decimal(str(row["size"])),
        fee=_optional_text_to_decimal(row["fee"]),
        liquidity_role=_optional_str(row["liquidity_role"]),
        payload=_json_loads(str(row["payload_json"])),
        created_at=_text_to_datetime(str(row["created_at"])),
    )


def _row_to_position(row: sqlite3.Row) -> StoredPosition:
    return StoredPosition(
        token_id=str(row["token_id"]),
        market_id=_optional_str(row["market_id"]),
        size=Decimal(str(row["size"])),
        avg_price=Decimal(str(row["avg_price"])),
        realized_pnl=Decimal(str(row["realized_pnl"])),
        payload=_json_loads(str(row["payload_json"])),
        updated_at=_text_to_datetime(str(row["updated_at"])),
    )


def _row_side(row: sqlite3.Row) -> OrderSide:
    side = str(row["side"])
    if side not in ("BUY", "SELL"):
        raise ValueError(f"stored side is invalid: {side}")
    return cast(OrderSide, side)


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite did not return a row id")
    return int(row_id)


def _json_dumps(value: object) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str) -> dict[str, Any]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("expected stored JSON object")
    return decoded


def _json_loads_list(value: str) -> list[dict[str, Any]]:
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        raise ValueError("expected stored JSON array")
    return [dict(item) for item in decoded]


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _datetime_to_text(value)
    raise TypeError(f"object is not JSON serializable: {type(value).__name__}")


def _datetime_to_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _optional_datetime_to_text(value: datetime | None) -> str | None:
    return _datetime_to_text(value) if value is not None else None


def _text_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_text_to_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _text_to_datetime(str(value))


def _optional_decimal_to_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _optional_text_to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _optional_bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _optional_int_to_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
