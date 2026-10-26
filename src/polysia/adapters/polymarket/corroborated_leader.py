"""Reuse finalized occurrence production in the existing Shadow source port."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from polysia.adapters.polymarket.session_source import CorroboratedSessionSource
from polysia.application.ports.copytrading import (
    LeaderInventorySnapshot,
    LeaderMarketMetadata,
    LeaderReadPurpose,
    LeaderTradeCheckpoint,
    LeaderTradeReadPage,
)
from polysia.domain.copytrading import LeaderPositionEffect, LeaderTradeAction, LeaderTradeEvent
from polysia.domain.financial_session import SessionBlocked, digest


class CorroboratedLeaderSource:
    def __init__(
        self,
        source: CorroboratedSessionSource,
        wallets: Mapping[str, str],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self.source, self.wallets, self.clock = source, dict(wallets), clock

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: LeaderTradeCheckpoint | None = None,
        purpose: LeaderReadPurpose = LeaderReadPurpose.DISCOVERY,
    ) -> LeaderTradeReadPage:
        if checkpoint is not None:
            raise SessionBlocked("legacy_checkpoint_requires_explicit_migration")
        fills = await self.source.read(
            wallet=self.wallets[leader_id], wallet_id=leader_id, start=start_at, end=end_at
        )
        if len(fills) > page_size:
            raise SessionBlocked("corroborated_source_window_row_budget_exhausted")
        events = tuple(
            LeaderTradeEvent(
                fill.occurrence.identity,
                fill.occurrence.source,
                leader_id,
                fill.occurrence.instrument.market,
                fill.occurrence.instrument.token,
                LeaderTradeAction(fill.occurrence.side),
                LeaderPositionEffect.UNKNOWN,
                fill.collateral / fill.shares,
                fill.shares,
                fill.occurrence.occurred_at,
                fill.occurrence.observed_at,
                fill.raw_digest,
                schema_version="corroborated-ctf-v2/v1",
                leader_position_before=fill.leader_position_before,
                baseline_evidence_digest=digest((fill.raw_digest, fill.leader_position_before)),
            )
            for fill in fills
        )
        return LeaderTradeReadPage(events, None, len(fills), 0, 0, 0)

    async def read_inventory(self, leader_id: str) -> LeaderInventorySnapshot:
        block = await self.source.chain.finalized()
        rows = await self.source.chain.holdings(self.wallets[leader_id], block=block)
        positions = {
            (self.source.chain.instruments[token].market, token): quantity
            for token, quantity in rows
        }
        return LeaderInventorySnapshot(leader_id, positions, self.clock(), digest((block, rows)))

    def market_metadata(
        self, market_reference: str, outcome_reference: str
    ) -> LeaderMarketMetadata:
        # This source has a deliberately narrow capability. Metadata/time/route
        # comes from the existing independent market port, not inferred log data.
        raise SessionBlocked("use_independent_market_port_for_corroborated_source")
