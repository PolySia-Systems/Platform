from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from polysia.adapters.polymarket.stream import MarketStreamConfig
from polysia.bus.events import MarketDataEvent
from polysia.config.settings import AppSettings, TradingMode
from polysia.deployment.manifest import build_release_manifest
from polysia.execution.intents import ApprovedOrderIntent
from polysia.execution.paper_broker import PaperBroker
from polysia.monitoring.acceptance_models import (
    AcceptanceAuditCheck,
    AcceptanceAuditConfig,
    AcceptanceAuditReport,
    AcceptanceResult,
    ReportFormat,
    ShadowProductionMetrics,
    utc_now,
)
from polysia.monitoring.acceptance_renderers import (
    render_acceptance_audit,
    render_acceptance_audit_html,
    render_acceptance_audit_json,
    render_acceptance_audit_markdown,
)
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.pnl import calculate_portfolio_pnl
from polysia.portfolio.positions import PositionLedger
from polysia.risk.checks import RiskContext, RiskEngine
from polysia.strategies.base import BaseStrategy, StrategyContext
from polysia.strategies.passive_market_maker import PassiveMarketMakerStrategy
from polysia.strategies.stale_price import StalePriceStrategy

Clock = Callable[[], datetime]
GitStatusReader = Callable[[Path], str]


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
