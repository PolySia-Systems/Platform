from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pm_trader.config.settings import TradingMode
from pm_trader.execution.intents import OrderIntent
from pm_trader.risk.kill_switch import KillSwitch
from pm_trader.risk.limits import RiskLimits


@dataclass(frozen=True, slots=True)
class RiskContext:
    """State required to evaluate one order intent."""

    trading_mode: TradingMode = TradingMode.DATA_ONLY
    live_trading_enabled: bool = False
    current_position: Decimal = Decimal("0")
    current_market_position: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    open_orders_count: int = 0
    market_data_age_ms: int = 0
    edge: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reason: str
    adjusted_size: Decimal | None = None


class RiskEngine:
    """Pre-trade risk gate for strategy-generated intents."""

    def __init__(
        self,
        *,
        limits: RiskLimits | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self._limits = limits or RiskLimits()
        self._kill_switch = kill_switch or KillSwitch()

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    def evaluate(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        checks = (
            self._check_kill_switch,
            self._check_trading_mode,
            self._check_live_trading,
            self._check_order_notional,
            self._check_token_position,
            self._check_market_position,
            self._check_daily_loss,
            self._check_open_orders,
            self._check_stale_data,
            self._check_edge,
        )
        for check in checks:
            decision = check(intent, context)
            if not decision.approved:
                return decision
        return RiskDecision(approved=True, reason="approved", adjusted_size=intent.size)

    def _check_kill_switch(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if self._kill_switch.is_active():
            reason = self._kill_switch.reason or "kill switch active"
            return RiskDecision(approved=False, reason=f"kill switch active: {reason}")
        return _approved()

    def _check_trading_mode(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if context.trading_mode == TradingMode.DATA_ONLY:
            return RiskDecision(approved=False, reason="trading mode DATA_ONLY blocks orders")
        if context.trading_mode not in (TradingMode.PAPER, TradingMode.LIVE):
            return RiskDecision(
                approved=False,
                reason=f"unsupported trading mode {context.trading_mode}",
            )
        return _approved()

    def _check_live_trading(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if context.trading_mode != TradingMode.LIVE:
            return _approved()
        if not context.live_trading_enabled:
            return RiskDecision(
                approved=False,
                reason="LIVE mode requires LIVE_TRADING_ENABLED=true",
            )
        if not self._limits.allow_live_trading:
            return RiskDecision(approved=False, reason="risk limits do not allow live trading")
        return _approved()

    def _check_order_notional(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        notional = intent.price * intent.size
        if notional > self._limits.max_order_notional:
            return RiskDecision(
                approved=False,
                reason=(
                    f"order notional {notional} exceeds max_order_notional "
                    f"{self._limits.max_order_notional}"
                ),
            )
        return _approved()

    def _check_token_position(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        after_trade = _position_after_trade(
            current_position=context.current_position,
            side=intent.side,
            size=intent.size,
        )
        if abs(after_trade) > self._limits.max_position_per_token:
            return RiskDecision(
                approved=False,
                reason=(
                    f"token position {after_trade} exceeds max_position_per_token "
                    f"{self._limits.max_position_per_token}"
                ),
            )
        return _approved()

    def _check_market_position(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        after_trade = _position_after_trade(
            current_position=context.current_market_position,
            side=intent.side,
            size=intent.size,
        )
        if abs(after_trade) > self._limits.max_position_per_market:
            return RiskDecision(
                approved=False,
                reason=(
                    f"market position {after_trade} exceeds max_position_per_market "
                    f"{self._limits.max_position_per_market}"
                ),
            )
        return _approved()

    def _check_daily_loss(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if context.daily_pnl < -self._limits.max_daily_loss:
            return RiskDecision(
                approved=False,
                reason=(
                    f"daily pnl {context.daily_pnl} breaches max_daily_loss "
                    f"{self._limits.max_daily_loss}"
                ),
            )
        return _approved()

    def _check_open_orders(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if context.open_orders_count >= self._limits.max_open_orders:
            return RiskDecision(
                approved=False,
                reason=(
                    f"open orders {context.open_orders_count} reached max_open_orders "
                    f"{self._limits.max_open_orders}"
                ),
            )
        return _approved()

    def _check_stale_data(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if context.market_data_age_ms > self._limits.max_stale_data_age_ms:
            return RiskDecision(
                approved=False,
                reason=(
                    f"market data age {context.market_data_age_ms}ms exceeds "
                    f"max_stale_data_age_ms {self._limits.max_stale_data_age_ms}"
                ),
            )
        return _approved()

    def _check_edge(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if self._limits.min_edge_required == Decimal("0"):
            return _approved()
        if context.edge is None:
            return RiskDecision(approved=False, reason="edge is required by risk limits")
        if abs(context.edge) < self._limits.min_edge_required:
            return RiskDecision(
                approved=False,
                reason=(
                    f"edge {context.edge} below min_edge_required "
                    f"{self._limits.min_edge_required}"
                ),
            )
        return _approved()


def _position_after_trade(
    *,
    current_position: Decimal,
    side: str,
    size: Decimal,
) -> Decimal:
    if side == "BUY":
        return current_position + size
    if side == "SELL":
        return current_position - size
    raise ValueError(f"unsupported side {side!r}")


def _approved() -> RiskDecision:
    return RiskDecision(approved=True, reason="ok")
