from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
