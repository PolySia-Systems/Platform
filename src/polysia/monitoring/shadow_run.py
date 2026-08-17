from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from pathlib import Path
from typing import Literal, Protocol

from polysia.bus.events import MarketDataEvent
from polysia.config.settings import AppSettings, TradingMode
from polysia.control.models import (
    DesiredStateRevision,
    ObservedOperationalState,
    ReconciliationStatus,
    RuntimeObservation,
    StrategyControlKey,
)
from polysia.control.shadow_runtime import STALE_PRICE_SHADOW_TARGET, ShadowIntentBoundary
from polysia.execution.intents import ApprovedOrderIntent
from polysia.execution.paper_broker import PaperBroker
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.pnl import calculate_portfolio_pnl
from polysia.portfolio.positions import PositionLedger
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.strategies.base import BaseStrategy, StrategyContext
from polysia.strategies.passive_market_maker import PassiveMarketMakerStrategy
from polysia.strategies.stale_price import StalePriceStrategy

Clock = Callable[[], datetime]
GitStatusReader = Callable[[Path], str]
ReportFormat = Literal["json", "markdown", "html"]
ShadowClassification = Literal[
    "SHADOW_HEALTHY",
    "SHADOW_PAUSED",
    "SHADOW_DEGRADED",
    "SHADOW_FAILED",
]


class ShadowControlStore(Protocol):
    def current_desired(
        self,
        key: StrategyControlKey,
    ) -> DesiredStateRevision | None: ...

    def record_runtime_observation(self, observation: RuntimeObservation) -> None: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ShadowRunConfig:
    settings: AppSettings
    project_root: Path
    duration_minutes: int = 1
    market_slug: str | None = None
    token_id: str | None = None
    strategy: str = "stale-price"
    sample_interval_seconds: int = 10
    max_events: int | None = None
    require_clean_git: bool = False

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        if self.sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")
        if self.max_events is not None and self.max_events <= 0:
            raise ValueError("max_events must be positive when provided")
        if not self.strategy:
            raise ValueError("strategy must not be empty")


@dataclass(frozen=True, slots=True)
class ShadowRunSample:
    timestamp: datetime
    event_index: int
    best_bid: Decimal | None
    best_ask: Decimal | None
    spread: Decimal | None
    mid: Decimal | None
    microprice: Decimal | None
    strategy_intents: int
    risk_approved: int
    risk_rejected: int
    paper_orders: int
    paper_fills: int
    paper_position: Decimal
    paper_total_pnl: Decimal
    decision_latency_ms: Decimal

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "best_ask": _optional_decimal(self.best_ask),
            "best_bid": _optional_decimal(self.best_bid),
            "decision_latency_ms": _decimal_to_str(self.decision_latency_ms),
            "event_index": self.event_index,
            "microprice": _optional_decimal(self.microprice),
            "mid": _optional_decimal(self.mid),
            "paper_fills": self.paper_fills,
            "paper_orders": self.paper_orders,
            "paper_position": _decimal_to_str(self.paper_position),
            "paper_total_pnl": _decimal_to_str(self.paper_total_pnl),
            "risk_approved": self.risk_approved,
            "risk_rejected": self.risk_rejected,
            "spread": _optional_decimal(self.spread),
            "strategy_intents": self.strategy_intents,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ShadowRunMetrics:
    start_time: datetime
    end_time: datetime
    duration_seconds: Decimal
    selected_market: str
    selected_token: str
    event_count: int
    event_rate_per_second: Decimal
    stream_health: str
    reconnect_count: int
    stale_event_count: int
    orderbook_updates: int
    best_bid_observations: int
    best_ask_observations: int
    spread_observations: int
    mid_observations: int
    microprice_observations: int
    strategy_intent_count: int
    risk_approval_count: int
    risk_rejection_count: int
    paper_order_count: int
    paper_fill_count: int
    paper_position: Decimal
    paper_realized_pnl: Decimal
    paper_unrealized_pnl: Decimal
    paper_total_pnl: Decimal
    max_drawdown: Decimal
    latency_average_ms: Decimal
    latency_p95_ms: Decimal
    latency_p99_ms: Decimal
    live_broker_used: bool = False

    def to_dict(self) -> dict[str, bool | int | str]:
        return {
            "best_ask_observations": self.best_ask_observations,
            "best_bid_observations": self.best_bid_observations,
            "duration_seconds": _decimal_to_str(self.duration_seconds),
            "end_time": self.end_time.isoformat(),
            "event_count": self.event_count,
            "event_rate_per_second": _decimal_to_str(self.event_rate_per_second),
            "latency_average_ms": _decimal_to_str(self.latency_average_ms),
            "latency_p95_ms": _decimal_to_str(self.latency_p95_ms),
            "latency_p99_ms": _decimal_to_str(self.latency_p99_ms),
            "live_broker_used": self.live_broker_used,
            "max_drawdown": _decimal_to_str(self.max_drawdown),
            "microprice_observations": self.microprice_observations,
            "mid_observations": self.mid_observations,
            "orderbook_updates": self.orderbook_updates,
            "paper_fill_count": self.paper_fill_count,
            "paper_order_count": self.paper_order_count,
            "paper_position": _decimal_to_str(self.paper_position),
            "paper_realized_pnl": _decimal_to_str(self.paper_realized_pnl),
            "paper_total_pnl": _decimal_to_str(self.paper_total_pnl),
            "paper_unrealized_pnl": _decimal_to_str(self.paper_unrealized_pnl),
            "reconnect_count": self.reconnect_count,
            "risk_approval_count": self.risk_approval_count,
            "risk_rejection_count": self.risk_rejection_count,
            "selected_market": self.selected_market,
            "selected_token_configured": bool(self.selected_token),
            "spread_observations": self.spread_observations,
            "stale_event_count": self.stale_event_count,
            "start_time": self.start_time.isoformat(),
            "strategy_intent_count": self.strategy_intent_count,
            "stream_health": self.stream_health,
        }


