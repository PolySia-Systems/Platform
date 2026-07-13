from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from polysia.adapters.polymarket.round_trip_reconciliation import (
    PolymarketRoundTripReader,
)


class FakeSecureAdapter:
    def __init__(self, *, trades: list[Any]) -> None:
        self.is_connected = False
        self.trades = trades
        self.connect_count = 0
        self.close_count = 0
        self.balance_reads: list[tuple[str, str | None]] = []

    async def connect(self) -> None:
        self.connect_count += 1
        self.is_connected = True

    async def close(self) -> None:
        self.close_count += 1
        self.is_connected = False

    async def get_order(self, *, order_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=order_id,
            token_id="token-down",
            side="SELL",
            price="0.58",
            original_size="5",
            size_matched="5",
            status="MATCHED",
        )

    async def list_account_trades(self, *, token_id: str) -> list[Any]:
        assert token_id == "token-down"
        return self.trades

    async def list_positions(self, *, size_threshold: float) -> list[Any]:
        assert size_threshold == 0
        return []

    async def get_balance_allowance(
        self,
        *,
        asset_type: str,
        token_id: str | None = None,
    ) -> SimpleNamespace:
        self.balance_reads.append((asset_type, token_id))
        return SimpleNamespace(balance="0", allowances={})


@pytest.mark.asyncio
async def test_reader_uses_matching_maker_leg_not_whole_taker_trade() -> None:
    maker = SimpleNamespace(
        fee_rate_bps=None,
        matched_amount="5",
        order_id="exit-order",
        price="0.58",
        side="SELL",
        token_id="token-down",
    )
    trade = SimpleNamespace(
        id="trade-1",
        fee_rate_bps="0",
        maker_orders=(maker,),
        matched_at="2026-07-12T20:54:00+00:00",
        price="0.57",
        size="25",
        status="CONFIRMED",
        taker_order_id="other-order",
    )
    adapter = FakeSecureAdapter(trades=[trade])

    snapshot = await PolymarketRoundTripReader(adapter).read_exit_state(
        order_id="exit-order",
        token_id="token-down",
    )

    assert snapshot.position_size == 0
    assert len(snapshot.fills) == 1
    fill = snapshot.fills[0]
    assert fill.size == 5
    assert fill.price == Decimal("0.58")
    assert fill.liquidity_role == "MAKER"
    assert fill.fee == 0
    assert fill.fee_source == "trade_fee_rate_bps_zero"
    assert adapter.balance_reads == [
        ("COLLATERAL", None),
        ("CONDITIONAL", "token-down"),
    ]
    assert adapter.connect_count == 1
    assert adapter.close_count == 1


@pytest.mark.asyncio
async def test_reader_marks_nonzero_fee_rate_amount_as_unknown() -> None:
    trade = SimpleNamespace(
        id="trade-2",
        fee_rate_bps="200",
        maker_orders=(),
        matched_at="2026-07-12T20:54:00+00:00",
        price="0.58",
        side="SELL",
        size="5",
        status="CONFIRMED",
        taker_order_id="exit-order",
    )
    adapter = FakeSecureAdapter(trades=[trade])

    snapshot = await PolymarketRoundTripReader(adapter).read_exit_state(
        order_id="exit-order",
        token_id="token-down",
    )

    assert snapshot.fills[0].fee is None
    assert snapshot.fills[0].fee_status == "unknown"
    assert snapshot.fills[0].fee_source == "trade_fee_rate_bps_present_amount_unknown"


@pytest.mark.asyncio
async def test_reader_preserves_missing_order_as_reconcilable_evidence() -> None:
    class MissingOrderAdapter(FakeSecureAdapter):
        async def get_order(self, *, order_id: str) -> None:
            return None

    adapter = MissingOrderAdapter(trades=[])

    snapshot = await PolymarketRoundTripReader(adapter).read_exit_state(
        order_id="exit-order",
        token_id="token-down",
    )

    assert snapshot.order is None
    assert snapshot.fills == ()
    assert snapshot.account_balances_readable is True
