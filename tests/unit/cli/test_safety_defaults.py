from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.cli import app
from polysia.cli_commands.live import _live_limit_order
from polysia.config.settings import AppSettings, TradingMode
from polysia.execution.live_broker import LiveBrokerError
from polysia.execution.tiny_live_execution import TinyLiveExecutionReport

runner = CliRunner()


def _tiny_execution_report(
    *,
    final_result: str = "DRY_RUN_PASS",
    blocking_reasons: tuple[str, ...] = (),
) -> TinyLiveExecutionReport:
    return TinyLiveExecutionReport(
        timestamp=datetime(2026, 7, 1, tzinfo=UTC),
        dry_run=final_result.startswith("DRY_RUN"),
        final_result=final_result,  # type: ignore[arg-type]
        token_allowlisted=True,
        geoblock_status={"status": "error", "blocked": None},
        kill_switch_active=False,
        risk_decision={"approved": False, "reason": "mock"},
        order_type="FAK",
        side="BUY",
        outcome="YES",
        max_notional="1.00",
        order_submitted=False,
        order_filled=False,
        fill_summary={},
        rejection_summary={},
        live_attempt_count=0,
        no_retry_statement="No retry was attempted",
        one_attempt_statement="Only one order attempt was allowed",
        no_strategy_loop_statement="No strategy loop or market-making loop was used",
        blocking_reasons=blocking_reasons,
        warnings=(),
        operator_next_steps=("Fix blocking reasons and rerun dry-run only.",),
        diagnostics={},
    )


class FakeSecureAdapter:
    instances: list[FakeSecureAdapter] = []

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.limit_order_calls: list[dict[str, object]] = []
        self.response: dict[str, object] = {
            "ok": True,
            "order_id": "order-1",
            "status": "live",
            "making_amount": Decimal("0.5"),
            "taking_amount": Decimal("1"),
            "trade_ids": (),
            "transactions_hashes": ("0xhash",),
        }
        self.instances.append(self)

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def place_limit_order(self, **kwargs: object) -> dict[str, object]:
        self.limit_order_calls.append(kwargs)
        return self.response


class AllowGeoblock:
    async def assert_allowed(self) -> GeoblockStatus:
        return GeoblockStatus(
            blocked=False,
            checked_at=datetime(2026, 7, 1, tzinfo=UTC),
            status="allowed",
        )


