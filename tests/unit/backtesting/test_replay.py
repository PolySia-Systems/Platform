from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.backtesting.replay import (
    BacktestConfig,
    BacktestEngine,
    ReplayError,
    load_market_data_events_jsonl,
    market_data_event_from_dict,
)
from polysia.strategies.passive_market_maker import (
    PassiveMarketMakerConfig,
    PassiveMarketMakerStrategy,
)
from polysia.strategies.stale_price import StalePriceStrategy, StalePriceStrategyConfig


def book_event(*, bid_size: str = "10", ask_size: str = "1") -> dict[str, object]:
    return {
        "event_type": "book",
        "payload": {
            "asks": [{"price": "0.50", "size": ask_size}],
            "bids": [{"price": "0.40", "size": bid_size}],
        },
        "raw_payload": {},
        "received_at": "2026-01-01T00:00:00+00:00",
        "source": "polymarket",
        "token_id": "token-1",
    }


def test_market_data_event_from_dict_parses_iso_datetimes() -> None:
    event = market_data_event_from_dict(
        {
            **book_event(),
            "exchange_ts": "2026-01-01T00:00:01Z",
        }
    )

    assert event.source == "polymarket"
    assert event.event_type == "book"
    assert event.token_id == "token-1"
    assert event.received_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert event.exchange_ts == datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)


def test_load_market_data_events_jsonl_skips_blank_lines_and_limits(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            (
                json.dumps(book_event()),
                "",
                json.dumps(book_event(bid_size="9")),
            )
        ),
        encoding="utf-8",
    )

    events = load_market_data_events_jsonl(path, max_events=1)

    assert len(events) == 1
    assert events[0].token_id == "token-1"


def test_load_market_data_events_jsonl_rejects_bad_json(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{bad", encoding="utf-8")

    with pytest.raises(ReplayError, match="invalid JSON"):
        load_market_data_events_jsonl(path)


@pytest.mark.asyncio
async def test_backtest_engine_replays_buy_fill_and_pnl() -> None:
    event = market_data_event_from_dict(book_event())
    strategy = StalePriceStrategy(
        config=StalePriceStrategyConfig(
            min_edge=Decimal("0.01"),
            order_size=Decimal("1"),
        )
    )
    engine = BacktestEngine(
        strategy=strategy,
        config=BacktestConfig(initial_cash=Decimal("100"), max_order_notional=Decimal("10")),
    )

    result = await engine.run([event])
    payload = result.to_dict()

    assert payload["status"] == "ok"
    assert payload["events_processed"] == 1
    assert payload["intents_generated"] == 1
    assert payload["orders_created"] == 1
    assert payload["fills_created"] == 1
    assert payload["final_cash"] == "99.50"
    assert payload["positions"] == {"token-1": {"avg_price": "0.50", "size": "1"}}
    assert payload["portfolio"]["total_equity"] == "99.95"
    assert payload["orders"][0]["order"]["status"] == "FILLED"


@pytest.mark.asyncio
async def test_backtest_engine_records_risk_rejection() -> None:
    event = market_data_event_from_dict(book_event())
    strategy = StalePriceStrategy(
        config=StalePriceStrategyConfig(
            min_edge=Decimal("0.01"),
            order_size=Decimal("5"),
        )
    )
    engine = BacktestEngine(
        strategy=strategy,
        config=BacktestConfig(initial_cash=Decimal("100"), max_order_notional=Decimal("1")),
    )

    result = await engine.run([event])
    payload = result.to_dict()

    assert payload["intents_generated"] == 1
    assert payload["risk_rejections"] == 1
    assert payload["orders_created"] == 0
    assert payload["orders"][0]["order"] is None
    assert "exceeds max_order_notional" in payload["orders"][0]["risk_decision"]["reason"]


@pytest.mark.asyncio
async def test_backtest_engine_runs_passive_market_maker_without_live_calls() -> None:
    event = market_data_event_from_dict(book_event())
    strategy = PassiveMarketMakerStrategy(
        config=PassiveMarketMakerConfig(
            quote_size=Decimal("1"),
            min_spread=Decimal("0.05"),
            max_inventory=Decimal("5"),
        )
    )
    engine = BacktestEngine(
        strategy=strategy,
        config=BacktestConfig(initial_cash=Decimal("100"), max_order_notional=Decimal("10")),
    )

    result = await engine.run([event])
    payload = result.to_dict()

    assert payload["intents_generated"] == 1
    assert payload["orders_created"] == 1
    assert payload["fills_created"] == 0
    assert payload["orders"][0]["order"]["status"] == "ACCEPTED"
    assert payload["positions"] == {}
