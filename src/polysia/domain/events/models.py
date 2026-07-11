from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketDataEvent:
    """Normalized market-data event with a venue-neutral source identifier."""

    source: str
    event_type: str
    token_id: str
    received_at: datetime
    exchange_ts: datetime | None
    payload: dict[str, Any]
    raw_payload: dict[str, Any]

