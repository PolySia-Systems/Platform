from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.reconciliation.live_round_trip import (
    LiveRoundTripReconciliationConfig,
    LiveRoundTripReconciliationError,
    LiveRoundTripVenueSnapshot,
    ObservedExitFill,
    ObservedExitOrder,
    reconcile_live_round_trip,
)
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import (
    FillRepository,
    LiveEntryAttemptRepository,
    LiveOrderCheckpointRepository,
    OrderRepository,
    PositionRepository,
)

RUN_ID = "live-004-run"
AUTHORIZATION_ID = "POLYSIA-LIVE-004"
ENTRY_ORDER_ID = "entry-order"
EXIT_ORDER_ID = "exit-order"
TOKEN_ID = "token-down"
NOW = datetime(2026, 7, 12, 20, 48, tzinfo=UTC)


class FakeVenueReader:
    def __init__(self, snapshot: LiveRoundTripVenueSnapshot) -> None:
        self.snapshot = snapshot
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
            timestamp=NOW,
        )
        orders.upsert(
            order_id=EXIT_ORDER_ID,
            broker="polymarket-live",
            strategy_id="btc-15m-favorite-take-profit",
            token_id=TOKEN_ID,
            side="SELL",
            price=Decimal("0.58"),
            size=Decimal("5"),
            status="live",
            timestamp=NOW,
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
            created_at=NOW,
        )
        PositionRepository(database.connection).upsert(
            token_id=TOKEN_ID,
            market_id="2884631",
            size=Decimal("5"),
            avg_price=Decimal("0.52"),
            realized_pnl=Decimal("0"),
            updated_at=NOW,
        )
        attempts = LiveEntryAttemptRepository(database.connection)
        assert attempts.claim(
            authorization_id=AUTHORIZATION_ID,
            run_id=RUN_ID,
            strategy_id="btc-15m-favorite-take-profit",
            market_id="2884631",
            attempted_at=NOW,
        )
        attempts.update_state(AUTHORIZATION_ID, "ENTRY_FILLED_EXIT_OPEN", updated_at=NOW)
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
                persisted_at=NOW,
            )


def _order(*, status: str, matched_size: str = "0") -> ObservedExitOrder:
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
    fill_id: str,
    size: str,
    *,
    price: str = "0.58",
    fee: Decimal | None = Decimal("0"),
    occurred_at: datetime = NOW + timedelta(minutes=6),
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
        fee=fee,
        fee_source="venue_confirmed" if fee is not None else "venue_fee_unavailable",
    )


def _snapshot(
    *,
    status: str = "LIVE",
    matched_size: str = "0",
    fills: tuple[ObservedExitFill, ...] = (),
    position_size: str = "5",
    order_present: bool = True,
    balances_readable: bool = True,
) -> LiveRoundTripVenueSnapshot:
    return LiveRoundTripVenueSnapshot(
        order=_order(status=status, matched_size=matched_size) if order_present else None,
        fills=fills,
        position_size=Decimal(position_size),
        account_balances_readable=balances_readable,
        read_at=NOW + timedelta(minutes=7),
    )


@pytest.mark.asyncio
async def test_unconsumed_authorization_is_rejected_before_venue_read(
    database_path: Path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE live_entry_attempts SET state = 'CLAIMED' WHERE authorization_id = ?",
            (AUTHORIZATION_ID,),
        )
    reader = FakeVenueReader(_snapshot())

    with pytest.raises(
        LiveRoundTripReconciliationError,
        match="has not reached a reconcilable exit state",
    ):
        await reconcile_live_round_trip(
            LiveRoundTripReconciliationConfig(
                database_path=database_path,
                run_id=RUN_ID,
                authorization_id=AUTHORIZATION_ID,
            ),
            venue_reader=reader,
        )

    assert reader.read_count == 0


