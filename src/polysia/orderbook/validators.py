from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation


class OrderBookValidationError(ValueError):
    """Raised when local orderbook state or input levels are invalid."""


NumericInput = Decimal | int | str

ZERO = Decimal("0")
ONE = Decimal("1")


def to_decimal(value: NumericInput, *, field_name: str) -> Decimal:
    """Convert supported numeric input to Decimal without float arithmetic."""
    if isinstance(value, bool):
        raise OrderBookValidationError(f"{field_name} must not be a bool")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise OrderBookValidationError(f"{field_name} is not a valid Decimal") from error
    raise OrderBookValidationError(
        f"{field_name} must be Decimal, int, or str; got {type(value).__name__}"
    )


def validate_price(price: Decimal) -> None:
    if price < ZERO or price > ONE:
        raise OrderBookValidationError("price must be within [0, 1]")


def validate_size(size: Decimal) -> None:
    if size < ZERO:
        raise OrderBookValidationError("size must not be negative")


def validate_not_crossed(
    bids: Mapping[Decimal, Decimal],
    asks: Mapping[Decimal, Decimal],
    *,
    allow_crossed: bool,
) -> None:
    if allow_crossed or not bids or not asks:
        return
    best_bid = max(bids)
    best_ask = min(asks)
    if best_bid > best_ask:
        raise OrderBookValidationError(
            f"crossed book rejected: best_bid={best_bid} best_ask={best_ask}"
        )
