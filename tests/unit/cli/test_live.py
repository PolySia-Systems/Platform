from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from polysia import cli_support
from polysia.cli import app
from polysia.cli_commands.live import _live_account_status
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.market import MarketDetails, MarketOutcomeSummary, MarketSummary

runner = CliRunner()


class FakeAccountStatusAdapter:
    instances: list[FakeAccountStatusAdapter] = []

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    def identity(self) -> SimpleNamespace:
        return SimpleNamespace(
            to_dict=lambda: {
                "active_wallet_source": "funder",
                "configured_signature_type": 3,
                "funder_configured": True,
                "legacy_wallet_configured": False,
                "sdk_signature_type": 3,
                "signature_type_matches_sdk": True,
                "signer_configured": True,
                "wallet_type": "DEPOSIT_WALLET",
            }
        )

    async def get_balance_allowance(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(balance=1000000, allowances={"exchange": 1, "adapter": 0})

    async def list_positions(self, **_kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(token_id="token-1", size=Decimal("1"))]

    async def get_open_orders(self, **_kwargs: object) -> list[SimpleNamespace]:
        return []


def test_controlled_second_tiny_live_command_writes_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "controlled"

    async def fake_run_controlled(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "controlled-second-tiny-live.json").write_text(
            json.dumps({"final_result": "DRY_RUN_READY"}),
            encoding="utf-8",
        )
        (config.output_dir / "controlled-second-tiny-live.md").write_text(
            "# PolySia — Polymarket Adapter — Controlled Second Tiny Live\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            final_result="DRY_RUN_READY",
            live_attempt_count=0,
            order_submitted=False,
        )

    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-yes")
    monkeypatch.setattr(
        "polysia.cli_commands.live.run_controlled_second_tiny_live",
        fake_run_controlled,
    )

    result = runner.invoke(
        app,
        [
            "live",
            "controlled-second-attempt",
            "--token-id",
            "token-yes",
            "--market-slug",
            "btc-updown-5m-test",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FOK",
            "--dry-run",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] == "DRY_RUN_READY"
    assert payload["live_attempt_count"] == 0
    assert (output_dir / "controlled-second-tiny-live.json").is_file()
    assert (output_dir / "controlled-second-tiny-live.md").is_file()


def test_manual_intervention_live_test_command_writes_dry_run_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "manual-intervention"

    async def fake_resolve_live_smoke_selection(**_kwargs):
        return SimpleNamespace(
            condition_id="condition-1",
            market_slug="btc-updown-5m-test",
            token_id="token-yes",
        )

    async def fake_run_manual_intervention_live_test(config):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "manual-intervention-live-test.json").write_text(
            json.dumps({"final_result": "DRY_RUN_READY"}),
            encoding="utf-8",
        )
        (config.output_dir / "manual-intervention-live-test.md").write_text(
            "# PolySia — Polymarket Adapter — Controlled Manual Intervention Live Test\n",
            encoding="utf-8",
        )
        assert config.dry_run is True
        assert config.token_id == "token-yes"
        return SimpleNamespace(
            final_result="DRY_RUN_READY",
            live_attempt_count=0,
            manual_intervention_detected=False,
            order_submitted=False,
            trading_should_pause=False,
        )

    apply_calls = []

    def fake_apply_secure_env_from_settings(settings):
        apply_calls.append(settings)

    monkeypatch.setattr(
        "polysia.cli_commands.core.resolve_live_smoke_selection",
        fake_resolve_live_smoke_selection,
    )
    monkeypatch.setattr(
        "polysia.cli_commands.live.run_manual_intervention_live_test",
        fake_run_manual_intervention_live_test,
    )
    monkeypatch.setattr(
        "polysia.cli_commands.live.cli_support.apply_secure_env_from_settings",
        fake_apply_secure_env_from_settings,
    )

    result = runner.invoke(
        app,
        [
            "live",
            "manual-intervention-test",
            "--auto-btc-5m",
            "--outcome",
            "YES",
            "--side",
            "BUY",
            "--max-notional",
            "1.00",
            "--order-type",
            "FOK",
            "--dry-run",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["final_result"] == "DRY_RUN_READY"
    assert payload["live_attempt_count"] == 0
    assert payload["order_submitted"] is False
    assert len(apply_calls) == 1
    assert (output_dir / "manual-intervention-live-test.json").is_file()
    assert (output_dir / "manual-intervention-live-test.md").is_file()


def test_tiny_live_execute_dry_run_writes_sanitized_reports(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-yes")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    output_dir = tmp_path / "reports"

    result = runner.invoke(
        app,
        [
            "live",
            "tiny-execute",
            "--token-id",
            "token-yes",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FAK",
            "--market-slug",
            "btc-updown-5m-test",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["final_result"] == "DRY_RUN_PASS"
    assert payload["order_submitted"] is False
    reports = [
        output_dir / "tiny_live_execution.json",
        output_dir / "tiny_live_execution.md",
        output_dir / "tiny_live_execution.html",
    ]
    assert all(path.is_file() for path in reports)
    combined = result.stdout + "".join(path.read_text(encoding="utf-8") for path in reports)
    assert "not-for-output" not in combined
    assert "No retry was attempted" in combined


def test_live_smoke_test_auto_btc_5m_selects_market(monkeypatch) -> None:
    calls = []

    class FakePublicAdapter:
        async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
            assert "Bitcoin" in query
            assert page_size == 30
            return [
                MarketSummary(
                    id="market-1",
                    slug="btc-updown-5m-1783000000",
                    active=True,
                    closed=False,
                    accepting_orders=True,
                )
            ]

        async def get_market_by_slug(self, slug: str) -> MarketDetails:
            assert slug == "btc-updown-5m-1783000000"
            return MarketDetails(
                id="market-1",
                slug=slug,
                condition_id="condition-1",
                outcomes=(
                    MarketOutcomeSummary(label="Up", token_id="token-up"),
                    MarketOutcomeSummary(label="Down", token_id="token-down"),
                ),
            )

    async def fake_run_live_smoke_test(config):
        calls.append(config)
        return SimpleNamespace(final_result="PASS")

    monkeypatch.setattr(
        "polysia.cli_commands.core.PolymarketPublicAdapter",
        FakePublicAdapter,
    )
    monkeypatch.setattr("polysia.cli_commands.live.run_live_smoke_test", fake_run_live_smoke_test)

    result = runner.invoke(
        app,
        [
            "live",
            "smoke-test",
            "--auto-btc-5m",
            "--outcome",
            "YES",
            "--side",
            "BUY",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert calls[0].market_slug == "btc-updown-5m-1783000000"
    assert calls[0].condition_id == "condition-1"
    assert calls[0].token_id == "token-up"
    assert calls[0].settings.polymarket_live_token_allowlist == ("token-up",)


def test_live_smoke_test_requires_selection_without_auto() -> None:
    result = runner.invoke(app, ["live", "smoke-test", "--dry-run"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "--auto-btc-5m" in payload["message"]


@pytest.mark.asyncio
async def test_live_account_status_reports_signer_funder_diagnostics(monkeypatch) -> None:
    FakeAccountStatusAdapter.instances.clear()
    monkeypatch.setattr(
        "polysia.cli_commands.live.PolymarketSecureAdapter", FakeAccountStatusAdapter
    )
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        POLYMARKET_PRIVATE_KEY="not-for-output",
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    payload = await _live_account_status(
        settings=settings,
        i_understand_this_uses_live_account=True,
    )

    assert payload["status"] == "ok"
    assert payload["account_identity"] == {
        "active_wallet_source": "funder",
        "configured_signature_type": 3,
        "funder_configured": True,
        "legacy_wallet_configured": False,
        "sdk_signature_type": 3,
        "signature_type_matches_sdk": True,
        "signer_configured": True,
        "wallet_type": "DEPOSIT_WALLET",
    }
    assert payload["balance_readable"] is True
    assert payload["approval_readable"] is True
    assert payload["positive_approval_count"] == 1
    assert payload["open_order_count"] == 0
    assert payload["position_count"] == 1
    assert "not-for-output" not in str(payload)
    assert "0xfunder" not in str(payload)


def test_live_open_orders_command_delegates_to_async_runner(monkeypatch) -> None:
    calls = []

    async def fake_live_open_orders(**kwargs):
        calls.append(kwargs)
        return {
            "count": 0,
            "dry_run": False,
            "orders": [],
            "request": {"action": "get_open_orders", "token_id": "token-1"},
            "status": "ok",
        }

    monkeypatch.setattr("polysia.cli_commands.live._live_open_orders", fake_live_open_orders)

    result = runner.invoke(
        app,
        [
            "live",
            "open-orders",
            "--token-id",
            "token-1",
            "--i-understand-this-uses-live-account",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["request"] == {"action": "get_open_orders", "token_id": "token-1"}
    assert calls[0]["token_id"] == "token-1"
    assert calls[0]["i_understand_this_uses_live_account"] is True


def test_live_cancel_market_orders_command_delegates_token(monkeypatch) -> None:
    calls = []

    async def fake_live_cancel_market_orders(**kwargs):
        calls.append(kwargs)
        return {
            "dry_run": kwargs["dry_run"],
            "request": {
                "action": "cancel_market_orders",
                "token_id": kwargs["token_id"],
            },
            "response": None,
            "status": "ok",
            "submitted": False,
        }

    monkeypatch.setattr(
        "polysia.cli_commands.live._live_cancel_market_orders",
        fake_live_cancel_market_orders,
    )

    result = runner.invoke(
        app,
        [
            "live",
            "cancel-market-orders",
            "--token-id",
            "token-1",
            "--i-understand-this-modifies-live-orders",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["request"] == {
        "action": "cancel_market_orders",
        "token_id": "token-1",
    }
    assert calls[0]["token_id"] == "token-1"
    assert calls[0]["dry_run"] is True


def test_safe_order_response_summarizes_transaction_hashes() -> None:
    payload = cli_support.safe_order_response(
        {
            "ok": True,
            "order_id": "order-1",
            "status": "live",
            "transactions_hashes": ("0xhash", "0xhash2"),
            "trade_ids": ("trade-1",),
        }
    )

    assert payload == {
        "ok": True,
        "order_id": "order-1",
        "status": "live",
        "trade_count": 1,
        "transaction_count": 2,
    }
    assert "0xhash" not in str(payload)


def test_live_open_order_serializer_excludes_wallet_addresses() -> None:
    order = SimpleNamespace(
        created_at=None,
        expires_at=None,
        id="order-1",
        maker_address="0xmaker",
        market="market-1",
        order_type="GTC",
        original_size=Decimal("10"),
        outcome="Yes",
        owner="0xowner",
        price=Decimal("0.55"),
        side="BUY",
        size_matched=Decimal("0"),
        status="live",
        token_id="token-1",
    )

    payload = cli_support.safe_open_order_to_dict(order)

    assert payload["id"] == "order-1"
    assert payload["price"] == "0.55"
    assert "owner" not in payload
    assert "maker_address" not in payload
    assert "0xowner" not in str(payload)
    assert "0xmaker" not in str(payload)