async def _reconcile(path: Path, snapshot: LiveRoundTripVenueSnapshot):
    reader = FakeVenueReader(snapshot)
    report = await reconcile_live_round_trip(
        LiveRoundTripReconciliationConfig(
            database_path=path,
            run_id=RUN_ID,
            authorization_id=AUTHORIZATION_ID,
        ),
        venue_reader=reader,
        clock=lambda: NOW + timedelta(minutes=8),
    )
    assert reader.read_count == 1
    return report


def _scalar(path: Path, sql: str, params: tuple[object, ...] = ()) -> object:
    with SQLiteDatabase(path) as database:
        row = database.connection.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


@pytest.mark.asyncio
async def test_zero_fill_keeps_open_exit_without_business_state_change(
    database_path: Path,
) -> None:
    report = await _reconcile(database_path, _snapshot())

    assert report.classification == "EXIT_OPEN"
    assert report.status == "ready"
    assert report.confirmed_exit_size == 0
    assert report.new_fill_count == 0
    assert report.new_ledger_event_count == 0
    assert _scalar(database_path, "SELECT size FROM positions WHERE token_id=?", (TOKEN_ID,)) == "5"


@pytest.mark.asyncio
async def test_partial_fill_updates_only_confirmed_quantity(database_path: Path) -> None:
    report = await _reconcile(
        database_path,
        _snapshot(
            matched_size="2",
            fills=(_fill("trade-1:maker:0", "2"),),
            position_size="3",
        ),
    )

    assert report.classification == "EXIT_PARTIALLY_FILLED_OPEN"
    assert report.status == "warning"
    assert report.expected_remaining_position == 3
    assert report.net_realized_pnl == Decimal("0.085056")
    assert report.new_fill_count == 1
    assert report.new_ledger_event_count == 2
    assert _scalar(database_path, "SELECT size FROM positions WHERE token_id=?", (TOKEN_ID,)) == "3"


@pytest.mark.asyncio
async def test_full_fill_closes_position_and_records_net_realized_pnl(
    database_path: Path,
) -> None:
    report = await _reconcile(
        database_path,
        _snapshot(
            status="MATCHED",
            matched_size="5",
            fills=(_fill("trade-1:maker:0", "5"),),
            position_size="0",
        ),
    )

    assert report.classification == "COMPLETED_ROUND_TRIP"
    assert report.status == "ready"
    assert report.weighted_average_exit_price == Decimal("0.58")
    assert report.gross_exit_proceeds == Decimal("2.90")
    assert report.exit_fee == 0
    assert report.net_realized_pnl == Decimal("0.21264")
    assert _scalar(database_path, "SELECT size FROM positions WHERE token_id=?", (TOKEN_ID,)) == "0"
    assert _scalar(
        database_path,
        "SELECT realized_pnl FROM positions WHERE token_id=?",
        (TOKEN_ID,),
    ) == "0.21264"
    assert (
        _scalar(database_path, "SELECT status FROM orders WHERE order_id=?", (EXIT_ORDER_ID,))
        == "FILLED"
    )
    persisted_report = json.loads(
        str(
            _scalar(
                database_path,
                "SELECT payload_json FROM live_round_trip_reconciliations",
            )
        )
    )
    assert persisted_report["new_fill_count"] == 1
    assert persisted_report["new_ledger_event_count"] == 2
    assert persisted_report["observation_recorded"] is True


@pytest.mark.asyncio
async def test_multiple_partial_fills_are_sorted_and_aggregated(database_path: Path) -> None:
    later = _fill("trade-2:maker:0", "1", occurred_at=NOW + timedelta(minutes=7))
    earlier = _fill("trade-1:maker:0", "2", occurred_at=NOW + timedelta(minutes=6))

    report = await _reconcile(
        database_path,
        _snapshot(
            matched_size="3",
            fills=(later, earlier),
            position_size="2",
        ),
    )

    assert report.classification == "EXIT_PARTIALLY_FILLED_OPEN"
    assert report.confirmed_exit_size == 3
    assert report.fill_count == 2
    assert report.new_fill_count == 2
    assert report.new_ledger_event_count == 4


