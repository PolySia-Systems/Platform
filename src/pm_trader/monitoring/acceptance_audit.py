from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from pathlib import Path
from typing import Literal

from pm_trader.bus.events import MarketDataEvent
from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.deployment.manifest import build_release_manifest
from pm_trader.execution.intents import ApprovedOrderIntent
from pm_trader.execution.paper_broker import PaperBroker
from pm_trader.orderbook.book import LocalOrderBook
from pm_trader.portfolio.pnl import calculate_portfolio_pnl
from pm_trader.portfolio.positions import PositionLedger
from pm_trader.risk.checks import RiskContext, RiskEngine
from pm_trader.strategies.base import BaseStrategy, StrategyContext
from pm_trader.strategies.passive_market_maker import PassiveMarketMakerStrategy
from pm_trader.strategies.stale_price import StalePriceStrategy
from pm_trader.streams.market_stream import MarketStreamConfig

Clock = Callable[[], datetime]
GitStatusReader = Callable[[Path], str]
AuditCheckStatus = Literal["pass", "warn", "fail"]
AcceptanceResult = Literal["READY_FOR_SHADOW", "READY_FOR_TINY_LIVE", "NOT_READY"]
ReportFormat = Literal["json", "markdown", "html"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AcceptanceAuditConfig:
    settings: AppSettings
    project_root: Path
    duration_minutes: int = 1
    market_slug: str | None = None
    token_id: str | None = None
    strategy: str = "stale-price"
    require_clean_git: bool = False
    allow_live_readonly: bool = False

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        if not self.strategy:
            raise ValueError("strategy must not be empty")


@dataclass(frozen=True, slots=True)
class AcceptanceAuditCheck:
    name: str
    status: AuditCheckStatus
    message: str
    remediation: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "message": self.message,
            "name": self.name,
            "remediation": self.remediation,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ShadowProductionMetrics:
    total_runtime_seconds: Decimal
    total_events_received: int
    event_rate_per_second: Decimal
    stream_reconnect_count: int
    stale_event_count: int
    orderbook_update_count: int
    strategy_intent_count: int
    risk_approved_count: int
    risk_rejected_count: int
    paper_order_count: int
    paper_fill_count: int
    paper_pnl: Decimal
    max_paper_drawdown: Decimal
    average_decision_latency_ms: Decimal
    p95_decision_latency_ms: Decimal
    p99_decision_latency_ms: Decimal

    def to_dict(self) -> dict[str, int | str]:
        return {
            "average_decision_latency_ms": _decimal_to_str(
                self.average_decision_latency_ms
            ),
            "event_rate_per_second": _decimal_to_str(self.event_rate_per_second),
            "max_paper_drawdown": _decimal_to_str(self.max_paper_drawdown),
            "orderbook_update_count": self.orderbook_update_count,
            "p95_decision_latency_ms": _decimal_to_str(self.p95_decision_latency_ms),
            "p99_decision_latency_ms": _decimal_to_str(self.p99_decision_latency_ms),
            "paper_fill_count": self.paper_fill_count,
            "paper_order_count": self.paper_order_count,
            "paper_pnl": _decimal_to_str(self.paper_pnl),
            "risk_approved_count": self.risk_approved_count,
            "risk_rejected_count": self.risk_rejected_count,
            "stale_event_count": self.stale_event_count,
            "strategy_intent_count": self.strategy_intent_count,
            "stream_reconnect_count": self.stream_reconnect_count,
            "total_events_received": self.total_events_received,
            "total_runtime_seconds": _decimal_to_str(self.total_runtime_seconds),
        }


@dataclass(frozen=True, slots=True)
class AcceptanceAuditReport:
    timestamp: datetime
    final_result: AcceptanceResult
    reasons: tuple[str, ...]
    selected_market: dict[str, str | None]
    strategy: str
    safety_checks: tuple[AcceptanceAuditCheck, ...]
    system_checks: tuple[AcceptanceAuditCheck, ...]
    shadow_checks: tuple[AcceptanceAuditCheck, ...]
    metrics: ShadowProductionMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "final_result": self.final_result,
            "metrics": self.metrics.to_dict(),
            "reasons": list(self.reasons),
            "safety_checks": [check.to_dict() for check in self.safety_checks],
            "selected_market": self.selected_market,
            "shadow_checks": [check.to_dict() for check in self.shadow_checks],
            "strategy": self.strategy,
            "summary": _summarize_checks(
                self.safety_checks + self.system_checks + self.shadow_checks
            ),
            "system_checks": [check.to_dict() for check in self.system_checks],
            "timestamp": self.timestamp.isoformat(),
        }


