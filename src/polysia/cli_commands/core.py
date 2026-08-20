"""Core, read-only, paper, and local simulation CLI commands."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from decimal import Decimal
from pathlib import Path
from typing import (
    Annotated,
    Literal,
)

import typer

from polysia import cli_support
from polysia.adapters.polymarket.public import (
    PolymarketPublicAdapter,
    PolymarketPublicAdapterError,
)
from polysia.adapters.polymarket.stream import (
    MarketStream,
    MarketStreamConfig,
    MarketStreamError,
)
from polysia.backtesting.replay import (
    BacktestConfig,
    BacktestEngine,
    ReplayError,
    load_market_data_events_jsonl,
)
from polysia.bus.events import market_data_event_to_dict
from polysia.bus.in_memory_bus import InMemoryEventBus
from polysia.cli_commands import print_error_and_exit
from polysia.config.settings import (
    AppSettings,
    TradingMode,
)
from polysia.config.status import build_configuration_status
from polysia.config.structured_logging import configure_logging
from polysia.domain.market import (
    MarketDetails,
    MarketSummary,
)
from polysia.execution.intents import ApprovedOrderIntent
from polysia.execution.paper_broker import PaperBroker
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.pnl import calculate_portfolio_pnl
from polysia.portfolio.positions import PositionLedger
from polysia.risk.checks import (
    RiskContext,
    RiskEngine,
)
from polysia.risk.limits import RiskLimits
from polysia.strategies.base import StrategyContext


@dataclass(frozen=True, slots=True)
class LiveSmokeSelection:
    market_slug: str
    condition_id: str
    token_id: str


def health() -> None:
    """Print a safe runtime health response."""
    settings = AppSettings()
    configure_logging(settings)

    payload = {
        "app_env": settings.app_env,
        "live_trading_allowed": settings.live_trading_allowed,
        "live_trading_enabled": settings.live_trading_enabled,
        "service": "polysia",
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "trading_mode": settings.trading_mode.value,
    }
    typer.echo(json.dumps(payload, sort_keys=True))


def configuration_status() -> None:
    """Print canonical, redacted runtime-configuration readiness."""

    settings = AppSettings()
    configure_logging(settings)
    status = build_configuration_status(settings)
    typer.echo(json.dumps(status.to_dict(), sort_keys=True))
    if status.status == "blocked":
        raise typer.Exit(code=1)


def discover_markets(
    limit: Annotated[int, typer.Option(min=1, max=100)] = 10,
) -> None:
    """Print active Polymarket markets from the public SDK."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        markets = asyncio.run(_discover_markets(limit))
    except PolymarketPublicAdapterError as error:
        error_payload = {
            "message": str(error),
            "status": "error",
        }
        typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error

    success_payload = {
        "count": len(markets),
        "markets": [market.model_dump(mode="json") for market in markets],
        "status": "ok",
    }
    typer.echo(json.dumps(success_payload, sort_keys=True))


async def _discover_markets(limit: int) -> list[MarketSummary]:
    adapter = PolymarketPublicAdapter()
    return await adapter.list_active_markets(page_size=limit)


async def resolve_live_smoke_selection(
    *,
    market_slug: str | None,
    condition_id: str | None,
    token_id: str | None,
    outcome: Literal["YES", "NO"],
    auto_btc_5m: bool,
) -> LiveSmokeSelection:
    if not auto_btc_5m:
        if not market_slug or not condition_id or not token_id:
            raise ValueError(
                "market_slug, condition_id, and token_id are required unless --auto-btc-5m is used."
            )
        return LiveSmokeSelection(
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
        )

    adapter = PolymarketPublicAdapter()
    markets = await adapter.search_markets("Bitcoin Up or Down 5m", page_size=30)
    candidates = [market for market in markets if _is_active_btc_5m_candidate(market)]
    candidates.sort(key=lambda market: market.end_date or datetime.max.replace(tzinfo=UTC))

    for candidate in candidates:
        if candidate.slug is None:
            continue
        details = await adapter.get_market_by_slug(candidate.slug)
        selected_token = _token_id_for_smoke_outcome(details, outcome)
        if details.condition_id and selected_token:
            return LiveSmokeSelection(
                market_slug=candidate.slug,
                condition_id=details.condition_id,
                token_id=selected_token,
            )

    raise ValueError("Could not auto-select an active BTC 5m market with a token id.")


async def resolve_monitor_btc_5m_market_slug() -> str:
    adapter = PolymarketPublicAdapter()
    markets = await adapter.search_markets("Bitcoin Up or Down 5m", page_size=30)
    candidates = [market for market in markets if _is_active_btc_5m_candidate(market)]
    candidates.sort(key=lambda market: market.end_date or datetime.max.replace(tzinfo=UTC))
    for candidate in candidates:
        if candidate.slug is not None:
            return candidate.slug
    raise ValueError("Could not auto-select an active BTC 5m market.")


