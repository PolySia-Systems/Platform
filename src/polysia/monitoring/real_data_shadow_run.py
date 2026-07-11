from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal, Protocol

from polysia.adapters.polymarket.public import (
    PolymarketPublicAdapter,
    PolymarketPublicAdapterError,
)
from polysia.adapters.polymarket.stream import MarketStream, MarketStreamConfig, MarketStreamError
from polysia.bus.events import MarketDataEvent
from polysia.bus.in_memory_bus import InMemoryEventBus
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.market import MarketDetails, MarketSummary
from polysia.execution.intents import ApprovedOrderIntent
from polysia.execution.order_state import OrderStatus
from polysia.execution.paper_broker import PaperBroker
from polysia.orderbook.book import LocalOrderBook
from polysia.orderbook.builder import BookBuilder
from polysia.orderbook.validators import OrderBookValidationError
from polysia.portfolio.pnl import calculate_portfolio_pnl
from polysia.portfolio.positions import PositionLedger
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.strategies.base import BaseStrategy, StrategyContext
from polysia.strategies.passive_market_maker import PassiveMarketMakerStrategy
from polysia.strategies.stale_price import StalePriceStrategy

Clock = Callable[[], datetime]
EventSource = Callable[[str, int], Awaitable[tuple[tuple[MarketDataEvent, ...], tuple[str, ...]]]]
RealDataShadowStatus = Literal[
    "REAL_DATA_SHADOW_HEALTHY",
    "REAL_DATA_SHADOW_WARNING",
    "REAL_DATA_SHADOW_FAILED",
]
ReportFormat = Literal["json", "markdown"]
StrategyName = Literal["stale-price", "passive-market-maker"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PublicMarketSelector(Protocol):
    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        """Read one market by slug."""

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
        """Search public markets."""


@dataclass(frozen=True, slots=True)
class RealDataShadowRunConfig:
    settings: AppSettings
    project_root: Path
    output_dir: Path
    market_slug: str | None = None
    auto_btc_5m: bool = False
    max_events: int = 100
    strategy: StrategyName = "stale-price"

    def __post_init__(self) -> None:
        if self.max_events <= 0:
            raise ValueError("max_events must be positive")
        if self.market_slug is None and not self.auto_btc_5m:
            raise ValueError("--market-slug or --auto-btc-5m is required")


@dataclass(frozen=True, slots=True)
class RealDataShadowMetrics:
    selected_market_slug: str
    selected_token_configured: bool
    event_count: int
    orderbook_updates: int
    orderbook_freshness_age_ms: int | None
    stream_health: str
    stream_warning_count: int
    strategy_intent_count: int
    risk_approval_count: int
    risk_denial_count: int
    paper_order_count: int
    paper_fill_count: int
    paper_position: Decimal
    paper_realized_pnl: Decimal
    paper_unrealized_pnl: Decimal
    paper_total_pnl: Decimal
    latency_average_ms: Decimal
    latency_p95_ms: Decimal
    latency_p99_ms: Decimal
    live_broker_used: bool = False

    def to_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "event_count": self.event_count,
            "latency_average_ms": _decimal_to_str(self.latency_average_ms),
            "latency_p95_ms": _decimal_to_str(self.latency_p95_ms),
            "latency_p99_ms": _decimal_to_str(self.latency_p99_ms),
            "live_broker_used": self.live_broker_used,
            "orderbook_freshness_age_ms": self.orderbook_freshness_age_ms,
            "orderbook_updates": self.orderbook_updates,
            "paper_fill_count": self.paper_fill_count,
            "paper_order_count": self.paper_order_count,
            "paper_position": _decimal_to_str(self.paper_position),
            "paper_realized_pnl": _decimal_to_str(self.paper_realized_pnl),
            "paper_total_pnl": _decimal_to_str(self.paper_total_pnl),
            "paper_unrealized_pnl": _decimal_to_str(self.paper_unrealized_pnl),
            "risk_approval_count": self.risk_approval_count,
            "risk_denial_count": self.risk_denial_count,
            "selected_market_slug": self.selected_market_slug,
            "selected_token_configured": self.selected_token_configured,
            "strategy_intent_count": self.strategy_intent_count,
            "stream_health": self.stream_health,
            "stream_warning_count": self.stream_warning_count,
        }


@dataclass(frozen=True, slots=True)
class RealDataShadowRunReport:
    timestamp: datetime
    final_result: RealDataShadowStatus
    strategy: StrategyName
    metrics: RealDataShadowMetrics
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    no_live_trading_statement: str
    events: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "events": list(self.events),
            "final_result": self.final_result,
            "metrics": self.metrics.to_dict(),
            "no_live_trading_statement": self.no_live_trading_statement,
            "reasons": list(self.reasons),
            "strategy": self.strategy,
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