@dataclass(frozen=True, slots=True)
class ShadowRunReport:
    timestamp: datetime
    classification: ShadowClassification
    reasons: tuple[str, ...]
    strategy: str
    metrics: ShadowRunMetrics
    samples: tuple[ShadowRunSample, ...]
    operational_state: ObservedOperationalState = ObservedOperationalState.UNKNOWN
    control_revision: int = 0
    control_reconciliation_status: ReconciliationStatus = ReconciliationStatus.PENDING

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "metrics": self.metrics.to_dict(),
            "operational_state": self.operational_state.value,
            "reasons": list(self.reasons),
            "samples": [sample.to_dict() for sample in self.samples],
            "strategy": self.strategy,
            "control_reconciliation_status": self.control_reconciliation_status.value,
            "control_revision": self.control_revision,
            "timestamp": self.timestamp.isoformat(),
        }


async def build_shadow_run(
    config: ShadowRunConfig,
    *,
    clock: Clock = utc_now,
    git_status_reader: GitStatusReader | None = None,
    risk_engine: RiskEngine | None = None,
    control_store: ShadowControlStore | None = None,
) -> ShadowRunReport:
    """Build one deterministic paper-only shadow-run report."""

    clean_git_error = _clean_git_error(
        config.project_root.resolve(),
        require_clean_git=config.require_clean_git,
        git_status_reader=git_status_reader,
    )
    if clean_git_error is not None:
        metrics = _empty_metrics(config, start=clock(), stream_health="blocked")
        return ShadowRunReport(
            timestamp=clock(),
            classification="SHADOW_FAILED",
            reasons=(clean_git_error,),
            strategy=config.strategy,
            metrics=metrics,
            samples=(),
        )

    if config.settings.live_trading_enabled:
        metrics = _empty_metrics(config, start=clock(), stream_health="blocked")
        return ShadowRunReport(
            timestamp=clock(),
            classification="SHADOW_FAILED",
            reasons=("LIVE_TRADING_ENABLED=true is forbidden for shadow-run.",),
            strategy=config.strategy,
            metrics=metrics,
            samples=(),
        )

    try:
        strategy = _strategy_from_name(config.strategy)
    except ValueError as error:
        metrics = _empty_metrics(config, start=clock(), stream_health="blocked")
        return ShadowRunReport(
            timestamp=clock(),
            classification="SHADOW_FAILED",
            reasons=(str(error),),
            strategy=config.strategy,
            metrics=metrics,
            samples=(),
        )

    controlled_target = (
        strategy.strategy_id == STALE_PRICE_SHADOW_TARGET.strategy_id
        and getattr(strategy, "strategy_version", None)
        == STALE_PRICE_SHADOW_TARGET.strategy_version
    )
    operational_boundary: ShadowIntentBoundary | None = None
    observation: RuntimeObservation | None = None
    if controlled_target:
        operational_boundary = ShadowIntentBoundary(STALE_PRICE_SHADOW_TARGET, clock=clock)
        try:
            desired = (
                control_store.current_desired(STALE_PRICE_SHADOW_TARGET)
                if control_store is not None
                else None
            )
            observation = (
                operational_boundary.reconcile(desired)
                if desired is not None
                else operational_boundary.observe()
            )
            if control_store is not None:
                control_store.record_runtime_observation(observation)
        except Exception as error:
            metrics = _empty_metrics(config, start=clock(), stream_health="blocked")
            return ShadowRunReport(
                timestamp=clock(),
                classification="SHADOW_FAILED",
                reasons=(f"{type(error).__name__}: Shadow control reconciliation failed",),
                strategy=config.strategy,
                metrics=metrics,
                samples=(),
                operational_state=ObservedOperationalState.UNKNOWN,
                control_reconciliation_status=ReconciliationStatus.FAILED,
            )

    active_risk_engine = risk_engine or RiskEngine()
    start = clock()
    token_id = config.token_id or "shadow-token"
    samples = await _run_mocked_public_shadow(
        config,
        selected_token=token_id,
        strategy=strategy,
        risk_engine=active_risk_engine,
        start=start,
        clock=clock,
        operational_boundary=operational_boundary,
    )
    metrics = _metrics_from_samples(
        config,
        samples=samples,
        start=start,
        selected_token=token_id,
    )
    classification, reasons = classify_shadow_run(
        metrics,
        operational_state=(
            observation.observed_state
            if observation is not None
            else ObservedOperationalState.RUNNING
        ),
    )
    return ShadowRunReport(
        timestamp=clock(),
        classification=classification,
        reasons=reasons,
        strategy=config.strategy,
        metrics=metrics,
        samples=samples,
        operational_state=(
            observation.observed_state
            if observation is not None
            else ObservedOperationalState.RUNNING
        ),
        control_revision=observation.desired_revision if observation is not None else 0,
        control_reconciliation_status=(
            observation.reconciliation_status
            if observation is not None
            else ReconciliationStatus.SUCCESS
        ),
    )


