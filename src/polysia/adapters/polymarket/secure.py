from __future__ import annotations

import os
from collections.abc import Awaitable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from polymarket import AsyncSecureClient, PolymarketError

from polysia.adapters.polymarket.capabilities import POLYMARKET_CAPABILITIES
from polysia.config.logging import get_logger
from polysia.domain.market import VenueCapabilityProfile

OrderSide = Literal["BUY", "SELL"]
MarketOrderType = Literal["FAK", "FOK"]
BalanceAssetType = Literal["COLLATERAL", "CONDITIONAL"]

PRIVATE_KEY_ENV = "POLYMARKET_PRIVATE_KEY"
FUNDER_ADDRESS_ENV = "POLYMARKET_FUNDER_ADDRESS"
WALLET_ADDRESS_ENV = "POLYMARKET_WALLET_ADDRESS"
SIGNATURE_TYPE_ENV = "POLYMARKET_SIGNATURE_TYPE"
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "api_secret",
        "api_passphrase",
        "builder_secret",
        "credentials",
        "funder",
        "funder_address",
        "private_key",
        "signed_payload",
        "signature",
        "wallet",
        "wallet_address",
    }
)


class SecureClientFactory(Protocol):
    def __call__(self, *, private_key: str, wallet: str | None) -> Awaitable[Any]:
        """Create an authenticated SDK client."""


class PolymarketSecureAdapterError(RuntimeError):
    """Raised when an authenticated Polymarket action fails or is unsafe."""


@dataclass(frozen=True, slots=True)
class SecureClientIdentity:
    """Sanitized authenticated wallet identity; never includes raw addresses."""

    signer_configured: bool
    funder_configured: bool
    legacy_wallet_configured: bool
    active_wallet_source: Literal["funder", "legacy_wallet", "sdk_default"]
    wallet_type: str | None
    sdk_signature_type: int | None
    configured_signature_type: int | None
    signature_type_matches_sdk: bool | None

    def to_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "active_wallet_source": self.active_wallet_source,
            "configured_signature_type": self.configured_signature_type,
            "funder_configured": self.funder_configured,
            "legacy_wallet_configured": self.legacy_wallet_configured,
            "sdk_signature_type": self.sdk_signature_type,
            "signature_type_matches_sdk": self.signature_type_matches_sdk,
            "signer_configured": self.signer_configured,
            "wallet_type": self.wallet_type,
        }


async def _default_client_factory(*, private_key: str, wallet: str | None) -> Any:
    return await AsyncSecureClient.create(private_key=private_key, wallet=wallet)