async def build_real_data_shadow_run(
    config: RealDataShadowRunConfig,
    *,
    public_adapter: PublicMarketSelector | None = None,
    event_source: EventSource | None = None,
    risk_engine: RiskEngine | None = None,
    clock: Clock = _utc_now,
) -> RealDataShadowRunReport:
    """Run a public-data, paper-only shadow simulation."""

    if config.settings.live_trading_enabled:
        return _failed_report(
            config=config,
            clock=clock,
            reason="LIVE_TRADING_ENABLED=true is forbidden for shadow-run-real-data.",
        )

    adapter = public_adapter or PolymarketPublicAdapter()
    try:
        market = await _select_market(config, adapter)
    except (PolymarketPublicAdapterError, ValueError) as error:
        return _failed_report(config=config, clock=clock, reason=str(error))

    token_id = _first_token_id(market)
    if token_id is None:
        return _failed_report(
            config=config,
            clock=clock,
            reason="Selected market does not expose an outcome token id.",
        )

    source = event_source or _collect_public_stream_events
    try:
        events, stream_warnings = await source(token_id, config.max_events)
    except (MarketStreamError, OSError, TimeoutError, ValueError) as error:
        events = ()
        stream_warnings = (f"Public stream ended with warning: {type(error).__name__}.",)

    strategy = _strategy_from_name(config.strategy)
    return await _simulate_events(
        config=config,
        market=market,
        selected_token=token_id,
        events=events[: config.max_events],
        strategy=strategy,
        risk_engine=risk_engine or RiskEngine(),
        stream_warnings=stream_warnings,
        clock=clock,
    )


