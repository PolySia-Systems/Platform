from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pm_trader.adapters.geoblock import GeoblockStatus
from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.execution.controlled_second_tiny_live import (
    ControlledSecondTinyLiveConfig,
    render_controlled_second_tiny_live,
    run_controlled_second_tiny_live,
)
from pm_trader.risk.checks import RiskEngine
from pm_trader.risk.kill_switch import KillSwitch
from pm_trader.risk.limits import RiskLimits


class FakeControlledTinyAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.submit_calls: list[dict[str, Any]] = []
        self.response: dict[str, object] = {"ok": True, "status": "matched"}
        self.identity_payload = {
            "active_wallet_source": "funder",
            "funder_configured": True,
            "signer_configured": True,
            "wallet_address": "0x1111111111111111111111111111111111111111",
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
        return SimpleNamespace(balance="4.00", allowances={"exchange": "1.00"})

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[object]:
        return []

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        self.submit_calls.append(kwargs)
        return self.response


class FakeGeoblockCheck:
    def __init__(self, *, blocked: bool | None = False, status: str = "allowed") -> None:
        self.blocked = blocked
        self.status = status

    async def check(self) -> GeoblockStatus:
        return GeoblockStatus(
            status=self.status,  # type: ignore[arg-type]
            checked_at=fixed_clock(),
            blocked=self.blocked,
        )


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, 13, 15, tzinfo=UTC)


def live_settings(
    *,
    trading_mode: TradingMode = TradingMode.LIVE,
    live_enabled: bool = True,
    token: str = "token-secret",
    funder: str = "0xfunder",
) -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=trading_mode,
        LIVE_TRADING_ENABLED=live_enabled,
        POLYMARKET_FUNDER_ADDRESS=funder,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=token,
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


def config(
    tmp_path: Path,
    *,
    settings: AppSettings | None = None,
    token_id: str = "token-secret",
    market_slug: str = "btc-updown-5m-test",
    dry_run: bool = True,
    submit_requested: bool = False,
    acknowledgement: bool = False,
    second_acknowledgement: bool = False,
    max_notional: Decimal = Decimal("1.00"),
    order_type: str = "FOK",
) -> ControlledSecondTinyLiveConfig:
    return ControlledSecondTinyLiveConfig(
        settings=settings or live_settings(),
        output_dir=tmp_path,
        token_id=token_id,
        side="BUY",
        outcome="YES",
        max_notional=max_notional,
        order_type=order_type,  # type: ignore[arg-type]
        market_slug=market_slug,
        dry_run=dry_run,
        submit_requested=submit_requested,
        acknowledgement=acknowledgement,
        second_acknowledgement=second_acknowledgement,
        project_root=tmp_path,
    )


@pytest.mark.asyncio
async def test_controlled_second_tiny_live_dry_run_is_default(tmp_path: Path) -> None:
    adapter = FakeControlledTinyAdapter()

    report = await run_controlled_second_tiny_live(
        config(tmp_path),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "DRY_RUN_READY"
    assert report.dry_run is True
    assert report.submit_requested is False
    assert report.order_submitted is False
    assert report.live_attempt_count == 0
    assert adapter.submit_calls == []
    assert (tmp_path / "controlled-second-tiny-live.json").is_file()
    assert (tmp_path / "controlled-second-tiny-live.md").is_file()


@pytest.mark.asyncio
async def test_submit_blocks_without_both_acknowledgements(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=False,
        ),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("second-controlled" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_blocks_if_trading_mode_is_not_live(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            settings=live_settings(trading_mode=TradingMode.DATA_ONLY),
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("TRADING_MODE=LIVE" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_blocks_if_live_enabled_false(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            settings=live_settings(live_enabled=False),
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("LIVE_TRADING_ENABLED" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_blocks_if_kill_switch_active(tmp_path: Path) -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual stop")
    risk_engine = RiskEngine(
        limits=RiskLimits(max_order_notional=Decimal("1"), allow_live_trading=True),
        kill_switch=kill_switch,
    )

    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        risk_engine=risk_engine,
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("kill switch" in reason.lower() for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_blocks_if_geoblock_blocked(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(blocked=True, status="blocked"),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("geoblock" in reason.lower() for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_blocks_if_token_not_allowlisted(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            settings=live_settings(token="other-token"),
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("allowlisted" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_blocks_if_token_is_not_btc_5m_selected(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            market_slug="not-a-btc-market",
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("BTC Up/Down 5m" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_blocks_if_max_notional_exceeds_cap(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(tmp_path, max_notional=Decimal("1.01")),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("above 1.00" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_only_fok_or_fak_allowed(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(tmp_path, order_type="GTC"),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "BLOCKED"
    assert any("FOK or FAK" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_submit_attempt_count_cannot_exceed_one(tmp_path: Path) -> None:
    adapter = FakeControlledTinyAdapter()

    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_FILLED"
    assert report.live_attempt_count == 1
    assert len(adapter.submit_calls) == 1


@pytest.mark.asyncio
async def test_no_retry_after_rejected_submit(tmp_path: Path) -> None:
    adapter = FakeControlledTinyAdapter()
    adapter.response = {"ok": False, "status": "rejected", "message": "test reject"}

    report = await run_controlled_second_tiny_live(
        config(
            tmp_path,
            dry_run=False,
            submit_requested=True,
            acknowledgement=True,
            second_acknowledgement=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert report.final_result == "LIVE_ORDER_REJECTED"
    assert report.live_attempt_count == 1
    assert len(adapter.submit_calls) == 1
    assert "No retry" in report.no_retry_statement


@pytest.mark.asyncio
async def test_no_loop_or_strategy_path_is_reported(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(tmp_path),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    assert "No strategy automation" in report.no_strategy_statement
    assert "At most one live order attempt" in report.one_attempt_statement


@pytest.mark.asyncio
async def test_report_is_sanitized(tmp_path: Path) -> None:
    report = await run_controlled_second_tiny_live(
        config(tmp_path),
        adapter=FakeControlledTinyAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        git_reader=fake_git,
    )

    rendered = render_controlled_second_tiny_live(
        report,
        "json",
    ) + render_controlled_second_tiny_live(report, "markdown")
    assert "not-for-output" not in rendered
    assert "token-secret" not in rendered
    assert "0xfunder" not in rendered
    assert "0x1111111111111111111111111111111111111111" not in rendered


def fake_git(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
