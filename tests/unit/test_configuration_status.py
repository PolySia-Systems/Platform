from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from polysia.cli import app
from polysia.config.settings import AppSettings, TradingMode
from polysia.config.status import (
    CANONICAL_ENVIRONMENT_VARIABLES,
    DEPRECATED_ENVIRONMENT_VARIABLES,
    build_configuration_status,
)


@pytest.fixture(autouse=True)
def _clear_host_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (*CANONICAL_ENVIRONMENT_VARIABLES, *DEPRECATED_ENVIRONMENT_VARIABLES):
        monkeypatch.delenv(variable, raising=False)


def test_data_only_configuration_status_is_ready_and_redacted() -> None:
    settings = AppSettings(_env_file=None)

    status = build_configuration_status(settings)
    payload = status.to_dict()

    assert status.status == "ready"
    assert status.operation_scope == "data_only"
    assert payload["values_redacted"] is True
    assert "POLYMARKET_PRIVATE_KEY" in payload["canonical_variables"]
    assert payload["configured"]["copy_signal_arbiter_full_enabled"] is False


def test_live_configuration_reports_missing_deprecated_and_conflicting_names() -> None:
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xlegacy",
    )

    status = build_configuration_status(settings)
    rendered = json.dumps(status.to_dict(), sort_keys=True)

    assert status.status == "blocked"
    assert set(status.missing_variables) == {
        "LIVE_TRADING_ENABLED",
        "POLYMARKET_LIVE_TOKEN_ALLOWLIST",
        "POLYMARKET_PRIVATE_KEY",
        "POLYMARKET_SIGNATURE_TYPE",
    }
    assert status.deprecated_variables == ("POLYMARKET_WALLET_ADDRESS",)
    assert status.conflicts
    assert "0xfunder" not in rendered
    assert "0xlegacy" not in rendered


def test_configuration_status_cli_outputs_no_secret_values(monkeypatch) -> None:
    settings = AppSettings(
        _env_file=None,
        POLYMARKET_PRIVATE_KEY="never-print-this",
        POLYMARKET_FUNDER_ADDRESS="0xprivate-funder",
    )
    monkeypatch.setattr("polysia.cli_commands.core.AppSettings", lambda: settings)

    result = CliRunner().invoke(app, ["system", "configuration"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "ready"
    assert "never-print-this" not in result.stdout
    assert "0xprivate-funder" not in result.stdout
