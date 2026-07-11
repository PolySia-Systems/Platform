from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.bus.events import MarketDataEvent
from polysia.domain.market import MarketOutcomeSummary, MarketSummary
from polysia.orderbook.book import LocalOrderBook
from polysia.storage.db import connect_sqlite, initialize_database
from polysia.storage.repositories import (
    DecisionRepository,
    EventRepository,
    FillRepository,
    MarketRepository,
    OrderBookSnapshotRepository,
    OrderRepository,
    PositionRepository,
)


@pytest.fixture
def connection():
    active_connection = connect_sqlite()
    initialize_database(active_connection)
    try:
        yield active_connection
    finally:
        active_connection.close()


def test_event_repository_round_trips_market_data_event(connection) -> None:
    event = MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id="token-1",
        received_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        exchange_ts=datetime(2026, 1, 1, 11, 59, tzinfo=UTC),
        payload={"price": Decimal("0.52")},
        raw_payload={"type": "book"},
    )
    repository = EventRepository(connection)

    event_id = repository.add(event)
    rows = repository.list_recent(token_id="token-1")

    assert event_id > 0
    assert len(rows) == 1
    assert rows[0].event.token_id == "token-1"
    assert rows[0].event.payload == {"price": "0.52"}
    assert rows[0].event.exchange_ts == datetime(2026, 1, 1, 11, 59, tzinfo=UTC)


def test_market_repository_upserts_and_lists_active_markets(connection) -> None:
    repository = MarketRepository(connection)
    market = MarketSummary(
        id="market-1",
        slug="example-market",
        question="Will this pass?",
        category="Testing",
        active=True,
        closed=False,
        accepting_orders=True,
        liquidity=Decimal("100.25"),
        volume=Decimal("200.50"),
        best_bid=Decimal("0.49"),
        best_ask=Decimal("0.52"),
        outcomes=(
            MarketOutcomeSummary(label="Yes", token_id="yes-token", price=Decimal("0.51")),
            MarketOutcomeSummary(label="No", token_id="no-token", price=Decimal("0.49")),
        ),
    )

    repository.upsert(market, updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    stored = repository.get("market-1")
    active_markets = repository.list_active()

    assert stored is not None
    assert stored.slug == "example-market"
    assert stored.best_bid == Decimal("0.49")
    assert stored.outcomes[0]["token_id"] == "yes-token"
    assert [item.market_id for item in active_markets] == ["market-1"]


def test_orderbook_snapshot_repository_saves_latest_snapshot(connection) -> None:
    repository = OrderBookSnapshotRepository(connection)
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=(("0.49", "10"),),
        asks=(("0.52", "20"),),
    )

    snapshot_id = repository.add(book, captured_at=datetime(2026, 1, 1, tzinfo=UTC))
    latest = repository.latest("token-1")

    assert snapshot_id > 0
    assert latest is not None
    assert latest.snapshot["best_bid"] == "0.49"
    assert latest.snapshot["microprice"] == "0.50"


def test_decision_repository_stores_audit_payload(connection) -> None:
    repository = DecisionRepository(connection)

    decision_id = repository.add(
        strategy_id="strategy-1",
        token_id="token-1",
        decision_type="ORDER_INTENT",
        reason="test",
        approved=False,
        payload={"edge": Decimal("0.02")},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    decision = repository.get(decision_id)

    assert decision is not None
    assert decision.approved is False
    assert decision.payload == {"edge": "0.02"}


def test_order_fill_and_position_repositories_round_trip_state(connection) -> None:
    orders = OrderRepository(connection)
    fills = FillRepository(connection)
    positions = PositionRepository(connection)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)

    orders.upsert(
        order_id="order-1",
        broker="paper",
        strategy_id="strategy-1",
        token_id="token-1",
        side="BUY",
        price=Decimal("0.51"),
        size=Decimal("10"),
        status="ACCEPTED",
        payload={"note": "created"},
        timestamp=timestamp,
    )
    orders.upsert(
        order_id="order-1",
        broker="paper",
        strategy_id="strategy-1",
        token_id="token-1",
        side="BUY",
        price=Decimal("0.51"),
        size=Decimal("10"),
        status="FILLED",
        payload={"note": "updated"},
        timestamp=timestamp,
    )
    fills.add(
        fill_id="fill-1",
        order_id="order-1",
        token_id="token-1",
        side="BUY",
        price=Decimal("0.51"),
        size=Decimal("10"),
        fee=Decimal("0"),
        liquidity_role="TAKER",
        created_at=timestamp,
    )
    positions.upsert(
        token_id="token-1",
        market_id="market-1",
        size=Decimal("10"),
        avg_price=Decimal("0.51"),
        realized_pnl=Decimal("0"),
        updated_at=timestamp,
    )

    order = orders.get("order-1")
    fill = fills.get("fill-1")
    position = positions.get("token-1")

    assert order is not None
    assert order.status == "FILLED"
    assert order.payload == {"note": "updated"}
    assert fill is not None
    assert fill.order_id == "order-1"
    assert fill.fee == Decimal("0")
    assert position is not None
    assert position.size == Decimal("10")
