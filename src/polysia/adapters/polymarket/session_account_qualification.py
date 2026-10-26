"""Separately authorized read-only opening evidence; never financial provision.

This administrative root has its own acquisition allowance and no financial
journal or custody capability. Research and web roots never call it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
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
) -> dict[str, Any]:
    if not read_account:
        return {"status": "DISABLED", "account_read": "NOT_PERFORMED", "network": "NOT_CONSTRUCTED"}
    from polymarket import ApiKeyCreds, AsyncSecureClient

    from polysia.adapters.polymarket.research_rpc import BoundedResearchRPC
    from polysia.adapters.polymarket.session_account import (
        ExactAccountMapping,
        ExactSessionAccountReader,
    )
    from polysia.adapters.polymarket.session_chain import CTFChainReader, ReadOnlyRPC
    from polysia.adapters.polymarket.session_composition import _Eligibility
    from polysia.adapters.polymarket.session_sdk import confine_sdk_http, require_sdk_scope

    if version("polymarket-client") != "0.13.0":
        raise SessionBlocked("read_only_SDK_contract_requires_reviewed_0_13_0")
    # Only exact read endpoints; a policy cannot add a credential/bootstrap or
    # financial mutation endpoint to this root.
    endpoints = {
        config.rpc_url,
        "https://polymarket.com/api/geoblock",
        "https://clob.polymarket.com/data/orders",
        "https://clob.polymarket.com/data/trades",
        "https://clob.polymarket.com/balance-allowance",
    }
    if set(acquisition.policy.endpoints) != endpoints:
        raise SessionBlocked("exact_read_only_account_allowance_required")
    mapping = ExactAccountMapping(**asdict(config.account_mapping))
    require_sdk_scope(config, instruments)
    acquisition.initialize()

    def transport() -> httpx.AsyncBaseTransport:
        return BoundedResearchRPC(acquisition, authenticated_gets=True, clock=clock)

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
                client, transport, rpc_url=config.rpc_url, timeout=config.request_timeout_seconds
            )
            chain = CTFChainReader(
                ReadOnlyRPC(http, config.rpc_url),
                exchange=config.exchange,
                ctf=config.ctf,
                collateral=mapping.collateral,
                instruments=instruments,
            )
            account = ExactSessionAccountReader(
                client,
                chain,
                mapping,
                maximum_pages=config.maximum_pages,
                maximum_age_seconds=30,
                clock=clock,
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
