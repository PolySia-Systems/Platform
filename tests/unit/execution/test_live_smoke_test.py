from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.config.settings import AppSettings, TradingMode
from polysia.execution.live_smoke_test import (
    LiveSmokeTestConfig,
    OneOrderAttemptGuard,
    run_live_smoke_test,
)


class FakeSmokeAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.balance = SimpleNamespace(balance=4_000_000, allowances={"exchange": 1})
        self.conditional = SimpleNamespace(balance=1, allowances={"exchange": 1})
        self.market = fake_market()
        self.order_book = fake_order_book()
        self.positions = [
            SimpleNamespace(
                token_id="token-yes",
                size=Decimal("2"),
                avg_price=Decimal("0.40"),
                current_value=Decimal("1.00"),
                outcome="Yes",
            )
        ]
        self.trades: list[Any] = []
        self.open_orders: list[Any] = []
        self.cancel_calls: list[str] = []
        self.order_calls: list[dict[str, Any]] = []
        self.response: dict[str, object] = {
            "ok": True,
            "order_id": "order-1",
            "status": "matched",
        }

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def get_balance_allowance(
        self,
        *,
        asset_type: str,
        token_id: str | None = None,
    ) -> Any:
        return self.conditional if asset_type == "CONDITIONAL" else self.balance

    async def get_market(self, *, id: str | None = None, slug: str | None = None) -> Any:
        return self.market

    async def get_order_book(self, *, token_id: str) -> Any:
        return self.order_book

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        return self.positions

    async def list_account_trades(
        self,
        *,
        token_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        return self.trades

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        return self.open_orders

    async def cancel_order(self, *, order_id: str) -> dict[str, object]:
        self.cancel_calls.append(order_id)
        return {"canceled": (order_id,), "not_canceled": {}}

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        self.order_calls.append(kwargs)
        return self.response


class FakeGeoblockCheck:
    def __init__(self, status: GeoblockStatus | None = None) -> None:
        self.status = status or GeoblockStatus(
            status="allowed",
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            blocked=False,
        )
        self.calls = 0

    async def check(self) -> GeoblockStatus:
        self.calls += 1
        return self.status


def fake_market() -> Any:
    return SimpleNamespace(
        slug="btc-up-or-down-5m",
        condition_id="condition-1",
        question="BTC up?",
        state=SimpleNamespace(active=True, closed=False, accepting_orders=True),
        trading=SimpleNamespace(
            minimum_order_size=Decimal("1"),
            minimum_tick_size=Decimal("0.01"),
        ),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id="token-yes"),
            no=SimpleNamespace(token_id="token-no"),
        ),
    )


def fake_order_book() -> Any:
    return SimpleNamespace(
        market="condition-1",
        token_id="token-yes",
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        bids=(SimpleNamespace(price=Decimal("0.48"), size=Decimal("10")),),
        asks=(SimpleNamespace(price=Decimal("0.50"), size=Decimal("10")),),
    )


def smoke_config(
    tmp_path: Path,
    *,
    dry_run: bool = True,
    settings: AppSettings | None = None,
    acknowledgement: bool = False,
    max_notional: Decimal = Decimal("1.00"),
    order_type: str = "FAK",
    side: str = "BUY",
) -> LiveSmokeTestConfig:
    return LiveSmokeTestConfig(
        settings=settings or AppSettings(),
        market_slug="btc-up-or-down-5m",
        condition_id="condition-1",
        token_id="token-yes",
        outcome="YES",
        side=side,  # type: ignore[arg-type]
        max_notional=max_notional,
        order_type=order_type,  # type: ignore[arg-type]
        dry_run=dry_run,
        acknowledgement=acknowledgement,
        project_root=tmp_path,
        report_json_path=tmp_path / "live_smoke_test.json",
        report_markdown_path=tmp_path / "live_smoke_test.md",
    )


def live_settings(*, allowlist: str = "token-yes") -> AppSettings:
    return AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=allowlist,
        POLYMARKET_PRIVATE_KEY="not-for-output",
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
    )


