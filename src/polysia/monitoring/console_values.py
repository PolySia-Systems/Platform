"""Bounded display values shared by Console projections and workspaces."""

from math import isfinite
from typing import Any


def text(value: Any, *, metric: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, (str, int)):
        return str(value) if len(str(value)) <= 2048 else "UNKNOWN_OVERSIZED_VALUE"
    if metric and isinstance(value, float) and isfinite(value):
        return str(value)
    if isinstance(value, list):
        return "; ".join(filter(None, (text(item) for item in value[:30])))[:2048] or None
    return None
