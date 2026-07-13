from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from polysia.adapters.polymarket.secure import PolymarketSecureAdapter
from polysia.reconciliation.live_round_trip import (
    LiveRoundTripVenueSnapshot,
    ObservedExitFill,
    ObservedExitOrder,
)


class PolymarketRoundTripReadError(RuntimeError):
    """Raised when authenticated read-only lifecycle evidence is unusable."""


class PolymarketRoundTripReader:
    """Translate authenticated Polymarket reads into venue-neutral lifecycle evidence."""

    def __init__(self, adapter: PolymarketSecureAdapter | None = None) -> None:
        self._adapter = adapter or PolymarketSecureAdapter()

    async def read_exit_state(
        self,
        *,
        order_id: str,
        token_id: str,
    ) -> LiveRoundTripVenueSnapshot:
        opened_here = not self._adapter.is_connected
        try:
            if opened_here:
                await self._adapter.connect()
            raw_order = await self._adapter.get_order(order_id=order_id)
            raw_trades = await self._adapter.list_account_trades(token_id=token_id)
            raw_positions = await self._adapter.list_positions(size_threshold=0)
            await self._adapter.get_balance_allowance(asset_type="COLLATERAL")
            await self._adapter.get_balance_allowance(
                asset_type="CONDITIONAL",
                token_id=token_id,
            )
            read_at = datetime.now(UTC)
            order = None if raw_order is None else _order_observation(raw_order)
            fills = _fill_observations(
                raw_trades,
                order_id=order_id,
                token_id=token_id,
                fallback_time=read_at,
            )
            position_size = sum(
                (
                    _decimal(_read(position, "size"))
                    for position in raw_positions
                    if str(_read(position, "token_id") or "") == token_id
                ),
                Decimal("0"),
            )
            return LiveRoundTripVenueSnapshot(
                order=order,
                fills=fills,
                position_size=position_size,
                account_balances_readable=True,
                read_at=read_at,
            )
        except PolymarketRoundTripReadError:
            raise
        except Exception as error:
            raise PolymarketRoundTripReadError(
                "authenticated Polymarket lifecycle reads did not complete"
            ) from error
        finally:
            if opened_here and self._adapter.is_connected:
                await self._adapter.close()


def _order_observation(raw_order: Any) -> ObservedExitOrder:
    order_id = _required(raw_order, "id")
    return ObservedExitOrder(
        order_id=order_id,
        token_id=_required(raw_order, "token_id"),
        side=_required(raw_order, "side"),
        price=_decimal(_read(raw_order, "price")),
        original_size=_decimal(_read(raw_order, "original_size")),
        matched_size=_decimal(_read(raw_order, "size_matched")),
        status=_required(raw_order, "status"),
    )


def _fill_observations(
    trades: list[Any],
    *,
    order_id: str,
    token_id: str,
    fallback_time: datetime,
) -> tuple[ObservedExitFill, ...]:
    fills: list[ObservedExitFill] = []
    for trade in trades:
        trade_id = _required(trade, "id")
        occurred_at = _optional_datetime(
            _read(trade, "matched_at") or _read(trade, "updated_at")
        ) or fallback_time
        status = str(_read(trade, "status") or "UNKNOWN")
        if str(_read(trade, "taker_order_id") or "") == order_id:
            fee, source = _fee_from_basis_points(_read(trade, "fee_rate_bps"), "trade")
            fills.append(
                ObservedExitFill(
                    fill_id=f"{trade_id}:taker",
                    order_id=order_id,
                    token_id=token_id,
                    side=str(_read(trade, "side") or "SELL"),
                    price=_decimal(_read(trade, "price")),
                    size=_decimal(_read(trade, "size")),
                    status=status,
                    liquidity_role="TAKER",
                    occurred_at=occurred_at,
                    fee=fee,
                    fee_source=source,
                )
            )
        for index, maker in enumerate(_read(trade, "maker_orders") or ()):
            if str(_read(maker, "order_id") or "") != order_id:
                continue
            fee_bps = _read(maker, "fee_rate_bps")
            fee_source = "maker"
            if fee_bps is None:
                fee_bps = _read(trade, "fee_rate_bps")
                fee_source = "trade"
            fee, source = _fee_from_basis_points(fee_bps, fee_source)
            fills.append(
                ObservedExitFill(
                    fill_id=f"{trade_id}:maker:{index}",
                    order_id=order_id,
                    token_id=str(_read(maker, "token_id") or token_id),
                    side=str(_read(maker, "side") or "SELL"),
                    price=_decimal(_read(maker, "price")),
                    size=_decimal(_read(maker, "matched_amount")),
                    status=status,
                    liquidity_role="MAKER",
                    occurred_at=occurred_at,
                    fee=fee,
                    fee_source=source,
                )
            )
    return tuple(fills)


def _fee_from_basis_points(value: object, source: str) -> tuple[Decimal | None, str]:
    if value is None:
        return None, "venue_fee_unavailable"
    basis_points = _decimal(value)
    if basis_points == 0:
        return Decimal("0"), f"{source}_fee_rate_bps_zero"
    return None, f"{source}_fee_rate_bps_present_amount_unknown"


def _read(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _required(value: Any, key: str) -> str:
    item = _read(value, key)
    if item is None or not str(item):
        raise PolymarketRoundTripReadError(f"Polymarket {key} is missing")
    return str(item)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PolymarketRoundTripReadError("Polymarket returned an invalid decimal") from error


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = ["PolymarketRoundTripReadError", "PolymarketRoundTripReader"]