def _is_active_btc_5m_candidate(market: MarketSummary) -> bool:
    if market.slug is None or not market.slug.startswith("btc-updown-5m-"):
        return False
    if market.active is not True or market.closed is True or market.accepting_orders is False:
        return False
    if market.end_date is None:
        return True
    end_date = market.end_date
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=UTC)
    return end_date > datetime.now(UTC) + timedelta(seconds=45)


def _token_id_for_smoke_outcome(
    market: MarketDetails,
    outcome: Literal["YES", "NO"],
) -> str | None:
    preferred_labels = {"yes", "up"} if outcome == "YES" else {"no", "down"}
    for market_outcome in market.outcomes:
        if market_outcome.label.lower() in preferred_labels:
            return market_outcome.token_id

    fallback_index = 0 if outcome == "YES" else 1
    if len(market.outcomes) <= fallback_index:
        return None
    return market.outcomes[fallback_index].token_id


def stream_market(
    token_id: Annotated[str, typer.Option("--token-id", help="Polymarket outcome token ID.")],
    max_events: Annotated[int | None, typer.Option(min=1)] = None,
    stale_after_seconds: Annotated[float, typer.Option(min=1.0)] = 30.0,
) -> None:
    """Print normalized realtime market events for one token."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        asyncio.run(
            _stream_market(
                token_id=token_id,
                max_events=max_events,
                stale_after_seconds=stale_after_seconds,
            )
        )
    except MarketStreamError as error:
        error_payload = {
            "message": str(error),
            "status": "error",
        }
        typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error


async def _stream_market(
    *,
    token_id: str,
    max_events: int | None,
    stale_after_seconds: float,
) -> None:
    bus = InMemoryEventBus()
    subscription = bus.subscribe()
    stream = MarketStream(
        bus=bus,
        config=MarketStreamConfig(
            token_ids=(token_id,),
            stale_after=timedelta(seconds=stale_after_seconds),
        ),
    )
    runner = asyncio.create_task(stream.run(max_events=max_events))
    printed = 0

    try:
        async with subscription:
            while max_events is None or printed < max_events:
                next_event = asyncio.create_task(anext(subscription))
                done, pending = await asyncio.wait(
                    {next_event, runner},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if next_event in done:
                    event = next_event.result()
                    typer.echo(json.dumps(market_data_event_to_dict(event), sort_keys=True))
                    printed += 1
                    continue

                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                _raise_runner_error(runner)
                break
    finally:
        if not runner.done():
            runner.cancel()
            with suppress(asyncio.CancelledError):
                await runner
        await subscription.close()
        await bus.close()


def _raise_runner_error(runner: asyncio.Task[None]) -> None:
    error = runner.exception()
    if error is not None:
        raise error


def paper_trade(
    token_id: Annotated[str, typer.Option("--token-id", help="Polymarket outcome token ID.")],
    strategy: Annotated[str, typer.Option("--strategy")] = "stale-price",
    best_bid: Annotated[str, typer.Option("--best-bid")] = "0.49",
    bid_size: Annotated[str, typer.Option("--bid-size")] = "100",
    best_ask: Annotated[str, typer.Option("--best-ask")] = "0.52",
    ask_size: Annotated[str, typer.Option("--ask-size")] = "10",
    order_size: Annotated[str, typer.Option("--order-size")] = "1",
    min_edge: Annotated[str, typer.Option("--min-edge")] = "0.01",
    initial_cash: Annotated[str, typer.Option("--initial-cash")] = "100",
) -> None:
    """Run a deterministic paper-trading simulation from a local book."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _paper_trade(
                token_id=token_id,
                strategy=strategy,
                best_bid=cli_support.parse_decimal(best_bid, "best_bid"),
                bid_size=cli_support.parse_decimal(bid_size, "bid_size"),
                best_ask=cli_support.parse_decimal(best_ask, "best_ask"),
                ask_size=cli_support.parse_decimal(ask_size, "ask_size"),
                order_size=cli_support.parse_decimal(order_size, "order_size"),
                min_edge=cli_support.parse_decimal(min_edge, "min_edge"),
                initial_cash=cli_support.parse_decimal(initial_cash, "initial_cash"),
            )
        )
    except ValueError as error:
        error_payload = {
            "message": str(error),
            "status": "error",
        }
        typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(json.dumps(payload, sort_keys=True))


