"""Actual normalization and budget owners over deterministic HTTP boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from polysia.adapters.polymarket.session_chain import (
    ERC20_TRANSFER,
    ORDER_FILLED,
    TRANSFER_BATCH,
    TRANSFER_SINGLE,
    CTFChainReader,
    ReadOnlyRPC,
    topic_address,
    transfer_deltas,
)
from polysia.adapters.polymarket.session_network import SessionNetwork
from polysia.application.ports.financial_session import RequestCharge
from polysia.application.services.follower_qualification import (
    FollowerSample,
    estimate_forward_price,
    produce_qualification,
)
from polysia.domain.financial_session import InstrumentScope, SessionBlocked
from tests.integration.test_financial_session import NOW, Harness

D = Decimal
WALLET, EXCHANGE, CTF, CASH = ("0x" + digit * 40 for digit in "1edc")
TX, BLOCK_HASH = "0x" + "a" * 64, "0x" + "f" * 64
BLOCK = {"hash": BLOCK_HASH, "number": "0x100", "timestamp": hex(int(NOW.timestamp()))}
SCOPE = InstrumentScope("0x" + "b" * 64, "101", CASH, "ctf-exchange-v2-standard")


def abi(*values: int) -> str:
    return "0x" + "".join(f"{value:064x}" for value in values)


def fill_log(index: int, *, shares: int = 2000000) -> dict:
    return {
        "address": EXCHANGE,
        "topics": [
            ORDER_FILLED,
            "0x" + "2" * 64,
            topic_address(WALLET),
            topic_address("0x" + "3" * 40),
        ],
        "data": abi(0, 101, 1000000, shares, 1234, 0, 0),
        "transactionHash": TX,
        "blockNumber": BLOCK["number"],
        "blockHash": BLOCK_HASH,
        "removed": False,
        "logIndex": hex(index),
    }


def chain_transport(logs: list[dict], *, reorg: bool = False) -> httpx.MockTransport:
    def handle(request):
        body = json.loads(request.content)
        method = body["method"]
        if method == "eth_getTransactionReceipt":
            result = {
                "transactionHash": TX,
                "blockHash": BLOCK_HASH,
                "blockNumber": BLOCK["number"],
                "status": "0x1",
                "logs": logs,
            }
        elif method in {"eth_getBlockByNumber", "eth_getBlockByHash"}:
            result = {**BLOCK, "hash": "other"} if reorg else BLOCK
        elif method == "eth_chainId":
            result = "0x89"
        elif method == "eth_getLogs":
            result = logs
        elif method == "eth_call":
            result = "0x1"  # one smallest-unit dust balance
        else:
            raise AssertionError("unreviewed RPC")
        return httpx.Response(200, json={"id": body["id"], "jsonrpc": "2.0", "result": result})

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_same_transaction_distinct_occurrences_and_repeated_views() -> None:
    logs = [fill_log(10), fill_log(11), fill_log(10)]
    async with httpx.AsyncClient(transport=chain_transport(logs)) as http:
        chain = CTFChainReader(
            ReadOnlyRPC(http, "https://rpc.fixture/"),
            exchange=EXCHANGE,
            ctf=CTF,
            collateral=CASH,
            instruments=(SCOPE,),
        )
        fills = await chain.fills(WALLET, block=BLOCK, observed_at=NOW, transaction=TX)
        assert len(fills) == 2 and len({row.occurrence.identity for row in fills}) == 2
        assert all(
            row.shares == 2 and row.collateral == 1 and row.fee == D("0.001234") for row in fills
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect", ["conflict", "reorg", "removed", "wrong_transaction", "malformed"]
)
async def test_ambiguous_or_noncanonical_occurrences_are_rejected(defect: str) -> None:
    logs = [fill_log(10)]
    if defect == "conflict":
        logs.append(fill_log(10, shares=3000000))
    elif defect == "removed":
        logs[0]["removed"] = True
    elif defect == "wrong_transaction":
        logs[0]["transactionHash"] = "0x" + "0" * 64
    elif defect == "malformed":
        logs[0]["data"] = "0x123"
    async with httpx.AsyncClient(transport=chain_transport(logs, reorg=defect == "reorg")) as http:
        chain = CTFChainReader(
            ReadOnlyRPC(http, "https://rpc.fixture/"),
            exchange=EXCHANGE,
            ctf=CTF,
            collateral=CASH,
            instruments=(SCOPE,),
        )
        with pytest.raises(SessionBlocked):
            await chain.fills(WALLET, block=BLOCK, observed_at=NOW, transaction=TX)


@pytest.mark.asyncio
async def test_dust_is_retained_and_RPC_mutation_is_unreachable() -> None:
    async with httpx.AsyncClient(transport=chain_transport([])) as http:
        rpc = ReadOnlyRPC(http, "https://rpc.fixture/")
        chain = CTFChainReader(
            rpc, exchange=EXCHANGE, ctf=CTF, collateral=CASH, instruments=(SCOPE,)
        )
        assert await chain.holdings(WALLET, block=BLOCK) == (("101", D("0.000001")),)
        with pytest.raises(SessionBlocked, match="mutation"):
            await rpc.call("eth_sendRawTransaction", ["fictional"])


@pytest.mark.asyncio
async def test_actual_redemption_cash_is_once_and_manual_transfer_is_unexplained() -> None:
    adapter = "0x" + "a" * 40
    moved = {
        **fill_log(10),
        "address": CTF,
        "topics": [
            TRANSFER_SINGLE,
            topic_address(adapter),
            topic_address(WALLET),
            topic_address(adapter),
        ],
        "data": abi(101, 2000000),
    }
    paid = {
        **fill_log(11),
        "address": CASH,
        "topics": [
            ERC20_TRANSFER,
            topic_address(adapter),
            topic_address(WALLET),
        ],
        "data": abi(1500000),
    }
    calls, selector = [], ["0x01b7037c"]

    def wire(request):
        body = json.loads(request.content)
        calls.append(body["method"])
        result = {
            "eth_getLogs": [moved],
            "eth_getBlockByNumber": BLOCK,
            "eth_getTransactionReceipt": {
                "transactionHash": TX,
                "blockHash": BLOCK_HASH,
                "blockNumber": BLOCK["number"],
                "status": "0x1",
                "logs": [moved, paid, paid],
            },
            "eth_getTransactionByHash": {
                "from": WALLET,
                "to": adapter,
                "input": selector[0] + abi(0, 0, int(SCOPE.market, 16), 128, 2, 1, 2)[2:],
            },
        }[body["method"]]
        return httpx.Response(200, json={"id": body["id"], "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as http:
        chain = CTFChainReader(
            ReadOnlyRPC(http, "https://rpc.fixture/"),
            exchange=EXCHANGE,
            ctf=CTF,
            collateral=CASH,
            instruments=(SCOPE,),
        )
        events = await chain.redemptions(
            WALLET,
            account_id="fixture-account",
            adapter=adapter,
            since=NOW - timedelta(seconds=1),
            block=BLOCK,
        )
        assert len(events) == 1 and events[0].removed == (("101", D(2)),)
        assert events[0].confirmed_cash == D("1.5")  # duplicate receipt view is not extra cash
        selector[0] = "0xdeadbeef"
        assert (
            await chain.redemptions(
                WALLET,
                account_id="fixture-account",
                adapter=adapter,
                since=NOW - timedelta(seconds=1),
                block=BLOCK,
            )
            == ()
        )
    assert all(method in ReadOnlyRPC.METHODS for method in calls)


def test_malformed_batch_cannot_hide_inventory() -> None:
    log = {
        "topics": [
            TRANSFER_BATCH,
            topic_address(EXCHANGE),
            topic_address(EXCHANGE),
            topic_address(WALLET),
        ],
        "removed": False,
        "data": abi(64, 128, 1, 101, 2, 1, 2),
    }
    with pytest.raises(SessionBlocked, match="batch"):
        transfer_deltas(log, WALLET)


def sample(index: int = 0) -> FollowerSample:
    at = NOW + timedelta(seconds=index)
    return FollowerSample(
        "wallet",
        "101",
        str(index),
        at,
        at,
        at,
        at + timedelta(seconds=10),
        at + timedelta(seconds=11),
        D("0.4"),
        D("0.6"),
        D("0.01"),
        D(100),
        D(100),
        D("0.01"),
        True,
        True,
        "fixture-retained-digest",
    )


def test_missing_edge_and_future_selection_evidence_stay_unknown_or_blocked() -> None:
    end, available, evaluation = (
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=2),
        NOW + timedelta(hours=3),
    )
    rows = (replace(sample(), complete=False),)
    estimate = estimate_forward_price(
        rows,
        wallet="wallet",
        token="101",
        selection_end=end,
        available_at=available,
        confidence=D("0.95"),
        minimum_samples=20,
    )
    assert (
        estimate.fair_price is None and estimate.uncertainty is None and estimate.sample_count == 0
    )
    with pytest.raises(SessionBlocked, match="not_available"):
        estimate_forward_price(
            (sample(),),
            wallet="wallet",
            token="101",
            selection_end=NOW,
            available_at=available,
            confidence=D("0.95"),
            minimum_samples=1,
        )
    with pytest.raises(SessionBlocked, match="leakage"):
        produce_qualification(
            (sample(),),
            wallet="wallet",
            selection_start=NOW - timedelta(hours=1),
            selection_end=end,
            available_at=available,
            evaluation_start=end,
            confidence=D("0.95"),
        )
    result = produce_qualification(
        (sample(),),
        wallet="wallet",
        selection_start=NOW - timedelta(hours=1),
        selection_end=end,
        available_at=available,
        evaluation_start=evaluation,
        confidence=D("0.95"),
    )
    assert (
        result.follower_net_per_unit < 0
    )  # one favorable observation is not positive qualified edge


@pytest.mark.asyncio
async def test_actual_wire_bound_overrun_unknown_retention_and_no_retry(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    calls = []
    network = SessionNetwork(
        harness.journal,
        allowed_origins=frozenset({"https://rpc.fixture"}),
        rpc_url="https://rpc.fixture/",
        maximum_response_bytes=100,
        maximum_queued=1,
        timeout_seconds=1,
        guard=lambda: None,
        clock=lambda: harness.now,
    )

    def register():
        harness.coordinator._charge("ACCOUNT", protective=True)
        network.register_bound("ACCOUNT", RequestCharge(1, 100, D(0)))

    try:
        with pytest.raises(SessionBlocked, match="durable_charge"):
            network.register_bound("ACCOUNT", RequestCharge(1, 100, D(0)))
        register()

        def overrun(request):
            calls.append(request)
            return httpx.Response(200, content=b"x" * 101)

        async with httpx.AsyncClient(
            transport=network.transport(httpx.MockTransport(overrun))
        ) as http:
            with network.action("ACCOUNT"):
                with pytest.raises(SessionBlocked, match="overrun"):
                    await http.post("https://rpc.fixture/", json={"method": "eth_chainId"})
                with pytest.raises(SessionBlocked, match="reserved_bound"):
                    await http.post("https://rpc.fixture/", json={"method": "eth_chainId"})
        assert len(calls) == 1 and network.observation()["unknown_response_count"] == 1
        assert network.observation()["queue_depth"] == 0
    finally:
        harness.journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["revoked", "expired"])
async def test_queued_request_rechecks_revocation_before_wire(tmp_path: Path, failure: str) -> None:
    harness = Harness(tmp_path)
    revoked = [False]

    def guard():
        if revoked[0]:
            raise SessionBlocked("fixture_revoked")

    network = SessionNetwork(
        harness.journal,
        allowed_origins=frozenset({"https://rpc.fixture"}),
        rpc_url="https://rpc.fixture/",
        maximum_response_bytes=100,
        maximum_queued=1,
        timeout_seconds=1,
        guard=guard,
        clock=lambda: harness.now,
    )
    harness.coordinator._charge("ACCOUNT", protective=True)
    network.register_bound("ACCOUNT", RequestCharge(1, 100, D(0)))

    class RevokingScheduler:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def request(self, *args, **kwargs):
            revoked[0] = failure == "revoked"
            harness.now = NOW + timedelta(seconds=2)
            yield

    network.scheduler = RevokingScheduler()
    calls = []
    try:
        async with httpx.AsyncClient(
            transport=network.transport(
                httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))
            )
        ) as http:
            with (
                network.action("ACCOUNT", evidence_deadline=NOW + timedelta(seconds=1)),
                pytest.raises(SessionBlocked, match=failure),
            ):
                await http.post("https://rpc.fixture/", json={"method": "eth_chainId"})
        assert calls == [] and network._queued == 0
        assert all(
            row["transport_invoked"] is False for row in harness.journal.read()["wire"].values()
        )
    finally:
        harness.journal.close()


@pytest.mark.parametrize("dimension", ["bytes", "cost", "requests"])
def test_entry_saturation_preserves_protective_resource_reserve(
    tmp_path: Path, dimension: str
) -> None:
    from tests.integration.test_financial_session import authorization

    auth = authorization(
        version=2,
        max_response_bytes=1000,
        protective_byte_reserve=800,
        max_requests=10,
        protective_request_reserve=8,
        max_source_cost=D(10),
        protective_cost_reserve=D(8),
    )
    harness = Harness(tmp_path, auth)
    # Harness setup uses no requests. Choose the selected constraint; other
    # dimensions remain inside their protected budget.
    charge = {
        "bytes": RequestCharge(1, 150, D(0)),
        "requests": RequestCharge(2, 0, D(0)),
        "cost": RequestCharge(1, 0, D(2)),
    }[dimension]
    harness.execution.charge_bound = lambda _: charge
    try:
        harness.coordinator._charge("ACCOUNT", protective=False)
        with pytest.raises(SessionBlocked, match="budget"):
            harness.coordinator._charge("ACCOUNT", protective=False)
        harness.coordinator._charge("ACCOUNT", protective=True)
        assert harness.journal.read()["resource_class"] == "PROTECTIVE"
    finally:
        harness.journal.close()
