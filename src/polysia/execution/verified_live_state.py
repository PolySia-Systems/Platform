from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from polysia.risk.evidence import (
    LiveStateUnavailableError,
    MeasuredDecimal,
    MeasuredInt,
    VerifiedLiveRiskSnapshot,
)


class LiveAccountStateSource(Protocol):
    """Read-only account observations used to build verified Live risk evidence."""

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]: ...

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]: ...

    async def list_account_trades(
        self,
        *,
        token_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]: ...


async def collect_verified_live_risk_snapshot(
    source: LiveAccountStateSource,
    *,
    token_id: str,
    market_id: str,
    account_source_id: str,
    market_data_observed_at: datetime,
    observed_at: datetime,
) -> VerifiedLiveRiskSnapshot:
    """Build verified Live risk evidence from authenticated read-only account data.

    Daily P&L is the realized cash effect of today's account trades. If trades or
    timestamps cannot be read, the value stays unknown and Live remains blocked.
    """

    if not account_source_id.strip():
        raise LiveStateUnavailableError("account/source identity is unavailable")
    positions = await source.list_positions(size_threshold=0)
    open_orders = await source.get_open_orders()
    trades = await source.list_account_trades()
    return snapshot_from_account_reads(
        positions=positions,
        open_orders=open_orders,
        trades=trades,
        token_id=token_id,
        market_id=market_id,
        account_source_id=account_source_id,
        market_data_observed_at=market_data_observed_at,
        observed_at=observed_at,
    )


def snapshot_from_account_reads(
    *,
    positions: list[Any],
    open_orders: list[Any],
    trades: list[Any],
    token_id: str,
    market_id: str,
    account_source_id: str,
    market_data_observed_at: datetime,
    observed_at: datetime,
) -> VerifiedLiveRiskSnapshot:
    position = _token_position_size(positions, token_id)
    market_position = _market_position_size(positions, market_id)
    daily_pnl = _daily_realized_cash_effect(trades, now=observed_at)
    return VerifiedLiveRiskSnapshot(
        current_position=MeasuredDecimal.verified(position, observed_at=observed_at),
        current_market_position=MeasuredDecimal.verified(
            market_position,
            observed_at=observed_at,
        ),
        daily_pnl=MeasuredDecimal.verified(daily_pnl, observed_at=observed_at),
        open_order_count=MeasuredInt.verified(len(open_orders), observed_at=observed_at),
        market_data_observed_at=market_data_observed_at,
        account_source_id=account_source_id,
        observed_at=observed_at,
    )


def account_source_id_from_identity(identity: object) -> str:
    if identity is None:
        raise LiveStateUnavailableError("account identity is unavailable")
    source = _text(identity, "active_wallet_source")
    wallet_type = _text(identity, "wallet_type") or "unspecified"
    if source is None:
        raise LiveStateUnavailableError("account source identity is unavailable")
    return f"{source}:{wallet_type}"


def _token_position_size(positions: list[Any], token_id: str) -> Decimal:
    total = Decimal("0")
    for position in positions:
        item_token = _text(position, "token_id", "asset")
        if item_token != token_id:
            continue
        total += _required_decimal(position, "size")
    return total


def _market_position_size(positions: list[Any], market_id: str) -> Decimal:
    total = Decimal("0")
    for position in positions:
        item_market = _text(position, "condition_id", "market", "conditionId")
        if item_market != market_id:
            continue
        total += _required_decimal(position, "size")
    return total


def _daily_realized_cash_effect(trades: list[Any], *, now: datetime) -> Decimal:
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    total = Decimal("0")
    for trade in trades:
        matched_at = _as_datetime(_field(trade, "matched_at", "matchedAt", "updated_at"))
        if matched_at is None:
            raise LiveStateUnavailableError(
                "account trade matched_at is unavailable; daily pnl is unknown"
            )
        if matched_at.tzinfo is None:
            matched_at = matched_at.replace(tzinfo=UTC)
        if matched_at < start:
            continue
        side = (_text(trade, "side") or "").upper()
        price = _required_decimal(trade, "price")
        size = _required_decimal(trade, "size")
        notional = price * size
        if side == "BUY":
            total -= notional
        elif side == "SELL":
            total += notional
        else:
            raise LiveStateUnavailableError("account trade side is unavailable")
    return total


def _required_decimal(value: object, name: str) -> Decimal:
    raw = _field(value, name)
    if raw is None:
        raise LiveStateUnavailableError(f"{name} is unavailable")
    return Decimal(str(raw))


def _text(value: object, *names: str) -> str | None:
    raw = _field(value, *names)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _field(value: object, *names: str) -> object:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            found = value[name]
            if found is not None:
                return found
        found = getattr(value, name, None)
        if found is not None:
            return found
    return None


def _as_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise LiveStateUnavailableError("timestamp is not a datetime")
