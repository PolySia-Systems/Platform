from __future__ import annotations

from decimal import Decimal

from polysia.config.settings import AppSettings, TradingMode


def test_defaults_are_data_only(monkeypatch) -> None:
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_FUNDER_ADDRESS", raising=False)
    monkeypatch.delenv("POLYMARKET_SIGNATURE_TYPE", raising=False)
    monkeypatch.delenv("POLYMARKET_WALLET_ADDRESS", raising=False)
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", raising=False)
    monkeypatch.delenv("POLYMARKET_LIVE_MAX_ORDER_SIZE", raising=False)
    monkeypatch.delenv("POLYMARKET_LIVE_MAX_ORDER_NOTIONAL", raising=False)
    monkeypatch.delenv("POLYMARKET_LIVE_MAX_OPEN_ORDERS", raising=False)

    settings = AppSettings(_env_file=None)

    assert settings.trading_mode == TradingMode.DATA_ONLY
    assert settings.live_trading_enabled is False
    assert settings.live_trading_allowed is False
    assert settings.polymarket_live_token_allowlist == ()
    assert settings.polymarket_live_max_order_size == Decimal("1")
    assert settings.polymarket_live_max_order_notional == Decimal("1")
    assert settings.polymarket_live_max_open_orders == 1
    assert settings.polymarket_private_key is None
    assert settings.polymarket_funder_address is None
    assert settings.polymarket_signature_type is None


def test_live_trading_requires_live_mode_and_enable_flag(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    settings = AppSettings(_env_file=None)

    assert settings.trading_mode == TradingMode.LIVE
    assert settings.live_trading_enabled is True
    assert settings.live_trading_allowed is True


def test_safe_public_dict_does_not_include_private_key(monkeypatch) -> None:
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-logs")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0x1111111111111111111111111111111111111111")
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "3")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0x0000000000000000000000000000000000000000")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1, token-2")
    monkeypatch.setenv("POLYMARKET_LIVE_MAX_ORDER_SIZE", "2")
    monkeypatch.setenv("POLYMARKET_LIVE_MAX_ORDER_NOTIONAL", "0.75")
    monkeypatch.setenv("POLYMARKET_LIVE_MAX_OPEN_ORDERS", "3")

    settings = AppSettings(_env_file=None)

    safe_settings = settings.safe_public_dict()
    assert "polymarket_private_key" not in safe_settings
    assert safe_settings["polymarket_live_token_allowlist_count"] == 2
    assert safe_settings["polymarket_live_max_order_size"] == "2"
    assert safe_settings["polymarket_live_max_order_notional"] == "0.75"
    assert safe_settings["polymarket_live_max_open_orders"] == 3
    assert safe_settings["polymarket_funder_address_configured"] is True
    assert safe_settings["polymarket_signature_type"] == 3
    assert safe_settings["polymarket_wallet_address_configured"] is True
    assert "0x0000000000000000000000000000000000000000" not in str(safe_settings)
    assert "0x1111111111111111111111111111111111111111" not in str(safe_settings)


def test_funder_address_takes_precedence_over_legacy_wallet(monkeypatch) -> None:
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "0xlegacy")

    settings = AppSettings(_env_file=None)

    assert settings.polymarket_live_funder_address == "0xfunder"


def test_live_token_allowlist_is_parsed_from_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", " token-1,token-2,, token-3 ")

    settings = AppSettings(_env_file=None)

    assert settings.polymarket_live_token_allowlist == ("token-1", "token-2", "token-3")
