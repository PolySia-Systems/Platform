from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class TradingMode(StrEnum):
    """Supported runtime modes."""

    DATA_ONLY = "DATA_ONLY"
    PAPER = "PAPER"
    LIVE = "LIVE"


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", validation_alias="APP_ENV")
    trading_mode: TradingMode = Field(
        default=TradingMode.DATA_ONLY,
        validation_alias="TRADING_MODE",
    )
    live_trading_enabled: bool = Field(default=False, validation_alias="LIVE_TRADING_ENABLED")
    polymarket_private_key: SecretStr | None = Field(
        default=None,
        validation_alias="POLYMARKET_PRIVATE_KEY",
    )
    polymarket_wallet_address: str | None = Field(
        default=None,
        validation_alias="POLYMARKET_WALLET_ADDRESS",
    )
    polymarket_funder_address: str | None = Field(
        default=None,
        validation_alias="POLYMARKET_FUNDER_ADDRESS",
    )
    polymarket_signature_type: int | None = Field(
        default=None,
        validation_alias="POLYMARKET_SIGNATURE_TYPE",
    )
    polymarket_live_token_allowlist: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(),
        validation_alias="POLYMARKET_LIVE_TOKEN_ALLOWLIST",
    )
    polymarket_live_max_order_size: Decimal = Field(
        default=Decimal("1"),
        validation_alias="POLYMARKET_LIVE_MAX_ORDER_SIZE",
    )
    polymarket_live_max_order_notional: Decimal = Field(
        default=Decimal("1"),
        validation_alias="POLYMARKET_LIVE_MAX_ORDER_NOTIONAL",
    )
    polymarket_live_max_open_orders: int = Field(
        default=1,
        validation_alias="POLYMARKET_LIVE_MAX_OPEN_ORDERS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("polymarket_live_token_allowlist", mode="before")
    @classmethod
    def parse_live_token_allowlist(cls, value: Any) -> tuple[str, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return tuple(token.strip() for token in value.split(",") if token.strip())
        if isinstance(value, (list, tuple, set)):
            return tuple(str(token).strip() for token in value if str(token).strip())
        raise TypeError("POLYMARKET_LIVE_TOKEN_ALLOWLIST must be a comma-separated string")

    @field_validator("polymarket_wallet_address", "polymarket_funder_address", mode="before")
    @classmethod
    def empty_address_is_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("polymarket_live_max_order_size", "polymarket_live_max_order_notional")
    @classmethod
    def require_positive_live_decimal_limit(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("live order limits must be positive")
        return value

    @field_validator("polymarket_live_max_open_orders")
    @classmethod
    def require_non_negative_live_open_orders(cls, value: int) -> int:
        if value < 0:
            raise ValueError("POLYMARKET_LIVE_MAX_OPEN_ORDERS must not be negative")
        return value

    @field_validator("polymarket_signature_type")
    @classmethod
    def validate_signature_type(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value not in {0, 1, 2, 3}:
            raise ValueError("POLYMARKET_SIGNATURE_TYPE must be 0, 1, 2, or 3")
        return value

    @property
    def live_trading_allowed(self) -> bool:
        """Live trading requires both LIVE mode and an explicit enable flag."""
        return self.trading_mode == TradingMode.LIVE and self.live_trading_enabled

    @property
    def polymarket_live_funder_address(self) -> str | None:
        """Explicit funder/proxy wallet, falling back to legacy wallet env only if needed."""
        return self.polymarket_funder_address or self.polymarket_wallet_address

    def safe_public_dict(self) -> dict[str, bool | int | str | None]:
        """Return settings that are safe to log or print."""
        return {
            "app_env": self.app_env,
            "polymarket_funder_address_configured": bool(self.polymarket_funder_address),
            "live_trading_allowed": self.live_trading_allowed,
            "live_trading_enabled": self.live_trading_enabled,
            "log_level": self.log_level,
            "polymarket_live_token_allowlist_count": len(self.polymarket_live_token_allowlist),
            "polymarket_live_max_open_orders": self.polymarket_live_max_open_orders,
            "polymarket_live_max_order_notional": str(
                self.polymarket_live_max_order_notional
            ),
            "polymarket_live_max_order_size": str(self.polymarket_live_max_order_size),
            "polymarket_signature_type": self.polymarket_signature_type,
            "polymarket_wallet_address_configured": bool(self.polymarket_wallet_address),
            "trading_mode": self.trading_mode.value,
        }