@pytest.mark.asyncio
async def test_duplicate_fill_event_is_ingested_once(database_path: Path) -> None:
    fill = _fill("trade-1:maker:0", "5")

    report = await _reconcile(
        database_path,
        _snapshot(
            status="MATCHED",
            matched_size="5",
            fills=(fill, fill),
            position_size="0",
        ),
    )

    assert report.duplicate_fill_count == 1
    assert report.new_fill_count == 1
    assert _scalar(
        database_path,
        "SELECT COUNT(*) FROM fills WHERE fill_id LIKE ?",
        (f"{RUN_ID}:exit:%",),
    ) == 1


@pytest.mark.asyncio
async def test_identical_repeat_reconciliation_is_idempotent(database_path: Path) -> None:
    snapshot = _snapshot(
        status="MATCHED",
        matched_size="5",
        fills=(_fill("trade-1:maker:0", "5"),),
        position_size="0",
    )

    first = await _reconcile(database_path, snapshot)
    second = await _reconcile(database_path, snapshot)

    assert first.observation_recorded is True
    assert second.observation_recorded is False
    assert second.new_fill_count == 0
    assert second.new_ledger_event_count == 0
    assert _scalar(
        database_path,
        "SELECT COUNT(*) FROM live_round_trip_reconciliations WHERE run_id=?",
        (RUN_ID,),
    ) == 1
    assert _scalar(
        database_path,
        "SELECT COUNT(*) FROM ledger_events WHERE run_id=? AND event_type LIKE 'LIVE_EXIT_%'",
        (RUN_ID,),
    ) == 2


@pytest.mark.asyncio
async def test_restart_merges_persisted_partial_with_new_fill(database_path: Path) -> None:
    await _reconcile(
        database_path,
        _snapshot(
            matched_size="2",
            fills=(_fill("trade-1:maker:0", "2"),),
            position_size="3",
        ),
    )

    report = await _reconcile(
        database_path,
        _snapshot(
            status="MATCHED",
            matched_size="5",
            fills=(_fill("trade-2:maker:0", "3"),),
            position_size="0",
        ),
    )

    assert report.classification == "COMPLETED_ROUND_TRIP"
    assert report.confirmed_exit_size == 5
    assert report.new_fill_count == 1
    assert report.net_realized_pnl == Decimal("0.21264")
    assert _scalar(
        database_path,
        "SELECT COUNT(*) FROM fills WHERE fill_id LIKE ?",
        (f"{RUN_ID}:exit:%",),
    ) == 2


