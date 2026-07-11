from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pm_trader.orderbook.validators import (
    ZERO,
    NumericInput,
    OrderBookValidationError,
    to_decimal,
    validate_not_crossed,
    validate_price,
    validate_size,
)

BookSide = Literal["BUY", "SELL"]
LevelInput = tuple[NumericInput, NumericInput]


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(slots=True)
class LocalOrderBook:
    """Mutable in-memory orderbook for one Polymarket outcome token."""

    token_id: str
    allow_crossed: bool = False
    _bids: dict[Decimal, Decimal] = field(default_factory=dict, init=False, repr=False)
    _asks: dict[Decimal, Decimal] = field(default_factory=dict, init=False, repr=False)

    def apply_snapshot(
        self,
        *,
        bids: Iterable[LevelInput],
        asks: Iterable[LevelInput],
    ) -> None:
        """Replace book state with a full snapshot."""
        next_bids = self._normalize_levels(bids)
        next_asks = self._normalize_levels(asks)
        validate_not_crossed(next_bids, next_asks, allow_crossed=self.allow_crossed)
        self._bids = next_bids
        self._asks = next_asks

    def apply_update(self, *, side: BookSide, price: NumericInput, size: NumericInput) -> None:
        """Apply one incremental level update. Size zero deletes the level."""
        normalized_side = _normalize_side(side)
        normalized_price = to_decimal(price, field_name="price")
        normalized_size = to_decimal(size, field_name="size")
        validate_price(normalized_price)
        validate_size(normalized_size)

        levels = self._bids if normalized_side == "BUY" else self._asks
        previous_size = levels.get(normalized_price)

        if normalized_size == ZERO:
            levels.pop(normalized_price, None)
        else:
            levels[normalized_price] = normalized_size

        try:
            validate_not_crossed(self._bids, self._asks, allow_crossed=self.allow_crossed)
        except OrderBookValidationError:
            if previous_size is None:
                levels.pop(normalized_price, None)
            else:
                levels[normalized_price] = previous_size
            raise

    @property
    def bids(self) -> tuple[BookLevel, ...]:
        return tuple(
            BookLevel(price, size)
            for price, size in sorted(self._bids.items(), reverse=True)
        )

    @property
    def asks(self) -> tuple[BookLevel, ...]:
        return tuple(BookLevel(price, size) for price, size in sorted(self._asks.items()))

    @property
    def best_bid(self) -> Decimal | None:
        return max(self._bids) if self._bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return min(self._asks) if self._asks else None

    @property
    def mid(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / Decimal("2")

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def bid_depth(self) -> Decimal:
        best_bid = self.best_bid
        if best_bid is None:
            return ZERO
        return self._bids[best_bid]

    @property
    def ask_depth(self) -> Decimal:
        best_ask = self.best_ask
        if best_ask is None:
            return ZERO
        return self._asks[best_ask]

    @property
    def orderbook_imbalance(self) -> Decimal | None:
        total_depth = self.bid_depth + self.ask_depth
        if total_depth == ZERO:
            return None
        return self.bid_depth / total_depth

    @property
    def microprice(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        top_depth = self.bid_depth + self.ask_depth
        if top_depth == ZERO:
            return None
        return ((self.best_ask * self.bid_depth) + (self.best_bid * self.ask_depth)) / top_depth

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-friendly view of current state."""
        return {
            "asks": [{"price": str(level.price), "size": str(level.size)} for level in self.asks],
            "best_ask": str(self.best_ask) if self.best_ask is not None else None,
            "best_bid": str(self.best_bid) if self.best_bid is not None else None,
            "bid_depth": str(self.bid_depth),
            "ask_depth": str(self.ask_depth),
            "bids": [{"price": str(level.price), "size": str(level.size)} for level in self.bids],
            "imbalance": (
                str(self.orderbook_imbalance)
                if self.orderbook_imbalance is not None
                else None
            ),
            "microprice": str(self.microprice) if self.microprice is not None else None,
            "mid": str(self.mid) if self.mid is not None else None,
            "spread": str(self.spread) if self.spread is not None else None,
            "token_id": self.token_id,
        }

    def _normalize_levels(self, levels: Iterable[LevelInput]) -> dict[Decimal, Decimal]:
        normalized: dict[Decimal, Decimal] = {}
        for raw_price, raw_size in levels:
            price = to_decimal(raw_price, field_name="price")
            size = to_decimal(raw_size, field_name="size")
            validate_price(price)
            validate_size(size)
            if size == ZERO:
                continue
            normalized[price] = size
        return normalized


def _normalize_side(side: BookSide) -> BookSide:
    if side not in ("BUY", "SELL"):
        raise OrderBookValidationError(f"side must be BUY or SELL, got {side!r}")
    return side
