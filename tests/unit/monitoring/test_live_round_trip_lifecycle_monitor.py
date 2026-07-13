from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.monitoring.live_round_trip import (
    LifecycleHealthSnapshot,
    LiveRoundTripMonitorConfig,
    monitor_live_round_trip,
    render_live_round_trip_monitor,
)
from polysia.reconciliation.live_round_trip import (
    LiveRoundTripVenueReadError,
    LiveRoundTripVenueSnapshot,
    ObservedExitFill,
    ObservedExitOrder,
)
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import (
    FillRepository,
    LiveEntryAttemptRepository,
    LiveOrderCheckpointRepository,
    OrderRepository,
    PositionRepository,
)

RUN_ID = "live-monitor-run"
AUTHORIZATION_ID = "POLYSIA-LIVE-004"
ENTRY_ORDER_ID = "entry-order"
EXIT_ORDER_ID = "exit-order"
TOKEN_ID = "token-down"
STARTED_AT = datetime(2026, 7, 13, 10, tzinfo=UTC)
NOW = STARTED_AT + timedelta(minutes=6)


class FakeVenueReader:
    def __init__(
        self,
        snapshot: LiveRoundTripVenueSnapshot | None = None,
        error: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.error = error
        self.read_count = 0

    async def read_exit_state(
        self,
        *,
        order_id: str,
        token_id: str,
    ) -> LiveRoundTripVenueSnapshot:
        assert order_id == EXIT_ORDER_ID
        assert token_id == TOKEN_ID
        self.read_count += 1
        if self.error is not None:
            raise self.error
        assert self.snapshot is not None
        return self.snapshot


class FakeHealthReader:
    def __init__(self, snapshot: LifecycleHealthSnapshot | None = None) -> None:
        self.snapshot = snapshot or LifecycleHealthSnapshot(
            checked_at=NOW,
            server_time_readable=True,
            clock_drift_seconds=Decimal("0.25"),
            geoblock_status="allowed",
            geoblocked=False,
        )

    async def read_health(self) -> LifecycleHealthSnapshot:
        return self.snapshot


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "polysia.sqlite3"
    _seed_round_trip(path)
    return path


def _seed_round_trip(path: Path) -> None:
    with SQLiteDatabase(path) as database:
        orders = OrderRepository(database.connection)
        orders.upsert(
            order_id=ENTRY_ORDER_ID,
            broker="polymarket-live",
            strategy_id="btc-15m-favorite-take-profit",
            token_id=TOKEN_ID,
            side="BUY",
            price=Decimal("0.52"),
            size=Decimal("5"),
            status="CONFIRMED_FILL",
            timestamp=STARTED_AT,
        )
        orders.upsert(
            order_id=EXIT_ORDER_ID,
            broker="polymarket-live",
            strategy_id="btc-15m-favorite-take-profit",
            token_id=TOKEN_ID,
            side="SELL",
            price=Decimal("0.58"),
            size=Decimal("5"),
            status="LIVE",
            timestamp=STARTED_AT,
        )
        FillRepository(database.connection).add(
            fill_id=f"{RUN_ID}:entry",
            order_id=ENTRY_ORDER_ID,
            token_id=TOKEN_ID,
            side="BUY",
            price=Decimal("0.52"),
            size=Decimal("5"),
            fee=Decimal("0.08736"),
            liquidity_role="TAKER",
            created_at=STARTED_AT,
        )
        PositionRepository(database.connection).upsert(
            token_id=TOKEN_ID,
            market_id="market-1",
            size=Decimal("5"),
            avg_price=Decimal("0.52"),
            realized_pnl=Decimal("0"),
            updated_at=STARTED_AT,
        )
        attempts = LiveEntryAttemptRepository(database.connection)
        assert attempts.claim(
            authorization_id=AUTHORIZATION_ID,
            run_id=RUN_ID,
            strategy_id="btc-15m-favorite-take-profit",
            market_id="market-1",
            attempted_at=STARTED_AT,
        )
        attempts.update_state(AUTHORIZATION_ID, "ENTRY_FILLED_EXIT_OPEN", updated_at=STARTED_AT)
        checkpoints = LiveOrderCheckpointRepository(database.connection)
        for phase, client_id, venue_id in (
            ("ENTRY_RESPONSE", f"{RUN_ID}:entry", ENTRY_ORDER_ID),
            ("ENTRY_FILL_CONFIRMED", f"{RUN_ID}:entry", ENTRY_ORDER_ID),
            ("ENTRY_POSITION_RECONCILED", f"{RUN_ID}:entry", ENTRY_ORDER_ID),
            ("EXIT_RESPONSE", f"{RUN_ID}:exit", EXIT_ORDER_ID),
        ):
            checkpoints.upsert(
                run_id=RUN_ID,
                phase=phase,
                client_order_id=client_id,
                venue_order_id=venue_id,
                payload={"phase": phase},
                persisted_at=STARTED_AT,
            )


def _order(status: str, matched_size: str = "0") -> ObservedExitOrder:
    return ObservedExitOrder(
        order_id=EXIT_ORDER_ID,
        token_id=TOKEN_ID,
        side="SELL",
        price=Decimal("0.58"),
        original_size=Decimal("5"),
        matched_size=Decimal(matched_size),
        status=status,
    )


def _fill(
    fill_id: str = "venue-fill",
    size: str = "5",
    *,
    price: str = "0.58",
    occurred_at: datetime = NOW,
) -> ObservedExitFill:
    return ObservedExitFill(
        fill_id=fill_id,
        order_id=EXIT_ORDER_ID,
        token_id=TOKEN_ID,
        side="SELL",
        price=Decimal(price),
        size=Decimal(size),
        status="CONFIRMED",
        liquidity_role="MAKER",
        occurred_at=occurred_at,
        fee=Decimal("0"),
        fee_source="venue_confirmed",
    )


def _snapshot(
    *,
    status: str = "LIVE",
    matched_size: str = "0",
    fills: tuple[ObservedExitFill, ...] = (),
    position_size: str = "5",
) -> LiveRoundTripVenueSnapshot:
    return LiveRoundTripVenueSnapshot(
        order=_order(status, matched_size),
        fills=fills,
        position_size=Decimal(position_size),
        account_balances_readable=True,
        read_at=NOW,
    )


async def _monitor(
    path: Path,
    reader: FakeVenueReader,
    *,
    health: LifecycleHealthSnapshot | None = None,
):
    return await monitor_live_round_trip(
        LiveRoundTripMonitorConfig(
            database_path=path,
            run_id=RUN_ID,
            authorization_id=AUTHORIZATION_ID,
        ),
        venue_reader=reader,
        health_reader=FakeHealthReader(health),
        clock=lambda: NOW,
    )


def _codes(report) -> set[str]:
    return {alert.code for cycle in report.cycles for alert in cycle.alerts}


@pytest.mark.asyncio
async def test_open_and_stale_exit_alerts_are_idempotent(database_path: Path) -> None:
    reader = FakeVenueReader(_snapshot())

    first = await _monitor(database_path, reader)
    second = await _monitor(database_path, reader)

    assert first.status == "warning"
    assert _codes(first) == {"EXIT_ORDER_OPEN", "EXIT_ORDER_STALE"}
    assert first.new_alert_count == 2
    assert second.new_alert_count == 0
    assert second.duplicate_alert_count == 2
    assert reader.read_count == 2
    assert not hasattr(reader, "submit_order")
    with SQLiteDatabase(database_path) as database:
        count = database.connection.execute("SELECT COUNT(*) FROM live_lifecycle_alerts").fetchone()
        assert count is not None and count[0] == 2


@pytest.mark.asyncio
async def test_polling_is_explicitly_bounded(database_path: Path) -> None:
    reader = FakeVenueReader(_snapshot())
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    report = await monitor_live_round_trip(
        LiveRoundTripMonitorConfig(
            database_path=database_path,
            run_id=RUN_ID,
            authorization_id=AUTHORIZATION_ID,
            max_cycles=2,
            interval_seconds=30,
        ),
        venue_reader=reader,
        health_reader=FakeHealthReader(),
        clock=lambda: NOW,
        sleep=fake_sleep,
    )

    assert len(report.cycles) == 2
    assert reader.read_count == 2
    assert sleeps == [30]


@pytest.mark.asyncio
async def test_partial_and_late_full_fill_are_classified(database_path: Path) -> None:
    partial = await _monitor(
        database_path,
        FakeVenueReader(
            _snapshot(
                matched_size="2",
                fills=(_fill("partial", "2", occurred_at=STARTED_AT + timedelta(minutes=1)),),
                position_size="3",
            )
        ),
    )
    assert "EXIT_PARTIALLY_FILLED" in _codes(partial)

    full = await _monitor(
        database_path,
        FakeVenueReader(
            _snapshot(
                status="FILLED",
                matched_size="5",
                fills=(
                    _fill("partial", "2", occurred_at=STARTED_AT + timedelta(minutes=1)),
                    _fill("remainder", "3", occurred_at=NOW),
                ),
                position_size="0",
            )
        ),
    )
    assert {"ROUND_TRIP_CLOSED", "EXIT_FILLED_LATE"}.issubset(_codes(full))
    assert full.cycles[0].reconciliation is not None
    assert full.cycles[0].reconciliation.net_realized_pnl == Decimal("0.21264")


@pytest.mark.asyncio
async def test_mismatches_and_unexpected_state_block(database_path: Path) -> None:
    mismatch = await _monitor(
        database_path,
        FakeVenueReader(_snapshot(position_size="4")),
    )
    assert mismatch.status == "blocked"
    assert {"POSITION_MISMATCH", "RECONCILIATION_FAILED"}.issubset(_codes(mismatch))

    unexpected = await _monitor(
        database_path,
        FakeVenueReader(_snapshot(status="UNKNOWN")),
    )
    assert "UNEXPECTED_VENUE_STATE" in _codes(unexpected)


@pytest.mark.asyncio
async def test_ledger_and_duplicate_event_detection(database_path: Path) -> None:
    snapshot = _snapshot(
        status="FILLED",
        matched_size="5",
        fills=(_fill(),),
        position_size="0",
    )
    await _monitor(database_path, FakeVenueReader(snapshot))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "DELETE FROM ledger_events WHERE run_id = ? "
            "AND event_type = 'LIVE_EXIT_COLLATERAL_INCREASE'",
            (RUN_ID,),
        )

    repeated = await _monitor(database_path, FakeVenueReader(snapshot))

    assert {"LEDGER_MISMATCH", "DUPLICATE_EVENT"}.issubset(_codes(repeated))
    assert repeated.status == "blocked"


