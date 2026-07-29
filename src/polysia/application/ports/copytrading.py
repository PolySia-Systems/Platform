from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from polysia.domain.copytrading import LeaderTradeEvent


@dataclass(frozen=True, slots=True)
class LeaderTradeCheckpoint:
    """Opaque source checkpoint safe to persist in a later stage."""

    value: str


@dataclass(frozen=True, slots=True)
class LeaderTradeReadPage:
    """One bounded, normalized page from an external leader-trade source."""

    events: tuple[LeaderTradeEvent, ...]
    next_checkpoint: LeaderTradeCheckpoint | None
    raw_count: int
    filtered_count: int
    rejected_count: int
    duplicate_count: int


@dataclass(frozen=True, slots=True)
class LeaderInventorySnapshot:
    """Complete public opening-inventory evidence with no source address."""

    leader_id: str
    positions: dict[tuple[str, str], Decimal]
    observed_at: datetime
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class LeaderMarketMetadata:
    """Strictly verified market metadata associated with a normalized event."""

    market_reference: str
    outcome_reference: str
    external_slug: str
    outcome_label: str
    starts_at: datetime
    ends_at: datetime


class LeaderTradeSourcePort(Protocol):
    """Read-only boundary for retrieving confirmed leader executions."""

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: LeaderTradeCheckpoint | None = None,
    ) -> LeaderTradeReadPage: ...

    async def read_inventory(self, leader_id: str) -> LeaderInventorySnapshot: ...

    def market_metadata(
        self,
        market_reference: str,
        outcome_reference: str,
    ) -> LeaderMarketMetadata: ...