@pytest.mark.asyncio
async def test_live_smoke_dry_run_never_submits_order(tmp_path: Path) -> None:
    adapter = FakeSmokeAdapter()

    report = await run_live_smoke_test(
        smoke_config(tmp_path),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "PASS"
    assert report.dry_run is True
    assert report.order_submitted is False
    assert adapter.order_calls == []
    assert (tmp_path / "live_smoke_test.json").is_file()
    assert (tmp_path / "live_smoke_test.md").is_file()


@pytest.mark.asyncio
async def test_live_smoke_live_mode_is_blocked_by_default(tmp_path: Path) -> None:
    adapter = FakeSmokeAdapter()

    report = await run_live_smoke_test(
        smoke_config(tmp_path, dry_run=False, acknowledgement=True),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "TRADING_MODE=LIVE" in report.errors[0]
    assert adapter.connected is False
    assert adapter.order_calls == []


@pytest.mark.asyncio
async def test_live_smoke_missing_ack_blocks_order(tmp_path: Path) -> None:
    adapter = FakeSmokeAdapter()

    report = await run_live_smoke_test(
        smoke_config(tmp_path, dry_run=False, settings=live_settings()),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "i-understand-this-places-a-real-order" in report.errors[0]
    assert adapter.order_calls == []


@pytest.mark.asyncio
async def test_live_smoke_missing_funder_blocks_order(tmp_path: Path) -> None:
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-yes",
        POLYMARKET_PRIVATE_KEY="not-for-output",
    )

    report = await run_live_smoke_test(
        smoke_config(
            tmp_path,
            dry_run=False,
            settings=settings,
            acknowledgement=True,
        ),
        adapter=FakeSmokeAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "POLYMARKET_FUNDER_ADDRESS" in report.errors[0]


@pytest.mark.asyncio
async def test_live_smoke_rejects_max_notional_above_one(tmp_path: Path) -> None:
    report = await run_live_smoke_test(
        smoke_config(tmp_path, max_notional=Decimal("1.01")),
        adapter=FakeSmokeAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "above 1.00" in report.errors[0]


@pytest.mark.asyncio
async def test_live_smoke_buy_allows_one_dollar_amount_when_min_order_size_is_shares(
    tmp_path: Path,
) -> None:
    adapter = FakeSmokeAdapter()
    adapter.order_book.min_order_size = Decimal("5")

    report = await run_live_smoke_test(
        smoke_config(tmp_path),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "PASS"
    assert report.max_notional == "1.00"
    assert report.min_order_size == "5"
    assert adapter.order_calls == []


@pytest.mark.asyncio
async def test_live_smoke_sell_aborts_when_worst_case_notional_exceeds_cap(
    tmp_path: Path,
) -> None:
    adapter = FakeSmokeAdapter()
    adapter.order_book.min_order_size = Decimal("3")

    report = await run_live_smoke_test(
        smoke_config(tmp_path, side="SELL"),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "Worst-case notional" in report.errors[0]
    assert adapter.order_calls == []


@pytest.mark.asyncio
async def test_live_smoke_token_not_allowlisted_aborts(tmp_path: Path) -> None:
    adapter = FakeSmokeAdapter()

    report = await run_live_smoke_test(
        smoke_config(
            tmp_path,
            dry_run=False,
            settings=live_settings(allowlist="other-token"),
            acknowledgement=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "allowlist" in report.errors[0].lower()
    assert adapter.order_calls == []


@pytest.mark.asyncio
async def test_live_smoke_rejects_gtc_and_gtd(tmp_path: Path) -> None:
    for order_type in ("GTC", "GTD"):
        report = await run_live_smoke_test(
            smoke_config(tmp_path, order_type=order_type),
            adapter=FakeSmokeAdapter(),
            geoblock_check=FakeGeoblockCheck(),
            git_reader=fake_git,
        )
        assert report.final_result == "ABORTED"
        assert "FAK or FOK" in report.errors[0]


@pytest.mark.asyncio
async def test_one_order_attempt_guard_rejects_second_attempt() -> None:
    adapter = FakeSmokeAdapter()
    guard = OneOrderAttemptGuard()

    await guard.place_market_order_once(
        adapter,
        token_id="token-yes",
        side="BUY",
        amount=Decimal("1"),
        shares=None,
        max_price=Decimal("0.51"),
        min_price=None,
        order_type="FAK",
    )

    with pytest.raises(RuntimeError, match="one-order-attempt"):
        await guard.place_market_order_once(
            adapter,
            token_id="token-yes",
            side="BUY",
            amount=Decimal("1"),
            shares=None,
            max_price=Decimal("0.51"),
            min_price=None,
            order_type="FAK",
        )


@pytest.mark.asyncio
async def test_live_smoke_geoblock_blocked_aborts(tmp_path: Path) -> None:
    status = GeoblockStatus(
        status="blocked",
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
        blocked=True,
    )

    report = await run_live_smoke_test(
        smoke_config(tmp_path),
        adapter=FakeSmokeAdapter(),
        geoblock_check=FakeGeoblockCheck(status),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "blocked=true" in report.errors[0]
    assert report.geoblock_status is not None
    assert report.geoblock_status["blocked"] is True


@pytest.mark.asyncio
async def test_live_smoke_geoblock_error_fails_closed(tmp_path: Path) -> None:
    status = GeoblockStatus(
        status="error",
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
        blocked=None,
        error_type="TimeoutError",
    )

    report = await run_live_smoke_test(
        smoke_config(tmp_path),
        adapter=FakeSmokeAdapter(),
        geoblock_check=FakeGeoblockCheck(status),
        git_reader=fake_git,
    )

    assert report.final_result == "ABORTED"
    assert "failed closed" in report.errors[0]


@pytest.mark.asyncio
async def test_live_smoke_geoblock_false_allows_workflow_to_continue(tmp_path: Path) -> None:
    geoblock = FakeGeoblockCheck()

    report = await run_live_smoke_test(
        smoke_config(tmp_path),
        adapter=FakeSmokeAdapter(),
        geoblock_check=geoblock,
        git_reader=fake_git,
    )

    assert report.final_result == "PASS"
    assert geoblock.calls == 1
    assert report.computed_limit_price == "0.51"


@pytest.mark.asyncio
async def test_live_smoke_secret_redaction_in_reports(tmp_path: Path) -> None:
    report = await run_live_smoke_test(
        smoke_config(tmp_path, settings=live_settings()),
        adapter=FakeSmokeAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    report_text = (tmp_path / "live_smoke_test.json").read_text(encoding="utf-8")
    assert report.final_result == "PASS"
    assert "not-for-output" not in report_text
    assert "0xwallet" not in report_text


@pytest.mark.asyncio
async def test_live_smoke_cancels_residual_open_order_with_mocks(tmp_path: Path) -> None:
    adapter = FakeSmokeAdapter()
    adapter.open_orders = [SimpleNamespace(id="order-1", status="live")]

    report = await run_live_smoke_test(
        smoke_config(
            tmp_path,
            dry_run=False,
            settings=live_settings(),
            acknowledgement=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        git_reader=fake_git,
    )

    assert report.final_result == "PASS"
    assert report.order_submitted is True
    assert report.residual_open_order is True
    assert report.cancel_attempted is True
    assert adapter.cancel_calls == ["order-1"]
    assert len(adapter.order_calls) == 1


def fake_git(_root: Path, command: tuple[str, ...]) -> str:
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "abc1234\n"
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")
