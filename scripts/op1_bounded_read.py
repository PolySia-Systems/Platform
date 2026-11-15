"""Finite, owner-authorized GET-only qualification. Never signs trading orders."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from eth_account import Account
from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.auth import build_l1_auth_headers
from polymarket._internal.l1_auth import sign_api_key_auth
from polymarket._internal.wallet import try_classify_wallet_type
from polymarket.environments import PRODUCTION

from polysia.adapters.polymarket.order_lifecycle_account import (
    OrderLifecycleAccountReader,
    explicit_zero_fee_market,
    scoped_opening,
)
from polysia.adapters.polymarket.session_account import ExactAccountMapping
from polysia.adapters.polymarket.session_sdk import confine_sdk_http, require_sdk_scope
from polysia.domain.financial_session import InstrumentScope, canonical_json
from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy
from polysia.storage.acquisition_authority import AcquisitionAuthority

ROOT = Path("/probe")
CONDITION = os.environ.get("POLYSIA_OP1_MARKET", "")
TOKEN = os.environ.get("POLYSIA_OP1_TOKEN", "")
MARKET_URL = "https://clob.polymarket.com/clob-markets/" + CONDITION
ENDPOINTS = (
    "https://polymarket.com/api/geoblock",
    "https://clob.polymarket.com/time",
    "https://clob.polymarket.com/auth/derive-api-key",
    "https://clob.polymarket.com/data/orders",
    "https://clob.polymarket.com/data/wallet-open-orders",
    "https://clob.polymarket.com/data/trades",
    "https://clob.polymarket.com/balance-allowance",
    MARKET_URL,
    "https://clob.polymarket.com/fee-rate",
    "https://gamma-api.polymarket.com/markets",
    "https://clob.polymarket.com/book",
)


def private_write(path: Path, value: object) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        f.write(canonical_json(value) + "\n")


def credential_json(credentials: ApiKeyCreds) -> str:
    """Use the SDK's validation alias; default model dumping does not round-trip it."""
    return json.dumps(
        {
            "apiKey": credentials.key,
            "secret": credentials.secret,
            "passphrase": credentials.passphrase,
        }
    )


def read_bounds(
    grant: dict[str, Any],
    continuation: dict[str, Any] | None,
    *,
    now: datetime,
) -> tuple[int, int, datetime, datetime, int, int]:
    """Only a fresh explicit grant can create a new, deductive GET allowance."""
    maximum_requests = grant["maximum_requests"]
    maximum_bytes = grant["maximum_bytes"]
    first_start = datetime.fromisoformat(grant["starts_at"])
    prior_requests = 0 if continuation is None else continuation["requests_charged"]
    prior_bytes = 0 if continuation is None else continuation["bytes_charged"]
    if (
        grant["scope"] != "GET_ONLY"
        or type(maximum_requests) is not int
        or not 0 < maximum_requests <= 100
        or type(maximum_bytes) is not int
        or not 0 < maximum_bytes <= 12 * 1024 * 1024
        or first_start.utcoffset() != timedelta(0)
        or now.utcoffset() != timedelta(0)
        or not first_start <= now < first_start + timedelta(hours=2)
        or type(prior_requests) is not int
        or not 0 <= prior_requests < maximum_requests
        or type(prior_bytes) is not int
        or not 0 <= prior_bytes < maximum_bytes
    ):
        raise ValueError("Explicit finite GET grant and retained consumption required")
    return (
        prior_requests,
        prior_bytes,
        first_start,
        min(now + timedelta(seconds=115), first_start + timedelta(hours=2)),
        maximum_requests,
        maximum_bytes,
    )


