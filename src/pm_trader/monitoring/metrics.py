from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.orderbook.book import LocalOrderBook
from pm_trader.portfolio.pnl import calculate_portfolio_pnl
from pm_trader.portfolio.positions import PositionLedger
from pm_trader.risk.kill_switch import KillSwitch

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RuntimeSafetyMetrics:
    """Sanitized runtime and live-trading guardrail state."""

    app_env: str
    live_trading_allowed: bool
    live_trading_enabled: bool
    live_token_allowlist_count: int
    live_max_order_size: Decimal
    live_max_order_notional: Decimal
    live_max_open_orders: int
    log_level: str
    funder_address_configured: bool
    private_key_configured: bool
    wallet_address_configured: bool
    trading_mode: TradingMode

    def to_dict(self) -> dict[str, bool | int | str]:
        return {
            "app_env": self.app_env,
            "live_trading_allowed": self.live_trading_allowed,
            "live_trading_enabled": self.live_trading_enabled,
            "live_token_allowlist_count": self.live_token_allowlist_count,
            "live_max_open_orders": self.live_max_open_orders,
            "live_max_order_notional": str(self.live_max_order_notional),
            "live_max_order_size": str(self.live_max_order_size),
            "log_level": self.log_level,
            "funder_address_configured": self.funder_address_configured,
            "private_key_configured": self.private_key_configured,
            "trading_mode": self.trading_mode.value,
            "wallet_address_configured": self.wallet_address_configured,
        }


@dataclass(frozen=True, slots=True)
class OperatorStatus:
    """One JSON-friendly status payload for operator dashboards and checks."""

    status: str
    timestamp: datetime
    runtime: RuntimeSafetyMetrics
    kill_switch_active: bool
    kill_switch_reason: str | None
    tiny_live_orders_ready: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kill_switch_active": self.kill_switch_active,
            "kill_switch_reason": self.kill_switch_reason,
            "runtime": self.runtime.to_dict(),
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "tiny_live_orders_ready": self.tiny_live_orders_ready,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class OrderBookMetrics:
    token_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    bid_depth: Decimal
    ask_depth: Decimal
    bid_level_count: int
    ask_level_count: int
    imbalance: Decimal | None
    microprice: Decimal | None
    mid: Decimal | None
    spread: Decimal | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "ask_depth": str(self.ask_depth),
            "ask_level_count": self.ask_level_count,
            "best_ask": _decimal_or_none(self.best_ask),
            "best_bid": _decimal_or_none(self.best_bid),
            "bid_depth": str(self.bid_depth),
            "bid_level_count": self.bid_level_count,
            "imbalance": _decimal_or_none(self.imbalance),
            "microprice": _decimal_or_none(self.microprice),
            "mid": _decimal_or_none(self.mid),
            "spread": _decimal_or_none(self.spread),
            "token_id": self.token_id,
        }


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    cash: Decimal
    gross_market_value: Decimal
    realized_pnl: Decimal
    total_equity: Decimal
    unrealized_pnl: Decimal
    position_count: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "cash": str(self.cash),
            "gross_market_value": str(self.gross_market_value),
            "position_count": self.position_count,
            "realized_pnl": str(self.realized_pnl),
            "total_equity": str(self.total_equity),
            "unrealized_pnl": str(self.unrealized_pnl),
        }


def build_runtime_safety_metrics(settings: AppSettings) -> RuntimeSafetyMetrics:
    return RuntimeSafetyMetrics(
        app_env=settings.app_env,
        live_trading_allowed=settings.live_trading_allowed,
        live_trading_enabled=settings.live_trading_enabled,
        live_token_allowlist_count=len(settings.polymarket_live_token_allowlist),
        live_max_order_size=settings.polymarket_live_max_order_size,
        live_max_order_notional=settings.polymarket_live_max_order_notional,
        live_max_open_orders=settings.polymarket_live_max_open_orders,
        log_level=settings.log_level,
        funder_address_configured=bool(settings.polymarket_funder_address),
        private_key_configured=settings.polymarket_private_key is not None,
        wallet_address_configured=bool(settings.polymarket_wallet_address),
        trading_mode=settings.trading_mode,
    )


def build_operator_status(
    *,
    settings: AppSettings,
    kill_switch: KillSwitch | None = None,
    clock: Clock = utc_now,
) -> OperatorStatus:
    runtime = build_runtime_safety_metrics(settings)
    active_kill_switch = kill_switch or KillSwitch()
    warnings = _operator_warnings(settings, active_kill_switch)
    tiny_ready = not warnings and settings.live_trading_allowed
    return OperatorStatus(
        status="ok" if not warnings else "blocked",
        timestamp=clock(),
        runtime=runtime,
        kill_switch_active=active_kill_switch.is_active(),
        kill_switch_reason=active_kill_switch.reason,
        tiny_live_orders_ready=tiny_ready,
        warnings=warnings,
    )


def build_orderbook_metrics(orderbook: LocalOrderBook) -> OrderBookMetrics:
    return OrderBookMetrics(
        token_id=orderbook.token_id,
        best_bid=orderbook.best_bid,
        best_ask=orderbook.best_ask,
        bid_depth=orderbook.bid_depth,
        ask_depth=orderbook.ask_depth,
        bid_level_count=len(orderbook.bids),
        ask_level_count=len(orderbook.asks),
        imbalance=orderbook.orderbook_imbalance,
        microprice=orderbook.microprice,
        mid=orderbook.mid,
        spread=orderbook.spread,
    )


def build_portfolio_metrics(
    ledger: PositionLedger,
    mark_prices: dict[str, Decimal],
) -> PortfolioMetrics:
    pnl = calculate_portfolio_pnl(ledger, mark_prices)
    return PortfolioMetrics(
        cash=pnl.cash,
        gross_market_value=pnl.gross_market_value,
        realized_pnl=pnl.realized_pnl,
        total_equity=pnl.total_equity,
        unrealized_pnl=pnl.unrealized_pnl,
        position_count=len(ledger.positions),
    )


def _operator_warnings(
    settings: AppSettings,
    kill_switch: KillSwitch,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if settings.trading_mode != TradingMode.LIVE:
        warnings.append("TRADING_MODE is not LIVE")
    if not settings.live_trading_enabled:
        warnings.append("LIVE_TRADING_ENABLED is false")
    if not settings.polymarket_live_token_allowlist:
        warnings.append("POLYMARKET_LIVE_TOKEN_ALLOWLIST is empty")
    if settings.polymarket_private_key is None:
        warnings.append("POLYMARKET_PRIVATE_KEY is not configured")
    if settings.polymarket_funder_address is None:
        warnings.append("POLYMARKET_FUNDER_ADDRESS is not configured")
    if kill_switch.is_active():
        warnings.append("kill switch is active")
    return tuple(warnings)


def _decimal_or_none(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)