def classify_shadow_run(
    metrics: ShadowRunMetrics,
    *,
    operational_state: ObservedOperationalState = ObservedOperationalState.RUNNING,
) -> tuple[ShadowClassification, tuple[str, ...]]:
    """Classify one shadow run conservatively."""

    if metrics.live_broker_used:
        return ("SHADOW_FAILED", ("live broker usage was detected",))
    if metrics.event_count == 0:
        return ("SHADOW_FAILED", ("no market events were observed",))
    if metrics.orderbook_updates == 0:
        return ("SHADOW_FAILED", ("local orderbook did not update",))
    if metrics.stale_event_count > 0:
        return ("SHADOW_DEGRADED", ("stale market events were observed",))
    if operational_state is ObservedOperationalState.PAUSED:
        if any(
            (
                metrics.strategy_intent_count,
                metrics.risk_approval_count,
                metrics.risk_rejection_count,
                metrics.paper_order_count,
                metrics.paper_fill_count,
            )
        ):
            return ("SHADOW_FAILED", ("PAUSED Shadow runtime produced downstream activity",))
        return (
            "SHADOW_PAUSED",
            ("runtime acknowledged PAUSED and suppressed every new strategy intent",),
        )
    if operational_state is ObservedOperationalState.UNKNOWN:
        return ("SHADOW_FAILED", ("Shadow operational state is unknown",))
    if metrics.strategy_intent_count == 0:
        return ("SHADOW_DEGRADED", ("strategy produced no paper intents",))
    if metrics.risk_approval_count == 0:
        return ("SHADOW_DEGRADED", ("risk engine approved no paper intents",))
    if metrics.paper_fill_count == 0:
        return ("SHADOW_DEGRADED", ("paper broker produced no fills",))
    return (
        "SHADOW_HEALTHY",
        ("mocked public shadow run exercised market data, strategy, risk, and paper fills",),
    )


