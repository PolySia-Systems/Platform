from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pm_trader.adapters.geoblock import (
    GeoblockStatus,
    PreLiveOrderGeoblockCheck,
    PreLiveOrderGeoblockError,
)
from pm_trader.adapters.polymarket_secure import (
    BalanceAssetType,
    MarketOrderType,
    OrderSide,
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.risk.checks import RiskEngine

SmokeOutcome = Literal["YES", "NO"]
SmokeSide = Literal["BUY", "SELL"]
SmokeOrderType = Literal["FAK", "FOK"]
SmokeFinalResult = Literal["PASS", "FAIL", "ABORTED"]
Clock = Callable[[], datetime]
GitReader = Callable[[Path, tuple[str, ...]], str]

MAX_SMOKE_NOTIONAL = Decimal("1.00")


def utc_now() -> datetime:
    return datetime.now(UTC)


class LiveSmokeTestError(RuntimeError):
    """Raised for guarded live smoke-test aborts."""


class LiveSmokeAdapter(Protocol):
    @property
    def is_connected(self) -> bool:
        """Whether the authenticated adapter is connected."""

    async def connect(self) -> None:
        """Connect to authenticated Polymarket APIs."""

    async def close(self) -> None:
        """Close authenticated resources."""

    async def get_balance_allowance(
        self,
        *,
        asset_type: BalanceAssetType,
        token_id: str | None = None,
    ) -> Any:
        """Fetch account balance and approval metadata."""

    async def get_market(self, *, id: str | None = None, slug: str | None = None) -> Any:
        """Fetch market metadata."""

    async def get_order_book(self, *, token_id: str) -> Any:
        """Fetch CLOB order book."""

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        """Fetch account positions."""

    async def list_account_trades(
        self,
        *,
        token_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        """Fetch account trades."""

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        """Fetch open orders."""

    async def cancel_order(self, *, order_id: str) -> Any:
        """Cancel one order."""

    async def place_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | None = None,
        shares: Decimal | None = None,
        max_spend: Decimal | None = None,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> Any:
        """Submit one marketable FAK/FOK order."""


class SmokeGeoblockCheck(Protocol):
    async def check(self) -> GeoblockStatus:
        """Return a sanitized geoblock status."""


@dataclass(frozen=True, slots=True)
class LiveSmokeTestConfig:
    settings: AppSettings
    market_slug: str
    condition_id: str
    token_id: str
    outcome: SmokeOutcome
    side: SmokeSide
    max_notional: Decimal = Decimal("1.00")
    order_type: SmokeOrderType = "FAK"
    max_slippage_bps: int = 200
    dry_run: bool = True
    require_clean_git: bool = False
    acknowledgement: bool = False
    project_root: Path = Path(".")
    report_json_path: Path = Path("live_smoke_test.json")
    report_markdown_path: Path = Path("live_smoke_test.md")


@dataclass(frozen=True, slots=True)
class LiveSmokeTestReport:
    timestamp: datetime
    git_commit: str | None
    dry_run: bool
    geoblock_status: dict[str, object] | None
    selected_market: dict[str, object]
    selected_token: str
    side: SmokeSide
    outcome: SmokeOutcome
    max_notional: str
    tick_size: str | None
    min_order_size: str | None
    best_bid: str | None
    best_ask: str | None
    computed_limit_price: str | None
    order_type: SmokeOrderType
    order_submitted: bool
    order_id: str | None
    response_status: str | None
    filled_size: str | None
    average_fill_price: str | None
    residual_open_order: bool
    cancel_attempted: bool
    final_position: dict[str, object] | None
    errors: tuple[str, ...]
    final_result: SmokeFinalResult

    def to_dict(self) -> dict[str, object]:
        return {
            "average_fill_price": self.average_fill_price,
            "best_ask": self.best_ask,
            "best_bid": self.best_bid,
            "cancel_attempted": self.cancel_attempted,
            "computed_limit_price": self.computed_limit_price,
            "dry_run": self.dry_run,
            "errors": list(self.errors),
            "filled_size": self.filled_size,
            "final_position": self.final_position,
            "final_result": self.final_result,
            "geoblock_status": self.geoblock_status,
            "git_commit": self.git_commit,
            "max_notional": self.max_notional,
            "min_order_size": self.min_order_size,
            "order_id": self.order_id,
            "order_submitted": self.order_submitted,
            "order_type": self.order_type,
            "outcome": self.outcome,
            "residual_open_order": self.residual_open_order,
            "response_status": self.response_status,
            "selected_market": self.selected_market,
            "selected_token": self.selected_token,
            "side": self.side,
            "tick_size": self.tick_size,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SmokeOrderPlan:
    computed_limit_price: Decimal
    worst_case_notional: Decimal
    amount: Decimal | None
    shares: Decimal | None


class OneOrderAttemptGuard:
    """Enforces the one-live-order-attempt invariant."""

    def __init__(self) -> None:
        self.attempts = 0

    async def place_market_order_once(
        self,
        adapter: LiveSmokeAdapter,
        *,
        token_id: str,
        side: SmokeSide,
        amount: Decimal | None,
        shares: Decimal | None,
        max_price: Decimal | None,
        min_price: Decimal | None,
        order_type: SmokeOrderType,
    ) -> Any:
        if self.attempts >= 1:
            raise LiveSmokeTestError("one-order-attempt invariant violated.")
        self.attempts += 1
        return await adapter.place_market_order(
            token_id=token_id,
            side=cast(OrderSide, side),
            amount=amount,
            shares=shares,
            max_price=max_price,
            min_price=min_price,
            order_type=cast(MarketOrderType, order_type),
        )


async def run_live_smoke_test(
    config: LiveSmokeTestConfig,
    *,
    adapter: LiveSmokeAdapter | None = None,
    geoblock_check: SmokeGeoblockCheck | None = None,
    risk_engine: RiskEngine | None = None,
    clock: Clock = utc_now,
    git_reader: GitReader | None = None,
) -> LiveSmokeTestReport:
    """Run one guarded connectivity smoke test and always write an audit report."""

    active_adapter = adapter or PolymarketSecureAdapter()
    active_geoblock_check = geoblock_check or PreLiveOrderGeoblockCheck()
    active_risk_engine = risk_engine or RiskEngine()
    errors: list[str] = []
    geoblock_status: dict[str, object] | None = None
    selected_market: dict[str, object] = {"slug": config.market_slug}
    tick_size: Decimal | None = None
    min_order_size: Decimal | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    computed_limit_price: Decimal | None = None
    order_submitted = False
    order_id: str | None = None
    response_status: str | None = None
    filled_size: Decimal | None = None
    average_fill_price: Decimal | None = None
    residual_open_order = False
    cancel_attempted = False
    final_position: dict[str, object] | None = None
    final_result: SmokeFinalResult = "ABORTED"
    git_commit = _git_commit(config.project_root, git_reader=git_reader)

    try:
        _validate_static_config(config)
        _assert_live_gates(config, active_risk_engine, git_reader=git_reader)

        if not active_adapter.is_connected:
            await active_adapter.connect()

        collateral = await active_adapter.get_balance_allowance(asset_type="COLLATERAL")
        _assert_balance_allowance_ready(collateral, side=config.side)

        status = await active_geoblock_check.check()
        geoblock_status = status.to_safe_dict()
        _assert_geoblock_status_allows_live(status)

        market = await active_adapter.get_market(slug=config.market_slug)
        selected_market = _safe_market_summary(market, config)
        _assert_market_open(market)

        order_book = await active_adapter.get_order_book(token_id=config.token_id)
        _assert_market_and_token_match(market, order_book, config)

        tick_size = _decimal_field(order_book, "tick_size") or _market_trading_decimal(
            market, "minimum_tick_size"
        )
        min_order_size = _decimal_field(order_book, "min_order_size") or _market_trading_decimal(
            market, "minimum_order_size"
        )
        if tick_size is None or tick_size <= 0:
            raise LiveSmokeTestError("CLOB tick_size is missing or invalid.")
        if min_order_size is None or min_order_size <= 0:
            raise LiveSmokeTestError("CLOB min_order_size is missing or invalid.")

        best_bid, best_ask = _best_bid_ask(order_book)
        plan = _build_order_plan(
            side=config.side,
            max_notional=config.max_notional,
            max_slippage_bps=config.max_slippage_bps,
            tick_size=tick_size,
            min_order_size=min_order_size,
            best_bid=best_bid,
            best_ask=best_ask,
        )
        computed_limit_price = plan.computed_limit_price
        if plan.worst_case_notional > config.max_notional:
            raise LiveSmokeTestError("Worst-case notional exceeds max_notional; aborting.")

        positions = await active_adapter.list_positions(
            market=(config.condition_id,),
            size_threshold=0,
        )
        if config.side == "SELL":
            conditional = await active_adapter.get_balance_allowance(
                asset_type="CONDITIONAL",
                token_id=config.token_id,
            )
            _assert_balance_allowance_ready(conditional, side=config.side)
            position_size = _position_size(positions, config.token_id)
            if plan.shares is None or position_size < plan.shares:
                raise LiveSmokeTestError("SELL smoke test requires enough existing shares.")

        if config.dry_run:
            final_position = _safe_position_for_token(positions, config.token_id)
            final_result = "PASS"
        else:
            guard = OneOrderAttemptGuard()
            response = await guard.place_market_order_once(
                active_adapter,
                token_id=config.token_id,
                side=config.side,
                amount=plan.amount,
                shares=plan.shares,
                max_price=plan.computed_limit_price if config.side == "BUY" else None,
                min_price=plan.computed_limit_price if config.side == "SELL" else None,
                order_type=config.order_type,
            )
            order_submitted = True
            response_payload = _model_or_mapping_to_dict(response)
            order_id = _string_or_none(response_payload.get("order_id"))
            response_status = _string_or_none(response_payload.get("status"))
            _assert_response_not_rejected(response_payload)

            open_orders = await active_adapter.get_open_orders(token_id=config.token_id)
            residual_orders = _residual_orders(open_orders, order_id)
            residual_open_order = bool(residual_orders)
            if residual_orders:
                cancel_attempted = True
                for open_order in residual_orders:
                    await active_adapter.cancel_order(order_id=_read_required_order_id(open_order))

            trades = await active_adapter.list_account_trades(token_id=config.token_id)
            filled_size, average_fill_price = _fill_summary(trades, order_id=order_id)
            final_positions = await active_adapter.list_positions(
                market=(config.condition_id,),
                size_threshold=0,
            )
            final_position = _safe_position_for_token(final_positions, config.token_id)
            final_result = "PASS"
    except (
        LiveSmokeTestError,
        PolymarketSecureAdapterError,
        PreLiveOrderGeoblockError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        errors.append(str(error))
        final_result = "FAIL" if order_submitted else "ABORTED"
    finally:
        await active_adapter.close()

    report = LiveSmokeTestReport(
        timestamp=clock(),
        git_commit=git_commit,
        dry_run=config.dry_run,
        geoblock_status=geoblock_status,
        selected_market=selected_market,
        selected_token=config.token_id,
        side=config.side,
        outcome=config.outcome,
        max_notional=str(config.max_notional),
        tick_size=_decimal_to_str(tick_size),
        min_order_size=_decimal_to_str(min_order_size),
        best_bid=_decimal_to_str(best_bid),
        best_ask=_decimal_to_str(best_ask),
        computed_limit_price=_decimal_to_str(computed_limit_price),
        order_type=config.order_type,
        order_submitted=order_submitted,
        order_id=order_id,
        response_status=response_status,
        filled_size=_decimal_to_str(filled_size),
        average_fill_price=_decimal_to_str(average_fill_price),
        residual_open_order=residual_open_order,
        cancel_attempted=cancel_attempted,
        final_position=final_position,
        errors=tuple(errors),
        final_result=final_result,
    )
    write_live_smoke_report(report, config.report_json_path, config.report_markdown_path)
    return report


def write_live_smoke_report(
    report: LiveSmokeTestReport,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        f"{json.dumps(report.to_dict(), indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown_report(report), encoding="utf-8")


def _validate_static_config(config: LiveSmokeTestConfig) -> None:
    if not config.market_slug.strip():
        raise LiveSmokeTestError("--market-slug is required.")
    if not config.condition_id.strip():
        raise LiveSmokeTestError("--condition-id is required.")
    if not config.token_id.strip():
        raise LiveSmokeTestError("--token-id is required.")
    if config.outcome not in ("YES", "NO"):
        raise LiveSmokeTestError("--outcome must be YES or NO.")
    if config.side not in ("BUY", "SELL"):
        raise LiveSmokeTestError("--side must be BUY or SELL.")
    if config.order_type not in ("FAK", "FOK"):
        raise LiveSmokeTestError("live-smoke-test only supports FAK or FOK orders.")
    if config.max_notional <= 0:
        raise LiveSmokeTestError("--max-notional must be positive.")
    if config.max_notional > MAX_SMOKE_NOTIONAL:
        raise LiveSmokeTestError("--max-notional above 1.00 is rejected.")
    if config.max_slippage_bps < 0:
        raise LiveSmokeTestError("--max-slippage-bps must not be negative.")


def _assert_live_gates(
    config: LiveSmokeTestConfig,
    risk_engine: RiskEngine,
    *,
    git_reader: GitReader | None,
) -> None:
    if config.dry_run:
        return
    if config.settings.trading_mode != TradingMode.LIVE:
        raise LiveSmokeTestError("live smoke order requires TRADING_MODE=LIVE.")
    if not config.settings.live_trading_enabled:
        raise LiveSmokeTestError("live smoke order requires LIVE_TRADING_ENABLED=true.")
    if not config.acknowledgement:
        raise LiveSmokeTestError(
            "live smoke order requires --i-understand-this-places-a-real-order."
        )
    if risk_engine.kill_switch.is_active():
        reason = risk_engine.kill_switch.reason or "kill switch active"
        raise LiveSmokeTestError(f"live smoke order blocked by kill switch: {reason}")
    if not config.settings.polymarket_live_token_allowlist:
        raise LiveSmokeTestError("live smoke order requires POLYMARKET_LIVE_TOKEN_ALLOWLIST.")
    if not config.settings.polymarket_funder_address:
        raise LiveSmokeTestError(
            "live smoke order requires POLYMARKET_FUNDER_ADDRESS for the "
            "Polymarket trading proxy/funder wallet."
        )
    if config.token_id not in config.settings.polymarket_live_token_allowlist:
        raise LiveSmokeTestError("selected token_id is not in POLYMARKET_LIVE_TOKEN_ALLOWLIST.")
    if config.require_clean_git and _git_status(config.project_root, git_reader=git_reader).strip():
        raise LiveSmokeTestError("Repository has uncommitted changes.")


def _assert_balance_allowance_ready(balance_allowance: Any, *, side: SmokeSide) -> None:
    payload = _model_or_mapping_to_dict(balance_allowance)
    balance = _decimal_or_none(payload.get("balance"))
    allowances = payload.get("allowances")
    has_allowance = False
    if isinstance(allowances, dict):
        for value in allowances.values():
            parsed_allowance = _decimal_or_none(value)
            if parsed_allowance is not None and parsed_allowance > 0:
                has_allowance = True
                break
    if side == "BUY" and (balance is None or balance <= 0):
        raise LiveSmokeTestError("Account collateral balance is not available for smoke test.")
    if not has_allowance:
        raise LiveSmokeTestError("Trading approval allowance is missing or zero.")


def _assert_geoblock_status_allows_live(status: GeoblockStatus) -> None:
    if status.status == "allowed" and status.blocked is False:
        return
    if status.status == "blocked" or status.blocked is True:
        raise LiveSmokeTestError("Polymarket geoblock returned blocked=true.")
    raise LiveSmokeTestError("Polymarket geoblock check failed closed.")


def _assert_market_open(market: Any) -> None:
    state = _read_field(market, "state")
    active = _read_nested_bool(state, "active")
    closed = _read_nested_bool(state, "closed")
    accepting_orders = _read_nested_bool(state, "accepting_orders")
    if active is not True:
        raise LiveSmokeTestError("Selected market is not active.")
    if closed is True:
        raise LiveSmokeTestError("Selected market is closed.")
    if accepting_orders is False:
        raise LiveSmokeTestError("Selected market is not accepting orders.")


def _assert_market_and_token_match(
    market: Any,
    order_book: Any,
    config: LiveSmokeTestConfig,
) -> None:
    market_condition_id = _string_or_none(_read_field(market, "condition_id"))
    clob_condition_id = _string_or_none(_read_field(order_book, "market"))
    if market_condition_id is not None and market_condition_id != config.condition_id:
        raise LiveSmokeTestError("condition_id does not match selected market metadata.")
    if clob_condition_id is not None and clob_condition_id != config.condition_id:
        raise LiveSmokeTestError("condition_id does not match selected CLOB order book.")
    if _string_or_none(_read_field(order_book, "token_id")) != config.token_id:
        raise LiveSmokeTestError("token_id does not match selected CLOB order book.")
    if config.token_id not in _market_token_ids(market):
        raise LiveSmokeTestError("token_id does not belong to selected market outcomes.")


def _build_order_plan(
    *,
    side: SmokeSide,
    max_notional: Decimal,
    max_slippage_bps: int,
    tick_size: Decimal,
    min_order_size: Decimal,
    best_bid: Decimal | None,
    best_ask: Decimal | None,
) -> SmokeOrderPlan:
    slippage_multiplier = Decimal(max_slippage_bps) / Decimal("10000")
    if side == "BUY":
        if best_ask is None:
            raise LiveSmokeTestError("Order book has no ask for BUY smoke test.")
        raw_price = best_ask * (Decimal("1") + slippage_multiplier)
        price = min(Decimal("1"), _quantize_to_tick(raw_price, tick_size, rounding=ROUND_CEILING))
        return SmokeOrderPlan(
            computed_limit_price=price,
            worst_case_notional=max_notional,
            amount=max_notional,
            shares=None,
        )

    if best_bid is None:
        raise LiveSmokeTestError("Order book has no bid for SELL smoke test.")
    raw_price = best_bid * (Decimal("1") - slippage_multiplier)
    price = max(tick_size, _quantize_to_tick(raw_price, tick_size, rounding=ROUND_FLOOR))
    worst_case_notional = min_order_size * price
    return SmokeOrderPlan(
        computed_limit_price=price,
        worst_case_notional=worst_case_notional,
        amount=None,
        shares=min_order_size,
    )


def _best_bid_ask(order_book: Any) -> tuple[Decimal | None, Decimal | None]:
    bids = [_decimal_field(level, "price") for level in _read_levels(order_book, "bids")]
    asks = [_decimal_field(level, "price") for level in _read_levels(order_book, "asks")]
    valid_bids = [price for price in bids if price is not None]
    valid_asks = [price for price in asks if price is not None]
    return (max(valid_bids) if valid_bids else None, min(valid_asks) if valid_asks else None)


def _read_levels(order_book: Any, field_name: str) -> list[Any]:
    levels = _read_field(order_book, field_name)
    if levels is None:
        return []
    if isinstance(levels, list):
        return levels
    if isinstance(levels, tuple):
        return list(levels)
    return []


def _quantize_to_tick(price: Decimal, tick_size: Decimal, *, rounding: str) -> Decimal:
    ticks = (price / tick_size).to_integral_value(rounding=rounding)
    return ticks * tick_size


def _assert_response_not_rejected(response: dict[str, object]) -> None:
    if response.get("ok", True) is False:
        code = response.get("code", "unknown")
        message = response.get("message", "order rejected")
        raise LiveSmokeTestError(f"Polymarket rejected smoke order: {code}: {message}")


def _residual_orders(open_orders: list[Any], order_id: str | None) -> list[Any]:
    if order_id is None:
        return []
    return [
        order
        for order in open_orders
        if _string_or_none(_read_field(order, "id")) == order_id
        and _string_or_none(_read_field(order, "status")) not in {"canceled", "filled"}
    ]


def _read_required_order_id(order: Any) -> str:
    order_id = _string_or_none(_read_field(order, "id"))
    if order_id is None:
        raise LiveSmokeTestError("Residual open order did not include an order id.")
    return order_id


def _fill_summary(
    trades: list[Any],
    *,
    order_id: str | None,
) -> tuple[Decimal | None, Decimal | None]:
    if order_id is None:
        return None, None
    matched = [
        trade
        for trade in trades
        if _string_or_none(_read_field(trade, "taker_order_id")) == order_id
        or _trade_has_maker_order(trade, order_id)
    ]
    sizes = [_decimal_field(trade, "size") for trade in matched]
    prices = [_decimal_field(trade, "price") for trade in matched]
    pairs = [
        (size, price)
        for size, price in zip(sizes, prices, strict=False)
        if size is not None and price is not None
    ]
    if not pairs:
        return None, None
    total_size = sum((size for size, _price in pairs), Decimal("0"))
    if total_size <= 0:
        return None, None
    total_value = sum((size * price for size, price in pairs), Decimal("0"))
    return total_size, total_value / total_size


def _trade_has_maker_order(trade: Any, order_id: str) -> bool:
    maker_orders = _read_field(trade, "maker_orders")
    if not isinstance(maker_orders, (list, tuple)):
        return False
    return any(
        _string_or_none(_read_field(order, "order_id")) == order_id
        for order in maker_orders
    )


def _position_size(positions: list[Any], token_id: str) -> Decimal:
    total = Decimal("0")
    for position in positions:
        if _string_or_none(_read_field(position, "token_id")) != token_id:
            continue
        size = _decimal_field(position, "size")
        if size is not None:
            total += size
    return total


def _safe_position_for_token(positions: list[Any], token_id: str) -> dict[str, object] | None:
    for position in positions:
        if _string_or_none(_read_field(position, "token_id")) != token_id:
            continue
        return {
            "avg_price": _decimal_to_str(_decimal_field(position, "avg_price")),
            "current_value": _decimal_to_str(_decimal_field(position, "current_value")),
            "outcome": _string_or_none(_read_field(position, "outcome")),
            "size": _decimal_to_str(_decimal_field(position, "size")),
            "token_id": token_id,
        }
    return None


def _safe_market_summary(market: Any, config: LiveSmokeTestConfig) -> dict[str, object]:
    return {
        "active": _read_nested_bool(_read_field(market, "state"), "active"),
        "accepting_orders": _read_nested_bool(_read_field(market, "state"), "accepting_orders"),
        "closed": _read_nested_bool(_read_field(market, "state"), "closed"),
        "condition_id": _string_or_none(_read_field(market, "condition_id")),
        "question": _string_or_none(_read_field(market, "question")),
        "slug": _string_or_none(_read_field(market, "slug")) or config.market_slug,
    }


def _market_token_ids(market: Any) -> set[str]:
    outcomes = _read_field(market, "outcomes")
    token_ids: set[str] = set()
    if outcomes is None:
        return token_ids
    for outcome in _iter_outcomes(outcomes):
        token_id = _string_or_none(_read_field(outcome, "token_id"))
        if token_id is not None:
            token_ids.add(token_id)
    return token_ids


def _iter_outcomes(outcomes: Any) -> list[Any]:
    if isinstance(outcomes, dict):
        return list(outcomes.values())
    if isinstance(outcomes, (list, tuple)):
        return list(outcomes)
    collected = []
    for name in ("yes", "no"):
        outcome = getattr(outcomes, name, None)
        if outcome is not None:
            collected.append(outcome)
    return collected


def _market_trading_decimal(market: Any, field_name: str) -> Decimal | None:
    trading = _read_field(market, "trading")
    return _decimal_field(trading, field_name)


def _decimal_field(source: Any, field_name: str) -> Decimal | None:
    return _decimal_or_none(_read_field(source, field_name))


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ValueError:
            return None
    return None


def _read_nested_bool(source: Any, field_name: str) -> bool | None:
    value = _read_field(source, field_name)
    return value if isinstance(value, bool) else None


def _read_field(source: Any, field_name: str) -> object:
    if source is None:
        return None
    if hasattr(source, "model_dump"):
        data = source.model_dump(mode="python")
        return data.get(field_name)
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def _model_or_mapping_to_dict(source: object) -> dict[str, object]:
    if hasattr(source, "model_dump"):
        return dict(source.model_dump(mode="python"))
    if isinstance(source, dict):
        return dict(source)
    return {
        field_name: getattr(source, field_name)
        for field_name in dir(source)
        if not field_name.startswith("_") and not callable(getattr(source, field_name))
    }


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _decimal_to_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _git_commit(project_root: Path, *, git_reader: GitReader | None) -> str | None:
    try:
        return _run_git(project_root, ("git", "rev-parse", "--short", "HEAD"), git_reader).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _git_status(project_root: Path, *, git_reader: GitReader | None) -> str:
    return _run_git(project_root, ("git", "status", "--short"), git_reader)


def _run_git(project_root: Path, command: tuple[str, ...], git_reader: GitReader | None) -> str:
    root = project_root.resolve()
    if git_reader is not None:
        return git_reader(root, command)
    result = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        cwd=root,
        text=True,
        timeout=5,
    )
    return result.stdout


def _render_markdown_report(report: LiveSmokeTestReport) -> str:
    payload = report.to_dict()
    lines = [
        "# Polymarket Live Smoke Test",
        "",
        f"- Final result: {report.final_result}",
        f"- Dry run: {report.dry_run}",
        f"- Git commit: {report.git_commit}",
        f"- Market: {payload['selected_market']}",
        f"- Token: {report.selected_token}",
        f"- Side/outcome: {report.side} {report.outcome}",
        f"- Max notional: {report.max_notional}",
        f"- Order type: {report.order_type}",
        f"- Geoblock: {report.geoblock_status}",
        f"- Best bid/ask: {report.best_bid} / {report.best_ask}",
        f"- Limit price: {report.computed_limit_price}",
        f"- Submitted: {report.order_submitted}",
        f"- Order id: {report.order_id}",
        f"- Response status: {report.response_status}",
        f"- Filled size: {report.filled_size}",
        f"- Average fill price: {report.average_fill_price}",
        f"- Residual open order: {report.residual_open_order}",
        f"- Cancel attempted: {report.cancel_attempted}",
        f"- Final position: {report.final_position}",
        "",
        "## Errors",
        "",
    ]
    if report.errors:
        lines.extend(f"- {error}" for error in report.errors)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)
