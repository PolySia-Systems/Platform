"""Public V2 discovery corroborated by real finalized on-chain occurrences."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from polysia.adapters.polymarket.data_api_v2 import (
    DATA_API_V2_TRADES_PATH,
    DataApiV2Transport,
    fetch_data_api_v2_window,
)
from polysia.adapters.polymarket.session_chain import ChainFill, CTFChainReader
from polysia.domain.financial_session import SessionBlocked, utc


class CorroboratedSessionSource:
    def __init__(
        self,
        transport: DataApiV2Transport,
        chain: CTFChainReader,
        *,
        maximum_pages: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.transport, self.chain = transport, chain
        self.maximum_pages, self.clock = maximum_pages, clock

    async def read(
        self,
        *,
        wallet: str,
        wallet_id: str,
        start: datetime,
        end: datetime,
    ) -> tuple[ChainFill, ...]:
        if not utc(start) < utc(end) <= utc(self.clock()):
            raise SessionBlocked("invalid_prospective_source_window")
        rows = await fetch_data_api_v2_window(
            self.transport,
            DATA_API_V2_TRADES_PATH,
            {
                "user": wallet,
                "start": int(start.timestamp()),
                "end": int(end.timestamp()),
                "limit": 500,
                "taker_only": False,
            },
            max_pages=self.maximum_pages,
            max_requests=self.maximum_pages,
        )
        transactions = set()
        for row in rows:
            if str(row.get("proxyWallet", "")).lower() != wallet.lower():
                raise SessionBlocked("public_source_wallet_mismatch")
            transaction = row.get("transactionHash")
            if not isinstance(transaction, str) or len(transaction) != 66:
                raise SessionBlocked("public_source_occurrence_needs_transaction_corroboration")
            transactions.add(transaction)
        block = await self.chain.finalized()
        result: dict[str, ChainFill] = {}
        for transaction in sorted(transactions):
            fills = await self.chain.fills(
                wallet, block=block, observed_at=self.clock(), transaction=transaction
            )
            if not fills:
                raise SessionBlocked("public_source_has_no_unique_corroborated_occurrence")
            for fill in fills:
                if not start <= fill.occurrence.occurred_at <= end:
                    continue
                event = replace(
                    fill.occurrence,
                    wallet=wallet_id,
                    source_key=fill.raw_digest,
                )
                baseline = await self.chain.position_before(fill, wallet)
                normalized = replace(fill, occurrence=event, leader_position_before=baseline)
                if event.identity in result and result[event.identity] != normalized:
                    raise SessionBlocked("source_occurrence_conflict")
                result[event.identity] = normalized
        return tuple(result[key] for key in sorted(result))