@pytest.mark.asyncio
async def test_transaction_failure_rolls_back_all_reconciliation_writes(
    database_path: Path,
) -> None:
    with SQLiteDatabase(database_path) as database:
        database.connection.executescript(
            """
            CREATE TRIGGER fail_exit_ledger
            BEFORE INSERT ON ledger_events
            WHEN NEW.event_type = 'LIVE_EXIT_POSITION_DECREASE'
            BEGIN
                SELECT RAISE(ABORT, 'forced rollback');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced rollback"):
        await _reconcile(
            database_path,
            _snapshot(
                status="MATCHED",
                matched_size="5",
                fills=(_fill("trade-1:maker:0", "5"),),
                position_size="0",
            ),
        )

    assert _scalar(
        database_path,
        "SELECT COUNT(*) FROM live_round_trip_reconciliations",
    ) == 0
    assert _scalar(
        database_path,
        "SELECT COUNT(*) FROM fills WHERE fill_id LIKE ?",
        (f"{RUN_ID}:exit:%",),
    ) == 0
    assert _scalar(database_path, "SELECT size FROM positions WHERE token_id=?", (TOKEN_ID,)) == "5"


@pytest.mark.asyncio
async def test_internal_venue_position_mismatch_fails_closed(database_path: Path) -> None:
    report = await _reconcile(
        database_path,
        _snapshot(
            status="MATCHED",
            matched_size="5",
            fills=(_fill("trade-1:maker:0", "5"),),
            position_size="5",
        ),
    )

    assert report.status == "blocked"
    assert "venue position does not match" in " ".join(report.blocking_reasons)
    assert report.new_fill_count == 0
    assert _scalar(database_path, "SELECT size FROM positions WHERE token_id=?", (TOKEN_ID,)) == "5"


@pytest.mark.asyncio
async def test_missing_venue_order_fails_closed(database_path: Path) -> None:
    report = await _reconcile(database_path, _snapshot(order_present=False))

    assert report.classification == "RECONCILIATION_BLOCKED"
    assert report.status == "blocked"
    assert "could not be identified" in " ".join(report.blocking_reasons)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["CANCELED", "REJECTED"])
async def test_cancelled_or_rejected_unfilled_exit_fails_closed(
    database_path: Path,
    status: str,
) -> None:
    report = await _reconcile(database_path, _snapshot(status=status))

    assert report.status == "blocked"
    assert report.classification == "RECONCILIATION_BLOCKED"


@pytest.mark.asyncio
async def test_fill_before_order_status_update_closes_with_warning(
    database_path: Path,
) -> None:
    report = await _reconcile(
        database_path,
        _snapshot(
            status="LIVE",
            matched_size="0",
            fills=(_fill("trade-1:maker:0", "5"),),
            position_size="0",
        ),
    )

    assert report.classification == "COMPLETED_ROUND_TRIP"
    assert report.status == "warning"
    assert "status" in " ".join(report.warnings)


@pytest.mark.asyncio
async def test_missing_exit_fee_is_explicit_and_not_estimated(database_path: Path) -> None:
    report = await _reconcile(
        database_path,
        _snapshot(
            status="MATCHED",
            matched_size="5",
            fills=(_fill("trade-1:maker:0", "5", fee=None),),
            position_size="0",
        ),
    )

    assert report.classification == "COMPLETED_ROUND_TRIP"
    assert report.status == "warning"
    assert report.fee_status == "unknown"
    assert report.exit_fee is None
    assert report.net_realized_pnl is None
    assert report.new_ledger_event_count == 1
    assert _scalar(
        database_path,
        "SELECT realized_pnl FROM positions WHERE token_id=?",
        (TOKEN_ID,),
    ) == "0"


@pytest.mark.asyncio
async def test_later_confirmed_fee_completes_accounting_without_duplicate_fill(
    database_path: Path,
) -> None:
    unknown_fee_snapshot = _snapshot(
        status="MATCHED",
        matched_size="5",
        fills=(_fill("trade-1:maker:0", "5", fee=None),),
        position_size="0",
    )
    await _reconcile(database_path, unknown_fee_snapshot)

    report = await _reconcile(
        database_path,
        _snapshot(
            status="MATCHED",
            matched_size="5",
            fills=(_fill("trade-1:maker:0", "5", fee=Decimal("0")),),
            position_size="0",
        ),
    )

    assert report.fee_status == "confirmed"
    assert report.net_realized_pnl == Decimal("0.21264")
    assert report.new_fill_count == 0
    assert report.new_ledger_event_count == 1
    assert _scalar(
        database_path,
        "SELECT fee FROM fills WHERE fill_id LIKE ?",
        (f"{RUN_ID}:exit:%",),
    ) == "0"
    assert _scalar(
        database_path,
        "SELECT realized_pnl FROM positions WHERE token_id=?",
        (TOKEN_ID,),
    ) == "0.21264"


@pytest.mark.asyncio
async def test_required_balance_read_failure_blocks_persistence(database_path: Path) -> None:
    report = await _reconcile(database_path, _snapshot(balances_readable=False))

    assert report.status == "blocked"
    assert "balance reads" in " ".join(report.blocking_reasons)
    assert report.new_fill_count == 0