def write_real_data_shadow_run_reports(
    report: RealDataShadowRunReport,
    output_dir: Path,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in ("json", "markdown"):
        path = output_dir / real_data_shadow_run_filename(report_format)
        path.write_text(
            f"{render_real_data_shadow_run(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)
    events_path = output_dir / "shadow-run-real-data-events.jsonl"
    events_path.write_text(render_real_data_shadow_run_events_jsonl(report), encoding="utf-8")
    artifacts["events"] = str(events_path)
    return artifacts


def render_real_data_shadow_run(
    report: RealDataShadowRunReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return render_real_data_shadow_run_markdown(report)


def render_real_data_shadow_run_markdown(report: RealDataShadowRunReport) -> str:
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    reasons = "\n".join(f"- {reason}" for reason in report.reasons) or "- None"
    return "\n".join(
        (
            "# Polymarket Real Data Shadow Run",
            "",
            f"- Final result: {report.final_result}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Strategy: {report.strategy}",
            f"- Event count: {report.metrics.event_count}",
            "",
            "## Metrics",
            "",
            _table(report.metrics.to_dict()),
            "",
            "## Reasons",
            "",
            reasons,
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Live Trading",
            "",
            report.no_live_trading_statement,
            "",
        )
    )


def render_real_data_shadow_run_events_jsonl(report: RealDataShadowRunReport) -> str:
    return "\n".join(json.dumps(event, sort_keys=True) for event in report.events)


def real_data_shadow_run_filename(report_format: ReportFormat) -> str:
    return {
        "json": "shadow-run-real-data.json",
        "markdown": "shadow-run-real-data.md",
    }[report_format]


async def _select_market(
    config: RealDataShadowRunConfig,
    adapter: PublicMarketSelector,
) -> MarketDetails:
    if config.market_slug is not None:
        return await adapter.get_market_by_slug(config.market_slug)

    markets = await adapter.search_markets("Bitcoin Up or Down 5m", page_size=30)
    candidates = [market for market in markets if _is_active_btc_5m_candidate(market)]
    candidates.sort(key=lambda market: market.end_date or datetime.max.replace(tzinfo=UTC))
    for candidate in candidates:
        if candidate.slug:
            return await adapter.get_market_by_slug(candidate.slug)
    raise ValueError("Could not auto-select an active BTC Up/Down 5m market.")


async def _collect_public_stream_events(
    token_id: str,
    max_events: int,
) -> tuple[tuple[MarketDataEvent, ...], tuple[str, ...]]:
    bus = InMemoryEventBus()
    subscription = bus.subscribe(max_queue_size=max(1000, max_events))
    stream = MarketStream(
        bus=bus,
        config=MarketStreamConfig(
            token_ids=(token_id,),
            stale_after=timedelta(seconds=15),
            max_reconnects=0,
        ),
    )
    task = asyncio.create_task(stream.run(max_events=max_events))
    events: list[MarketDataEvent] = []
    warnings: list[str] = []
    try:
        while len(events) < max_events:
            if task.done():
                break
            try:
                events.append(await asyncio.wait_for(subscription.__anext__(), timeout=20))
            except TimeoutError:
                warnings.append("Public stream timed out before max-events was reached.")
                break
        if task.done():
            try:
                await task
            except (MarketStreamError, OSError) as error:
                warnings.append(f"Public stream ended with warning: {type(error).__name__}.")
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError, MarketStreamError, OSError):
            await task
        await subscription.close()
        await bus.close()
    return tuple(events), tuple(warnings)


async def _simulate_events(
    *,
    config: RealDataShadowRunConfig,
    market: MarketDetails,
    selected_token: str,
    events: tuple[MarketDataEvent, ...],
    strategy: BaseStrategy,
    risk_engine: RiskEngine,
    stream_warnings: tuple[str, ...],
    clock: Clock,
) -> RealDataShadowRunReport:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger, clock=clock)
    builder = BookBuilder(allow_crossed=True)
    warnings = list(stream_warnings)
    reasons: list[str] = []
    orderbook_updates = 0
    strategy_intents = 0
    risk_approved = 0
    risk_denied = 0
    latencies: list[Decimal] = []
    final_book: LocalOrderBook | None = None
    sanitized_events: list[dict[str, object]] = []

    for index, event in enumerate(events):
        started = clock()
        try:
            book = builder.apply(event)
        except OrderBookValidationError as error:
            warnings.append(f"Orderbook update skipped: {type(error).__name__}.")
            continue
        final_book = book
        orderbook_updates += 1
        context = StrategyContext(
            orderbook=book,
            latest_market=market,
            positions={token: position.size for token, position in ledger.positions.items()},
            clock=clock,
        )
        intents = await strategy.on_market_event(event, context)
        strategy_intents += len(intents)
        for intent in intents:
            position = ledger.get(intent.token_id)
            decision = risk_engine.evaluate(
                intent,
                RiskContext(
                    trading_mode=TradingMode.PAPER,
                    live_trading_enabled=False,
                    current_position=position.size,
                    current_market_position=position.size,
                    daily_pnl=ledger.realized_pnl,
                    open_orders_count=_open_paper_order_count(broker),
                    market_data_age_ms=_event_age_ms(event, clock()),
                ),
            )
            if decision.approved and decision.adjusted_size is not None:
                risk_approved += 1
                broker.submit_limit_order(
                    ApprovedOrderIntent(
                        intent=intent,
                        approved_size=decision.adjusted_size,
                        risk_reason=decision.reason,
                        approved_at=clock(),
                    ),
                    book,
                )
            else:
                risk_denied += 1
        latencies.append(_elapsed_ms(started, clock()))
        sanitized_events.append(_sanitized_event(event, index=index))

    mark_price = (final_book.mid if final_book is not None else None) or Decimal("0")
    pnl = calculate_portfolio_pnl(ledger, {selected_token: mark_price})
    metrics = RealDataShadowMetrics(
        selected_market_slug=market.slug or config.market_slug or "selected-public-market",
        selected_token_configured=True,
        event_count=len(events),
        orderbook_updates=orderbook_updates,
        orderbook_freshness_age_ms=_freshness_ms(events[-1], clock()) if events else None,
        stream_health="public_stream" if events else "public_stream_warning",
        stream_warning_count=len(warnings),
        strategy_intent_count=strategy_intents,
        risk_approval_count=risk_approved,
        risk_denial_count=risk_denied,
        paper_order_count=len(broker.orders),
        paper_fill_count=len(broker.fills),
        paper_position=ledger.get(selected_token).size,
        paper_realized_pnl=pnl.realized_pnl,
        paper_unrealized_pnl=pnl.unrealized_pnl,
        paper_total_pnl=pnl.realized_pnl + pnl.unrealized_pnl,
        latency_average_ms=_average(tuple(latencies)),
        latency_p95_ms=_percentile(tuple(latencies), Decimal("0.95")),
        latency_p99_ms=_percentile(tuple(latencies), Decimal("0.99")),
        live_broker_used=False,
    )
    final_result, result_reasons = _classify(metrics, warnings)
    reasons.extend(result_reasons)
    return RealDataShadowRunReport(
        timestamp=clock(),
        final_result=final_result,
        strategy=config.strategy,
        metrics=metrics,
        warnings=tuple(warnings),
        reasons=tuple(reasons),
        no_live_trading_statement=(
            "No live broker, live submit, live cancel, retry, loop, or market-making "
            "path was used; paper broker only."
        ),
        events=tuple(sanitized_events),
    )


def _failed_report(
    *,
    config: RealDataShadowRunConfig,
    clock: Clock,
    reason: str,
) -> RealDataShadowRunReport:
    metrics = RealDataShadowMetrics(
        selected_market_slug=config.market_slug or "unselected",
        selected_token_configured=False,
        event_count=0,
        orderbook_updates=0,
        orderbook_freshness_age_ms=None,
        stream_health="not_started",
        stream_warning_count=0,
        strategy_intent_count=0,
        risk_approval_count=0,
        risk_denial_count=0,
        paper_order_count=0,
        paper_fill_count=0,
        paper_position=Decimal("0"),
        paper_realized_pnl=Decimal("0"),
        paper_unrealized_pnl=Decimal("0"),
        paper_total_pnl=Decimal("0"),
        latency_average_ms=Decimal("0"),
        latency_p95_ms=Decimal("0"),
        latency_p99_ms=Decimal("0"),
        live_broker_used=False,
    )
    return RealDataShadowRunReport(
        timestamp=clock(),
        final_result="REAL_DATA_SHADOW_FAILED",
        strategy=config.strategy,
        metrics=metrics,
        warnings=(),
        reasons=(reason,),
        no_live_trading_statement="No live trading path was touched.",
        events=(),
    )


def _classify(
    metrics: RealDataShadowMetrics,
    warnings: list[str],
) -> tuple[RealDataShadowStatus, tuple[str, ...]]:
    if metrics.live_broker_used:
        return ("REAL_DATA_SHADOW_FAILED", ("live broker usage was detected",))
    if metrics.event_count == 0:
        return ("REAL_DATA_SHADOW_WARNING", ("no public stream events were processed",))
    if metrics.orderbook_updates == 0:
        return ("REAL_DATA_SHADOW_WARNING", ("no orderbook updates were applied",))
    if warnings:
        return ("REAL_DATA_SHADOW_WARNING", ("public data shadow run completed with warnings",))
    return (
        "REAL_DATA_SHADOW_HEALTHY",
        ("public data, orderbook, strategy, risk, and paper broker were exercised",),
    )


def _strategy_from_name(name: StrategyName) -> BaseStrategy:
    if name == "stale-price":
        return StalePriceStrategy()
    if name == "passive-market-maker":
        return PassiveMarketMakerStrategy()
    raise ValueError(f"Unsupported strategy: {name}")


def _first_token_id(market: MarketDetails) -> str | None:
    for outcome in market.outcomes:
        if outcome.token_id:
            return outcome.token_id
    return None


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


def _open_paper_order_count(broker: PaperBroker) -> int:
    return sum(
        1
        for order in broker.orders.values()
        if order.status in {OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}
    )


def _event_age_ms(event: MarketDataEvent, now: datetime) -> int:
    timestamp = event.exchange_ts or event.received_at
    return max(0, int((now - timestamp).total_seconds() * 1000))


def _freshness_ms(event: MarketDataEvent, now: datetime) -> int:
    return _event_age_ms(event, now)


def _elapsed_ms(started: datetime, ended: datetime) -> Decimal:
    elapsed = Decimal(str(max(0.0, (ended - started).total_seconds() * 1000)))
    return elapsed.quantize(Decimal("0.0001"))


def _sanitized_event(event: MarketDataEvent, *, index: int) -> dict[str, object]:
    return {
        "event_index": index,
        "event_type": event.event_type,
        "exchange_ts": event.exchange_ts.isoformat() if event.exchange_ts else None,
        "received_at": event.received_at.isoformat(),
        "selected_token": True,
    }


def _average(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        return Decimal("0")
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(Decimal("0.0001"))


def _percentile(values: tuple[Decimal, ...], percentile: Decimal) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = tuple(sorted(values))
    if len(ordered) == 1:
        return ordered[0]
    rank = (Decimal(len(ordered) - 1) * percentile).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return ordered[int(rank)]


def _decimal_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _table(values: Mapping[str, object]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in sorted(values.items()))
    return "\n".join(("| Metric | Value |", "| --- | --- |", rows))


__all__ = [
    "RealDataShadowMetrics",
    "RealDataShadowRunConfig",
    "RealDataShadowRunReport",
    "build_real_data_shadow_run",
    "real_data_shadow_run_filename",
    "render_real_data_shadow_run",
    "render_real_data_shadow_run_events_jsonl",
    "render_real_data_shadow_run_markdown",
    "write_real_data_shadow_run_reports",
]
