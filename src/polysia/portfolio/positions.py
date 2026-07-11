from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from polysia.execution.order_state import PaperFill

ZERO = Decimal("0")


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

    def get(self, token_id: str) -> Position:
        return self.positions.get(token_id, Position(token_id=token_id))

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
        new_avg_price = ((current.avg_price * current.size) + (fill.price * fill.size)) / new_size
        self.cash -= fill.price * fill.size
        updated = Position(token_id=fill.token_id, size=new_size, avg_price=new_avg_price)
        self.positions[fill.token_id] = updated
        return updated

    def _apply_sell(self, fill: PaperFill) -> Position:
        current = self.get(fill.token_id)
        if fill.size > current.size:
            raise ValueError("sell fill exceeds current position")
        self.cash += fill.price * fill.size
        self.realized_pnl += (fill.price - current.avg_price) * fill.size
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
