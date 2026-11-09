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
    ExactSessionEntry,
    InstrumentScope,
    SessionAccountIdentity,
    SessionBlocked,
    canonical_json,
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


def test_owner_entry_runner_follows_the_protective_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime

    from polysia.cli_commands import session as command

    envelope = authorization(protective_until=NOW + timedelta(hours=1, seconds=1))
    times = iter([NOW, NOW, NOW, envelope.protective_until])
    calls: list[bool] = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    class Session:
        async def start(self):
            return None

        async def tick(self, *, owner_entry: bool):
            calls.append(owner_entry)
            return {"polls": len(calls)}

        async def close(self):
            calls.append(False)

    async def compose(*args, **kwargs):
        return Session()

    async def sleep(seconds):
        assert seconds <= 1

    config = replace(runtime_config(tmp_path), exact_entry=ExactSessionEntry(D(5), D("0.50")))
    monkeypatch.setattr(command, "datetime", Clock)
    monkeypatch.setattr(command, "load_runtime_config", lambda _: config)
    monkeypatch.setattr(command, "load_authority", lambda _: envelope)
    monkeypatch.setattr(command, "compose_session", compose)
    monkeypatch.setattr(command.asyncio, "sleep", sleep)
    command.run(tmp_path / "config", tmp_path / "authority", mode=TradingMode.LIVE,
                live_enabled=True, owner_entry=True)
    assert calls == [True, True, False]


