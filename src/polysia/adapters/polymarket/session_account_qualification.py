"""Separately authorized read-only opening evidence; never financial provision.

This administrative root has its own acquisition allowance and no financial
journal or custody capability. Research and web roots never call it.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version
from typing import Any

import httpx

from polysia.deployment.financial_session_runtime import SessionRuntimeConfig
from polysia.domain.financial_session import InstrumentScope, SessionBlocked
from polysia.storage.acquisition_authority import AcquisitionAuthority


async def qualify_account(
    config: SessionRuntimeConfig,
    instruments: tuple[InstrumentScope, ...],
    acquisition: AcquisitionAuthority,
    *,
    read_account: bool,
    clock: Callable[[], datetime],
    prime_history: bool = False,
    lifecycle_orders: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not read_account:
        return {"status": "DISABLED", "account_read": "NOT_PERFORMED", "network": "NOT_CONSTRUCTED"}
    from polymarket import ApiKeyCreds, AsyncSecureClient

    from polysia.adapters.polymarket.research_rpc import BoundedResearchRPC
    from polysia.adapters.polymarket.session_account import (
        WALLET_OPEN_ORDERS_PATH,
        ExactAccountMapping,
        ExactSessionAccountReader,
    )
    from polysia.adapters.polymarket.session_chain import CTFChainReader, ReadOnlyRPC
    from polysia.adapters.polymarket.session_composition import _Eligibility
    from polysia.adapters.polymarket.session_log_checkpoint import FinalizedLogCheckpoint
    from polysia.adapters.polymarket.session_sdk import (
        confine_sdk_http,
        require_sdk_scope,
        rpc_auth_headers,
    )

    if version("polymarket-client") != "0.13.0":
        raise SessionBlocked("read_only_SDK_contract_requires_reviewed_0_13_0")
    # Only exact read endpoints; a policy cannot add a credential/bootstrap or
    # financial mutation endpoint to this root.
    lifecycle = lifecycle_orders is not None
    if lifecycle and (
        prime_history or len(instruments) != 1 or config.account_mapping.signature_type != 3
    ):
        raise SessionBlocked("lifecycle_requires_one_deposit_wallet_instrument_and_API_only")
    endpoints = {
        "https://polymarket.com/api/geoblock",
        "https://clob.polymarket.com/data/orders",
        "https://clob.polymarket.com/data/trades",
        "https://clob.polymarket.com/balance-allowance",
    }
    if lifecycle:
        gamma_url = "https://gamma-api.polymarket.com/markets"
        fee_url = "https://clob.polymarket.com/fee-rate"
        condition = instruments[0].market
        if re.fullmatch(r"0x[0-9a-fA-F]{64}", condition) is None:
            raise SessionBlocked("canonical_CLOB_condition_required")
        market_url = "https://clob.polymarket.com/clob-markets/" + condition
        endpoints.update((market_url, gamma_url, fee_url))
        if lifecycle_orders is None or len(lifecycle_orders) > 2 or any(
            re.fullmatch(r"0x[0-9a-fA-F]{64}", order_id) is None or side not in {"BUY", "SELL"}
            for order_id, side in lifecycle_orders.items()
        ):
            raise SessionBlocked("canonical_bounded_lifecycle_order_ids_required")
        endpoints.update(
            "https://clob.polymarket.com/data/order/" + order_id for order_id in lifecycle_orders
        )
    else:
        endpoints.add(config.rpc_url)
    if config.account_mapping.signature_type == 3:
        endpoints.add("https://clob.polymarket.com" + WALLET_OPEN_ORDERS_PATH)
    if set(acquisition.policy.endpoints) != endpoints:
        raise SessionBlocked("exact_read_only_account_allowance_required")
    mapping = ExactAccountMapping(**asdict(config.account_mapping))
    reconciliation_scope = instruments if lifecycle else config.reconciliation_scope(instruments)
    require_sdk_scope(config, reconciliation_scope)
    checkpoint = (
        FinalizedLogCheckpoint(config.rpc_checkpoint_path, config.rpc_url)
        if config.rpc_checkpoint_path is not None and not lifecycle else None
    )
    if prime_history and checkpoint is None:
        raise SessionBlocked("protected_RPC_checkpoint_required_for_bootstrap")
    rpc_headers = None if lifecycle else rpc_auth_headers(config.rpc_bearer_token_reference)
    acquisition.initialize()

    class QualificationTransport(BoundedResearchRPC):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if lifecycle and request.method != "GET":
                raise SessionBlocked("lifecycle_qualification_GET_only")
            return await super().handle_async_request(request)

    def transport() -> httpx.AsyncBaseTransport:
        return QualificationTransport(acquisition, authenticated_gets=True, clock=clock)

    client = None
    async with httpx.AsyncClient(
        transport=transport(), follow_redirects=False, timeout=config.request_timeout_seconds
    ) as http:
        await _Eligibility(http, clock).assert_allowed()
        private, encoded = (
            os.environ.get(config.private_key_reference),
            os.environ.get(config.api_credentials_reference),
        )
        if not private or not encoded:
            raise SessionBlocked("preprovisioned_read_only_credentials_missing")
        try:
            credentials = ApiKeyCreds.model_validate(json.loads(encoded))
            client = await AsyncSecureClient._create(
                private_key=private,
                wallet=mapping.funder,
                credentials=credentials,
                validate_credentials=False,
            )
        except Exception:
            raise SessionBlocked("read_only_credentials_or_identity_invalid") from None
        try:
            await confine_sdk_http(
                client, transport, rpc_url=config.rpc_url, timeout=config.request_timeout_seconds,
                rpc_headers=rpc_headers,
            )
            if lifecycle_orders is not None:
                from polysia.adapters.polymarket.order_lifecycle_account import (
                    OrderLifecycleAccountReader,
                    explicit_zero_fee_market,
                    scoped_opening,
                )

                instrument = instruments[0]
                market = await http.get(market_url)
                market.raise_for_status()
                gamma = await http.get(gamma_url, params={"condition_ids": instrument.market})
                gamma.raise_for_status()
                fee_rate = await http.get(fee_url, params={"token_id": instrument.token})
                fee_rate.raise_for_status()
                market_data = json.loads(market.content, parse_float=Decimal)
                if not isinstance(market_data, dict) or market_data.get("c") != instrument.market:
                    raise SessionBlocked("lifecycle_CLOB_market_identity_mismatch")
                zero_fee = explicit_zero_fee_market(
                    market_data, instrument.token, gamma=gamma.json(), fee_rate=fee_rate.json(),
                )
                account_read = OrderLifecycleAccountReader(
                    client, mapping, maximum_pages=config.maximum_pages, clock=clock,
                )
                evidence = await account_read.observe(
                    instrument, exchange=config.exchange,
                    tracked=lifecycle_orders, explicit_zero_fee=zero_fee,
                )
                opening = scoped_opening(
                    evidence, account=mapping.account_id, explicit_zero_fee=zero_fee,
                ) if not lifecycle_orders else None
                return {
                    "status": "API_LIFECYCLE_OBSERVED",
                    "lifecycle": evidence,
                    "explicit_zero_fee": zero_fee,
                    "scoped_opening": None if opening is None else asdict(opening),
                    "mapping": asdict(config.account_mapping),
                    "acquisition": acquisition.status(),
                    "financial_authority": "NOT_ISSUED",
                    "live_activation": "NOT_PERFORMED",
                }
            chain = CTFChainReader(
                ReadOnlyRPC(
                    http, config.rpc_url, log_block_span=config.rpc_log_block_span,
                    checkpoint=checkpoint,
                    headers=rpc_headers,
                ),
                exchange=config.exchange,
                ctf=config.ctf,
                collateral=mapping.collateral,
                instruments=reconciliation_scope,
            )
            account = ExactSessionAccountReader(
                client,
                chain,
                mapping,
                maximum_pages=config.maximum_pages,
                maximum_age_seconds=30,
                executable_markets=frozenset(item.market for item in instruments),
                clock=clock,
            )
            if prime_history:
                account.require_identity()
                block = await chain.finalized()
                await chain.fills(mapping.funder, block=block, observed_at=clock())
                await chain.holdings(mapping.funder, block=block)
                await chain.redemptions(
                    mapping.funder, account_id=mapping.account_id,
                    adapter=config.collateral_adapter, block=block,
                    since=datetime.fromtimestamp(int(block["timestamp"], 16), UTC)
                    + timedelta(seconds=1),
                )
            observation = await account.observe(instruments[0])
            return {
                "status": "READ_ONLY_OBSERVED",
                "opening": asdict(observation),
                "mapping": asdict(config.account_mapping),
                "evidence": account.last_evidence,
                "acquisition": acquisition.status(),
                "financial_authority": "NOT_ISSUED",
                "live_activation": "NOT_PERFORMED",
            }
        finally:
            if client is not None:
                await client.close()
