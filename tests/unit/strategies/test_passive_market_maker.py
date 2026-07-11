from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pm_trader.bus.events import MarketDataEvent
from pm_trader.orderbook.book import LocalOrderBook
from pm_trader.strategies.base import StrategyContext
from pm_trader.strategies.passive_market_maker import (
    PassiveMarketMakerConfig,
    PassiveMarketMakerStrategy,
)


def make_event(token_id: str = "token-1") -> MarketDataEvent:
    return MarketDataEvent(
        source="polymarket",
        event_type="book",
        token_id=token_id,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        exchange_ts=None,
        payload={},
        raw_payload={},
    )


def make_book(*, best_bid: str = "0.40", best_ask: str = "0.50") -> LocalOrderBook:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=((Decimal(best_bid), Decimal("10")),),
        asks=((Decimal(best_ask), Decimal("10")),),
    )
    return book


def test_config_validates_positive_controls() -> None:
    with pytest.raises(ValueError, match="quote_size"):
        PassiveMarketMakerConfig(quote_size=Decimal("0"))
    with pytest.raises(ValueError, match="min_spread"):
        PassiveMarketMakerConfig(min_spread=Decimal("0"))
    with pytest.raises(ValueError, match="max_inventory"):
        PassiveMarketMakerConfig(max_inventory=Decimal("-1"))


@pytest.mark.asyncio
async def test_flat_inventory_emits_passive_buy_only() -> None:
    strategy = PassiveMarketMakerStrategy(
        config=PassiveMarketMakerConfig(
            quote_size=Decimal("2"),
            min_spread=Decimal("0.05"),
            max_inventory=Decimal("5"),
        )
    )

    intents = await strategy.on_market_event(
        make_event(),
        StrategyContext(orderbook=make_book(), positions={}),
    )

    assert len(intents) == 1
    assert intents[0].side == "BUY"
    assert intents[0].price == Decimal("0.40")
    assert intents[0].size == Decimal("2")
    assert intents[0].strategy_id == "passive-market-maker"


@pytest.mark.asyncio
async def test_existing_inventory_emits_buy_and_sell() -> None:
    strategy = PassiveMarketMakerStrategy(
        config=PassiveMarketMakerConfig(
            quote_size=Decimal("2"),
            min_spread=Decimal("0.05"),
            max_inventory=Decimal("5"),
        )
    )

    intents = await strategy.on_market_event(
        make_event(),
        StrategyContext(
            orderbook=make_book(),
            positions={"token-1": Decimal("3")},
        ),
    )

    assert [(intent.side, intent.price, intent.size) for intent in intents] == [
        ("BUY", Decimal("0.40"), Decimal("2")),
        ("SELL", Decimal("0.50"), Decimal("2")),
    ]


@pytest.mark.asyncio
async def test_buy_size_is_clipped_by_max_inventory() -> None:
    strategy = PassiveMarketMakerStrategy(
        config=PassiveMarketMakerConfig(
            quote_size=Decimal("2"),
            min_spread=Decimal("0.05"),
            max_inventory=Decimal("5"),
        )
    )

    intents = await strategy.on_market_event(
        make_event(),
        StrategyContext(
            orderbook=make_book(),
            positions={"token-1": Decimal("4.5")},
        ),
    )

    assert intents[0].side == "BUY"
    assert intents[0].size == Decimal("0.5")


@pytest.mark.asyncio
async def test_no_quotes_when_spread_is_too_tight() -> None:
    strategy = PassiveMarketMakerStrategy(
        config=PassiveMarketMakerConfig(min_spread=Decimal("0.05"))
    )

    intents = await strategy.on_market_event(
        make_event(),
        StrategyContext(orderbook=make_book(best_bid="0.40", best_ask="0.43")),
    )

    assert intents == []