def test_external_owner_receipt_round_trip_and_tamper_denial(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from polysia.cli_commands.session import session_app
    from polysia.deployment.financial_session_runtime import load_authority

    config = runtime_config(tmp_path)
    envelope, _ = signed(config)
    draft = replace(envelope, owner_receipt="UNSIGNED")
    source, message, signature, trust, output = (
        tmp_path / name for name in ("draft", "message", "signature", "trust", "receipt")
    )
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes_raw()
    trust.write_text(json.dumps({"owner": base64.b64encode(public_key).decode()}))
    source.write_text(canonical_json(asdict(draft)))
    receipt_id = "test-receipt-external-001"
    opts = ["--authority", str(source), "--key-id", "owner", "--receipt-id", receipt_id]
    runner = CliRunner()
    result = runner.invoke(session_app, ["receipt-message", *opts, "--output", str(message)])
    assert result.exit_code == 0, result.output
    assert message.read_bytes() == receipt_message(draft, key_id="owner", receipt_id=receipt_id)
    signature.write_bytes(key.sign(message.read_bytes()))
    attach = ["attach-receipt", *opts, "--signature", str(signature), "--trust", str(trust)]
    result = runner.invoke(session_app, [*attach, "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert SessionReceiptVerifier({"owner": public_key}).verify(
        load_authority(output), draft.binding, now=NOW
    ).receipt_id == receipt_id
    source.write_text(canonical_json(asdict(replace(draft, max_attempts=draft.max_attempts + 1))))
    rejected = tmp_path / "rejected"
    result = runner.invoke(session_app, [*attach, "--output", str(rejected)])
    assert result.exit_code != 0 and not rejected.exists()

D = Decimal
SESSION_TOKEN = str(1 << 40)


def runtime_config(
    root: Path, signer: str = "0x" + "1" * 40, *, include_history: bool = False
) -> SessionRuntimeConfig:
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
        rpc_url=("https://polygon-mainnet.g.alchemy.com/v2" if include_history
                 else "https://rpc.fixture/"),
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
        rpc_checkpoint_path=root / "checkpoint.sqlite3" if include_history else None,
        rpc_bearer_token_reference="POLYSIA_FIXTURE_RPC" if include_history else None,
        historical_instruments=(InstrumentScope(
            "0x" + "c" * 64, str(int(SESSION_TOKEN) + 1), mapping.collateral,
            mapping.settlement_route,
        ),) if include_history else (),
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
@pytest.mark.parametrize("payout", [0, 1])
async def test_retained_inventory_requires_pinned_condition_resolution(payout: int) -> None:
    from polysia.adapters.polymarket.session_chain import CTFChainReader, ReadOnlyRPC

    market = "0x" + "ab" * 32
    block = {"hash": "0x" + "cd" * 32}
    ctf = "0x" + "ab" * 20

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["method"] == "eth_call"
        assert payload["params"] == [
            {"to": ctf, "data": "0xdd34de67" + market[2:]},
            {"blockHash": block["hash"], "requireCanonical": True},
        ]
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": payload["id"], "result": f"0x{payout:064x}"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        chain = CTFChainReader(
            ReadOnlyRPC(http, "https://rpc.example"),
            exchange=ctf, ctf=ctf, collateral=ctf, instruments=(),
        )
        if payout:
            assert await chain.require_resolved(market, block=block) == payout
        else:
            with pytest.raises(SessionBlocked, match="retained_inventory_resolution_unverified"):
                await chain.require_resolved(market, block=block)


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
@pytest.mark.parametrize(("signature_type", "cancel"), [(0, False), (3, False), (3, True)])
async def test_actual_sdk_account_reader_and_independent_custody_are_composed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signature_type: int, cancel: bool
) -> None:
    from polymarket._internal.wallet import derive_beacon_deposit_wallet_address
    from polymarket.environments import PRODUCTION

    ephemeral = Account.create()
    config = runtime_config(tmp_path, ephemeral.address, include_history=cancel)
    if cancel:
        config = replace(config, exact_entry=ExactSessionEntry(D(5), D("0.50")))
    historical = next(iter(config.historical_instruments), None)
    funder = ephemeral.address
    if signature_type == 3:
        funder = derive_beacon_deposit_wallet_address(
            ephemeral.address, PRODUCTION._config.wallet_derivation
        )
        config = replace(
            config, account_mapping=replace(
                config.account_mapping, funder=funder, signature_type=signature_type
            )
        )
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
    rpc_methods: list[str] = []
    observed_fill = {"enabled": False, "price": "0.5"}

    def wire(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url == httpx.URL(config.rpc_url) and historical is not None:
            assert request.headers["Authorization"] == "Bearer fixture-rpc-value"
        else:
            assert "Authorization" not in request.headers
        if request.url.path == "/order" and request.method == "DELETE":
            assert cancel
            assert request.headers["POLY_ADDRESS"].lower() == ephemeral.address.lower()
            assert json.loads(request.content) == {"orderID": "0x" + "2" * 64}
            return httpx.Response(200, json={"canceled": ["0x" + "2" * 64], "not_canceled": {}})
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
            assert order["signatureType"] == signature_type
            assert order["signer"].lower() == funder.lower()
            assert order["maker"].lower() == funder.lower()
            assert order["makerAmount"] == ("2500000" if cancel else "1000000")
            assert order["takerAmount"] == ("5000000" if cancel else "2000000")
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
        if request.url == httpx.URL(config.rpc_url):
            body = json.loads(request.content)
            method = body["method"]
            rpc_methods.append(method)
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
                and (observed_fill["enabled"] or historical is not None)
                and body["params"][0]["address"] == config.exchange
            ):
                from polysia.adapters.polymarket.session_chain import topic_address
                from tests.integration.test_session_sources_and_resources import abi, fill_log

                log = fill_log(10)
                log["address"] = config.exchange
                token = historical.token if historical is not None else SESSION_TOKEN
                fee = 0 if historical is not None else 1234
                log["data"] = abi(0, int(token), 1000000, 2000000, fee, 0, 0)
                log["topics"][2] = topic_address(funder)
                result = [log]
            if method == "eth_call":
                data = body["params"][0]["data"]
                if data.startswith("0x4e1273f4"):
                    from eth_abi import decode, encode

                    accounts, tokens = decode(["address[]", "uint256[]"], bytes.fromhex(data[10:]))
                    assert set(accounts) == {funder.lower()}
                    assert set(tokens) == {int(SESSION_TOKEN), int(historical.token)}
                    result = "0x" + encode(["uint256[]"], [[0, 0]]).hex()
                else:
                    result = (
                        hex(98998766 if observed_fill["enabled"] else 100000000)
                        if data.startswith("0x70a08231")
                        else (hex(2000000) if observed_fill["enabled"] else "0x0")
                    )
            assert result is not None
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
        if request.url.path == "/balance-allowance":
            assert request.url.params["signature_type"] == str(signature_type)
            return httpx.Response(
                200,
                json={
                    "balance": "98998766" if observed_fill["enabled"] else "100000000",
                    "allowances": {},
                },
            )
        if request.url.path == "/data/wallet-open-orders":
            assert signature_type == 3
            cursor = request.url.params.get("cursor")
            assert cursor in {None, "fixture-wallet-page"}
            next_cursor = "fixture-wallet-page" if cancel and cursor is None else ""
            return httpx.Response(200, json={"data": [], "next_cursor": next_cursor})
        if request.url.path in {"/data/orders", "/data/trades"}:
            rows = []
            if request.url.path == "/data/trades" and (
                observed_fill["enabled"] or historical is not None
            ):
                rows = [
                    {
                        "id": "fixture-trade",
                        "market": historical.market if historical else auth.instruments[0].market,
                        "asset_id": historical.token if historical else SESSION_TOKEN,
                        "owner": "fixture-api",
                        "maker_address": funder,
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
    if config.rpc_bearer_token_reference is not None:
        monkeypatch.setenv(config.rpc_bearer_token_reference, "fixture-rpc-value")
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
    supervisor_time = 0.0

    def await_supervisor(seconds: float) -> None:
        nonlocal supervisor_time
        # This proof composes the actual owners with deterministic scheduling.
        # A polling thread can queue duplicate inspections and race SQLite reads
        # with its own ACK transaction on slow Windows storage. Complete the
        # actual inspection at the injected wait boundary. Advance the test
        # clock only for the simulated polling wait. Process ownership
        # and durable STOP have separate acceptance tests.
        supervisor.inspect()
        supervisor_time += seconds

    from functools import partial

    import polysia.adapters.polymarket.session_composition as composition
    from polysia.application.services.financial_session import FinancialSessionCoordinator

    monkeypatch.setattr(
        composition, "CheckpointPublisher",
        partial(CheckpointPublisher, wait=await_supervisor, monotonic=lambda: supervisor_time),
    )
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
        if historical is not None:
            assert session.account.last_fills[0].occurrence.instrument == historical
            broker = session.coordinator.execution.broker
            assert broker._allowed_token_ids == {SESSION_TOKEN}
        assert session.network.observation()["actual_requests"] == len(requests)
        assert all(method == "GET" or path == httpx.URL(config.rpc_url).path
                   for method, path in requests)
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
            ) + (("https://clob.polymarket.com/data/wallet-open-orders",)
                 if signature_type == 3 else ()),
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
        warm_start = len(rpc_methods)
        qualified = await qualify_account(
            config, auth.instruments, allowance, read_account=True, clock=lambda: NOW
        )
        assert qualified["opening"]["cash"] == 100 and qualified["opening"]["positions"] == ()
        assert qualified["financial_authority"] == "NOT_ISSUED"
        assert qualified["acquisition"]["requests_charged"] == len(requests) - before
        if historical is not None:
            assert "eth_getLogs" not in rpc_methods[warm_start:]
            assert rpc_methods[warm_start:].count("eth_call") == 2  # cash and one CTF batch
            missing_history = replace(config, historical_instruments=())
            with pytest.raises(SessionBlocked, match="trade_ownership_or_contribution_unknown"):
                await qualify_account(
                    missing_history, auth.instruments, allowance,
                    read_account=True, clock=lambda: NOW,
                )
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
            shares=D(5) if cancel else D(2),
        )
        candidate = replace(
            candidate, event=replace(candidate.event, instrument=auth.instruments[0])
        )
        intent_id = await session.coordinator.submit(candidate)
        assert session.coordinator.journal.read()["orders"][intent_id]["state"] == "ACCEPTED"
        if cancel:
            await session.coordinator.cancel(intent_id)
            assert requests.count(("DELETE", "/order")) == 1
            pending = session.coordinator.journal.read()["orders"][intent_id]
            assert pending["state"] == "CANCEL_PENDING"
            with pytest.raises(SessionBlocked, match="known_open_order"):
                await session.coordinator.cancel(intent_id)
            assert requests.count(("DELETE", "/order")) == 1
            return
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
@pytest.mark.parametrize("signature_type", [0, 3])
async def test_actual_sdk_signature_preserves_exact_amounts_and_exchange(side, signature_type):
    from types import SimpleNamespace

    from polymarket import AsyncSecureClient
    from polymarket._internal.actions.orders.types import OrderDraft
    from polymarket._internal.wallet import derive_beacon_deposit_wallet_address
    from polymarket.environments import PRODUCTION
    from polymarket.types import EvmAddress

    from polysia.adapters.polymarket.session_sdk import assert_exact_prepared

    signer = Account.create()
    exchange = PRODUCTION._config.standard_exchange
    funder = EvmAddress(signer.address)
    wallet_type = "EOA"
    if signature_type == 3:
        funder = derive_beacon_deposit_wallet_address(
            signer.address, PRODUCTION._config.wallet_derivation
        )
        wallet_type = "DEPOSIT_WALLET"
    client = SimpleNamespace(
        _ctx=SimpleNamespace(
            wallet=funder, wallet_type=wallet_type, signer=signer, signer_type="OWNER"
        )
    )
    draft = OrderDraft(
        chain_id=137,
        exchange_address=exchange,
        expiration=2000000000,
        funder_address=funder,
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
    check = dict(
        exchange=exchange, signer=signer.address, funder=funder, signature_type=signature_type,
        request=request,
    )
    assert_exact_prepared(prepared, **check)
    if signature_type == 3:
        wrong_nibble = "f" if prepared.signature[-1] != "f" else "e"
        changed_signature = replace(prepared, signature=prepared.signature[:-1] + wrong_nibble)
        with pytest.raises(SessionBlocked, match="authorized_exchange"):
            assert_exact_prepared(changed_signature, **check)
        with pytest.raises(SessionBlocked, match="envelope"):
            assert_exact_prepared(replace(prepared, signer=signer.address), **check)
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
