from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pm_trader.bus.events import MarketDataEvent
from pm_trader.orderbook.book import LocalOrderBook
from pm_trader.strategies.base import StrategyContext
from pm_trader.strategies.stale_price import StalePriceStrategy, StalePriceStrategyConfig


def make_event(event_type: str = "book", token_id: str = "token-1") -> MarketDataEvent:
    return MarketDataEvent(
        source="polymarket",
        event_type=event_type,
        token_id=token_id,
        received_at=datetime.now(UTC),
        exchange_ts=None,
        payload={},
        raw_payload={},
    )


def make_book(*, bid_size: str, ask_size: str) -> LocalOrderBook:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=(("0.49", bid_size),),
        asks=(("0.52", ask_size),),
    )
    return book


@pytest.mark.asyncio
async def test_stale_price_strategy_generates_buy_intent_when_microprice_above_mid() -> None:
    strategy = StalePriceStrategy(
        config=StalePriceStrategyConfig(
            min_edge=Decimal("0.01"),
            order_size=Decimal("2"),
            confidence=Decimal("0.6"),
        )
    )
    context = StrategyContext(orderbook=make_book(bid_size="100", ask_size="10"))

    intents = await strategy.on_market_event(make_event(), context)

    assert len(intents) == 1
    assert intents[0].side == "BUY"
    assert intents[0].price == Decimal("0.52")
    assert intents[0].size == Decimal("2")
    assert intents[0].strategy_id == "stale-price"


@pytest.mark.asyncio
async def test_stale_price_strategy_generates_sell_intent_when_microprice_below_mid() -> None:
    strategy = StalePriceStrategy(
        config=StalePriceStrategyConfig(min_edge=Decimal("0.01"))
    )
    context = StrategyContext(orderbook=make_book(bid_size="10", ask_size="100"))

    intents = await strategy.on_market_event(make_event(), context)

    assert len(intents) == 1
    assert intents[0].side == "SELL"
    assert intents[0].price == Decimal("0.49")


@pytest.mark.asyncio
async def test_stale_price_strategy_returns_no_intents_without_signal() -> None:
    strategy = StalePriceStrategy(
        config=StalePriceStrategyConfig(min_edge=Decimal("0.10"))
    )
    context = StrategyContext(orderbook=make_book(bid_size="100", ask_size="10"))

    intents = await strategy.on_market_event(make_event(), context)

    assert intents == []


@pytest.mark.asyncio
async def test_stale_price_strategy_ignores_wrong_event_or_book() -> None:
    strategy = StalePriceStrategy()

    assert await strategy.on_market_event(make_event("last_trade_price"), StrategyContext()) == []
    assert await strategy.on_market_event(
        make_event(token_id="other-token"),
        StrategyContext(orderbook=make_book(bid_size="100", ask_size="10")),
    ) == []
