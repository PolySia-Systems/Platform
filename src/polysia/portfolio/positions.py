from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from polysia.execution.order_state import PaperFill

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class Position:
    token_id: str
    size: Decimal = ZERO
    avg_price: Decimal = ZERO

    def market_value(self, mark_price: Decimal) -> Decimal:
        return self.size * mark_price


@dataclass(slots=True)
class PositionLedger:
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    daily_realized_pnl: dict[date, Decimal] = field(default_factory=dict)
    daily_fees: dict[date, Decimal] = field(default_factory=dict)
    last_event_at: datetime | None = None

    def get(self, token_id: str) -> Position:
        return self.positions.get(token_id, Position(token_id=token_id))

    def daily_net_pnl(self, as_of: datetime) -> Decimal:
        day = _utc_day(as_of)
        return self.daily_realized_pnl.get(day, ZERO) - self.daily_fees.get(day, ZERO)

    def settle_resolution(
        self, token_id: str, price: Decimal, *, at: datetime
    ) -> Decimal | None:
        """Close one open position at a verified 0 or 1 price.

        Fees already charged on fills stay unchanged. A missing position is a no-op.
        """

        if price not in {ZERO, ONE}:
            raise ValueError("settlement price must be 0 or 1")
        current = self.positions.get(token_id)
        if current is None or current.size <= ZERO:
            return None
        day = _utc_day(at)
        realized = (price - current.avg_price) * current.size
        self.cash += price * current.size
        self.realized_pnl += realized
        self.daily_realized_pnl[day] = self.daily_realized_pnl.get(day, ZERO) + realized
        self.last_event_at = at.astimezone(UTC)
        self.positions.pop(token_id, None)
        return realized

    def apply_fill(self, fill: PaperFill) -> Position:
        if fill.side == "BUY":
            return self._apply_buy(fill)
        if fill.side == "SELL":
            return self._apply_sell(fill)
        raise ValueError(f"unsupported fill side {fill.side!r}")

    def _apply_buy(self, fill: PaperFill) -> Position:
        current = self.get(fill.token_id)
        new_size = current.size + fill.size
        if new_size <= ZERO:
            raise ValueError("buy fill produced non-positive position size")
        day = _utc_day(fill.created_at)
        new_avg_price = ((current.avg_price * current.size) + (fill.price * fill.size)) / new_size
        self.fees += fill.fee
        self.daily_fees[day] = self.daily_fees.get(day, ZERO) + fill.fee
        self.last_event_at = fill.created_at.astimezone(UTC)
        self.cash -= fill.price * fill.size + fill.fee
        updated = Position(token_id=fill.token_id, size=new_size, avg_price=new_avg_price)
        self.positions[fill.token_id] = updated
        return updated

    def _apply_sell(self, fill: PaperFill) -> Position:
        current = self.get(fill.token_id)
        if fill.size > current.size:
            raise ValueError("sell fill exceeds current position")
        day = _utc_day(fill.created_at)
        realized = (fill.price - current.avg_price) * fill.size
        self.fees += fill.fee
        self.daily_fees[day] = self.daily_fees.get(day, ZERO) + fill.fee
        self.cash += fill.price * fill.size - fill.fee
        self.realized_pnl += realized
        self.daily_realized_pnl[day] = self.daily_realized_pnl.get(day, ZERO) + realized
        self.last_event_at = fill.created_at.astimezone(UTC)
        remaining_size = current.size - fill.size
        updated = Position(
            token_id=fill.token_id,
            size=remaining_size,
            avg_price=current.avg_price if remaining_size > ZERO else ZERO,
        )
        if remaining_size == ZERO:
            self.positions.pop(fill.token_id, None)
        else:
            self.positions[fill.token_id] = updated
        return updated


def _utc_day(value: datetime) -> date:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("paper accounting event clock must be timezone-aware")
    return value.astimezone(UTC).date()
