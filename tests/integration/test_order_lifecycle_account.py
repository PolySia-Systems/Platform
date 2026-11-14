from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from polymarket.errors import RequestRejectedError

from polysia.adapters.polymarket.order_lifecycle_account import (
    OrderLifecycleAccountReader,
    OrderLifecycleSessionAccount,
    explicit_zero_fee_market,
)
from polysia.domain.financial_session import InstrumentScope, SessionBlocked

NOW = datetime(2026, 11, 9, tzinfo=UTC)
WALLET = "0x" + "1" * 40
EXCHANGE = "0x" + "2" * 40
COLLATERAL = "0x" + "3" * 40
INSTRUMENT = InstrumentScope("market", "123", COLLATERAL, "route")


def detail(order_id, side, *, matched="2", status="CANCELED", maker=WALLET):
    return {
        "id": order_id, "side": side, "market": "market", "asset_id": "123",
        "maker_address": maker, "size_matched": matched, "original_size": "5", "status": status,
    }


def fill(order_id, side, *, price="0.5", matched_at=NOW, **changes):
    return {
        "id": "trade-" + order_id, "status": "CONFIRMED", "trader_side": "TAKER",
        "taker_order_id": order_id, "maker_address": WALLET, "asset_id": "123", "market": "market",
        "side": side, "size": "2", "price": price, "transaction_hash": "tx",
        "matched_at": matched_at, **changes,
    }


class Client:
    def __init__(self, *, trades=(), details=None, live=(), allowance=2_700_000):
        self.trades, self.details, self.live = trades, details or {}, live
        self.allowance = allowance
        self.signer = self.wallet = WALLET
        self.wallet_type = "DEPOSIT_WALLET"
        self._ctx = SimpleNamespace(
            signer_type="OWNER", secure_clob=SimpleNamespace(get_json=self.wallet_orders),
        )

    async def wallet_orders(self, path, *, params):
        assert path == "/data/wallet-open-orders" and params == {}
        return {"data": list(self.live), "next_cursor": ""}

    async def list_open_orders(self):
        yield SimpleNamespace(items=self.live, has_more=False, limit_reached=False)

    async def list_account_trades(self):
        yield SimpleNamespace(items=self.trades, has_more=False, limit_reached=False)

    async def get_balance_allowance(self, *, asset_type, asset_id=None):
        if asset_type == "CONDITIONAL":
            assert asset_id == INSTRUMENT.token
            return {"balance": 2_000_000, "allowances": {}}
        assert asset_type == "COLLATERAL"
        return {"balance": 10_000_000, "allowances": {EXCHANGE: self.allowance}}

    async def get_order(self, *, order_id):
        if order_id not in self.details:
            raise RequestRejectedError("missing", status=404)
        return self.details[order_id]


async def read(client, tracked=None, *, zero_fee=True):
    mapping = SimpleNamespace(
        signer=WALLET, funder=WALLET, collateral=COLLATERAL, signature_type=3,
        settlement_route=INSTRUMENT.settlement_route,
    )
    account = OrderLifecycleAccountReader(client, mapping, maximum_pages=2, clock=lambda: NOW)
    return await account.observe(
        INSTRUMENT, exchange=EXCHANGE, tracked=tracked or {}, explicit_zero_fee=zero_fee,
    )


async def test_empty_wallet_order_view_limits_usable_balance_without_claiming_inventory():
    snapshot = await read(Client(trades=[fill("old", "BUY")]))
    assert snapshot["usable_collateral"] == Decimal("2.7")
    assert snapshot["wallet_inventory"] == "UNASSESSED"
    assert snapshot["full_account_reconciled"] is False
    assert snapshot["confirmed_fills"] == []


async def test_pending_or_untracked_order_withholds_usable_balance():
    client = Client(
        trades=[{"id": "pending", "status": "MATCHED_NOT_BROADCASTED"}],
        live=[detail("foreign", "SELL", status="LIVE")],
    )
    snapshot = await read(client)
    assert snapshot["untracked_open_order_ids"] == ["foreign"]
    assert snapshot["pending_trade_ids"] == ["pending"]
    assert snapshot["usable_collateral"] is None


async def test_owned_partial_fill_and_cancel_are_separate_from_old_inventory_and_cash():
    client = Client(trades=[fill("buy", "BUY"), fill("old", "BUY")],
                    details={"buy": detail("buy", "BUY")})
    result = await read(client, {"buy": "BUY"}, zero_fee=False)
    assert result["order_evidence"]["buy"]["terminal_evidence"] is True
    assert result["confirmed_run_inventory_delta"] == Decimal(2)
    assert result["confirmed_run_fees"] is None and result["realized_pnl"] is None


