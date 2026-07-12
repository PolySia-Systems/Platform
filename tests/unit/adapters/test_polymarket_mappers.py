from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from polysia.adapters.polymarket.mappers import PolymarketMarketMapper


def test_mapper_translates_sdk_shaped_market_without_leaking_sdk_types() -> None:
    market = SimpleNamespace(
        id="external-market",
        slug="event-slug",
        question="Will it map?",
        category="test",
        state=SimpleNamespace(active=True, closed=False, accepting_orders=True, end_date=None),
        metrics=SimpleNamespace(liquidity_num=Decimal("10"), volume_num=Decimal("20")),
        prices=SimpleNamespace(best_bid=Decimal("0.4"), best_ask=Decimal("0.6")),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(label="Yes", token_id="yes-token", price=Decimal("0.55")),
            no=SimpleNamespace(label="No", token_id="no-token", price=Decimal("0.45")),
        ),
    )

    summary = PolymarketMarketMapper().to_summary(market)

    assert summary.id == "external-market"
    assert summary.best_bid == Decimal("0.4")
    assert summary.outcomes[0].token_id == "yes-token"
    assert type(summary).__module__ == "polysia.domain.market.models"


def test_mapper_normalizes_round_trip_market_rules_and_order_book() -> None:
    market = SimpleNamespace(
        id="market",
        slug="btc-updown-15m-123",
        condition_id="condition",
        question="Bitcoin Up or Down?",
        category="crypto",
        state=SimpleNamespace(
            active=True,
            archived=False,
            closed=False,
            accepting_orders=True,
            enable_order_book=True,
            start_date=datetime(2026, 7, 11, 11, 45, tzinfo=UTC),
            end_date=datetime(2026, 7, 11, 12, tzinfo=UTC),
        ),
        metrics=SimpleNamespace(liquidity_num=Decimal("10"), volume_num=Decimal("20")),
        prices=SimpleNamespace(best_bid=Decimal("0.4"), best_ask=Decimal("0.6")),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(label="Up", token_id="up", price=Decimal("0.6")),
            no=SimpleNamespace(label="Down", token_id="down", price=Decimal("0.4")),
        ),
        trading=SimpleNamespace(
            minimum_order_size=Decimal("5"),
            minimum_tick_size=Decimal("0.01"),
            seconds_delay=0,
            fees_enabled=True,
            fee_type="crypto",
            fee_schedule=SimpleNamespace(
                rate=Decimal("0.25"),
                exponent=Decimal("1"),
                taker_only=True,
                rebate_rate=Decimal("0.2"),
            ),
        ),
        tags=(),
    )
    raw_book = SimpleNamespace(
        token_id="up",
        market="condition",
        timestamp="1783771200000",
        bids=(SimpleNamespace(price="0.58", size="5"),),
        asks=(SimpleNamespace(price="0.60", size="4"),),
        min_order_size="1",
        tick_size="0.01",
        neg_risk=False,
        hash="book-hash",
    )
    mapper = PolymarketMarketMapper()

    details = mapper.to_details(market)
    book = mapper.to_order_book(raw_book)

    assert details.enable_order_book is True
    assert details.fee_schedule is not None
    assert details.fee_schedule.rate == Decimal("0.25")
    assert book.best_bid is not None and book.best_bid.price == Decimal("0.58")
    assert book.best_ask is not None and book.best_ask.size == Decimal("4")
    assert book.minimum_order_size == Decimal("1")
