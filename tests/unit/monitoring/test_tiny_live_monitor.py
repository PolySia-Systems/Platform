from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pm_trader.adapters.geoblock import GeoblockStatus
from pm_trader.adapters.polymarket_secure import PolymarketSecureAdapterError
from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.monitoring.tiny_live_monitor import (
    TinyLiveMonitorConfig,
    build_tiny_live_monitor,
    render_tiny_live_monitor,
    write_tiny_live_monitor_reports,
)
from pm_trader.risk.kill_switch import KillSwitch


class FakeTinyLiveMonitorAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.open_orders: list[object] = []
        self.positions: list[object] = []
        self.account_error = False
        self.open_orders_error = False
        self.submit_calls = 0
        self.cancel_calls = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        if self.account_error:
            raise PolymarketSecureAdapterError("read unavailable")
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    def identity(self) -> dict[str, object]:
        return {
            "funder_configured": True,
            "signer_configured": True,
            "wallet_address": "0x1111111111111111111111111111111111111111",
        }

    async def get_balance_allowance(
        self,
        *,
        asset_type: str,
        token_id: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(balance="4.00", allowances={"exchange": "1.00"})

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[object]:
        if self.open_orders_error:
            raise PolymarketSecureAdapterError("open orders unavailable")
        return self.open_orders

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[object]:
        return self.positions

    async def place_market_order(self, **_kwargs: Any) -> None:
        self.submit_calls += 1
        raise AssertionError("tiny live monitor must never submit orders")

    async def cancel_order(self, **_kwargs: Any) -> None:
        self.cancel_calls += 1
        raise AssertionError("tiny live monitor must never cancel orders")


class FakeGeoblockCheck:
    def __init__(self, *, blocked: bool | None = False, status: str = "allowed") -> None:
        self.blocked = blocked
        self.status = status

    async def check(self) -> GeoblockStatus:
        return GeoblockStatus(
            blocked=self.blocked,
            checked_at=fixed_clock(),
            status=self.status,  # type: ignore[arg-type]
        )


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, 12, 45, tzinfo=UTC)


async def no_sleep(_seconds: float) -> None:
    return None


def safe_settings(
    *,
    token: str = "token-secret",
    live_enabled: bool = False,
) -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=live_enabled,
        POLYMARKET_FUNDER_ADDRESS="0x3333333333333333333333333333333333333333",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=token,
        POLYMARKET_WALLET_ADDRESS="0x2222222222222222222222222222222222222222",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


@pytest.mark.asyncio
async def test_tiny_live_monitor_writes_valid_sanitized_reports(tmp_path: Path) -> None:
    adapter = FakeTinyLiveMonitorAdapter()
    output_dir = ready_artifacts(tmp_path)

    report = await write_tiny_live_monitor_reports(
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=output_dir,
            market_slug="btc-updown-5m",
            token_id="token-secret",
        ),
        account_adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleep=no_sleep,
    )

    json_path = output_dir / "tiny-live-monitor.json"
    markdown_path = output_dir / "tiny-live-monitor.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    combined = (
        json_path.read_text(encoding="utf-8")
        + markdown_path.read_text(encoding="utf-8")
    )
    assert report.status == "ready"
    assert payload["status"] == "ready"
    assert payload["max_cycles"] == 1
    assert markdown_path.is_file()
    assert adapter.submit_calls == 0
    assert adapter.cancel_calls == 0
    assert "not-for-output" not in combined
    assert "token-secret" not in combined
    assert "0x2222222222222222222222222222222222222222" not in combined
    assert "0x3333333333333333333333333333333333333333" not in combined
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in combined
    assert "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in combined


def test_tiny_live_monitor_rejects_fast_loop_interval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=tmp_path,
            output_dir=tmp_path,
            interval_seconds=29,
        )


@pytest.mark.asyncio
async def test_tiny_live_monitor_blocks_when_kill_switch_active(tmp_path: Path) -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual stop")

    report = await build_tiny_live_monitor(
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=FakeTinyLiveMonitorAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        kill_switch=kill_switch,
        clock=fixed_clock,
        sleep=no_sleep,
    )

    assert report.status == "blocked"
    assert any("Kill switch" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_tiny_live_monitor_blocks_when_geoblock_blocked(tmp_path: Path) -> None:
    report = await build_tiny_live_monitor(
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=FakeTinyLiveMonitorAdapter(),
        geoblock_check=FakeGeoblockCheck(blocked=True, status="blocked"),
        clock=fixed_clock,
        sleep=no_sleep,
    )

    assert report.status == "blocked"
    assert any("Geoblock" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_tiny_live_monitor_warns_when_account_unavailable(tmp_path: Path) -> None:
    adapter = FakeTinyLiveMonitorAdapter()
    adapter.account_error = True

    report = await build_tiny_live_monitor(
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleep=no_sleep,
    )

    assert report.status == "warning"
    assert any("Account status" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_tiny_live_monitor_warns_when_open_orders_unavailable(
    tmp_path: Path,
) -> None:
    adapter = FakeTinyLiveMonitorAdapter()
    adapter.open_orders_error = True

    report = await build_tiny_live_monitor(
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleep=no_sleep,
    )

    assert report.status == "warning"
    assert any("Open orders" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_tiny_live_monitor_summarizes_open_orders_only(tmp_path: Path) -> None:
    adapter = FakeTinyLiveMonitorAdapter()
    adapter.open_orders = [
        {"id": "secret-order-1", "wallet": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
        {"id": "secret-order-2", "token_id": "token-secret"},
    ]

    report = await build_tiny_live_monitor(
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleep=no_sleep,
    )
    rendered = render_tiny_live_monitor(report, "json") + render_tiny_live_monitor(
        report,
        "markdown",
    )

    assert report.cycles[0].open_order_count == 2
    assert "secret-order-1" not in rendered
    assert "secret-order-2" not in rendered
    assert "token-secret" not in rendered
    assert "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in rendered


@pytest.mark.asyncio
async def test_tiny_live_monitor_runs_multiple_cycles_without_fast_interval(
    tmp_path: Path,
) -> None:
    sleep_calls: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    report = await build_tiny_live_monitor(
        TinyLiveMonitorConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
            max_cycles=2,
            interval_seconds=30,
        ),
        account_adapter=FakeTinyLiveMonitorAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleep=record_sleep,
    )

    assert report.max_cycles == 2
    assert len(report.cycles) == 2
    assert sleep_calls == [30]


def ready_project(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Polymarket\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "TRADING_MODE=DATA_ONLY",
                "LIVE_TRADING_ENABLED=false",
                "POLYMARKET_PRIVATE_KEY=",
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
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
build-backend = "hatchling.build"

[project]
name = "polymarket-trading-system"
version = "0.1.0"
requires-python = ">=3.11"
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


def ready_artifacts(project_root: Path) -> Path:
    output_dir = project_root / "release-artifacts"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "post-live-reconciliation.json").write_text(
        json.dumps({"reconciliation_status": "ready"}),
        encoding="utf-8",
    )
    (output_dir / "observability-snapshot.json").write_text(
        json.dumps({"status": "ready"}),
        encoding="utf-8",
    )
    (output_dir / "tiny_live_execution.json").write_text(
        json.dumps(
            {
                "dry_run": False,
                "final_result": "LIVE_ORDER_FILLED",
                "live_attempt_count": 1,
                "max_notional": "1.00",
                "order_submitted": True,
                "order_type": "FOK",
                "outcome": "YES",
                "side": "BUY",
                "token_id": "token-secret",
                "transaction_hash": (
                    "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                ),
                "wallet_address": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        ),
        encoding="utf-8",
    )
    return output_dir