@pytest.mark.asyncio
async def test_missing_and_corrupt_checkpoints_are_critical(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "DELETE FROM live_order_checkpoints WHERE run_id = ? AND phase = 'EXIT_RESPONSE'",
            (RUN_ID,),
        )
    missing_reader = FakeVenueReader(_snapshot())
    missing = await _monitor(database_path, missing_reader)
    assert "MISSING_CHECKPOINT" in _codes(missing)
    assert missing_reader.read_count == 0

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO live_order_checkpoints ("
            "run_id, phase, client_order_id, venue_order_id, payload_json, persisted_at"
            ") VALUES (?, 'EXIT_RESPONSE', ?, ?, ?, ?)",
            (
                RUN_ID,
                f"{RUN_ID}:exit",
                EXIT_ORDER_ID,
                '{"phase":"EXIT_RESPONSE"}',
                STARTED_AT.isoformat(),
            ),
        )
        connection.execute(
            "UPDATE live_order_checkpoints SET payload_json = 'not-json' "
            "WHERE run_id = ? AND phase = 'EXIT_RESPONSE'",
            (RUN_ID,),
        )
    corrupt = await _monitor(database_path, FakeVenueReader(_snapshot()))
    assert "CORRUPT_CHECKPOINT" in _codes(corrupt)