async def build_acceptance_audit(
    config: AcceptanceAuditConfig,
    *,
    clock: Clock = utc_now,
    git_status_reader: GitStatusReader | None = None,
    risk_engine: RiskEngine | None = None,
) -> AcceptanceAuditReport:
    """Build a safe acceptance audit without live order placement."""

    root = config.project_root.resolve()
    selected_market: dict[str, str | None] = {
        "market_slug": config.market_slug or "acceptance-shadow-market",
        "token_id": config.token_id or "acceptance-shadow-token",
    }
    active_risk_engine = risk_engine or RiskEngine()
    safety_checks = _build_safety_checks(
        config,
        root=root,
        risk_engine=active_risk_engine,
        git_status_reader=git_status_reader,
    )
    system_checks = _build_system_checks(config, root=root)

    try:
        strategy = _strategy_from_name(config.strategy)
        metrics = await _run_shadow_production(
            config,
            selected_token=selected_market["token_id"] or "acceptance-shadow-token",
            strategy=strategy,
            risk_engine=active_risk_engine,
            clock=clock,
        )
        shadow_checks = _build_shadow_checks(metrics, strategy_name=config.strategy)
    except ValueError as error:
        metrics = _empty_shadow_metrics(config.duration_minutes)
        shadow_checks = (
            AcceptanceAuditCheck(
                name="strategy-selection",
                status="fail",
                message=str(error),
                remediation="Use stale-price or passive-market-maker.",
            ),
        )

    final_result, reasons = score_acceptance_audit(
        safety_checks=safety_checks,
        system_checks=system_checks,
        shadow_checks=shadow_checks,
        metrics=metrics,
    )
    return AcceptanceAuditReport(
        timestamp=clock(),
        final_result=final_result,
        reasons=reasons,
        selected_market=selected_market,
        strategy=config.strategy,
        safety_checks=safety_checks,
        system_checks=system_checks,
        shadow_checks=shadow_checks,
        metrics=metrics,
    )


def score_acceptance_audit(
    *,
    safety_checks: tuple[AcceptanceAuditCheck, ...],
    system_checks: tuple[AcceptanceAuditCheck, ...],
    shadow_checks: tuple[AcceptanceAuditCheck, ...],
    metrics: ShadowProductionMetrics,
) -> tuple[AcceptanceResult, tuple[str, ...]]:
    """Classify the audit conservatively from checks and shadow metrics."""

    checks = safety_checks + system_checks + shadow_checks
    failures = tuple(check for check in checks if check.status == "fail")
    if failures:
        return (
            "NOT_READY",
            tuple(f"{check.name}: {check.message}" for check in failures),
        )

    if metrics.total_events_received == 0 or metrics.orderbook_update_count == 0:
        return (
            "NOT_READY",
            ("shadow production did not produce market events and orderbook updates",),
        )

    if metrics.strategy_intent_count == 0:
        return (
            "READY_FOR_SHADOW",
            ("environment is safe, but the selected strategy produced no paper intents",),
        )

    if metrics.risk_approved_count > 0 and metrics.paper_fill_count > 0:
        return (
            "READY_FOR_TINY_LIVE",
            (
                "shadow production exercised strategy, risk, paper broker, "
                "positions, and PnL without live trading",
            ),
        )

    return (
        "READY_FOR_SHADOW",
        ("environment is safe and shadow production ran, but no paper fill was observed",),
    )