class PolymarketSecureAdapter:
    """Authenticated SDK adapter with explicit lifecycle and no secret logging."""

    def __init__(
        self,
        *,
        client_factory: SecureClientFactory | None = None,
        private_key_env: str = PRIVATE_KEY_ENV,
        funder_address_env: str = FUNDER_ADDRESS_ENV,
        wallet_address_env: str = WALLET_ADDRESS_ENV,
        signature_type_env: str = SIGNATURE_TYPE_ENV,
        logger: Any | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._private_key_env = private_key_env
        self._funder_address_env = funder_address_env
        self._wallet_address_env = wallet_address_env
        self._signature_type_env = signature_type_env
        self._logger = logger or get_logger(__name__)
        self._client: Any | None = None
        self._active_wallet_source: Literal["funder", "legacy_wallet", "sdk_default"] = (
            "sdk_default"
        )
        self._configured_signature_type: int | None = None

    @property
    def capabilities(self) -> VenueCapabilityProfile:
        return POLYMARKET_CAPABILITIES

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        """Create the secure SDK client from environment variables only."""
        if self._client is not None:
            return

        private_key = os.environ.get(self._private_key_env)
        if not private_key:
            raise PolymarketSecureAdapterError(
                f"{self._private_key_env} is required to create a secure Polymarket client."
            )

        funder = _non_empty_env_value(self._funder_address_env)
        legacy_wallet = _non_empty_env_value(self._wallet_address_env)
        wallet = funder or legacy_wallet
        if funder is not None:
            self._active_wallet_source = "funder"
        elif legacy_wallet is not None:
            self._active_wallet_source = "legacy_wallet"
        else:
            self._active_wallet_source = "sdk_default"
        self._configured_signature_type = _optional_int_env_value(self._signature_type_env)

        try:
            self._client = await self._client_factory(private_key=private_key, wallet=wallet)
        except PolymarketError as error:
            self._log_sdk_error("connect", error)
            raise PolymarketSecureAdapterError(
                "Could not create authenticated Polymarket client."
            ) from error

        self._logger.info(
            "polymarket_secure_connected",
            funder_address_configured=funder is not None,
            legacy_wallet_address_configured=legacy_wallet is not None,
            wallet_address_configured=wallet is not None,
        )

    async def close(self) -> None:
        """Close the underlying SDK client when it exists."""
        client = self._client
        self._client = None
        if client is not None:
            await client.close()

    def identity(self) -> SecureClientIdentity:
        """Return sanitized signer/funder identity details for diagnostics."""
        client = self._require_client()
        wallet_type = _optional_str(getattr(client, "wallet_type", None))
        sdk_signature_type = _signature_type_for_wallet_type(wallet_type)
        signature_type_matches_sdk = (
            None
            if self._configured_signature_type is None or sdk_signature_type is None
            else self._configured_signature_type == sdk_signature_type
        )
        return SecureClientIdentity(
            signer_configured=_non_empty_env_value(self._private_key_env) is not None,
            funder_configured=_non_empty_env_value(self._funder_address_env) is not None,
            legacy_wallet_configured=_non_empty_env_value(self._wallet_address_env) is not None,
            active_wallet_source=self._active_wallet_source,
            wallet_type=wallet_type,
            sdk_signature_type=sdk_signature_type,
            configured_signature_type=self._configured_signature_type,
            signature_type_matches_sdk=signature_type_matches_sdk,
        )

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        """Return one page of open orders from the authenticated account."""
        client = self._require_client()
        try:
            paginator = client.list_open_orders(token_id=token_id, id=order_id, market=market)
            page = await paginator.first_page()
            return list(page.items)
        except PolymarketError as error:
            self._log_sdk_error(
                "get_open_orders",
                error,
                token_id=token_id,
                order_id=order_id,
                market=market,
            )
            raise PolymarketSecureAdapterError("Could not fetch open orders.") from error

    async def get_market(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
    ) -> Any:
        """Fetch market metadata through the authenticated SDK client."""
        client = self._require_client()
        try:
            return await client.get_market(id=id, slug=slug, include_tag=True)
        except PolymarketError as error:
            self._log_sdk_error("get_market", error, id=id, slug=slug)
            raise PolymarketSecureAdapterError("Could not fetch Polymarket market.") from error

    async def get_order_book(self, *, token_id: str) -> Any:
        """Fetch one CLOB order book by token id."""
        client = self._require_client()
        try:
            return await client.get_order_book(token_id=token_id)
        except PolymarketError as error:
            self._log_sdk_error("get_order_book", error, token_id=token_id)
            raise PolymarketSecureAdapterError("Could not fetch Polymarket order book.") from error

    async def get_balance_allowance(
        self,
        *,
        asset_type: BalanceAssetType,
        token_id: str | None = None,
    ) -> Any:
        """Fetch sanitized account balance/allowance metadata."""
        client = self._require_client()
        try:
            return await client.get_balance_allowance(asset_type=asset_type, token_id=token_id)
        except PolymarketError as error:
            self._log_sdk_error(
                "get_balance_allowance",
                error,
                asset_type=asset_type,
                token_id=token_id,
            )
            raise PolymarketSecureAdapterError(
                "Could not fetch Polymarket balance allowance."
            ) from error

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        """Return one page of account positions without exposing wallet identifiers."""
        client = self._require_client()
        try:
            paginator = client.list_positions(market=market, size_threshold=size_threshold)
            page = await paginator.first_page()
            return list(page.items)
        except PolymarketError as error:
            self._log_sdk_error("list_positions", error)
            raise PolymarketSecureAdapterError("Could not fetch Polymarket positions.") from error

    async def list_account_trades(
        self,
        *,
        token_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        """Return one page of account trades with raw identifiers kept out of logs."""
        client = self._require_client()
        try:
            paginator = client.list_account_trades(token_id=token_id, market=market)
            page = await paginator.first_page()
            return list(page.items)
        except PolymarketError as error:
            self._log_sdk_error("list_account_trades", error, token_id=token_id, market=market)
            raise PolymarketSecureAdapterError("Could not fetch Polymarket trades.") from error

    async def cancel_order(self, *, order_id: str) -> Any:
        """Cancel one authenticated order by id."""
        client = self._require_client()
        try:
            return await client.cancel_order(order_id=order_id)
        except PolymarketError as error:
            self._log_sdk_error("cancel_order", error, order_id=order_id)
            raise PolymarketSecureAdapterError("Could not cancel Polymarket order.") from error

    async def cancel_market_orders(
        self,
        *,
        market: str | None = None,
        token_id: str | None = None,
    ) -> Any:
        """Cancel authenticated orders for one market or token."""
        client = self._require_client()
        try:
            return await client.cancel_market_orders(market=market, token_id=token_id)
        except PolymarketError as error:
            self._log_sdk_error(
                "cancel_market_orders",
                error,
                market=market,
                token_id=token_id,
            )
            raise PolymarketSecureAdapterError(
                "Could not cancel Polymarket market orders."
            ) from error

    async def place_limit_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        price: Decimal,
        size: Decimal,
        post_only: bool = False,
        expiration: int | None = None,
        builder_code: str | None = None,
    ) -> Any:
        """Submit a limit order through the authenticated SDK client."""
        _validate_side(side)
        client = self._require_client()
        try:
            return await client.place_limit_order(
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                post_only=post_only,
                expiration=expiration,
                builder_code=builder_code,
            )
        except PolymarketError as error:
            self._log_sdk_error(
                "place_limit_order",
                error,
                **sanitize_order_request(
                    action="place_limit_order",
                    token_id=token_id,
                    side=side,
                    price=price,
                    size=size,
                    post_only=post_only,
                    expiration=expiration,
                ),
            )
            raise PolymarketSecureAdapterError("Could not place Polymarket limit order.") from error

    async def place_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | None = None,
        shares: Decimal | None = None,
        max_spend: Decimal | None = None,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> Any:
        """Submit a market order through the authenticated SDK client."""
        _validate_side(side)
        _validate_market_order_inputs(amount=amount, shares=shares, max_spend=max_spend)
        client = self._require_client()
        try:
            return await client.place_market_order(
                token_id=token_id,
                side=side,
                amount=amount,
                shares=shares,
                max_spend=max_spend,
                max_price=max_price,
                min_price=min_price,
                order_type=order_type,
                builder_code=builder_code,
            )
        except PolymarketError as error:
            self._log_sdk_error(
                "place_market_order",
                error,
                **sanitize_order_request(
                    action="place_market_order",
                    token_id=token_id,
                    side=side,
                    amount=amount,
                    shares=shares,
                    max_spend=max_spend,
                    max_price=max_price,
                    min_price=min_price,
                    order_type=order_type,
                ),
            )
            raise PolymarketSecureAdapterError(
                "Could not place Polymarket market order."
            ) from error

    def _require_client(self) -> Any:
        if self._client is None:
            raise PolymarketSecureAdapterError("Secure Polymarket adapter is not connected.")
        return self._client

    def _log_sdk_error(self, operation: str, error: PolymarketError, **context: Any) -> None:
        self._logger.warning(
            "polymarket_secure_sdk_error",
            operation=operation,
            error_type=type(error).__name__,
            **context,
        )


def sanitize_order_request(action: str, **fields: Any) -> dict[str, object]:
    """Return order fields that are safe to print in logs or dry-run output."""
    sanitized: dict[str, object] = {"action": action}
    for key, value in fields.items():
        if value is None:
            continue
        if key.lower() in SENSITIVE_FIELD_NAMES:
            sanitized[key] = "<redacted>"
        elif isinstance(value, Decimal):
            sanitized[key] = str(value)
        else:
            sanitized[key] = value
    return sanitized


def _validate_side(side: str) -> None:
    if side not in ("BUY", "SELL"):
        raise PolymarketSecureAdapterError(f"unsupported order side {side!r}")


def _validate_market_order_inputs(
    *,
    amount: Decimal | None,
    shares: Decimal | None,
    max_spend: Decimal | None,
) -> None:
    if amount is None and shares is None and max_spend is None:
        raise PolymarketSecureAdapterError(
            "market order requires amount, shares, or max_spend."
        )


def _non_empty_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value


def _optional_int_env_value(name: str) -> int | None:
    value = _non_empty_env_value(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _signature_type_for_wallet_type(wallet_type: str | None) -> int | None:
    if wallet_type is None:
        return None
    return {
        "EOA": 0,
        "POLY_PROXY": 1,
        "GNOSIS_SAFE": 2,
        "DEPOSIT_WALLET": 3,
    }.get(wallet_type)
