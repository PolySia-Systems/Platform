from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polysia.config.settings import AppSettings, TradingMode

ConfigurationState = Literal["ready", "warning", "blocked"]
OperationScope = Literal["data_only", "authenticated_read", "live"]

CANONICAL_ENVIRONMENT_VARIABLES = (
    "APP_ENV",
    "TRADING_MODE",
    "LIVE_TRADING_ENABLED",
    "POLYSIA_COPY_SIGNAL_ARBITER_FULL_ENABLED",
    "POLYMARKET_PRIVATE_KEY",
    "POLYMARKET_FUNDER_ADDRESS",
    "POLYMARKET_SIGNATURE_TYPE",
    "POLYMARKET_LIVE_TOKEN_ALLOWLIST",
    "POLYMARKET_LIVE_MAX_ORDER_SIZE",
    "POLYMARKET_LIVE_MAX_ORDER_NOTIONAL",
    "POLYMARKET_LIVE_MAX_OPEN_ORDERS",
    "POLYMARKET_READ_MAX_ATTEMPTS",
    "POLYMARKET_READ_BACKOFF_SECONDS",
    "POLYMARKET_SERVER_TIME_TIMEOUT_SECONDS",
    "POLYMARKET_MAX_CLOCK_DRIFT_SECONDS",
    "LOG_LEVEL",
)
DEPRECATED_ENVIRONMENT_VARIABLES = ("POLYMARKET_WALLET_ADDRESS",)


@dataclass(frozen=True, slots=True)
class ConfigurationStatus:
    status: ConfigurationState
    operation_scope: OperationScope
    canonical_variables: tuple[str, ...]
    configured: dict[str, bool | int | str]
    missing_variables: tuple[str, ...]
    deprecated_variables: tuple[str, ...]
    conflicts: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_variables": list(self.canonical_variables),
            "configured": self.configured,
            "conflicts": list(self.conflicts),
            "deprecated_variables": list(self.deprecated_variables),
            "missing_variables": list(self.missing_variables),
            "operation_scope": self.operation_scope,
            "status": self.status,
            "values_redacted": True,
        }


def build_configuration_status(settings: AppSettings) -> ConfigurationStatus:
    scope = _operation_scope(settings)
    missing: list[str] = []
    conflicts: list[str] = []
    deprecated = (
        ("POLYMARKET_WALLET_ADDRESS",) if settings.polymarket_wallet_address is not None else ()
    )

    if scope in {"authenticated_read", "live"} and settings.polymarket_private_key is None:
        missing.append("POLYMARKET_PRIVATE_KEY")
    if scope == "live":
        if not settings.live_trading_enabled:
            missing.append("LIVE_TRADING_ENABLED")
        if settings.polymarket_funder_address is None:
            missing.append("POLYMARKET_FUNDER_ADDRESS")
        if settings.polymarket_signature_type is None:
            missing.append("POLYMARKET_SIGNATURE_TYPE")
        if not settings.polymarket_live_token_allowlist:
            missing.append("POLYMARKET_LIVE_TOKEN_ALLOWLIST")

    if (
        settings.polymarket_funder_address is not None
        and settings.polymarket_wallet_address is not None
    ):
        conflicts.append(
            "POLYMARKET_FUNDER_ADDRESS and deprecated POLYMARKET_WALLET_ADDRESS are both set"
        )
    if settings.live_trading_enabled and settings.trading_mode != TradingMode.LIVE:
        conflicts.append("LIVE_TRADING_ENABLED is true while TRADING_MODE is not LIVE")

    status: ConfigurationState
    if missing or conflicts:
        status = "blocked"
    elif deprecated:
        status = "warning"
    else:
        status = "ready"
    return ConfigurationStatus(
        status=status,
        operation_scope=scope,
        canonical_variables=CANONICAL_ENVIRONMENT_VARIABLES,
        configured={
            "copy_signal_arbiter_full_enabled": settings.copy_signal_arbiter_full_enabled,
            "legacy_wallet_configured": settings.polymarket_wallet_address is not None,
            "live_token_allowlist_count": len(settings.polymarket_live_token_allowlist),
            "live_trading_enabled": settings.live_trading_enabled,
            "polymarket_funder_configured": settings.polymarket_funder_address is not None,
            "polymarket_private_key_configured": settings.polymarket_private_key is not None,
            "polymarket_signature_type_configured": (
                settings.polymarket_signature_type is not None
            ),
            "trading_mode": settings.trading_mode.value,
        },
        missing_variables=tuple(missing),
        deprecated_variables=deprecated,
        conflicts=tuple(conflicts),
    )


def _operation_scope(settings: AppSettings) -> OperationScope:
    if settings.trading_mode == TradingMode.LIVE:
        return "live"
    if any(
        (
            settings.polymarket_private_key is not None,
            settings.polymarket_funder_address is not None,
            settings.polymarket_wallet_address is not None,
            settings.polymarket_signature_type is not None,
        )
    ):
        return "authenticated_read"
    return "data_only"


__all__ = [
    "CANONICAL_ENVIRONMENT_VARIABLES",
    "ConfigurationStatus",
    "DEPRECATED_ENVIRONMENT_VARIABLES",
    "build_configuration_status",
]