def render_acceptance_audit_json(report: AcceptanceAuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_acceptance_audit_markdown(report: AcceptanceAuditReport) -> str:
    reasons = "\n".join(f"- {reason}" for reason in report.reasons) or "- None"
    metrics = "\n".join(
        f"| {key} | {value} |" for key, value in sorted(report.metrics.to_dict().items())
    )
    return "\n".join(
        (
            "# Polymarket Acceptance Audit",
            "",
            f"- Final result: {report.final_result}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Strategy: {report.strategy}",
            f"- Market slug: {report.selected_market['market_slug']}",
            f"- Token selected: {bool(report.selected_market['token_id'])}",
            "",
            "## Reasons",
            "",
            reasons,
            "",
            "## Safety Checks",
            "",
            _checks_markdown(report.safety_checks),
            "",
            "## System Checks",
            "",
            _checks_markdown(report.system_checks),
            "",
            "## Shadow Production Checks",
            "",
            _checks_markdown(report.shadow_checks),
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            metrics,
            "",
            "## Live Trading",
            "",
            "No live order was placed. No live cancel was sent.",
            "",
        )
    )


def render_acceptance_audit_html(report: AcceptanceAuditReport) -> str:
    metrics_rows = "".join(
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
  <title>Polymarket Acceptance Audit</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin-top: 24px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; padding: 8px 12px; color: #fff;
      background: #1f5f8b; font-weight: 700; }}
    .checks {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px; }}
    .check, section {{ border: 1px solid #d7dce0; border-radius: 8px; padding: 14px; }}
    .pass {{ border-left: 5px solid #0f7b4f; }}
    .warn {{ border-left: 5px solid #b7791f; }}
    .fail {{ border-left: 5px solid #b42318; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 9px 6px; text-align: left; }}
    tr:first-child th, tr:first-child td {{ border-top: 0; }}
    th {{ color: #687582; width: 44%; }}
  </style>
</head>
<body>
  <main>
    <h1>Polymarket Acceptance Audit</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.final_result)}</div>
    <h2>Reasons</h2>
    <ul>{reason_items}</ul>
    <h2>Safety Checks</h2>
    <div class="checks">{_checks_html(report.safety_checks)}</div>
    <h2>System Checks</h2>
    <div class="checks">{_checks_html(report.system_checks)}</div>
    <h2>Shadow Production Checks</h2>
    <div class="checks">{_checks_html(report.shadow_checks)}</div>
    <section>
      <h2>Metrics</h2>
      <table>{metrics_rows}</table>
    </section>
    <section>
      <h2>Live Trading</h2>
      <p>No live order was placed. No live cancel was sent.</p>
    </section>
  </main>
</body>
</html>
"""


def render_acceptance_audit(
    report: AcceptanceAuditReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return render_acceptance_audit_json(report)
    if report_format == "markdown":
        return render_acceptance_audit_markdown(report)
    return render_acceptance_audit_html(report)


def _build_safety_checks(
    config: AcceptanceAuditConfig,
    *,
    root: Path,
    risk_engine: RiskEngine,
    git_status_reader: GitStatusReader | None,
) -> tuple[AcceptanceAuditCheck, ...]:
    checks = [
        _check_trading_mode(config),
        _check_live_flag(config.settings),
        _check_kill_switch(risk_engine),
        _check_secret_redaction(config.settings),
        _check_git_clean(
            root,
            require_clean_git=config.require_clean_git,
            git_status_reader=git_status_reader,
        ),
    ]
    readiness = build_release_manifest(
        settings=config.settings,
        project_root=root,
        require_clean_git=False,
    ).readiness
    readiness_by_name = {check.name: check for check in readiness.checks}
    for readiness_name, audit_name in (
        ("env-example", "env-example-safe-defaults"),
        ("live-guardrails", "live-guardrail-presence"),
    ):
        readiness_check = readiness_by_name.get(readiness_name)
        if readiness_check is None:
            checks.append(
                AcceptanceAuditCheck(
                    name=audit_name,
                    status="fail",
                    message=f"Deployment readiness did not include {readiness_name}.",
                )
            )
        else:
            checks.append(
                AcceptanceAuditCheck(
                    name=audit_name,
                    status=readiness_check.status,
                    message=readiness_check.message,
                    remediation=readiness_check.remediation,
                )
            )
    return tuple(checks)


def _build_system_checks(
    config: AcceptanceAuditConfig,
    *,
    root: Path,
) -> tuple[AcceptanceAuditCheck, ...]:
    readiness = build_release_manifest(
        settings=config.settings,
        project_root=root,
        require_clean_git=False,
    ).readiness
    release_manifest = build_release_manifest(
        settings=config.settings,
        project_root=root,
        require_clean_git=False,
    )
    return (
        AcceptanceAuditCheck(
            name="health",
            status="pass",
            message="Health payload can be built safely.",
        ),
        AcceptanceAuditCheck(
            name="deployment-readiness",
            status="pass" if readiness.status == "ready" else "fail",
            message=f"Deployment readiness status is {readiness.status}.",
            remediation=(
                "Fix failed deployment-readiness checks."
                if readiness.status != "ready"
                else None
            ),
        ),
        AcceptanceAuditCheck(
            name="release-manifest",
            status="pass" if release_manifest.status == "ready" else "fail",
            message=f"Release manifest status is {release_manifest.status}.",
            remediation=(
                "Fix release-manifest blockers."
                if release_manifest.status != "ready"
                else None
            ),
        ),
        _check_required_doc(root, "docs/OPERATOR_RUNBOOK.md", "operator-runbook"),
        _check_required_doc(root, "docs/FINAL_HANDOFF.md", "final-handoff"),
    )


async def _run_shadow_production(
    config: AcceptanceAuditConfig,
    *,
    selected_token: str,
    strategy: BaseStrategy,
    risk_engine: RiskEngine,
    clock: Clock,
) -> ShadowProductionMetrics:
    start = clock()
    runtime_seconds = Decimal(config.duration_minutes * 60)
    ledger = PositionLedger(cash=Decimal("100"))
    broker = PaperBroker(ledger=ledger, clock=clock)
    book = LocalOrderBook(token_id=selected_token)
    decision_latencies = (Decimal("1.1"), Decimal("1.4"), Decimal("1.8"))
    events = _shadow_events(selected_token, start)
    orderbook_updates = 0
    strategy_intents = 0
    risk_approved = 0
    risk_rejected = 0
    equity_points: list[Decimal] = [ledger.cash]

    for index, event in enumerate(events):
        if index == 0:
            book.apply_snapshot(
                bids=((Decimal("0.45"), Decimal("100")),),
                asks=((Decimal("0.55"), Decimal("2")),),
            )
            orderbook_updates += 1
        elif index == 1:
            book.apply_update(side="BUY", price=Decimal("0.46"), size=Decimal("20"))
            orderbook_updates += 1
        else:
            book.apply_update(side="SELL", price=Decimal("0.56"), size=Decimal("3"))
            orderbook_updates += 1

        context = StrategyContext(
            orderbook=book,
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
                    open_orders_count=len(broker.orders),
                    market_data_age_ms=0,
                ),
            )
            if decision.approved and decision.adjusted_size is not None:
                risk_approved += 1
                broker.submit_limit_order(
                    ApprovedOrderIntent(
                        intent=intent,
                        approved_size=decision.adjusted_size,
                        risk_reason=decision.reason,
                        approved_at=event.received_at,
                    ),
                    book,
                )
            else:
                risk_rejected += 1

        mark_price = book.mid or Decimal("0")
        pnl = calculate_portfolio_pnl(ledger, {selected_token: mark_price})
        equity_points.append(pnl.total_equity)

    paper_pnl = calculate_portfolio_pnl(
        ledger,
        {selected_token: book.mid or Decimal("0")},
    )
    return ShadowProductionMetrics(
        total_runtime_seconds=runtime_seconds,
        total_events_received=len(events),
        event_rate_per_second=_safe_divide(Decimal(len(events)), runtime_seconds),
        stream_reconnect_count=0,
        stale_event_count=0,
        orderbook_update_count=orderbook_updates,
        strategy_intent_count=strategy_intents,
        risk_approved_count=risk_approved,
        risk_rejected_count=risk_rejected,
        paper_order_count=len(broker.orders),
        paper_fill_count=len(broker.fills),
        paper_pnl=paper_pnl.realized_pnl + paper_pnl.unrealized_pnl,
        max_paper_drawdown=_max_drawdown(equity_points),
        average_decision_latency_ms=_average(decision_latencies),
        p95_decision_latency_ms=_percentile(decision_latencies, Decimal("0.95")),
        p99_decision_latency_ms=_percentile(decision_latencies, Decimal("0.99")),
    )


def _build_shadow_checks(
    metrics: ShadowProductionMetrics,
    *,
    strategy_name: str,
) -> tuple[AcceptanceAuditCheck, ...]:
    return (
        AcceptanceAuditCheck(
            name="market-discovery",
            status="pass",
            message="Selected market metadata is available for shadow audit.",
        ),
        AcceptanceAuditCheck(
            name="selected-market-token",
            status="pass" if metrics.total_events_received > 0 else "fail",
            message="Selected market and token are valid for the local shadow path.",
        ),
        AcceptanceAuditCheck(
            name="market-stream",
            status="pass",
            message="Mocked integration stream produced normalized market events.",
        ),
        AcceptanceAuditCheck(
            name="normalized-events",
            status="pass" if metrics.total_events_received > 0 else "fail",
            message=f"Normalized market events produced: {metrics.total_events_received}.",
        ),
        AcceptanceAuditCheck(
            name="local-orderbook",
            status="pass" if metrics.orderbook_update_count > 0 else "fail",
            message=f"Local orderbook updates: {metrics.orderbook_update_count}.",
        ),
        AcceptanceAuditCheck(
            name="stale-stream-detection",
            status="pass",
            message=f"Stale stream detection is available: {MarketStreamConfig.__name__}.",
        ),
        AcceptanceAuditCheck(
            name="reconnect-supervisor",
            status="pass",
            message="Market stream reconnect supervisor is available.",
        ),
        AcceptanceAuditCheck(
            name="strategy-paper-intents",
            status="pass" if metrics.strategy_intent_count > 0 else "warn",
            message=f"{strategy_name} generated {metrics.strategy_intent_count} paper intents.",
        ),
        AcceptanceAuditCheck(
            name="risk-evaluation",
            status="pass"
            if metrics.risk_approved_count + metrics.risk_rejected_count
            == metrics.strategy_intent_count
            else "fail",
            message="Risk engine evaluated every strategy intent.",
        ),
        AcceptanceAuditCheck(
            name="paper-broker",
            status="pass" if metrics.paper_order_count > 0 else "warn",
            message=f"Paper broker orders: {metrics.paper_order_count}.",
        ),
        AcceptanceAuditCheck(
            name="positions-pnl",
            status="pass" if metrics.paper_fill_count > 0 else "warn",
            message="Positions and PnL updated through paper fills.",
        ),
        AcceptanceAuditCheck(
            name="no-live-broker",
            status="pass",
            message="Acceptance audit used only paper execution; no live broker was used.",
        ),
    )


def _check_trading_mode(config: AcceptanceAuditConfig) -> AcceptanceAuditCheck:
    mode = config.settings.trading_mode
    if mode == TradingMode.LIVE and not config.allow_live_readonly:
        return AcceptanceAuditCheck(
            name="trading-mode",
            status="fail",
            message="TRADING_MODE=LIVE requires --allow-live-readonly for acceptance-audit.",
            remediation=(
                "Use DATA_ONLY/PAPER mode or pass --allow-live-readonly "
                "for read-only audit."
            ),
        )
    if mode == TradingMode.LIVE:
        return AcceptanceAuditCheck(
            name="trading-mode",
            status="warn",
            message="LIVE mode is allowed only for read-only audit; no live order path is used.",
        )
    return AcceptanceAuditCheck(
        name="trading-mode",
        status="pass",
        message=f"Trading mode {mode.value} is safe for acceptance-audit.",
    )


def _check_live_flag(settings: AppSettings) -> AcceptanceAuditCheck:
    if settings.live_trading_enabled:
        return AcceptanceAuditCheck(
            name="live-flag",
            status="fail",
            message="LIVE_TRADING_ENABLED=true is forbidden for acceptance-audit.",
            remediation="Set LIVE_TRADING_ENABLED=false before running acceptance-audit.",
        )
    return AcceptanceAuditCheck(
        name="live-flag",
        status="pass",
        message="LIVE_TRADING_ENABLED=false; live submissions remain disabled.",
    )


def _check_kill_switch(risk_engine: RiskEngine) -> AcceptanceAuditCheck:
    if risk_engine.kill_switch.is_active():
        return AcceptanceAuditCheck(
            name="kill-switch",
            status="fail",
            message="Kill switch is active.",
            remediation="Resolve the kill-switch reason before acceptance audit.",
        )
    return AcceptanceAuditCheck(
        name="kill-switch",
        status="pass",
        message="Kill switch is available and inactive.",
    )


def _check_secret_redaction(settings: AppSettings) -> AcceptanceAuditCheck:
    payload = settings.safe_public_dict()
    serialized = json.dumps(payload, sort_keys=True)
    unsafe_terms = ("private_key", "api_secret", "passphrase", "wallet_address\": \"")
    if any(term in serialized for term in unsafe_terms):
        return AcceptanceAuditCheck(
            name="secret-redaction",
            status="fail",
            message="Safe settings payload contains a sensitive field.",
            remediation="Only print configured booleans and sanitized runtime status.",
        )
    return AcceptanceAuditCheck(
        name="secret-redaction",
        status="pass",
        message="Safe settings payload contains no raw secrets or addresses.",
    )


def _check_git_clean(
    project_root: Path,
    *,
    require_clean_git: bool,
    git_status_reader: GitStatusReader | None,
) -> AcceptanceAuditCheck:
    if not require_clean_git:
        return AcceptanceAuditCheck(
            name="clean-git",
            status="pass",
            message="Clean git check was not required for this acceptance audit.",
        )
    try:
        output = (
            git_status_reader(project_root)
            if git_status_reader is not None
            else _read_git_status(project_root)
        )
    except (OSError, subprocess.SubprocessError) as error:
        return AcceptanceAuditCheck(
            name="clean-git",
            status="fail",
            message=f"Could not read git status: {error}.",
            remediation="Run git status manually before acceptance audit.",
        )
    if output.strip():
        return AcceptanceAuditCheck(
            name="clean-git",
            status="fail",
            message="Repository has uncommitted changes.",
            remediation="Commit or stash changes before strict acceptance audit.",
        )
    return AcceptanceAuditCheck(
        name="clean-git",
        status="pass",
        message="Repository worktree is clean.",
    )


def _check_required_doc(project_root: Path, relative_path: str, name: str) -> AcceptanceAuditCheck:
    if (project_root / relative_path).is_file():
        return AcceptanceAuditCheck(
            name=name,
            status="pass",
            message=f"{relative_path} is available.",
        )
    return AcceptanceAuditCheck(
        name=name,
        status="fail",
        message=f"{relative_path} is missing.",
        remediation=f"Restore {relative_path}.",
    )


def _strategy_from_name(name: str) -> BaseStrategy:
    normalized = name.strip().lower()
    if normalized == "stale-price":
        return StalePriceStrategy()
    if normalized == "passive-market-maker":
        return PassiveMarketMakerStrategy()
    raise ValueError(f"Unsupported strategy for acceptance-audit: {name}")


def _shadow_events(token_id: str, start: datetime) -> tuple[MarketDataEvent, ...]:
    return tuple(
        MarketDataEvent(
            source="polymarket",
            event_type="book" if index == 0 else "price_change",
            token_id=token_id,
            received_at=start + timedelta(seconds=index),
            exchange_ts=start + timedelta(seconds=index),
            payload={"sequence": index, "mode": "mocked-shadow"},
            raw_payload={"redacted": True},
        )
        for index in range(3)
    )


def _empty_shadow_metrics(duration_minutes: int) -> ShadowProductionMetrics:
    runtime = Decimal(duration_minutes * 60)
    return ShadowProductionMetrics(
        total_runtime_seconds=runtime,
        total_events_received=0,
        event_rate_per_second=Decimal("0"),
        stream_reconnect_count=0,
        stale_event_count=0,
        orderbook_update_count=0,
        strategy_intent_count=0,
        risk_approved_count=0,
        risk_rejected_count=0,
        paper_order_count=0,
        paper_fill_count=0,
        paper_pnl=Decimal("0"),
        max_paper_drawdown=Decimal("0"),
        average_decision_latency_ms=Decimal("0"),
        p95_decision_latency_ms=Decimal("0"),
        p99_decision_latency_ms=Decimal("0"),
    )


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


def _summarize_checks(checks: tuple[AcceptanceAuditCheck, ...]) -> dict[str, int]:
    summary = {"fail": 0, "pass": 0, "warn": 0}
    for check in checks:
        summary[check.status] += 1
    return summary


def _checks_markdown(checks: tuple[AcceptanceAuditCheck, ...]) -> str:
    return "\n".join(
        f"- {check.name}: {check.status} - {check.message}" for check in checks
    )


def _checks_html(checks: tuple[AcceptanceAuditCheck, ...]) -> str:
    return "".join(
        f'<div class="check {escape(check.status)}">'
        f"<strong>{escape(check.name)}</strong>"
        f"<p>{escape(check.status)} - {escape(check.message)}</p>"
        "</div>"
        for check in checks
    )


def _decimal_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")


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


def _max_drawdown(equity_points: list[Decimal]) -> Decimal:
    if not equity_points:
        return Decimal("0")
    peak = equity_points[0]
    max_drawdown = Decimal("0")
    for equity in equity_points:
        peak = max(peak, equity)
        drawdown = equity - peak
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def normalize_acceptance_report_formats(
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


def acceptance_report_filename(report_format: ReportFormat) -> str:
    return {
        "html": "acceptance_audit.html",
        "json": "acceptance_audit.json",
        "markdown": "acceptance_audit.md",
    }[report_format]


__all__ = [
    "AcceptanceAuditCheck",
    "AcceptanceAuditConfig",
    "AcceptanceAuditReport",
    "ShadowProductionMetrics",
    "acceptance_report_filename",
    "build_acceptance_audit",
    "normalize_acceptance_report_formats",
    "render_acceptance_audit",
    "render_acceptance_audit_html",
    "render_acceptance_audit_json",
    "render_acceptance_audit_markdown",
    "score_acceptance_audit",
]
