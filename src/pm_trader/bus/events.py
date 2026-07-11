from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class MarketDataEvent:
    """Normalized market-data event consumed by internal systems."""

    source: Literal["polymarket"]
    event_type: str
    token_id: str
    received_at: datetime
    exchange_ts: datetime | None
    payload: dict[str, Any]
    raw_payload: dict[str, Any]


def market_data_event_to_dict(event: MarketDataEvent) -> dict[str, Any]:
    """Convert a market data event to a JSON-safe dictionary."""
    return {
        "exchange_ts": _json_safe(event.exchange_ts),
        "event_type": event.event_type,
        "payload": _json_safe(event.payload),
        "raw_payload": _json_safe(event.raw_payload),
        "received_at": _json_safe(event.received_at),
        "source": event.source,
        "token_id": event.token_id,
    }


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]
    return value
