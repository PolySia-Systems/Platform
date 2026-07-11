from decimal import Decimal, InvalidOperation
from typing import Literal


def parse_decimal(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field_name} must be a Decimal string") from error
    return parsed


def parse_outcome(value: str) -> Literal["YES", "NO"]:
    normalized = value.upper()
    if normalized not in ("YES", "NO"):
        raise ValueError("outcome must be YES or NO")
    return "YES" if normalized == "YES" else "NO"


def parse_side(value: str) -> Literal["BUY", "SELL"]:
    normalized = value.upper()
    if normalized not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    return "BUY" if normalized == "BUY" else "SELL"


def parse_order_type(value: str) -> Literal["FAK", "FOK"]:
    normalized = value.upper()
    if normalized not in ("FAK", "FOK"):
        raise ValueError("order_type must be FAK or FOK; GTC and GTD are rejected.")
    return "FAK" if normalized == "FAK" else "FOK"
