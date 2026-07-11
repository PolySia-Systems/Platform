from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from pm_trader.adapters.geoblock import (
    GeoblockStatus,
    PreLiveOrderGeoblockCheck,
    PreLiveOrderGeoblockError,
)
from pm_trader.adapters.polymarket_secure import (
    MarketOrderType,
    PolymarketSecureAdapter,
    sanitize_order_request,
)
from pm_trader.config.logging import get_logger
from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.execution.intents import ApprovedOrderIntent, OrderIntent
from pm_trader.risk.checks import RiskContext, RiskEngine

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class LiveOrderGeoblockCheck(Protocol):
    async def assert_allowed(self) -> GeoblockStatus:
        """Return when live order placement is geoblock-eligible."""


class LiveBrokerError(RuntimeError):
    """Raised when a live broker action is blocked or fails."""


@dataclass(frozen=True, slots=True)
class LiveBrokerResult:
    """Result of a live broker request or dry-run preview."""

    submitted: bool
    dry_run: bool
    request: dict[str, object]
    reason: str
    response: Any | None = None


class LiveBroker:
    """Authenticated broker guarded by settings, risk, kill switch, and confirmation."""

    def __init__(
        self,
        *,
        adapter: PolymarketSecureAdapter,
        risk_engine: RiskEngine,
        settings: AppSettings | None = None,
        allowed_token_ids: tuple[str, ...] = (),
        geoblock_check: LiveOrderGeoblockCheck | None = None,
        clock: Clock = utc_now,
        logger: Any | None = None,
    ) -> None:
        self._adapter = adapter
        self._risk_engine = risk_engine
        self._settings = settings or AppSettings()
        self._allowed_token_ids = frozenset(
            token_id.strip() for token_id in allowed_token_ids if token_id.strip()
        )
        self._geoblock_check = geoblock_check or PreLiveOrderGeoblockCheck()
        self._clock = clock
        self._logger = logger or get_logger(__name__)

    async def get_open_orders(
        self,
        *,
        i_understand_this_uses_live_account: bool,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> LiveBrokerResult:
        """Fetch authenticated open orders after an explicit live-account gate."""
        self._assert_live_account_read_allowed(
            i_understand_this_uses_live_account=i_understand_this_uses_live_account
        )
        request = sanitize_order_request(
            action="get_open_orders",
            token_id=token_id,
            order_id=order_id,
            market=market,
        )

        if not self._adapter.is_connected:
            await self._adapter.connect()

        orders = await self._adapter.get_open_orders(
            token_id=token_id,
            order_id=order_id,
            market=market,
        )
        return LiveBrokerResult(
            submitted=False,
            dry_run=False,
            request=request,
            reason="read",
            response=orders,
        )

    async def cancel_order(
        self,
        *,
        order_id: str,
        i_understand_this_modifies_live_orders: bool,
        dry_run: bool = True,
    ) -> LiveBrokerResult:
        """Cancel one live order, defaulting to a sanitized dry-run preview."""
        self._assert_live_account_write_allowed(
            i_understand_this_modifies_live_orders=i_understand_this_modifies_live_orders
        )
        request = sanitize_order_request(action="cancel_order", order_id=order_id)

        if dry_run:
            self._log_dry_run(request)
            return LiveBrokerResult(
                submitted=False,
                dry_run=True,
                request=request,
                reason="dry run; no cancel submitted",
            )

        if not self._adapter.is_connected:
            await self._adapter.connect()

        response = await self._adapter.cancel_order(order_id=order_id)
        return LiveBrokerResult(
            submitted=True,
            dry_run=False,
            request=request,
            reason="cancel submitted",
            response=response,
        )

    async def cancel_market_orders(
        self,
        *,
        i_understand_this_modifies_live_orders: bool,
        token_id: str | None = None,
        market: str | None = None,
        dry_run: bool = True,
    ) -> LiveBrokerResult:
        """Cancel live orders for one token, defaulting to a sanitized dry-run preview."""
        if token_id is None and market is None:
            raise LiveBrokerError("cancel_market_orders requires token_id or market.")

        self._assert_live_account_write_allowed(
            i_understand_this_modifies_live_orders=i_understand_this_modifies_live_orders
        )
        request = sanitize_order_request(
            action="cancel_market_orders",
            token_id=token_id,
            market=market,
        )

        if dry_run:
            self._log_dry_run(request)
            return LiveBrokerResult(
                submitted=False,
                dry_run=True,
                request=request,
                reason="dry run; no cancel submitted",
            )

        if token_id is None:
            raise LiveBrokerError(
                "actual market-wide cancel requires token_id allowlist in this phase."
            )
        self._assert_token_allowed(token_id)

        if not self._adapter.is_connected:
            await self._adapter.connect()

        response = await self._adapter.cancel_market_orders(token_id=token_id, market=market)
        return LiveBrokerResult(
            submitted=True,
            dry_run=False,
            request=request,
            reason="cancel submitted",
            response=response,
        )

    async def place_limit_order(
        self,
        intent: OrderIntent,
        context: RiskContext,
        *,
        i_understand_this_places_real_orders: bool,
        dry_run: bool = True,
        post_only: bool = False,
        expiration: int | None = None,
        builder_code: str | None = None,
    ) -> LiveBrokerResult:
        """Approve, preview, or submit a live limit order."""
        approved_intent = self._approve_intent(
            intent,
            context,
            i_understand_this_places_real_orders=i_understand_this_places_real_orders,
        )
        request = sanitize_order_request(
            action="place_limit_order",
            token_id=approved_intent.token_id,
            side=approved_intent.side,
            price=approved_intent.price,
            size=approved_intent.approved_size,
            post_only=post_only,
            expiration=expiration,
        )

        if dry_run:
            self._log_dry_run(request)
            return LiveBrokerResult(
                submitted=False,
                dry_run=True,
                request=request,
                reason="dry run; no order submitted",
            )

        self._assert_token_allowed(approved_intent.token_id)
        await self._assert_geoblock_allowed()

        if not self._adapter.is_connected:
            await self._adapter.connect()

        response = await self._adapter.place_limit_order(
            token_id=approved_intent.token_id,
            side=approved_intent.side,
            price=approved_intent.price,
            size=approved_intent.approved_size,
            post_only=post_only,
            expiration=expiration,
            builder_code=builder_code,
        )
        _assert_order_response_ok(response)
        return LiveBrokerResult(
            submitted=True,
            dry_run=False,
            request=request,
            reason="submitted",
            response=response,
        )

    async def place_market_order(
        self,
        intent: OrderIntent,
        context: RiskContext,
        *,
        i_understand_this_places_real_orders: bool,
        dry_run: bool = True,
        amount: Decimal | None = None,
        shares: Decimal | None = None,
        max_spend: Decimal | None = None,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> LiveBrokerResult:
        """Approve, preview, or submit a live market order."""
        approved_intent = self._approve_intent(
            intent,
            context,
            i_understand_this_places_real_orders=i_understand_this_places_real_orders,
        )
        shares = shares if shares is not None else approved_intent.approved_size
        request = sanitize_order_request(
            action="place_market_order",
            token_id=approved_intent.token_id,
            side=approved_intent.side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            max_price=max_price,
            min_price=min_price,
            order_type=order_type,
        )

        if dry_run:
            self._log_dry_run(request)
            return LiveBrokerResult(
                submitted=False,
                dry_run=True,
                request=request,
                reason="dry run; no order submitted",
            )

        self._assert_token_allowed(approved_intent.token_id)
        await self._assert_geoblock_allowed()

        if not self._adapter.is_connected:
            await self._adapter.connect()

        response = await self._adapter.place_market_order(
            token_id=approved_intent.token_id,
            side=approved_intent.side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            max_price=max_price,
            min_price=min_price,
            order_type=order_type,
            builder_code=builder_code,
        )
        _assert_order_response_ok(response)
        return LiveBrokerResult(
            submitted=True,
            dry_run=False,
            request=request,
            reason="submitted",
            response=response,
        )

    def _approve_intent(
        self,
        intent: OrderIntent,
        context: RiskContext,
        *,
        i_understand_this_places_real_orders: bool,
    ) -> ApprovedOrderIntent:
        self._assert_live_start_allowed(
            i_understand_this_places_real_orders=i_understand_this_places_real_orders
        )
        risk_context = replace(
            context,
            trading_mode=self._settings.trading_mode,
            live_trading_enabled=self._settings.live_trading_enabled,
        )
        decision = self._risk_engine.evaluate(intent, risk_context)
        if not decision.approved:
            raise LiveBrokerError(f"risk engine blocked live order: {decision.reason}")

        return ApprovedOrderIntent(
            intent=intent,
            approved_size=decision.adjusted_size or intent.size,
            risk_reason=decision.reason,
            approved_at=self._clock(),
        )

    def _assert_live_start_allowed(
        self,
        *,
        i_understand_this_places_real_orders: bool,
    ) -> None:
        if self._settings.trading_mode != TradingMode.LIVE:
            raise LiveBrokerError("live broker requires TRADING_MODE=LIVE.")
        if not self._settings.live_trading_enabled:
            raise LiveBrokerError("live broker requires LIVE_TRADING_ENABLED=true.")
        if self._risk_engine.kill_switch.is_active():
            reason = self._risk_engine.kill_switch.reason or "kill switch active"
            raise LiveBrokerError(f"live broker blocked by kill switch: {reason}")
        if not i_understand_this_places_real_orders:
            raise LiveBrokerError(
                "live broker requires --i-understand-this-places-real-orders."
            )

    def _assert_live_account_read_allowed(
        self,
        *,
        i_understand_this_uses_live_account: bool,
    ) -> None:
        if self._settings.trading_mode != TradingMode.LIVE:
            raise LiveBrokerError("live account reads require TRADING_MODE=LIVE.")
        if not i_understand_this_uses_live_account:
            raise LiveBrokerError(
                "live account reads require --i-understand-this-uses-live-account."
            )

    def _assert_live_account_write_allowed(
        self,
        *,
        i_understand_this_modifies_live_orders: bool,
    ) -> None:
        if self._settings.trading_mode != TradingMode.LIVE:
            raise LiveBrokerError("live account writes require TRADING_MODE=LIVE.")
        if not self._settings.live_trading_enabled:
            raise LiveBrokerError("live account writes require LIVE_TRADING_ENABLED=true.")
        if not i_understand_this_modifies_live_orders:
            raise LiveBrokerError(
                "live account writes require --i-understand-this-modifies-live-orders."
            )

    def _assert_token_allowed(self, token_id: str) -> None:
        if not self._allowed_token_ids:
            raise LiveBrokerError(
                "actual live submit/cancel requires POLYMARKET_LIVE_TOKEN_ALLOWLIST."
            )
        if token_id not in self._allowed_token_ids:
            raise LiveBrokerError(f"token_id {token_id!r} is not in the live allowlist.")

    async def _assert_geoblock_allowed(self) -> None:
        try:
            await self._geoblock_check.assert_allowed()
        except PreLiveOrderGeoblockError as error:
            raise LiveBrokerError(str(error)) from error

    def _log_dry_run(self, request: dict[str, object]) -> None:
        self._logger.info(
            "polymarket_live_dry_run",
            request=request,
        )


def _assert_order_response_ok(response: Any) -> None:
    ok = response.get("ok", True) if isinstance(response, dict) else getattr(response, "ok", True)
    if ok is True:
        return
    if isinstance(response, dict):
        code = response.get("code", "unknown")
        message = response.get("message", "order rejected")
    else:
        code = getattr(response, "code", "unknown")
        message = getattr(response, "message", "order rejected")
    raise LiveBrokerError(f"Polymarket rejected live order: {code}: {message}")