def test_tiny_live_execute_no_dry_run_blocks_without_ack(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-yes")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")

    result = runner.invoke(
        app,
        [
            "tiny-live-execute",
            "--token-id",
            "token-yes",
            "--side",
            "BUY",
            "--outcome",
            "YES",
            "--max-notional",
            "1.00",
            "--order-type",
            "FOK",
            "--output-dir",
            str(tmp_path),
            "--no-dry-run",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["order_submitted"] is False


def test_tiny_live_execute_no_dry_run_blocks_without_allowlist(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "not-for-output")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0xfunder")
    monkeypatch.delenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", raising=False)

    result = runner.invoke(
        app,
        [
            "tiny-live-execute",
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
            "--output-dir",
            str(tmp_path),
            "--no-dry-run",
            "--i-understand-this-places-one-real-order",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["live_attempt_count"] == 0


def test_tiny_live_execute_cli_geoblock_blocked_with_mock(monkeypatch, tmp_path: Path) -> None:
    async def fake_run(*_args: object, **_kwargs: object) -> TinyLiveExecutionReport:
        return _tiny_execution_report(
            final_result="LIVE_ORDER_BLOCKED",
            blocking_reasons=("Polymarket geoblock check failed closed.",),
        )

    monkeypatch.setattr("polysia.cli_commands.live.run_tiny_live_execution", fake_run)

    result = runner.invoke(
        app,
        [
            "tiny-live-execute",
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
            "--output-dir",
            str(tmp_path),
            "--no-dry-run",
            "--i-understand-this-places-one-real-order",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"


def test_acceptance_audit_command_blocks_when_live_flag_enabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    result = runner.invoke(
        app,
        [
            "acceptance-audit",
            "--json",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    report = json.loads((tmp_path / "acceptance_audit.json").read_text(encoding="utf-8"))
    assert report["final_result"] == "NOT_READY"


def test_shadow_run_command_blocks_when_live_flag_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    result = runner.invoke(
        app,
        [
            "shadow-run",
            "--json",
            "--control-database-path",
            str(tmp_path / "control.sqlite3"),
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    report = json.loads((tmp_path / "shadow_run.json").read_text(encoding="utf-8"))
    assert report["classification"] == "SHADOW_FAILED"


def test_live_open_orders_blocks_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)

    result = runner.invoke(
        app,
        ["live-open-orders", "--i-understand-this-uses-live-account"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "TRADING_MODE=LIVE" in payload["message"]


def test_live_cancel_order_command_defaults_to_dry_run(monkeypatch) -> None:
    calls = []

    async def fake_live_cancel_order(**kwargs):
        calls.append(kwargs)
        return {
            "dry_run": kwargs["dry_run"],
            "request": {"action": "cancel_order", "order_id": kwargs["order_id"]},
            "response": None,
            "status": "ok",
            "submitted": False,
        }

    monkeypatch.setattr("polysia.cli_commands.live._live_cancel_order", fake_live_cancel_order)

    result = runner.invoke(
        app,
        [
            "live-cancel-order",
            "--order-id",
            "order-1",
            "--i-understand-this-modifies-live-orders",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["submitted"] is False
    assert calls[0]["order_id"] == "order-1"
    assert calls[0]["dry_run"] is True
    assert calls[0]["i_understand_this_modifies_live_orders"] is True


def test_live_limit_order_blocks_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "live-limit-order",
            "--token-id",
            "token-1",
            "--price",
            "0.50",
            "--size",
            "1",
            "--i-understand-this-places-real-orders",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "TRADING_MODE=LIVE" in payload["message"]


def test_live_limit_order_command_defaults_to_dry_run(monkeypatch) -> None:
    calls = []

    async def fake_live_limit_order(**kwargs):
        calls.append(kwargs)
        return {
            "dry_run": kwargs["dry_run"],
            "request": {
                "action": "place_limit_order",
                "token_id": kwargs["token_id"],
                "price": str(kwargs["price"]),
                "size": str(kwargs["size"]),
                "post_only": True,
            },
            "response": None,
            "status": "ok",
            "submitted": False,
        }

    monkeypatch.setattr("polysia.cli_commands.live._live_limit_order", fake_live_limit_order)

    result = runner.invoke(
        app,
        [
            "live-limit-order",
            "--token-id",
            "token-1",
            "--price",
            "0.44",
            "--size",
            "0.5",
            "--i-understand-this-places-real-orders",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["submitted"] is False
    assert calls[0]["dry_run"] is True
    assert calls[0]["price"] == Decimal("0.44")
    assert calls[0]["size"] == Decimal("0.5")


@pytest.mark.asyncio
async def test_live_limit_order_dry_run_does_not_connect(monkeypatch) -> None:
    FakeSecureAdapter.instances.clear()
    monkeypatch.setattr("polysia.cli_commands.live.PolymarketSecureAdapter", FakeSecureAdapter)
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="1",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="1",
    )

    payload = await _live_limit_order(
        settings=settings,
        token_id="token-1",
        side="BUY",
        price=Decimal("0.50"),
        size=Decimal("1"),
        dry_run=True,
        strategy_id="operator-tiny-live",
        reason="unit test",
        current_position=Decimal("0"),
        current_market_position=Decimal("0"),
        daily_pnl=Decimal("0"),
        open_orders_count=0,
        market_data_age_ms=0,
        i_understand_this_places_real_orders=True,
    )

    adapter = FakeSecureAdapter.instances[-1]
    assert payload["dry_run"] is True
    assert payload["submitted"] is False
    assert payload["request"] == {
        "action": "place_limit_order",
        "token_id": "token-1",
        "side": "BUY",
        "price": "0.50",
        "size": "1",
        "post_only": True,
    }
    assert adapter.connected is False
    assert adapter.closed is True
    assert adapter.limit_order_calls == []


@pytest.mark.asyncio
async def test_live_limit_order_submit_uses_allowlisted_fake_adapter(monkeypatch) -> None:
    FakeSecureAdapter.instances.clear()
    monkeypatch.setattr("polysia.cli_commands.live.PolymarketSecureAdapter", FakeSecureAdapter)
    monkeypatch.setattr(
        "polysia.execution.live_broker.PreLiveOrderGeoblockCheck",
        lambda: AllowGeoblock(),
    )
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="1",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="1",
    )

    payload = await _live_limit_order(
        settings=settings,
        token_id="token-1",
        side="SELL",
        price=Decimal("0.50"),
        size=Decimal("1"),
        dry_run=False,
        strategy_id="operator-tiny-live",
        reason="unit test",
        current_position=Decimal("1"),
        current_market_position=Decimal("1"),
        daily_pnl=Decimal("0"),
        open_orders_count=0,
        market_data_age_ms=0,
        i_understand_this_places_real_orders=True,
    )

    adapter = FakeSecureAdapter.instances[-1]
    assert payload["submitted"] is True
    assert payload["dry_run"] is False
    assert payload["response"] == {
        "ok": True,
        "order_id": "order-1",
        "status": "live",
        "making_amount": "0.5",
        "taking_amount": "1",
        "trade_count": 0,
        "transaction_count": 1,
    }
    assert "0xhash" not in str(payload)
    assert adapter.connected is True
    assert adapter.closed is True
    assert adapter.limit_order_calls == [
        {
            "token_id": "token-1",
            "side": "SELL",
            "price": Decimal("0.50"),
            "size": Decimal("1"),
            "post_only": True,
            "expiration": None,
            "builder_code": None,
        }
    ]


@pytest.mark.asyncio
async def test_live_limit_order_rejects_size_above_tiny_cap(monkeypatch) -> None:
    FakeSecureAdapter.instances.clear()
    monkeypatch.setattr("polysia.cli_commands.live.PolymarketSecureAdapter", FakeSecureAdapter)
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="1",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="2",
    )

    with pytest.raises(LiveBrokerError, match="risk engine blocked"):
        await _live_limit_order(
            settings=settings,
            token_id="token-1",
            side="BUY",
            price=Decimal("0.50"),
            size=Decimal("2"),
            dry_run=True,
            strategy_id="operator-tiny-live",
            reason="unit test",
            current_position=Decimal("0"),
            current_market_position=Decimal("0"),
            daily_pnl=Decimal("0"),
            open_orders_count=0,
            market_data_age_ms=0,
            i_understand_this_places_real_orders=True,
        )

    adapter = FakeSecureAdapter.instances[-1]
    assert adapter.connected is False
    assert adapter.closed is True
    assert adapter.limit_order_calls == []
