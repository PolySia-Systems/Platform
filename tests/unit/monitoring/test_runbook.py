from __future__ import annotations

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.monitoring.metrics import build_operator_status
from pm_trader.monitoring.readiness import build_deployment_readiness
from pm_trader.monitoring.runbook import render_operator_runbook_markdown


def test_operator_runbook_includes_safe_default_sections(tmp_path) -> None:
    runbook = render_operator_runbook_markdown(
        operator_status=build_operator_status(settings=AppSettings()),
        readiness=build_deployment_readiness(
            settings=AppSettings(),
            project_root=ready_project(tmp_path),
        ),
    )

    assert runbook.startswith("# Polymarket Operator Runbook")
    assert "## 1. Start Of Day" in runbook
    assert "## 2. Data Collection" in runbook
    assert "## 3. Research Loop" in runbook
    assert "## Emergency Stop" in runbook
    assert "live-limit-order" not in runbook


def test_operator_runbook_can_include_live_dry_run_section(tmp_path) -> None:
    runbook = render_operator_runbook_markdown(
        operator_status=build_operator_status(settings=AppSettings()),
        readiness=build_deployment_readiness(
            settings=AppSettings(),
            project_root=ready_project(tmp_path),
        ),
        include_live=True,
    )

    assert "## 5. Live Dry-Run Only" in runbook
    assert "live-limit-order" in runbook
    assert "--dry-run" in runbook
    assert "--submit" not in runbook


def test_operator_runbook_is_sanitized_for_live_settings(tmp_path) -> None:
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )

    runbook = render_operator_runbook_markdown(
        operator_status=build_operator_status(settings=settings),
        readiness=build_deployment_readiness(
            settings=settings,
            project_root=ready_project(tmp_path),
        ),
        include_live=True,
    )

    assert "not-for-output" not in runbook
    assert "0xwallet" not in runbook
    assert "token-secret" not in runbook
    assert "Tiny live orders ready: True" in runbook


def ready_project(tmp_path):
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "TRADING_MODE=DATA_ONLY",
                "LIVE_TRADING_ENABLED=false",
                "POLYMARKET_PRIVATE_KEY" + "=",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "\n".join(
            (
                ".env",
                ".env.*",
                "!.env.example",
                "*.key",
                "*.pem",
                "*.sqlite3",
                "secrets/",
            )
        ),
        encoding="utf-8",
    )
    return tmp_path
