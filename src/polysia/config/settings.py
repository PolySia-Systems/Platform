from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator, model_validator
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

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    trading_mode: TradingMode = Field(
        default=TradingMode.DATA_ONLY,
        validation_alias="TRADING_MODE",
    )
    live_trading_enabled: bool = Field(default=False, validation_alias="LIVE_TRADING_ENABLED")
    copy_signal_arbiter_full_enabled: bool = Field(
        default=False,
        validation_alias="POLYSIA_COPY_SIGNAL_ARBITER_FULL_ENABLED",
    )
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
    polymarket_read_max_attempts: int = Field(
        default=2,
        validation_alias="POLYMARKET_READ_MAX_ATTEMPTS",
    )
    polymarket_read_backoff_seconds: Decimal = Field(
        default=Decimal("0.25"),
        validation_alias="POLYMARKET_READ_BACKOFF_SECONDS",
    )
    polymarket_server_time_timeout_seconds: Decimal = Field(
        default=Decimal("5"),
        validation_alias="POLYMARKET_SERVER_TIME_TIMEOUT_SECONDS",
    )
    polymarket_max_clock_drift_seconds: Decimal = Field(
        default=Decimal("5"),
        validation_alias="POLYMARKET_MAX_CLOCK_DRIFT_SECONDS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_environment(cls, value: Any) -> str:
        aliases = {
            "dev": "development",
            "local": "development",
            "prd": "production",
            "prod": "production",
            "qa": "test",
            "server": "production",
            "stage": "staging",
            "stg": "staging",
            "testing": "test",
        }
        normalized = str(value).strip().lower()
        return aliases.get(normalized, normalized)

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

    @field_validator("polymarket_read_max_attempts")
    @classmethod
    def validate_read_max_attempts(cls, value: int) -> int:
        if not 1 <= value <= 3:
            raise ValueError("POLYMARKET_READ_MAX_ATTEMPTS must be within [1, 3]")
        return value

    @field_validator("polymarket_read_backoff_seconds")
    @classmethod
    def validate_read_backoff_seconds(cls, value: Decimal) -> Decimal:
        if not Decimal("0") <= value <= Decimal("2"):
            raise ValueError("POLYMARKET_READ_BACKOFF_SECONDS must be within [0, 2]")
        return value

    @field_validator("polymarket_server_time_timeout_seconds")
    @classmethod
    def validate_server_time_timeout(cls, value: Decimal) -> Decimal:
        if not Decimal("0") < value <= Decimal("10"):
            raise ValueError("POLYMARKET_SERVER_TIME_TIMEOUT_SECONDS must be within (0, 10]")
        return value

    @field_validator("polymarket_max_clock_drift_seconds")
    @classmethod
    def validate_max_clock_drift(cls, value: Decimal) -> Decimal:
        if not Decimal("0") < value <= Decimal("5"):
            raise ValueError("POLYMARKET_MAX_CLOCK_DRIFT_SECONDS must be within (0, 5]")
        return value

    @field_validator("polymarket_signature_type")
    @classmethod
    def validate_signature_type(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value not in {0, 1, 2, 3}:
            raise ValueError("POLYMARKET_SIGNATURE_TYPE must be 0, 1, 2, or 3")
        return value

    @model_validator(mode="after")
    def block_experimental_full_arbiter_live_authority(self) -> AppSettings:
        """Keep the experimental FULL arbiter outside every Live authority path."""
        if self.live_trading_allowed and self.copy_signal_arbiter_full_enabled:
            raise ValueError(
                "experimental FULL copy-signal arbiter requires a separate owner "
                "authorization that this release does not accept; Live startup is blocked"
            )
        return self

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
            "copy_signal_arbiter_full_enabled": self.copy_signal_arbiter_full_enabled,
            "polymarket_funder_address_configured": bool(self.polymarket_funder_address),
            "live_trading_allowed": self.live_trading_allowed,
            "live_trading_enabled": self.live_trading_enabled,
            "log_level": self.log_level,
            "polymarket_live_token_allowlist_count": len(self.polymarket_live_token_allowlist),
            "polymarket_live_max_open_orders": self.polymarket_live_max_open_orders,
            "polymarket_live_max_order_notional": str(self.polymarket_live_max_order_notional),
            "polymarket_live_max_order_size": str(self.polymarket_live_max_order_size),
            "polymarket_max_clock_drift_seconds": str(self.polymarket_max_clock_drift_seconds),
            "polymarket_read_backoff_seconds": str(self.polymarket_read_backoff_seconds),
            "polymarket_read_max_attempts": self.polymarket_read_max_attempts,
            "polymarket_server_time_timeout_seconds": str(
                self.polymarket_server_time_timeout_seconds
            ),
            "polymarket_signature_type": self.polymarket_signature_type,
            "polymarket_wallet_address_configured": bool(self.polymarket_wallet_address),
            "trading_mode": self.trading_mode.value,
        }