async def main(*, credential_sink: Callable[[str, str], None] | None = None) -> None:
    now = datetime.now(UTC)
    if not CONDITION or not TOKEN:
        raise ValueError("Explicit frozen instrument required before provider reads")
    capacity_mode = (ROOT / "capacity-mode.json").exists()
    sdk_mode = capacity_mode or (ROOT / "refresh-mode").exists()
    capacity_config = None
    capacity_context = None
    if capacity_mode:
        from polysia.deployment.financial_session_runtime import load_runtime_config

        capacity_config = load_runtime_config(Path("/capacity-config.json"))
        capacity_context = json.loads((ROOT / "capacity-mode.json").read_text())
        if (
            capacity_config.maximum_response_bytes != 65536
            or capacity_config.maximum_pages != 1
            or capacity_config.maximum_queued != 1
        ):
            raise ValueError("Fixed bounded read workload required")
    continuation = (
        json.loads((ROOT / "continuation.json").read_text())
        if (ROOT / "continuation.json").exists()
        else None
    )
    grant = json.loads((ROOT / "grant.json").read_text())
    (prior_requests, prior_bytes, first_start, deadline, maximum_requests, maximum_bytes) = (
        read_bounds(grant, continuation, now=now)
    )
    policy_endpoints = (
        ENDPOINTS
        if not sdk_mode
        else tuple(url for url in ENDPOINTS if url != "https://gamma-api.polymarket.com/markets")
        + ("https://gamma-api.polymarket.com/markets/keyset",)
    )
    policy = AcquisitionPolicy(
        grant["id"] + ("" if continuation is None else "-continuation"),
        socket.gethostname(),
        now,
        deadline,
        policy_endpoints,
        maximum_requests - prior_requests,
        maximum_bytes - prior_bytes,
        65536 if capacity_mode else 512 * 1024,
        15,
        64 * 1024 * 1024,
        1,
        60,
        1,
        2,
        512 * 1024 * 1024,
        25,
        window_seconds=60,
        window_maximum_requests=60,
        window_maximum_bytes=maximum_bytes - prior_bytes,
    )
    authority = AcquisitionAuthority(ROOT / "allowance.sqlite3", policy)
    authority.initialize()
    private_write(ROOT / "read-policy.json", asdict(policy))
    wire = []
    started = time.monotonic()

    class ReadTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.AsyncHTTPTransport(retries=0)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.method != "GET" or time.monotonic() - started >= 115:
                raise RuntimeError("GET-only finite read boundary")
            endpoint = str(request.url.copy_with(query=None))
            request_id = authority.reserve(
                endpoint, now=datetime.now(UTC), host=socket.gethostname()
            )
            request.headers["Accept-Encoding"] = "identity"
            raw = bytearray()
            async with asyncio.timeout(15):
                response = await self.inner.handle_async_request(request)
                try:
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise RuntimeError("Unbounded content encoding")
                    async for chunk in response.aiter_raw():
                        raw.extend(chunk)
                        if len(raw) > policy.maximum_response_bytes:
                            raise RuntimeError("Bounded response limit")
                finally:
                    await response.aclose()
            authority.settle(request_id, response_bytes=len(raw))
            # Retain method/status/bytes only. Auth response bodies and headers
            # must never be written to a diagnostic or operational receipt.
            wire.append(
                {
                    "method": "GET",
                    "path": request.url.path,
                    "status": response.status_code,
                    "bytes": len(raw),
                }
            )
            return httpx.Response(
                response.status_code, content=bytes(raw), headers=response.headers, request=request
            )

        async def aclose(self) -> None:
            await self.inner.aclose()

    client = None
    receipt = {
        "status": "BLOCKED",
        "financial_actions": 0,
        "trading_order_signatures": 0,
        "evidence_scope": "OWNER_ORDER_LIFECYCLE_API",
        "full_account_reconciled": False,
    }
    try:
        secret = json.loads((ROOT / "credentials.json").read_text())
        private = secret["POLYMARKET_PRIVATE_KEY"]
        funder = secret["POLYMARKET_FUNDER_ADDRESS"]
        if secret.get("POLYMARKET_SIGNATURE_TYPE") not in (None, "", "3"):
            raise RuntimeError("Existing signature type is not 3")
        signer = Account.from_key(private)
        environment = PRODUCTION._config
        if (
            try_classify_wallet_type(
                signer=signer.address, wallet=funder, config=environment.wallet_derivation
            )
            != "DEPOSIT_WALLET"
        ):
            raise RuntimeError("Designated signer/funder mapping differs")
        mapping = ExactAccountMapping(
            "op1-owner-test",
            signer.address,
            funder,
            3,
            "polymarket",
            environment.collateral_token.lower(),
            "ctf-exchange-v2-standard",
        )
        scope = InstrumentScope(CONDITION, TOKEN, mapping.collateral, mapping.settlement_route)
        require_sdk_scope(
            SimpleNamespace(
                exchange=environment.standard_exchange.lower(),
                ctf=environment.conditional_tokens.lower(),
                collateral_adapter=environment.collateral_adapter.lower(),
                account_mapping=mapping,
            ),
            (scope,),
        )
        async with httpx.AsyncClient(
            transport=ReadTransport(), follow_redirects=False, timeout=15
        ) as http:
            geo = await http.get(ENDPOINTS[0])
            geo.raise_for_status()
            eligibility = geo.json()
            if eligibility.get("blocked") is not False:
                raise RuntimeError("Venue eligibility denied or unknown")
            timestamp = int(datetime.now(UTC).timestamp())
            if not capacity_mode:
                clock_response = await http.get(ENDPOINTS[1])
                clock_response.raise_for_status()
                timestamp = int(clock_response.json())
            headers = build_l1_auth_headers(
                sign_api_key_auth(
                    signer,
                    chain_id=137,
                    timestamp=timestamp,
                    nonce=0,
                )
            )
            derived = await http.get(ENDPOINTS[2], headers=headers)
            derived.raise_for_status()
            credentials = ApiKeyCreds.model_validate(derived.json())
            if credential_sink is not None:
                credential_sink(private, credential_json(credentials))
            client = await AsyncSecureClient._create(
                private_key=private,
                wallet=funder,
                credentials=credentials,
                validate_credentials=False,
                logger=logging.getLogger("op1-read-only"),
            )
            await confine_sdk_http(client, ReadTransport, rpc_url="", timeout=15)
            if (ROOT / "permissions-only").is_file():
                value = await client.get_balance_allowance(asset_type="CONDITIONAL", asset_id=TOKEN)
                matches = [
                    amount
                    for spender, amount in value.allowances.items()
                    if spender.lower() == environment.standard_exchange.lower()
                ]
                allowance = None if len(matches) != 1 else Decimal(matches[0]) / Decimal(1_000_000)
                receipt.update(
                    status="PROTECTIVE_ALLOWANCE_OBSERVED",
                    observed_at=datetime.now(UTC),
                    account_mapping=asdict(mapping),
                    tested_token_allowance=allowance,
                    five_share_exit_permitted=allowance is not None and allowance >= 5,
                )
                return
            sample_started = time.monotonic()
            raw_market = await http.get(MARKET_URL)
            raw_market.raise_for_status()
            if sdk_mode:
                gamma_rows = []
                async for page in client.list_markets(
                    condition_ids=(CONDITION,),
                    include_tag=True,
                    page_size=2,
                ):
                    if page.has_more or page.limit_reached or len(page.items) != 1:
                        raise RuntimeError("Unique complete SDK market lookup required")
                    model = page.items[0]
                    gamma_rows = [
                        {
                            "conditionId": model.condition_id,
                            "feesEnabled": model.trading.fees_enabled,
                            "negRisk": model.state.neg_risk,
                            "clobTokenIds": json.dumps(
                                [model.outcomes.yes.token_id, model.outcomes.no.token_id]
                            ),
                            "active": model.state.active,
                            "closed": model.state.closed,
                            "acceptingOrders": model.state.accepting_orders,
                        }
                    ]
                    break
            else:
                gamma = await http.get(ENDPOINTS[9], params={"condition_ids": CONDITION})
                gamma.raise_for_status()
                gamma_rows = gamma.json()
            rate = await http.get(ENDPOINTS[8], params={"token_id": TOKEN})
            rate.raise_for_status()
            zero = explicit_zero_fee_market(
                raw_market.json(), TOKEN, gamma=gamma_rows, fee_rate=rate.json()
            )
            reader = OrderLifecycleAccountReader(
                client,
                mapping,
                maximum_pages=1 if capacity_mode else 4,
                clock=lambda: datetime.now(UTC),
                trades_after=None
                if not capacity_mode
                else datetime.fromisoformat(capacity_context["initial_clear_baseline_at"])
                - timedelta(seconds=30),
            )
            evidence = await reader.observe(
                scope,
                exchange=environment.standard_exchange.lower(),
                tracked={},
                explicit_zero_fee=zero,
            )
            if sdk_mode:
                model_book = await client.get_order_book(asset_id=TOKEN)
                book_data = model_book.model_dump(mode="json")
                book_data["timestamp"] = str(int(model_book.timestamp.timestamp() * 1000))
            else:
                book = await http.get(ENDPOINTS[10], params={"token_id": TOKEN})
                book.raise_for_status()
                book_data = json.loads(book.content, parse_float=Decimal)
            asks = [(Decimal(x["price"]), Decimal(x["size"])) for x in book_data["asks"]]
            bids = [(Decimal(x["price"]), Decimal(x["size"])) for x in book_data["bids"]]
            ask = min((x[0] for x in asks), default=None)
            bid = max((x[0] for x in bids), default=None)
            candidate = {
                "instrument": asdict(scope),
                "zero_fee": zero,
                "best_ask": ask,
                "best_bid": bid,
                "minimum_size": Decimal(book_data["min_order_size"]),
                "negative_risk": book_data.get("neg_risk"),
                "entry_depth": sum((s for p, s in asks if p == ask), Decimal(0)),
                "exit_depth": sum((s for p, s in bids if p == bid), Decimal(0)),
            }
            opening = (
                None
                if capacity_mode and not (ROOT / "packet-mode").exists()
                else scoped_opening(evidence, account=mapping.account_id, explicit_zero_fee=zero)
            )
            flat_capacity_evidence = bool(
                capacity_mode
                and zero
                and evidence["tested_token_balance"] == 0
                and not evidence["open_order_ids"]
                and not evidence["pending_trade_ids"]
                and evidence["tested_token_allowance"] is not None
                and evidence["tested_token_allowance"] >= 5
                and evidence["usable_collateral"] is not None
            )
            rows = gamma_rows
            market = rows[0] if len(rows) == 1 else {}
            quote_age = datetime.now(UTC).timestamp() - int(book_data["timestamp"]) / 1000
            eligible = bool(
                (opening is not None or flat_capacity_evidence)
                and zero
                and ask is not None
                and bid is not None
                and 0 < ask <= Decimal("0.50")
                and 0 < bid < 1
                and candidate["entry_depth"] >= 5
                and candidate["exit_depth"] >= 5
                and 0 < candidate["minimum_size"] <= 5
                and book_data.get("neg_risk") is False
                and book_data.get("market") == CONDITION
                and book_data.get("asset_id") == TOKEN
                and market.get("active") is True
                and market.get("closed") is False
                and market.get("acceptingOrders") is True
                and 0 <= quote_age <= 30
                and evidence["usable_collateral"] >= 5 * ask
            )
            candidate["technically_eligible_at_observation"] = eligible
            candidate["quote_age_seconds"] = str(quote_age)
            if capacity_mode:
                import resource

                from polysia.deployment.financial_session_runtime import capacity_workload

                sample_seconds = Decimal(str(time.monotonic() - sample_started))
                rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                free_bytes = shutil.disk_usage(ROOT).free
                passed = bool(
                    eligible
                    and sample_seconds <= 30
                    and rss_bytes < 512 * 1024 * 1024
                    and free_bytes >= capacity_config.minimum_free_disk_bytes
                    and all(row["status"] == 200 and row["bytes"] <= 65536 for row in wire)
                )
                capacity_record = {
                    "version": "financial-session-capacity/v1",
                    "workload_digest": capacity_workload(capacity_config),
                    "host": socket.gethostname(),
                    "synthetic": False,
                    "status": "PASS" if passed else "BLOCKED",
                    "samples": 1,
                    "observed_at": datetime.now(UTC),
                    "expires_at": min(
                        datetime.now(UTC) + timedelta(minutes=30), first_start + timedelta(hours=2)
                    ),
                    "scope": "ONE_INSTRUMENT_AUTHENTICATED_API_READ_UNDER_FIXED_ALLOCATION",
                    "actual_sample_seconds": sample_seconds,
                    "actual_provider_requests": len(wire),
                    "largest_response_bytes": max(row["bytes"] for row in wire),
                    "peak_RSS_bytes": rss_bytes,
                    "free_disk_bytes": free_bytes,
                    "CPU_quota": Decimal("0.25"),
                    "memory_ceiling_bytes": 512 * 1024 * 1024,
                    "initial_clear_baseline_at": capacity_context["initial_clear_baseline_at"],
                    "limitations": [
                        "No global MaximumVerified or production capacity claim",
                        "No external financial mutations exercised",
                        "Execution amplification uses passed exact-source contracts",
                        "Full wallet inventory remains unassessed",
                    ],
                }
                private_write(ROOT / "capacity-qualification.json", capacity_record)
                receipt["capacity_qualification"] = capacity_record
            if eligible:
                private_write(
                    ROOT / "proposal.json",
                    {
                        "status": "PROPOSAL_NOT_AUTHORITY",
                        "observed_at": datetime.now(UTC),
                        "instrument": asdict(scope),
                        "shares": Decimal(5),
                        "entry_limit": ask,
                        "gross_entry": 5 * ask,
                        "verified_fee": Decimal(0),
                        "total_loss_cap": Decimal("2.675"),
                        "mutation_slots": ["ENTRY", "CANCEL_ENTRY", "EXIT", "CANCEL_EXIT"],
                        "entry_window_seconds": 60,
                        "GTD_expiry_after_start_seconds": 195,
                        "holding_limit_seconds": 120,
                        "protective_deadline_after_start_seconds": 600,
                        "order_submission": "OWNER_ONLY_AFTER_FROZEN_SIGNATURE_AND_COMMISSIONING",
                    },
                )
            receipt.update(
                status="API_ACCOUNT_OBSERVED",
                observed_at=datetime.now(UTC),
                account_mapping=asdict(mapping),
                eligibility=eligibility,
                lifecycle=evidence,
                candidate=candidate,
                scoped_opening=None if opening is None else asdict(opening),
            )
    except Exception as error:
        receipt["error_type"] = type(error).__name__
    finally:
        if client is not None:
            await client.close()
        authority.stop()
        receipt["acquisition"] = authority.status()
        if continuation is not None:
            receipt["same_campaign_continuation"] = continuation
        if grant is not None:
            receipt["explicit_read_grant"] = grant
        receipt["aggregate_campaign"] = {
            "requests_charged": prior_requests + authority.status()["requests_charged"],
            "bytes_charged": prior_bytes + authority.status()["bytes_charged"],
            "uncertain_requests": (
                0 if continuation is None else continuation["uncertain_requests"]
            )
            + authority.status()["uncertain_requests"],
            "maximum_requests": maximum_requests,
            "maximum_bytes": maximum_bytes,
            "absolute_deadline": first_start + timedelta(hours=2),
        }
        receipt["wire"] = wire
        private_write(ROOT / "receipt.json", receipt)
        (ROOT / "credentials.json").unlink(missing_ok=True)
    print(
        canonical_json(
            {
                "status": receipt["status"],
                "requests": authority.status()["requests_charged"],
                "bytes": authority.status()["bytes_charged"],
                "uncertain": authority.status()["uncertain_requests"],
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
