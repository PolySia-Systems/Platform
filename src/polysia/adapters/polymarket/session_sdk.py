"""Pinned SDK transport confinement, reused by financial and read-only roots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data
from polymarket._internal.actions.orders.context import resolve_order_exchange_address
from polymarket._internal.actions.orders.typed_data import build_order_typed_data
from polymarket._internal.actions.orders.types import BYTES32_ZERO, UnsignedOrder
from polymarket.environments import PRODUCTION
from polymarket.types import EvmAddress

from polysia.domain.financial_session import SessionBlocked


async def confine_sdk_http(
    client: Any, factory: Callable[[], httpx.AsyncBaseTransport], *, rpc_url: str, timeout: int
) -> None:
    rpc = client._ctx.rpc._transport
    await rpc._client.aclose()
    rpc._base_url = rpc_url
    rpc._client = httpx.AsyncClient(
        transport=factory(), base_url=rpc_url, follow_redirects=False, timeout=timeout
    )
    for name in (
        "secure_clob",
        "clob",
        "data",
        "gamma",
        "relayer",
        "combos",
        "builder_gateway",
        "rfq",
        "perps",
    ):
        transport = getattr(client._ctx, name, None)
        if transport is not None:
            await transport._client.aclose()
            transport._client = httpx.AsyncClient(
                transport=factory(),
                base_url=transport._base_url,
                follow_redirects=False,
                timeout=timeout,
            )


def require_sdk_scope(config: Any, instruments: tuple[Any, ...]) -> None:
    environment = PRODUCTION._config
    if (
        environment.chain_id != 137
        or any(
            str(actual).lower() != str(expected).lower()
            for actual, expected in (
                (environment.standard_exchange, config.exchange),
                (environment.conditional_tokens, config.ctf),
                (environment.collateral_adapter, config.collateral_adapter),
                (environment.collateral_token, config.account_mapping.collateral),
            )
        )
        or any(
            str(
                resolve_order_exchange_address(environment, asset_id=item.token, neg_risk=False)
            ).lower()
            != config.exchange.lower()
            for item in instruments
        )
    ):
        raise SessionBlocked("SDK_exchange_collateral_or_protocol_scope_mismatch")


def assert_exact_prepared(
    prepared: Any, *, exchange: str, signer: str, funder: str, request: dict[str, Any]
) -> None:
    if (
        str(prepared.token_id) != request["token_id"]
        or prepared.side != request["side"]
        or prepared.expiration != request.get("expiration")
        or prepared.post_only != request.get("post_only", False)
        or prepared.signature_type != 0
        or str(prepared.signer).lower() != signer.lower()
        or prepared.builder != BYTES32_ZERO
        or prepared.metadata != BYTES32_ZERO
        or prepared.order_type != ("GTD" if request.get("expiration") else "GTC")
        or str(prepared.maker).lower() != funder.lower()
    ):
        raise SessionBlocked("prepared_order_identity_or_envelope_changed")
    collateral, shares = (
        (prepared.maker_amount, prepared.taker_amount)
        if prepared.side == "BUY"
        else (prepared.taker_amount, prepared.maker_amount)
    )
    if (
        type(shares) is not int
        or type(collateral) is not int
        or shares <= 0
        or collateral <= 0
        or Decimal(shares) / 1000000 != request["size"]
        or Decimal(collateral) / 1000000 != request["size"] * request["price"]
    ):
        raise SessionBlocked("SDK_rounded_the_exact_approved_economics")
    fields = asdict(prepared)
    signature = fields.pop("signature")
    del fields["post_only"]
    unsigned = UnsignedOrder(
        chain_id=137, exchange_address=EvmAddress(exchange), protocol_version="2", **fields
    )
    try:
        recovered = Account.recover_message(
            encode_typed_data(full_message=build_order_typed_data(unsigned)), signature=signature
        )
    except ValueError, TypeError:
        raise SessionBlocked("prepared_order_signature_invalid") from None
    if recovered.lower() != signer.lower():
        raise SessionBlocked("prepared_order_signature_not_for_authorized_exchange")
