"""Composition tests replace only network, clock and temporary protected custody."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eth_account import Account

from polysia.application.services.source_cohort import SharedCohortSelection, _digest
from polysia.config.settings import TradingMode
from polysia.deployment.financial_recovery import prepare_recovery
from polysia.deployment.financial_session_runtime import (
    SessionRuntimeConfig,
    binding_for,
    capacity_workload,
    compose_session,
    package_tree_digest,
    provision_session,
)
from polysia.deployment.session_account_qualification import qualify_account
from polysia.deployment.session_supervision import (
    CheckpointPublisher,
    SessionSupervisor,
    SupervisionPolicy,
)
from polysia.domain.copytrading.copy_policy import CopyPolicy
from polysia.domain.financial_session import (
    InstrumentScope,
    SessionAccountIdentity,
    SessionBlocked,
)
from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy
from polysia.domain.wallet_intelligence.source_cohort import CohortCandidate, CohortSelectionPolicy
from polysia.risk.limits import RiskLimits
from polysia.security.session_authority import (
    SessionCustody,
    SessionReceiptVerifier,
    receipt_message,
)
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.financial_session import FinancialSessionJournal
from tests.integration.test_financial_session import NOW, FakeExecution, authorization

D = Decimal
SESSION_TOKEN = str(1 << 40)


def runtime_config(root: Path, signer: str = "0x" + "1" * 40) -> SessionRuntimeConfig:
    from polymarket.environments import PRODUCTION

    environment = PRODUCTION._config
    policy = CopyPolicy("e2-mirror/v1", "FIXED_DEBIT", D(1), D("0.1"), "MIRROR")
    mapping = SessionAccountIdentity(
        "fixture-account",
        signer,
        signer,
        0,
        "polymarket",
        environment.collateral_token.lower(),
        "ctf-exchange-v2-standard",
    )
    cohort_policy = CohortSelectionPolicy(
        "cohort/v1", 1, 20, timedelta(hours=1), D("0.1"), D(1), D(20), D(1), D(1), D("0.9"), D(1)
    )
    selection = SharedCohortSelection(
        "cohort/v1",
        NOW,
        (
            CohortCandidate(
                "wallet",
                ("native",),
                ("native",),
                "SELECTED",
                (),
                1,
                "fixture-evidence",
                NOW + timedelta(seconds=1),
                "fixture",
            ),
        ),
        (),
        (),
        "",
        cohort_policy,
    )
    selection = replace(selection, digest=_digest(asdict(selection)))
    cohort = root / "cohort.json"
    cohort.write_text(json.dumps(selection.to_dict()))
    samples = root / "samples.json"
    samples.write_text("[]")
    capacity = root / "capacity.json"
    capacity.write_text("{}")
    config = SessionRuntimeConfig(
        version=1,
        release="fixture-release",
        package_tree_digest=package_tree_digest(),
        host=socket.gethostname(),
        policy=policy,
        account_mapping=mapping,
        financial_path=root / "financial" / "session.sqlite3",
        witness_root=root / "witness",
        custody_path=root / "control" / "custody.sqlite3",
        outbox_path=root / "outbox.json",
        publication_path=root / "publication" / "report.json",
        cohort_path=cohort,
        follower_samples_path=samples,
        cohort_file_digest=hashlib.sha256(cohort.read_bytes()).hexdigest(),
        follower_samples_file_digest=hashlib.sha256(samples.read_bytes()).hexdigest(),
        source_wallets=(("wallet", "0x" + "2" * 40),),
        rpc_url="https://rpc.fixture/",
        exchange=environment.standard_exchange.lower(),
        ctf=environment.conditional_tokens.lower(),
        collateral_adapter=environment.collateral_adapter.lower(),
        maximum_pages=2,
        maximum_response_bytes=4096,
        maximum_queued=2,
        request_timeout_seconds=2,
        per_action_requests=tuple(
            (name, 30)
            for name in ("ACCOUNT", "SUBMIT", "CANCEL", "CANCELLATION_READ", "SOURCE", "MARKET")
        ),
        private_key_reference="POLYSIA_FIXTURE_SIGNER",
        api_credentials_reference="POLYSIA_FIXTURE_API",
        minimum_free_disk_bytes=1000,
        egress_allocation_receipt="fixture-isolated-egress",
        opening=FakeExecution(lambda: NOW).account(),
        risk_limits=RiskLimits(allow_live_trading=True),
        maximum_order_shares=D(10),
        estimator_confidence=D("0.95"),
        incident_path=root / "incidents.sqlite3",
        commands_path=root / "commands.sqlite3",
        capacity_evidence_path=capacity,
        capacity_evidence_digest=hashlib.sha256(capacity.read_bytes()).hexdigest(),
        maximum_backup_age_seconds=60,
        checkpoint_handshake_seconds=2,
        tick_interval_seconds=1,
    )
    capacity.write_text(
        json.dumps(
            {
                "version": "financial-session-capacity/v1",
                "workload_digest": capacity_workload(config),
                "host": config.host,
                "synthetic": False,
                "status": "PASS",
                "samples": 1,
                "observed_at": NOW.isoformat(),
                "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            }
        )
    )
    return replace(
        config, capacity_evidence_digest=hashlib.sha256(capacity.read_bytes()).hexdigest()
    )


def signed(config: SessionRuntimeConfig):
    scope = InstrumentScope(
        "0x" + "b" * 64,
        SESSION_TOKEN,
        config.account_mapping.collateral,
        config.account_mapping.settlement_route,
    )
    auth = authorization(
        version=2,
        binding=binding_for(config),
        strategy=config.policy.version,
        exit_policy=config.policy.version,
        instruments=(scope,),
        protective_attempt_reserve=2,
        protective_turnover_reserve=D(5),
        protective_byte_reserve=4000000,
        protective_storage_reserve=10000000,
        protective_order_reserve=1,
        max_requests=10000,
        protective_request_reserve=1000,
        max_response_bytes=20000000,
        max_storage_bytes=100000000,
    )
    private = Ed25519PrivateKey.generate()
    signature = private.sign(
        receipt_message(auth, key_id="owner", receipt_id="fixture-e2-receipt-001")
    )
    auth = replace(
        auth,
        owner_receipt=json.dumps(
            {
                "key_id": "owner",
                "receipt_id": "fixture-e2-receipt-001",
                "signature": base64.b64encode(signature).decode(),
            }
        ),
    )
    verifier = SessionReceiptVerifier({"owner": private.public_key().public_bytes_raw()})
    return auth, verifier


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [TradingMode.DATA_ONLY, TradingMode.PAPER])
async def test_nonlive_composition_has_no_signer_account_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: TradingMode
) -> None:
    config = runtime_config(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("non-Live path reached a network transport")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    result = await compose_session(config, mode=mode, live_enabled=True)
    assert result["financial_adapter"] == "NOT_CONSTRUCTED"
    assert result["live_trading_enabled"] is False
    assert not config.financial_path.exists() and not config.custody_path.exists()


@pytest.mark.asyncio
async def test_live_requires_receipt_before_financial_state_or_credentials(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    with pytest.raises(SessionBlocked, match="owner_receipt"):
        await compose_session(config, mode=TradingMode.LIVE, live_enabled=True)
    auth, verifier = signed(config)
    with pytest.raises(SessionBlocked, match="untrusted"):
        await compose_session(
            config,
            authority=replace(auth, max_attempts=500),
            verifier=verifier,
            mode=TradingMode.LIVE,
            live_enabled=True,
            clock=lambda: NOW,
        )
    assert not config.financial_path.exists()


@pytest.mark.asyncio
async def test_actual_sdk_account_reader_and_independent_custody_are_composed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ephemeral = Account.create()
    config = runtime_config(tmp_path, ephemeral.address)
    auth, verifier = signed(config)
    custody = SessionCustody(config.custody_path)
    custody.initialize()
    provision_session(config, auth, verifier, custody, now=NOW)
    journal = FinancialSessionJournal(config.financial_path, config.witness_root, auth)
    prepare_recovery(
        journal.path, journal.witness, tmp_path / "recovery", now=NOW, minimum_free_bytes=1000
    )
    backup = tmp_path / "recovery" / "receipt.json"
    publisher = CheckpointPublisher(
        auth, custody, config.outbox_path, clock=lambda: NOW, timeout_seconds=2
    )
    # Only commissioning opens this initial journal; publish the resulting exact
    # checkpoint and close. The worker must recover against independently retained proof.
    journal.open()
    publisher.publish(journal.checkpoint(), acknowledge=False)
    supervisor = SessionSupervisor(
        auth,
        custody,
        journal=journal.path,
        witness=journal.witness,
        outbox=config.outbox_path,
        backup_receipt=backup,
        policy=SupervisionPolicy(1000, 60, 2),
        clock=lambda: NOW,
        free_bytes=lambda _: 10000,
    )
    checkpoint = supervisor.inspect()
    custody.release_stop(auth.fingerprint, expected=checkpoint)
    journal.close()
    requests = []
    observed_fill = {"enabled": False, "price": "0.5"}

    def wire(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/geoblock":
            return httpx.Response(200, json={"blocked": False})
        if request.url.path == "/time":
            return httpx.Response(200, json=int(NOW.timestamp()))
        if request.url.path.startswith("/markets-by-token/"):
            return httpx.Response(200, json={"condition_id": auth.instruments[0].market})
        if request.url.path.startswith("/clob-markets/"):
            return httpx.Response(
                200, json={"nr": False, "mts": "0.01", "t": [{"t": SESSION_TOKEN}]}
            )
        if request.url.path == "/order" and request.method == "POST":
            state = session.coordinator.journal.read()
            assert any(row["state"] == "UNCERTAIN_SUBMIT" for row in state["orders"].values())
            order = json.loads(request.content)["order"]
            assert order["makerAmount"] == "1000000" and order["takerAmount"] == "2000000"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "errorMsg": "",
                    "orderID": "0x" + "2" * 64,
                    "status": "live",
                    "takingAmount": "0",
                    "makingAmount": "0",
                    "transactionsHashes": [],
                },
            )
        if request.url.host == "rpc.fixture":
            body = json.loads(request.content)
            method = body["method"]
            block = {
                "number": "0x100",
                "hash": "0x" + "f" * 64,
                "timestamp": hex(int(NOW.timestamp())),
            }
            result = {"eth_chainId": "0x89", "eth_getBlockByNumber": block, "eth_getLogs": []}.get(
                method
            )
            if (
                method == "eth_getLogs"
                and observed_fill["enabled"]
                and body["params"][0]["address"] == config.exchange
            ):
                from polysia.adapters.polymarket.session_chain import topic_address
                from tests.integration.test_session_sources_and_resources import abi, fill_log

                log = fill_log(10)
                log["address"] = config.exchange
                log["data"] = abi(0, int(SESSION_TOKEN), 1000000, 2000000, 1234, 0, 0)
                log["topics"][2] = topic_address(ephemeral.address)
                result = [log]
            if method == "eth_call":
                data = body["params"][0]["data"]
                result = (
                    hex(98998766 if observed_fill["enabled"] else 100000000)
                    if data.startswith("0x70a08231")
                    else (hex(2000000) if observed_fill["enabled"] else "0x0")
                )
            assert result is not None
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
        if request.url.path == "/balance-allowance":
            return httpx.Response(
                200,
                json={
                    "balance": "98998766" if observed_fill["enabled"] else "100000000",
                    "allowances": {},
                },
            )
        if request.url.path in {"/data/orders", "/data/trades"}:
            rows = []
            if request.url.path == "/data/trades" and observed_fill["enabled"]:
                rows = [
                    {
                        "id": "fixture-trade",
                        "market": auth.instruments[0].market,
                        "asset_id": SESSION_TOKEN,
                        "owner": "fixture-api",
                        "maker_address": ephemeral.address,
                        "taker_order_id": "0x" + "2" * 64,
                        "side": "BUY",
                        "trader_side": "TAKER",
                        "price": observed_fill["price"],
                        "size": "2",
                        "outcome": "Yes",
                        "status": "CONFIRMED",
                        "fee_rate_bps": "0",
                        "bucket_index": 0,
                        "transaction_hash": "0x" + "a" * 64,
                        "maker_orders": [],
                        "match_time": int(NOW.timestamp()),
                        "last_update": int(NOW.timestamp()),
                    }
                ]
            return httpx.Response(200, json={"data": rows, "next_cursor": "LTE=", "limit": 100})
        raise AssertionError("unexpected request; automatic credential or wallet setup forbidden")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(wire))
    monkeypatch.setenv(config.private_key_reference, ephemeral.key.hex())
    monkeypatch.setenv(
        config.api_credentials_reference,
        json.dumps(
            {
                "apiKey": "fixture-api",
                "secret": base64.urlsafe_b64encode(b"fixture-only").decode(),
                "passphrase": "fixture-only",
            }
        ),
    )
    def await_supervisor(_seconds: float) -> None:
        # This proof composes the actual owners with deterministic scheduling.
        # A polling thread can queue duplicate inspections and race SQLite reads
        # with its own ACK transaction on slow Windows storage. Complete the
        # actual inspection at the injected wait boundary; the publisher still
        # enforces its original real monotonic ACK deadline. Process ownership
        # and durable STOP have separate acceptance tests.
        supervisor.inspect()

    from functools import partial

    import polysia.adapters.polymarket.session_composition as composition
    from polysia.application.services.financial_session import FinancialSessionCoordinator

    monkeypatch.setattr(composition, "CheckpointPublisher",
                        partial(CheckpointPublisher, wait=await_supervisor))
    # UTC is frozen for this composition proof. Freeze the coordinator's
    # monotonic clock too, so slow fixture filesystem work does not simulate
    # elapsed supervision time. Dedicated expiry tests advance monotonic time
    # and prove that supervision expiry still blocks submission.
    monkeypatch.setattr(
        composition,
        "FinancialSessionCoordinator",
        partial(FinancialSessionCoordinator, monotonic=lambda: 0),
    )

    session = None
    try:
        session = await compose_session(
            config,
            authority=auth,
            verifier=verifier,
            mode=TradingMode.LIVE,
            live_enabled=True,
            clock=lambda: NOW,
        )
        assert requests == []  # construction performs no bootstrap network mutation/read
        await session.reconcile()
        assert session.coordinator.journal.read()["reconciliation_ok"] is True
        assert session.network.observation()["actual_requests"] == len(requests)
        assert all(method == "GET" or path == "/" for method, path in requests)
        before = len(requests)
        read_policy = AcquisitionPolicy(
            "fixture-read-only",
            socket.gethostname(),
            NOW,
            NOW + timedelta(hours=1),
            (
                config.rpc_url,
                "https://polymarket.com/api/geoblock",
                "https://clob.polymarket.com/data/orders",
                "https://clob.polymarket.com/data/trades",
                "https://clob.polymarket.com/balance-allowance",
            ),
            100,
            200000,
            4096,
            2,
            1000,
            1,
            60,
            1,
            2,
            100000000,
            25,
        )
        allowance = AcquisitionAuthority(tmp_path / "read-only/allowance.sqlite3", read_policy)
        disabled = await qualify_account(
            config, auth.instruments, allowance, read_account=False, clock=lambda: NOW
        )
        assert disabled["network"] == "NOT_CONSTRUCTED" and len(requests) == before
        qualified = await qualify_account(
            config, auth.instruments, allowance, read_account=True, clock=lambda: NOW
        )
        assert qualified["opening"]["cash"] == 100 and qualified["opening"]["positions"] == ()
        assert qualified["financial_authority"] == "NOT_ISSUED"
        assert qualified["acquisition"]["requests_charged"] == len(requests) - before
        # Complete the actual coordinator -> Risk -> LiveBroker -> SDK signing
        # and HTTP boundary. Only clock, network and temporary custody are fakes.
        from polymarket._internal.actions.orders import limit as sdk_limit

        from tests.integration.test_financial_session import opportunity

        monkeypatch.setattr(sdk_limit.time, "time", lambda: NOW.timestamp())
        await session.start()
        candidate = opportunity(
            strategy=config.policy.version,
            exit_policy=config.policy.version,
            policy_digest=config.policy.fingerprint,
        )
        candidate = replace(
            candidate, event=replace(candidate.event, instrument=auth.instruments[0])
        )
        intent_id = await session.coordinator.submit(candidate)
        assert session.coordinator.journal.read()["orders"][intent_id]["state"] == "ACCEPTED"
        observed_fill["enabled"] = True
        await session.reconcile()
        assert session.coordinator.journal.read()["orders"][intent_id]["state"] == "FINALIZED"
        assert session.coordinator.journal.read()["reconciliation_ok"] is True
        qualified = await qualify_account(
            config, auth.instruments, allowance, read_account=True, clock=lambda: NOW
        )
        assert qualified["opening"]["cash"] == D("98.998766")
        assert qualified["opening"]["positions"] == ((SESSION_TOKEN, D(2)),)
        assert qualified["opening"]["cumulative_fees"] == D("0.001234")
        observed_fill["price"] = "0.9"
        with pytest.raises(SessionBlocked, match="trade_inventory_disagree"):
            await qualify_account(
                config, auth.instruments, allowance, read_account=True, clock=lambda: NOW
            )
    finally:
        if session is not None:
            await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["BUY", "SELL"])
async def test_actual_sdk_eoa_signature_preserves_exact_amounts_and_exchange(side):
    from types import SimpleNamespace

    from polymarket import AsyncSecureClient
    from polymarket._internal.actions.orders.types import OrderDraft
    from polymarket.environments import PRODUCTION
    from polymarket.types import EvmAddress

    from polysia.adapters.polymarket.session_sdk import assert_exact_prepared

    signer = Account.create()
    exchange = PRODUCTION._config.standard_exchange
    client = SimpleNamespace(
        _ctx=SimpleNamespace(
            wallet=EvmAddress(signer.address), wallet_type="EOA", signer=signer, signer_type="OWNER"
        )
    )
    draft = OrderDraft(
        chain_id=137,
        exchange_address=exchange,
        expiration=2000000000,
        funder_address=EvmAddress(signer.address),
        offered_amount=1000000 if side == "BUY" else 2000000,
        requested_amount=2000000 if side == "BUY" else 1000000,
        order_type="GTD",
        side=side,
        signer=EvmAddress(signer.address),
        asset_id=SESSION_TOKEN,
    )
    prepared = await AsyncSecureClient._sign_order(client, draft, post_only=False)
    request = dict(
        token_id=SESSION_TOKEN, side=side, size=D(2), price=D("0.5"), expiration=2000000000
    )
    check = dict(exchange=exchange, signer=signer.address, funder=signer.address, request=request)
    assert_exact_prepared(prepared, **check)
    with pytest.raises(SessionBlocked, match="economics"):
        assert_exact_prepared(prepared, **{**check, "request": {**request, "size": D("2.001")}})
    with pytest.raises(SessionBlocked, match="authorized_exchange"):
        assert_exact_prepared(prepared, **{**check, "exchange": "0x" + "3" * 40})
    with pytest.raises(SessionBlocked, match="envelope"):
        assert_exact_prepared(replace(prepared, post_only=True), **check)
    changed = replace(prepared, maker_amount=prepared.maker_amount + 1)
    with pytest.raises(SessionBlocked, match="economics"):
        assert_exact_prepared(changed, **check)


def test_sdk_route_scope_denies_unreviewed_v3_namespace_and_contract(tmp_path):
    from polysia.adapters.polymarket.session_sdk import require_sdk_scope

    config = runtime_config(tmp_path)
    auth, _ = signed(config)
    require_sdk_scope(config, auth.instruments)
    with pytest.raises(SessionBlocked, match="scope_mismatch"):
        require_sdk_scope(replace(config, exchange="0x" + "3" * 40), auth.instruments)
    with pytest.raises(SessionBlocked, match="scope_mismatch"):
        require_sdk_scope(config, (replace(auth.instruments[0], token="101"),))


def test_frozen_input_hash_and_parser_share_one_snapshot(tmp_path, monkeypatch):
    import polysia.deployment.financial_session_runtime as runtime

    path = tmp_path / "bound.json"
    original = b'{"bound":"original"}'
    path.write_bytes(original)
    reader = runtime.read_publication_bytes
    reads = []

    def rotate_after_read(target, *, maximum_bytes):
        raw = reader(target, maximum_bytes=maximum_bytes)
        reads.append(target)
        target.write_bytes(b'{"bound":"unreviewed replacement"}')
        return raw

    monkeypatch.setattr(runtime, "read_publication_bytes", rotate_after_read)
    expected = hashlib.sha256(original).hexdigest()
    assert runtime.read_bound_json(path, expected) == {"bound": "original"}
    assert reads == [path]
    with pytest.raises(SessionBlocked, match="frozen_retained_input_changed"):
        runtime.read_bound_json(path, expected)