@pytest.mark.asyncio
async def test_authenticated_read_failure_and_public_health_alerts(database_path: Path) -> None:
    health = LifecycleHealthSnapshot(
        checked_at=NOW,
        server_time_readable=False,
        clock_drift_seconds=Decimal("6.5"),
        geoblock_status="blocked",
        geoblocked=True,
        error_types=("TimeoutError",),
    )
    report = await _monitor(
        database_path,
        FakeVenueReader(error=LiveRoundTripVenueReadError("sanitized")),
        health=health,
    )

    assert {
        "API_DEGRADED",
        "AUTHENTICATION_READ_FAILED",
        "CLOCK_DRIFT",
        "GEOBLOCKED",
    }.issubset(_codes(report))
    assert report.status == "blocked"


@pytest.mark.asyncio
async def test_fill_conflict_and_reports_are_safe(database_path: Path) -> None:
    snapshot = _snapshot(
        status="FILLED",
        matched_size="5",
        fills=(_fill(price="0.58"),),
        position_size="0",
    )
    await _monitor(database_path, FakeVenueReader(snapshot))
    conflicting = _snapshot(
        status="FILLED",
        matched_size="5",
        fills=(_fill(price="0.59"),),
        position_size="0",
    )

    report = await _monitor(database_path, FakeVenueReader(conflicting))
    rendered = render_live_round_trip_monitor(report, "json")

    assert "FILL_MISMATCH" in _codes(report)
    assert EXIT_ORDER_ID not in rendered
    assert TOKEN_ID not in rendered
    assert "submit" in report.read_only_statement