async def test_confirmed_round_trip_pnl_uses_only_owned_fills():
    client = Client(
        trades=[fill("buy", "BUY"), fill("sell", "SELL", price="0.4",
                                       matched_at=NOW + timedelta(seconds=1))],
        details={"buy": detail("buy", "BUY"), "sell": detail("sell", "SELL")},
    )
    result = await read(client, {"buy": "BUY", "sell": "SELL"})
    assert result["confirmed_run_inventory_delta"] == 0
    assert result["confirmed_run_fees"] == 0
    assert result["realized_pnl"] == Decimal("-0.2")


async def test_mismatched_order_owner_and_unknown_trade_status_fail_closed():
    client = Client(trades=[fill("buy", "BUY")],
                    details={"buy": detail("buy", "BUY", maker="0x" + "9" * 40)})
    with pytest.raises(SessionBlocked, match="tracked_order_detail_identity"):
        await read(client, {"buy": "BUY"})
    with pytest.raises(SessionBlocked, match="unrecognized_CLOB_trade_status"):
        await read(Client(trades=[{"id": "bad", "status": "NEW"}]))


async def test_missing_order_detail_is_not_terminal_even_with_confirmed_fill():
    result = await read(Client(trades=[fill("buy", "BUY")]), {"buy": "BUY"})
    assert result["order_evidence"]["buy"] == {"status": "UNKNOWN", "terminal_evidence": False}
    assert result["confirmed_run_inventory_delta"] == 2
    assert result["realized_pnl"] is None


def test_explicit_fee_proof_is_required_to_report_zero_for_tracked_taker_fills():
    assert not explicit_zero_fee_market({"t": [{"t": "123"}]}, "123")
    assert not explicit_zero_fee_market({"t": [{"t": "123"}], "fd": {"r": "bad"}}, "123")
    assert explicit_zero_fee_market(
        {"t": [{"t": "123"}], "fd": {"r": Decimal("0.000"), "to": True}}, "123",
    )



def test_missing_fee_curve_needs_matching_gamma_market_and_explicit_zero_base_fee():
    market = {"c": "market", "t": [{"t": "123"}], "fd": None}
    gamma = [{"conditionId": "market", "feesEnabled": False, "negRisk": False,
              "clobTokenIds": '["123", "456"]'}]
    assert explicit_zero_fee_market(market, "123", gamma=gamma, fee_rate={"base_fee": 0})
    assert not explicit_zero_fee_market(market, "123", gamma=gamma, fee_rate={"base_fee": False})
    assert not explicit_zero_fee_market(market, "456", gamma=gamma, fee_rate={"base_fee": 0})


async def test_session_adapter_projects_API_scope_and_exact_owned_fill_only():
    mapping = SimpleNamespace(
        account_id="account", signer=WALLET, funder=WALLET, collateral=COLLATERAL,
        signature_type=3, settlement_route=INSTRUMENT.settlement_route,
    )
    client = Client(trades=[fill("buy", "BUY")], details={"buy": detail("buy", "BUY")})
    reader = OrderLifecycleAccountReader(client, mapping, maximum_pages=2, clock=lambda: NOW)
    row = {"order_id": "buy", "side": "BUY"}
    journal = SimpleNamespace(read=lambda: {
        "opening": {"scope": "ORDER_LIFECYCLE_API"}, "orders": {"intent": row},
    })

    def respond(request):
        if request.url.path.startswith("/clob-markets/"):
            value = {"c": "market", "t": [{"t": "123"}], "fd": {"r": "0", "to": True}}
        elif request.url.host == "gamma-api.polymarket.com":
            value = []
        else:
            value = {"base_fee": 0}
        return httpx.Response(200, json=value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        account = OrderLifecycleSessionAccount(
            reader, journal, INSTRUMENT, exchange=EXCHANGE, http=http,
        )
        observation = await account.observe(INSTRUMENT)
        observation.require_complete("account", now=NOW, max_age=30, scope="ORDER_LIFECYCLE_API")
        with pytest.raises(SessionBlocked, match="account_evidence_incomplete"):
            observation.require_complete("account", now=NOW, max_age=30)
        assert observation.cash == Decimal("2.7")
        assert observation.positions == (("123", Decimal(2)),)
        confirmed = account.confirmed("intent", row)
        assert len(confirmed) == 1
        assert confirmed[0].shares == 2 and confirmed[0].fee == 0


async def test_API_session_cannot_fall_back_to_chain_source_entries():
    from polysia.adapters.polymarket.session_composition import OperationalSession

    session = SimpleNamespace(
        config=SimpleNamespace(opening=SimpleNamespace(scope="ORDER_LIFECYCLE_API")),
    )
    await OperationalSession._source_entries(session, allow_entry=False)
    with pytest.raises(SessionBlocked, match="owner_intent_entrypoint_pending"):
        await OperationalSession._source_entries(session, allow_entry=True)
