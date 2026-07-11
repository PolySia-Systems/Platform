from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pm_trader.bus.events import MarketDataEvent
from pm_trader.config.settings import TradingMode
from pm_trader.execution.intents import ApprovedOrderIntent
from pm_trader.execution.order_state import OrderStatus, PaperOrder
from pm_trader.execution.paper_broker import PaperBroker
from pm_trader.orderbook.book import LocalOrderBook
from pm_trader.orderbook.builder import BookBuilder
from pm_trader.portfolio.pnl import calculate_portfolio_pnl
from pm_trader.portfolio.positions import PositionLedger
from pm_trader.risk.checks import RiskContext, RiskEngine
from pm_trader.risk.limits import RiskLimits
from pm_trader.strategies.base import BaseStrategy, StrategyContext


class ReplayError(RuntimeError):
    """Raised when replay input cannot be parsed or simulated."""


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Risk and portfolio settings for a deterministic paper backtest."""

    initial_cash: Decimal = Decimal("100")
    max_order_notional: Decimal = Decimal("10")
    max_position_per_token: Decimal = Decimal("100")
    max_position_per_market: Decimal = Decimal("250")
    max_open_orders: int = 20

    def __post_init__(self) -> None:
        if self.initial_cash <= Decimal("0"):
            raise ValueError("initial_cash must be positive")
        if self.max_order_notional <= Decimal("0"):
            raise ValueError("max_order_notional must be positive")
        if self.max_position_per_token < Decimal("0"):
            raise ValueError("max_position_per_token must not be negative")
        if self.max_position_per_market < Decimal("0"):
            raise ValueError("max_position_per_market must not be negative")
        if self.max_open_orders < 0:
            raise ValueError("max_open_orders must not be negative")


@dataclass(frozen=True, slots=True)
class BacktestOrderRecord:
    event_index: int
    token_id: str
    intent: dict[str, object]
    risk_decision: dict[str, object]
    order: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """JSON-friendly replay result."""

    events_processed: int
    intents_generated: int
    risk_rejections: int
    orders_created: int
    fills_created: int
    rejected_orders: int
    final_cash: Decimal
    realized_pnl: Decimal
    portfolio: dict[str, object]
    positions: dict[str, dict[str, str]]
    last_books: dict[str, dict[str, object]]
    orders: tuple[BacktestOrderRecord, ...] = field(default_factory=tuple)
    audit_log: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_log": list(self.audit_log),
            "events_processed": self.events_processed,
            "fills_created": self.fills_created,
            "final_cash": str(self.final_cash),
            "intents_generated": self.intents_generated,
            "last_books": self.last_books,
            "orders": [
                {
                    "event_index": record.event_index,
                    "intent": record.intent,
                    "order": record.order,
                    "risk_decision": record.risk_decision,
                    "token_id": record.token_id,
                }
                for record in self.orders
            ],
            "orders_created": self.orders_created,
            "portfolio": self.portfolio,
            "positions": self.positions,
            "realized_pnl": str(self.realized_pnl),
            "rejected_orders": self.rejected_orders,
            "risk_rejections": self.risk_rejections,
            "status": "ok",
        }


class BacktestEngine:
    """Replay market-data events through a strategy, risk engine, and paper broker."""

    def __init__(
        self,
        *,
        strategy: BaseStrategy,
        config: BacktestConfig | None = None,
        allow_crossed_books: bool = False,
    ) -> None:
        self._strategy = strategy
        self._config = config or BacktestConfig()
        self._builder = BookBuilder(allow_crossed=allow_crossed_books)
        self._ledger = PositionLedger(cash=self._config.initial_cash)
        self._broker = PaperBroker(ledger=self._ledger)
        self._risk_engine = RiskEngine(
            limits=RiskLimits(
                max_order_notional=self._config.max_order_notional,
                max_position_per_token=self._config.max_position_per_token,
                max_position_per_market=self._config.max_position_per_market,
                max_open_orders=self._config.max_open_orders,
            )
        )
        self._latest_books: dict[str, LocalOrderBook] = {}

    async def run(self, events: Iterable[MarketDataEvent]) -> BacktestResult:
        orders: list[BacktestOrderRecord] = []
        events_processed = 0
        intents_generated = 0
        risk_rejections = 0

        for event_index, event in enumerate(events):
            events_processed += 1
            book = self._builder.apply(event)
            self._latest_books[event.token_id] = book
            intents = await self._strategy.on_market_event(
                event,
                StrategyContext(
                    orderbook=book,
                    positions={
                        token_id: position.size
                        for token_id, position in self._ledger.positions.items()
                    },
                ),
            )
            intents_generated += len(intents)

            for intent in intents:
                decision = self._risk_engine.evaluate(
                    intent,
                    RiskContext(
                        trading_mode=TradingMode.PAPER,
                        current_position=self._ledger.get(intent.token_id).size,
                        current_market_position=self._ledger.get(intent.token_id).size,
                        daily_pnl=self._ledger.realized_pnl,
                        open_orders_count=_open_order_count(self._broker.orders.values()),
                        market_data_age_ms=0,
                    ),
                )
                if not decision.approved or decision.adjusted_size is None:
                    risk_rejections += 1
                    orders.append(
                        BacktestOrderRecord(
                            event_index=event_index,
                            token_id=intent.token_id,
                            intent=_intent_to_dict(intent),
                            risk_decision={
                                "approved": decision.approved,
                                "reason": decision.reason,
                            },
                        )
                    )
                    continue

                approved = ApprovedOrderIntent(
                    intent=intent,
                    approved_size=decision.adjusted_size,
                    risk_reason=decision.reason,
                    approved_at=event.received_at,
                )
                paper_order = self._broker.submit_limit_order(approved, book)
                orders.append(
                    BacktestOrderRecord(
                        event_index=event_index,
                        token_id=intent.token_id,
                        intent=_intent_to_dict(intent),
                        risk_decision={
                            "approved": decision.approved,
                            "reason": decision.reason,
                        },
                        order=paper_order.to_dict(),
                    )
                )

        return self._build_result(
            events_processed=events_processed,
            intents_generated=intents_generated,
            risk_rejections=risk_rejections,
            orders=tuple(orders),
        )

    def _build_result(
        self,
        *,
        events_processed: int,
        intents_generated: int,
        risk_rejections: int,
        orders: tuple[BacktestOrderRecord, ...],
    ) -> BacktestResult:
        mark_prices: dict[str, Decimal] = {}
        for token_id, book in self._latest_books.items():
            mark_price = _mark_price(book)
            if mark_price is not None:
                mark_prices[token_id] = mark_price
        pnl = calculate_portfolio_pnl(self._ledger, mark_prices)
        order_values = list(self._broker.orders.values())
        return BacktestResult(
            events_processed=events_processed,
            intents_generated=intents_generated,
            risk_rejections=risk_rejections,
            orders_created=len(order_values),
            fills_created=len(self._broker.fills),
            rejected_orders=sum(
                1 for order in order_values if order.status == OrderStatus.REJECTED
            ),
            final_cash=self._ledger.cash,
            realized_pnl=self._ledger.realized_pnl,
            portfolio={
                "cash": str(pnl.cash),
                "gross_market_value": str(pnl.gross_market_value),
                "realized_pnl": str(pnl.realized_pnl),
                "total_equity": str(pnl.total_equity),
                "unrealized_pnl": str(pnl.unrealized_pnl),
            },
            positions={
                token_id: {
                    "avg_price": str(position.avg_price),
                    "size": str(position.size),
                }
                for token_id, position in self._ledger.positions.items()
            },
            last_books={
                token_id: book.snapshot() for token_id, book in self._latest_books.items()
            },
            orders=orders,
            audit_log=tuple(self._broker.audit_log),
        )


def load_market_data_events_jsonl(
    path: Path,
    *,
    max_events: int | None = None,
) -> list[MarketDataEvent]:
    events: list[MarketDataEvent] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ReplayError(f"could not read replay file: {path}") from error

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw_event = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise ReplayError(f"invalid JSON on line {line_number}") from error
        if not isinstance(raw_event, dict):
            raise ReplayError(f"line {line_number} must be a JSON object")
        events.append(market_data_event_from_dict(raw_event))
        if max_events is not None and len(events) >= max_events:
            break

    return events


def market_data_event_from_dict(data: Mapping[str, Any]) -> MarketDataEvent:
    source = data.get("source", "polymarket")
    if source != "polymarket":
        raise ReplayError(f"unsupported event source {source!r}")
    event_type = _required_text(data, "event_type")
    token_id = _required_text(data, "token_id")
    return MarketDataEvent(
        source="polymarket",
        event_type=event_type,
        token_id=token_id,
        received_at=_parse_datetime(data.get("received_at"), "received_at"),
        exchange_ts=_parse_optional_datetime(data.get("exchange_ts"), "exchange_ts"),
        payload=_dict_field(data.get("payload"), "payload"),
        raw_payload=_dict_field(data.get("raw_payload", {}), "raw_payload"),
    )


def _intent_to_dict(intent: Any) -> dict[str, object]:
    return {
        "confidence": str(intent.confidence),
        "price": str(intent.price),
        "reason": intent.reason,
        "side": intent.side,
        "size": str(intent.size),
        "strategy_id": intent.strategy_id,
        "token_id": intent.token_id,
    }


def _open_order_count(orders: Iterable[PaperOrder]) -> int:
    open_statuses = {
        OrderStatus.ACCEPTED,
        OrderStatus.NEW,
        OrderStatus.PARTIALLY_FILLED,
    }
    return sum(1 for order in orders if order.status in open_statuses)


def _mark_price(book: LocalOrderBook) -> Decimal | None:
    return book.mid or book.best_bid or book.best_ask


def _required_text(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value:
        raise ReplayError(f"event field {field_name!r} must be a non-empty string")
    return value


def _dict_field(value: object, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ReplayError(f"event field {field_name!r} must be an object")
    return value


def _parse_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReplayError(f"event field {field_name!r} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReplayError(f"event field {field_name!r} is not a valid ISO datetime") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, field_name)
