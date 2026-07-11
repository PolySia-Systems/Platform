from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pm_trader.bus.events import MarketDataEvent
from pm_trader.orderbook.book import BookSide, LevelInput, LocalOrderBook
from pm_trader.orderbook.validators import OrderBookValidationError


class BookBuilder:
    """Build and update local books from normalized market-data events."""

    def __init__(self, *, allow_crossed: bool = False) -> None:
        self._allow_crossed = allow_crossed
        self._books: dict[str, LocalOrderBook] = {}

    def get_book(self, token_id: str) -> LocalOrderBook | None:
        return self._books.get(token_id)

    def require_book(self, token_id: str) -> LocalOrderBook:
        book = self.get_book(token_id)
        if book is None:
            raise KeyError(f"no book exists for token_id={token_id}")
        return book

    def apply(self, event: MarketDataEvent) -> LocalOrderBook:
        """Apply one normalized market-data event to its local book."""
        book = self._books.setdefault(
            event.token_id,
            LocalOrderBook(token_id=event.token_id, allow_crossed=self._allow_crossed),
        )

        if event.event_type == "book":
            book.apply_snapshot(
                bids=_levels_from_payload(event.payload.get("bids", ())),
                asks=_levels_from_payload(event.payload.get("asks", ())),
            )
            return book

        if event.event_type == "price_change":
            price_change = event.payload.get("price_change")
            if not isinstance(price_change, dict):
                raise OrderBookValidationError("price_change payload must include a dict")
            book.apply_update(
                side=_side_from_payload(price_change),
                price=_required_value(price_change, "price"),
                size=_required_value(price_change, "size"),
            )
            return book

        return book


def _levels_from_payload(raw_levels: object) -> Iterable[LevelInput]:
    if not isinstance(raw_levels, list | tuple):
        raise OrderBookValidationError("book levels must be a list or tuple")
    levels: list[LevelInput] = []
    for raw_level in raw_levels:
        if not isinstance(raw_level, dict):
            raise OrderBookValidationError("book level must be a dict")
        levels.append(
            (
                _required_value(raw_level, "price"),
                _required_value(raw_level, "size"),
            )
        )
    return levels


def _side_from_payload(payload: dict[str, Any]) -> BookSide:
    raw_side = _required_value(payload, "side")
    if raw_side not in ("BUY", "SELL"):
        raise OrderBookValidationError(f"side must be BUY or SELL, got {raw_side!r}")
    return raw_side


def _required_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None:
        raise OrderBookValidationError(f"payload missing required field: {key}")
    return value