def render_shadow_run_json(report: ShadowRunReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_shadow_run_markdown(report: ShadowRunReport) -> str:
    reasons = "\n".join(f"- {reason}" for reason in report.reasons) or "- None"
    metric_rows = "\n".join(
        f"| {key} | {value} |" for key, value in sorted(report.metrics.to_dict().items())
    )
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Shadow Run",
            "",
            f"- Classification: {report.classification}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Strategy: {report.strategy}",
            f"- Operational state: {report.operational_state.value}",
            f"- Control revision: {report.control_revision}",
            f"- Reconciliation: {report.control_reconciliation_status.value}",
            f"- Samples: {len(report.samples)}",
            "",
            "## Reasons",
            "",
            reasons,
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            metric_rows,
            "",
            "## Live Trading",
            "",
            "No live order was placed. No live cancel was sent. Paper broker only.",
            "",
        )
    )


def render_shadow_run_html(report: ShadowRunReport) -> str:
    metric_rows = "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in sorted(report.metrics.to_dict().items())
    )
    reason_items = "".join(
        f"<li>{escape(reason)}</li>" for reason in report.reasons
    ) or "<li>None</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolySia — Polymarket Adapter — Shadow Run</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin-top: 24px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; padding: 8px 12px; color: #fff;
      background: #1f5f8b; font-weight: 700; }}
    section {{ border: 1px solid #d7dce0; border-radius: 8px; padding: 14px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 9px 6px; text-align: left; }}
    tr:first-child th, tr:first-child td {{ border-top: 0; }}
    th {{ color: #687582; width: 44%; }}
  </style>
</head>
<body>
  <main>
    <h1>PolySia — Polymarket Adapter — Shadow Run</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.classification)}</div>
    <section>
      <h2>Operational Control</h2>
      <p>State: {escape(report.operational_state.value)}</p>
      <p>Revision: {report.control_revision}</p>
      <p>Reconciliation: {escape(report.control_reconciliation_status.value)}</p>
    </section>
    <h2>Reasons</h2>
    <ul>{reason_items}</ul>
    <section>
      <h2>Metrics</h2>
      <table>{metric_rows}</table>
    </section>
    <section>
      <h2>Live Trading</h2>
      <p>No live order was placed. No live cancel was sent. Paper broker only.</p>
    </section>
  </main>
</body>
</html>
"""


def render_shadow_run(report: ShadowRunReport, report_format: ReportFormat) -> str:
    if report_format == "json":
        return render_shadow_run_json(report)
    if report_format == "markdown":
        return render_shadow_run_markdown(report)
    return render_shadow_run_html(report)


def render_shadow_run_timeseries_jsonl(report: ShadowRunReport) -> str:
    return "\n".join(json.dumps(sample.to_dict(), sort_keys=True) for sample in report.samples)


async def _run_mocked_public_shadow(
    config: ShadowRunConfig,
    *,
    selected_token: str,
    strategy: BaseStrategy,
    risk_engine: RiskEngine,
    start: datetime,
    clock: Clock,
    operational_boundary: ShadowIntentBoundary | None,
) -> tuple[ShadowRunSample, ...]:
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger, clock=clock)
    book = LocalOrderBook(token_id=selected_token)
    samples: list[ShadowRunSample] = []
    event_count = _event_count(config)
    equity_points = [ledger.cash]

    for index in range(event_count):
        event_time = start + timedelta(seconds=index * config.sample_interval_seconds)
        _apply_shadow_book_update(book, index)
        event = _shadow_event(selected_token, index=index, event_time=event_time)
        context = StrategyContext(
            orderbook=book,
            positions={token: position.size for token, position in ledger.positions.items()},
            clock=clock,
        )
        intents = (
            await operational_boundary.on_market_event(strategy, event, context)
            if operational_boundary is not None
            else await strategy.on_market_event(event, context)
        )
        approved = 0
        rejected = 0
        orders_before = len(broker.orders)
        fills_before = len(broker.fills)
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
                    open_orders_count=len(broker.orders),
                    market_data_age_ms=0,
                ),
            )
            if decision.approved and decision.adjusted_size is not None:
                approved += 1
                broker.submit_limit_order(
                    ApprovedOrderIntent(
                        intent=intent,
                        approved_size=decision.adjusted_size,
                        risk_reason=decision.reason,
                        approved_at=event_time,
                    ),
                    book,
                )
            else:
                rejected += 1

        pnl = calculate_portfolio_pnl(ledger, {selected_token: book.mid or Decimal("0")})
        equity_points.append(pnl.total_equity)
        samples.append(
            ShadowRunSample(
                timestamp=event_time,
                event_index=index,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
                spread=book.spread,
                mid=book.mid,
                microprice=book.microprice,
                strategy_intents=len(intents),
                risk_approved=approved,
                risk_rejected=rejected,
                paper_orders=len(broker.orders) - orders_before,
                paper_fills=len(broker.fills) - fills_before,
                paper_position=ledger.get(selected_token).size,
                paper_total_pnl=pnl.realized_pnl + pnl.unrealized_pnl,
                decision_latency_ms=_latency_for_index(index),
            )
        )

    return tuple(samples)


def _metrics_from_samples(
    config: ShadowRunConfig,
    *,
    samples: tuple[ShadowRunSample, ...],
    start: datetime,
    selected_token: str,
) -> ShadowRunMetrics:
    duration = Decimal(config.duration_minutes * 60)
    end = start + timedelta(seconds=int(duration))
    final = samples[-1] if samples else None
    total_orders = sum(sample.paper_orders for sample in samples)
    total_fills = sum(sample.paper_fills for sample in samples)
    total_intents = sum(sample.strategy_intents for sample in samples)
    total_approved = sum(sample.risk_approved for sample in samples)
    total_rejected = sum(sample.risk_rejected for sample in samples)
    latencies = tuple(sample.decision_latency_ms for sample in samples)
    pnl_series = [Decimal("0"), *(sample.paper_total_pnl for sample in samples)]
    return ShadowRunMetrics(
        start_time=start,
        end_time=end,
        duration_seconds=duration,
        selected_market=config.market_slug or "shadow-market",
        selected_token=selected_token,
        event_count=len(samples),
        event_rate_per_second=_safe_divide(Decimal(len(samples)), duration),
        stream_health="mocked_public_stream",
        reconnect_count=0,
        stale_event_count=0,
        orderbook_updates=len(samples),
        best_bid_observations=sum(1 for sample in samples if sample.best_bid is not None),
        best_ask_observations=sum(1 for sample in samples if sample.best_ask is not None),
        spread_observations=sum(1 for sample in samples if sample.spread is not None),
        mid_observations=sum(1 for sample in samples if sample.mid is not None),
        microprice_observations=sum(1 for sample in samples if sample.microprice is not None),
        strategy_intent_count=total_intents,
        risk_approval_count=total_approved,
        risk_rejection_count=total_rejected,
        paper_order_count=total_orders,
        paper_fill_count=total_fills,
        paper_position=final.paper_position if final is not None else Decimal("0"),
        paper_realized_pnl=Decimal("0"),
        paper_unrealized_pnl=final.paper_total_pnl if final is not None else Decimal("0"),
        paper_total_pnl=final.paper_total_pnl if final is not None else Decimal("0"),
        max_drawdown=_max_drawdown(pnl_series),
        latency_average_ms=_average(latencies),
        latency_p95_ms=_percentile(latencies, Decimal("0.95")),
        latency_p99_ms=_percentile(latencies, Decimal("0.99")),
        live_broker_used=False,
    )


def _empty_metrics(
    config: ShadowRunConfig,
    *,
    start: datetime,
    stream_health: str,
) -> ShadowRunMetrics:
    duration = Decimal(config.duration_minutes * 60)
    return ShadowRunMetrics(
        start_time=start,
        end_time=start + timedelta(seconds=int(duration)),
        duration_seconds=duration,
        selected_market=config.market_slug or "shadow-market",
        selected_token=config.token_id or "shadow-token",
        event_count=0,
        event_rate_per_second=Decimal("0"),
        stream_health=stream_health,
        reconnect_count=0,
        stale_event_count=0,
        orderbook_updates=0,
        best_bid_observations=0,
        best_ask_observations=0,
        spread_observations=0,
        mid_observations=0,
        microprice_observations=0,
        strategy_intent_count=0,
        risk_approval_count=0,
        risk_rejection_count=0,
        paper_order_count=0,
        paper_fill_count=0,
        paper_position=Decimal("0"),
        paper_realized_pnl=Decimal("0"),
        paper_unrealized_pnl=Decimal("0"),
        paper_total_pnl=Decimal("0"),
        max_drawdown=Decimal("0"),
        latency_average_ms=Decimal("0"),
        latency_p95_ms=Decimal("0"),
        latency_p99_ms=Decimal("0"),
        live_broker_used=False,
    )


def _event_count(config: ShadowRunConfig) -> int:
    duration_events = max(1, (config.duration_minutes * 60) // config.sample_interval_seconds)
    if config.max_events is None:
        return min(duration_events, 20)
    return min(config.max_events, duration_events)


def _apply_shadow_book_update(book: LocalOrderBook, index: int) -> None:
    if index == 0:
        book.apply_snapshot(
            bids=((Decimal("0.45"), Decimal("100")),),
            asks=((Decimal("0.55"), Decimal("4")),),
        )
        return
    bid = Decimal("0.45") + (Decimal(index) * Decimal("0.002"))
    ask = Decimal("0.55") + (Decimal(index % 2) * Decimal("0.002"))
    book.apply_update(side="BUY", price=bid, size=Decimal("100"))
    book.apply_update(side="SELL", price=ask, size=Decimal("4"))


def _shadow_event(token_id: str, *, index: int, event_time: datetime) -> MarketDataEvent:
    return MarketDataEvent(
        source="polymarket",
        event_type="book" if index == 0 else "price_change",
        token_id=token_id,
        received_at=event_time,
        exchange_ts=event_time,
        payload={"sequence": index, "mode": "mocked-shadow-run"},
        raw_payload={"redacted": True},
    )


def _strategy_from_name(name: str) -> BaseStrategy:
    normalized = name.strip().lower()
    if normalized == "stale-price":
        return StalePriceStrategy()
    if normalized == "passive-market-maker":
        return PassiveMarketMakerStrategy()
    raise ValueError(f"Unsupported strategy for shadow-run: {name}")


def _clean_git_error(
    project_root: Path,
    *,
    require_clean_git: bool,
    git_status_reader: GitStatusReader | None,
) -> str | None:
    if not require_clean_git:
        return None
    try:
        status = (
            git_status_reader(project_root)
            if git_status_reader is not None
            else _read_git_status(project_root)
        )
    except (OSError, subprocess.SubprocessError) as error:
        return f"Could not read git status: {error}."
    if status.strip():
        return "Repository has uncommitted changes."
    return None


def _read_git_status(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        cwd=project_root,
        text=True,
        timeout=5,
    )
    return result.stdout


def _latency_for_index(index: int) -> Decimal:
    return (Decimal("1.0") + (Decimal(index % 5) * Decimal("0.2"))).quantize(
        Decimal("0.0001")
    )


def _safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == Decimal("0"):
        return Decimal("0")
    return (numerator / denominator).quantize(Decimal("0.0001"))


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


def _max_drawdown(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    peak = values[0]
    max_drawdown = Decimal("0")
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value - peak)
    return max_drawdown


def _decimal_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_to_str(value)


def normalize_shadow_report_formats(
    *,
    json_enabled: bool,
    markdown_enabled: bool,
    html_enabled: bool,
) -> tuple[ReportFormat, ...]:
    selected: list[ReportFormat] = []
    if json_enabled:
        selected.append("json")
    if markdown_enabled:
        selected.append("markdown")
    if html_enabled:
        selected.append("html")
    if not selected:
        return ("json", "markdown", "html")
    return tuple(selected)


def shadow_report_filename(report_format: ReportFormat) -> str:
    return {
        "html": "shadow_run.html",
        "json": "shadow_run.json",
        "markdown": "shadow_run.md",
    }[report_format]


__all__ = [
    "ShadowRunConfig",
    "ShadowRunMetrics",
    "ShadowRunReport",
    "ShadowRunSample",
    "build_shadow_run",
    "classify_shadow_run",
    "normalize_shadow_report_formats",
    "render_shadow_run",
    "render_shadow_run_html",
    "render_shadow_run_json",
    "render_shadow_run_markdown",
    "render_shadow_run_timeseries_jsonl",
    "shadow_report_filename",
]
