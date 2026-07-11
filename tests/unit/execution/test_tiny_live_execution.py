from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.config.settings import AppSettings, TradingMode
from polysia.execution.tiny_live_execution import (
    TinyLiveExecutionConfig,
    render_tiny_live_execution_json,
    run_tiny_live_execution,
)
from polysia.risk.checks import RiskEngine
from polysia.risk.kill_switch import KillSwitch
from polysia.risk.limits import RiskLimits


class FakeTinyAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.submit_calls: list[dict[str, Any]] = []
        self.open_order_calls = 0
        self.response: dict[str, object] = {
            "ok": True,
            "order_id": "order-1",
            "status": "matched",
            "filled_size": "1",
            "average_fill_price": "0.50",
        }
        self.identity_payload = {
            "active_wallet_source": "funder",
            "funder_configured": True,
            "signer_configured": True,
            "wallet_type": "DEPOSIT_WALLET",
        }

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    def identity(self) -> dict[str, object]:
        return self.identity_payload

    async def get_balance_allowance(
        self,
        *,
        asset_type: str,
        token_id: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(balance=1_000_000, allowances={"exchange": 1})

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[object]:
        self.open_order_calls += 1
        return []

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        self.submit_calls.append(kwargs)
        return self.response


class FakeGeoblockCheck:
    def __init__(self, status: GeoblockStatus | None = None) -> None:
        self.status = status or GeoblockStatus(
            status="allowed",
            checked_at=datetime(2026, 7, 1, tzinfo=UTC),
            blocked=False,
        )
        self.calls = 0

    async def check(self) -> GeoblockStatus:
        self.calls += 1
        return self.status


def live_settings(*, allowlist: str = "token-yes", funder: str = "0xfunder") -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=allowlist,
        POLYMARKET_FUNDER_ADDRESS=funder,
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


def dry_settings() -> AppSettings:
    return AppSettings(
        _env_file=None,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-yes",
    )


def config(
    tmp_path: Path,
    *,
    settings: AppSettings | None = None,
    dry_run: bool = True,
    acknowledgement: bool = False,
    token_id: str = "token-yes",
    max_notional: Decimal = Decimal("1.00"),
    order_type: str = "FAK",
) -> TinyLiveExecutionConfig:
    return TinyLiveExecutionConfig(
        settings=settings or dry_settings(),
        token_id=token_id,
        side="BUY",
        outcome="YES",
        max_notional=max_notional,
        order_type=order_type,  # type: ignore[arg-type]
        output_dir=tmp_path,
        dry_run=dry_run,
        acknowledgement=acknowledgement,
        market_slug="btc-updown-5m-test",
        project_root=tmp_path,
    )


@pytest.mark.asyncio
async def test_dry_run_does_not_call_live_broker(tmp_path: Path) -> None:
    adapter = FakeTinyAdapter()

    report = await run_tiny_live_execution(
        config(tmp_path),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "DRY_RUN_PASS"
    assert report.order_submitted is False
    assert report.live_attempt_count == 0
    assert adapter.submit_calls == []
    assert (tmp_path / "tiny_live_execution.json").is_file()


@pytest.mark.asyncio
async def test_real_path_blocks_when_live_trading_disabled(tmp_path: Path) -> None:
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-yes",
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )

    report = await run_tiny_live_execution(
        config(tmp_path, settings=settings, dry_run=False, acknowledgement=True),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_BLOCKED"
    assert "TRADING_MODE=LIVE" in report.blocking_reasons[0]


@pytest.mark.asyncio
async def test_real_path_blocks_when_acknowledgement_missing(tmp_path: Path) -> None:
    report = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_BLOCKED"
    assert "one-real-order" in report.blocking_reasons[0]


@pytest.mark.asyncio
async def test_blocks_when_token_not_allowlisted(tmp_path: Path) -> None:
    report = await run_tiny_live_execution(
        config(
            tmp_path,
            settings=live_settings(allowlist="other"),
            dry_run=False,
            acknowledgement=True,
        ),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_BLOCKED"
    assert "allowlist" in report.blocking_reasons[0].lower()


@pytest.mark.asyncio
async def test_blocks_when_max_notional_above_one(tmp_path: Path) -> None:
    report = await run_tiny_live_execution(
        config(tmp_path, max_notional=Decimal("1.01")),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "DRY_RUN_BLOCKED"
    assert "above 1.00" in report.blocking_reasons[0]


@pytest.mark.asyncio
async def test_blocks_when_order_type_is_not_fak_or_fok(tmp_path: Path) -> None:
    report = await run_tiny_live_execution(
        config(tmp_path, order_type="GTC"),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "DRY_RUN_BLOCKED"
    assert "FAK or FOK" in report.blocking_reasons[0]


@pytest.mark.asyncio
async def test_blocks_when_kill_switch_active(tmp_path: Path) -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual stop")
    risk_engine = RiskEngine(
        limits=RiskLimits(max_order_notional=Decimal("1"), allow_live_trading=True),
        kill_switch=kill_switch,
    )

    report = await run_tiny_live_execution(
        config(tmp_path),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        risk_engine=risk_engine,
        git_reader=fake_git,
    )

    assert report.final_result == "DRY_RUN_BLOCKED"
    assert "kill switch" in report.blocking_reasons[0]


@pytest.mark.asyncio
async def test_blocks_when_geoblock_blocked_or_errors(tmp_path: Path) -> None:
    blocked = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False, acknowledgement=True),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(
            GeoblockStatus(
                status="blocked",
                checked_at=datetime(2026, 7, 1, tzinfo=UTC),
                blocked=True,
            )
        ),
        git_reader=fake_git,
    )
    failed_closed = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False, acknowledgement=True),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(
            GeoblockStatus(
                status="error",
                checked_at=datetime(2026, 7, 1, tzinfo=UTC),
                blocked=None,
            )
        ),
        git_reader=fake_git,
    )

    assert blocked.final_result == "LIVE_ORDER_BLOCKED"
    assert failed_closed.final_result == "LIVE_ORDER_BLOCKED"
    assert "failed closed" in failed_closed.blocking_reasons[0]


@pytest.mark.asyncio
async def test_blocks_when_funder_missing(tmp_path: Path) -> None:
    report = await run_tiny_live_execution(
        config(
            tmp_path,
            settings=live_settings(funder=""),
            dry_run=False,
            acknowledgement=True,
        ),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_BLOCKED"
    assert "FUNDER" in report.blocking_reasons[0]


@pytest.mark.asyncio
async def test_real_path_calls_live_broker_at_most_once(tmp_path: Path) -> None:
    adapter = FakeTinyAdapter()

    report = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False, acknowledgement=True),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_FILLED"
    assert report.live_attempt_count == 1
    assert len(adapter.submit_calls) == 1
    assert adapter.submit_calls[0]["amount"] == Decimal("1.00")


@pytest.mark.asyncio
async def test_no_retry_after_rejection(tmp_path: Path) -> None:
    adapter = FakeTinyAdapter()
    adapter.response = {"ok": False, "status": "rejected", "message": "test reject"}

    report = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False, acknowledgement=True),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_REJECTED"
    assert report.live_attempt_count == 1
    assert len(adapter.submit_calls) == 1
    assert "No retry was attempted" in report.no_retry_statement


@pytest.mark.asyncio
async def test_partial_and_expired_results_are_classified(tmp_path: Path) -> None:
    partial_adapter = FakeTinyAdapter()
    partial_adapter.response = {"ok": True, "status": "partially_filled", "filled_size": "0.5"}
    expired_adapter = FakeTinyAdapter()
    expired_adapter.response = {"ok": True, "status": "expired"}

    partial = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False, acknowledgement=True),
        adapter=partial_adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )
    expired = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False, acknowledgement=True),
        adapter=expired_adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert partial.final_result == "LIVE_ORDER_PARTIALLY_FILLED"
    assert expired.final_result == "LIVE_ORDER_EXPIRED"
    assert len(partial_adapter.submit_calls) == 1
    assert len(expired_adapter.submit_calls) == 1


@pytest.mark.asyncio
async def test_report_redacts_secrets(tmp_path: Path) -> None:
    report = await run_tiny_live_execution(
        config(tmp_path, settings=live_settings(), dry_run=False, acknowledgement=True),
        adapter=FakeTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    rendered = render_tiny_live_execution_json(report)
    assert "not-for-output" not in rendered
    assert "0xfunder" not in rendered
    assert "No strategy loop" in rendered


def fake_git(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