def backtest_jsonl(
    input_path: Annotated[Path, typer.Option("--input", help="JSONL market event file.")],
    strategy: Annotated[str, typer.Option("--strategy")] = "stale-price",
    initial_cash: Annotated[str, typer.Option("--initial-cash")] = "100",
    order_size: Annotated[str, typer.Option("--order-size")] = "1",
    min_edge: Annotated[str, typer.Option("--min-edge")] = "0.01",
    max_order_notional: Annotated[str, typer.Option("--max-order-notional")] = "10",
    max_position_per_token: Annotated[str, typer.Option("--max-position-per-token")] = "100",
    max_position_per_market: Annotated[str, typer.Option("--max-position-per-market")] = "250",
    max_open_orders: Annotated[int, typer.Option("--max-open-orders", min=0)] = 20,
    max_events: Annotated[int | None, typer.Option("--max-events", min=1)] = None,
) -> None:
    """Replay JSONL market events through strategy, risk, and paper broker."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _backtest_jsonl(
                input_path=input_path,
                strategy=strategy,
                initial_cash=cli_support.parse_decimal(initial_cash, "initial_cash"),
                order_size=cli_support.parse_decimal(order_size, "order_size"),
                min_edge=cli_support.parse_decimal(min_edge, "min_edge"),
                max_order_notional=cli_support.parse_decimal(
                    max_order_notional,
                    "max_order_notional",
                ),
                max_position_per_token=cli_support.parse_decimal(
                    max_position_per_token,
                    "max_position_per_token",
                ),
                max_position_per_market=cli_support.parse_decimal(
                    max_position_per_market,
                    "max_position_per_market",
                ),
                max_open_orders=max_open_orders,
                max_events=max_events,
            )
        )
    except (ReplayError, ValueError) as error:
        print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


async def _backtest_jsonl(
    *,
    input_path: Path,
    strategy: str,
    initial_cash: Decimal,
    order_size: Decimal,
    min_edge: Decimal,
    max_order_notional: Decimal,
    max_position_per_token: Decimal,
    max_position_per_market: Decimal,
    max_open_orders: int,
    max_events: int | None,
) -> dict[str, object]:
    events = load_market_data_events_jsonl(input_path, max_events=max_events)
    strategy_instance = cli_support.build_research_strategy(
        strategy=strategy,
        order_size=order_size,
        min_edge=min_edge,
    )
    engine = BacktestEngine(
        strategy=strategy_instance,
        config=BacktestConfig(
            initial_cash=initial_cash,
            max_order_notional=max_order_notional,
            max_position_per_token=max_position_per_token,
            max_position_per_market=max_position_per_market,
            max_open_orders=max_open_orders,
        ),
    )
    result = await engine.run(events)
    return result.to_dict()


async def _paper_trade(
    *,
    token_id: str,
    strategy: str,
    best_bid: Decimal,
    bid_size: Decimal,
    best_ask: Decimal,
    ask_size: Decimal,
    order_size: Decimal,
    min_edge: Decimal,
    initial_cash: Decimal,
) -> dict[str, object]:
    book = LocalOrderBook(token_id=token_id)
    book.apply_snapshot(
        bids=((best_bid, bid_size),),
        asks=((best_ask, ask_size),),
    )
    market_event = cli_support.local_market_event(token_id)
    strategy_instance = cli_support.build_research_strategy(
        strategy=strategy,
        order_size=order_size,
        min_edge=min_edge,
    )
    intents = await strategy_instance.on_market_event(
        market_event,
        StrategyContext(orderbook=book),
    )
    if not intents:
        return {
            "book": book.snapshot(),
            "intents": [],
            "orders": [],
            "portfolio": None,
            "status": "ok",
        }

    ledger = PositionLedger(cash=initial_cash)
    risk_engine = RiskEngine(
        limits=RiskLimits(
            max_order_notional=initial_cash,
            max_position_per_token=order_size,
            max_position_per_market=order_size,
        )
    )
    broker = PaperBroker(ledger=ledger)
    orders = []
    for intent in intents:
        decision = risk_engine.evaluate(
            intent,
            RiskContext(
                trading_mode=TradingMode.PAPER,
                current_position=ledger.get(intent.token_id).size,
                current_market_position=ledger.get(intent.token_id).size,
                market_data_age_ms=0,
                edge=min_edge,
            ),
        )
        if not decision.approved or decision.adjusted_size is None:
            orders.append(
                {
                    "intent": cli_support.intent_to_dict(intent),
                    "risk_decision": {
                        "approved": decision.approved,
                        "reason": decision.reason,
                    },
                }
            )
            continue
        approved = ApprovedOrderIntent(
            intent=intent,
            approved_size=decision.adjusted_size,
            risk_reason=decision.reason,
            approved_at=datetime.now(UTC),
        )
        order = broker.submit_limit_order(approved, book)
        orders.append(
            {
                "intent": cli_support.intent_to_dict(intent),
                "order": order.to_dict(),
                "risk_decision": {
                    "approved": decision.approved,
                    "reason": decision.reason,
                },
            }
        )

    mark_price = book.mid or best_bid
    pnl = calculate_portfolio_pnl(ledger, {token_id: mark_price})
    return {
        "book": book.snapshot(),
        "cash": str(ledger.cash),
        "orders": orders,
        "portfolio": {
            "gross_market_value": str(pnl.gross_market_value),
            "realized_pnl": str(pnl.realized_pnl),
            "total_equity": str(pnl.total_equity),
            "unrealized_pnl": str(pnl.unrealized_pnl),
        },
        "positions": {
            position_token_id: {
                "avg_price": str(position.avg_price),
                "size": str(position.size),
            }
            for position_token_id, position in ledger.positions.items()
        },
        "status": "ok",
    }
