from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from polysia.adapters.polymarket.secure import PolymarketSecureAdapterError
from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.post_live_reconciliation import (
    PostLiveReconciliationConfig,
    build_post_live_reconciliation,
    render_post_live_reconciliation,
    write_post_live_reconciliation_reports,
)
from polysia.risk.kill_switch import KillSwitch


class FakePostLiveAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.open_orders: list[object] = []
        self.positions: list[object] = []
        self.open_orders_error = False
        self.account_error = False
        self.submit_calls = 0

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
        raise AssertionError("post-live reconciliation must never submit orders")


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, tzinfo=UTC)


def safe_settings(
    *,
    live_enabled: bool = False,
    token: str = "token-secret",
    wallet: str = "0x2222222222222222222222222222222222222222",
    funder: str = "0x3333333333333333333333333333333333333333",
) -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=live_enabled,
        POLYMARKET_FUNDER_ADDRESS=funder,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=token,
        POLYMARKET_WALLET_ADDRESS=wallet,
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


@pytest.mark.asyncio
async def test_post_live_reconciliation_writes_valid_sanitized_reports(
    tmp_path: Path,
) -> None:
    project_root = ready_project(tmp_path)
    output_dir = ready_artifacts(project_root)
    adapter = FakePostLiveAdapter()

    report = await write_post_live_reconciliation_reports(
        PostLiveReconciliationConfig(
            settings=safe_settings(),
            project_root=project_root,
            output_dir=output_dir,
        ),
        account_adapter=adapter,
        clock=fixed_clock,
        git_runner=clean_git,
    )

    json_path = output_dir / "post-live-reconciliation.json"
    markdown_path = output_dir / "post-live-reconciliation.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    combined = (
        json_path.read_text(encoding="utf-8")
        + markdown_path.read_text(encoding="utf-8")
    )
    assert report.reconciliation_status == "ready"
    assert payload["reconciliation_status"] == "ready"
    assert markdown_path.is_file()
    assert adapter.submit_calls == 0
    assert "not-for-output" not in combined
    assert "token-secret" not in combined
    assert "0x2222222222222222222222222222222222222222" not in combined
    assert "0x3333333333333333333333333333333333333333" not in combined
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in combined
    assert "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in combined


@pytest.mark.asyncio
async def test_post_live_reconciliation_blocks_when_kill_switch_active(
    tmp_path: Path,
) -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual stop")

    report = await build_post_live_reconciliation(
        PostLiveReconciliationConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=FakePostLiveAdapter(),
        kill_switch=kill_switch,
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert report.reconciliation_status == "blocked"
    assert any("Kill switch" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_post_live_reconciliation_blocks_when_live_flag_remains_enabled(
    tmp_path: Path,
) -> None:
    report = await build_post_live_reconciliation(
        PostLiveReconciliationConfig(
            settings=safe_settings(live_enabled=True),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=FakePostLiveAdapter(),
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert report.reconciliation_status == "blocked"
    assert any("LIVE_TRADING_ENABLED" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_post_live_reconciliation_warns_when_open_orders_cannot_be_read(
    tmp_path: Path,
) -> None:
    adapter = FakePostLiveAdapter()
    adapter.open_orders_error = True

    report = await build_post_live_reconciliation(
        PostLiveReconciliationConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=adapter,
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert report.reconciliation_status == "warning"
    assert report.open_orders_readable is False
    assert any("Open orders" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_post_live_reconciliation_warns_when_account_cannot_be_read(
    tmp_path: Path,
) -> None:
    adapter = FakePostLiveAdapter()
    adapter.account_error = True

    report = await build_post_live_reconciliation(
        PostLiveReconciliationConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=adapter,
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert report.reconciliation_status == "warning"
    assert any("Account status" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_post_live_reconciliation_blocks_when_open_orders_remain(
    tmp_path: Path,
) -> None:
    adapter = FakePostLiveAdapter()
    adapter.open_orders = [object()]

    report = await build_post_live_reconciliation(
        PostLiveReconciliationConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=adapter,
        clock=fixed_clock,
        git_runner=clean_git,
    )

    assert report.reconciliation_status == "blocked"
    assert any("Open orders remain" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_post_live_reconciliation_renderer_stays_sanitized(tmp_path: Path) -> None:
    output_dir = ready_artifacts(tmp_path)
    payload = json.loads((output_dir / "tiny_live_execution.json").read_text(encoding="utf-8"))
    assert payload["token_id"] == "token-secret"

    report = await async_build_report(tmp_path)
    rendered = render_post_live_reconciliation(report, "json") + render_post_live_reconciliation(
        report,
        "markdown",
    )
    assert "token-secret" not in rendered


async def async_build_report(tmp_path: Path):
    return await build_post_live_reconciliation(
        PostLiveReconciliationConfig(
            settings=safe_settings(),
            project_root=ready_project(tmp_path),
            output_dir=ready_artifacts(tmp_path),
        ),
        account_adapter=FakePostLiveAdapter(),
        clock=fixed_clock,
        git_runner=clean_git,
    )


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
name = "polysia"
version = "0.1.0"
requires-python = ">=3.11"
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


def ready_artifacts(project_root: Path) -> Path:
    output_dir = project_root / "release-artifacts"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "final-handoff.md").write_text("# Final Handoff\n", encoding="utf-8")
    (output_dir / "tiny_live_execution.json").write_text(
        json.dumps(
            {
                "dry_run": False,
                "final_result": "LIVE_ORDER_FILLED",
                "geoblock_status": {
                    "blocked": False,
                    "endpoint": "https://polymarket.com/api/geoblock",
                    "status": "allowed",
                },
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


def clean_git(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "chore/live-smoke-test-e2e\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "a8ea887\n"
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
