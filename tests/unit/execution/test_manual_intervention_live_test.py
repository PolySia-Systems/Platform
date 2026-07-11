from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.config.settings import AppSettings, TradingMode
from polysia.execution import manual_intervention_live_test as module
from polysia.execution.manual_intervention_live_test import (
    ManualInterventionLiveTestConfig,
    render_manual_intervention_live_test,
    run_manual_intervention_live_test,
)


class FakeManualInterventionAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.submit_calls: list[dict[str, Any]] = []
        self.open_order_reads = 0
        self.position_reads = 0
        self.response: dict[str, object] = {
            "ok": True,
            "order_id": "order-1",
            "status": "submitted",
        }
        self.open_order_sequence: list[list[object]] = [
            [],
            [SimpleNamespace(id="order-1", status="live", token_id="token-yes")],
            [],
        ]
        self.position_sequence: list[list[object]] = []

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    def identity(self) -> dict[str, object]:
        return {
            "active_wallet_source": "funder",
            "funder_configured": True,
            "signer_configured": True,
            "wallet_type": "DEPOSIT_WALLET",
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
        self.open_order_reads += 1
        if self.open_order_sequence:
            return self.open_order_sequence.pop(0)
        return []

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[object]:
        self.position_reads += 1
        if self.position_sequence:
            return self.position_sequence.pop(0)
        return []

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        self.submit_calls.append(kwargs)
        return self.response


class FakeGeoblockCheck:
    async def check(self) -> GeoblockStatus:
        return GeoblockStatus(
            blocked=False,
            checked_at=fixed_clock(),
            status="allowed",
        )


def fixed_clock() -> datetime:
    fixed_clock.current += timedelta(seconds=1)
    return fixed_clock.current


fixed_clock.current = datetime(2026, 7, 2, 16, 0, tzinfo=UTC)


async def no_sleep(_seconds: float) -> None:
    return None


def live_settings(*, token: str = "token-yes") -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=token,
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


def dry_settings(*, token: str = "token-yes") -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=False,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST=token,
    )


def config(
    tmp_path: Path,
    *,
    settings: AppSettings | None = None,
    dry_run: bool = True,
    acknowledgement: bool = False,
    manual_ack: bool = False,
    token_id: str = "token-yes",
    max_notional: Decimal = Decimal("1.00"),
    order_type: str = "FOK",
) -> ManualInterventionLiveTestConfig:
    return ManualInterventionLiveTestConfig(
        settings=settings or dry_settings(),
        output_dir=tmp_path,
        token_id=token_id,
        side="BUY",
        outcome="YES",
        max_notional=max_notional,
        order_type=order_type,  # type: ignore[arg-type]
        market_slug="btc-updown-5m-test",
        condition_id="condition-1",
        dry_run=dry_run,
        acknowledgement=acknowledgement,
        manual_intervention_acknowledgement=manual_ack,
        poll_attempts=3,
        poll_interval_seconds=0,
        project_root=tmp_path,
    )


@pytest.mark.asyncio
async def test_dry_run_does_not_submit_or_poll(tmp_path: Path) -> None:
    adapter = FakeManualInterventionAdapter()

    report = await run_manual_intervention_live_test(
        config(tmp_path),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )

    assert report.final_result == "DRY_RUN_READY"
    assert report.order_submitted is False
    assert report.live_attempt_count == 0
    assert adapter.submit_calls == []
    assert report.manual_intervention_detected is False
    assert (tmp_path / "manual-intervention-live-test.json").is_file()
    assert (tmp_path / "manual-intervention-live-test.md").is_file()


@pytest.mark.asyncio
async def test_real_path_blocks_without_manual_acknowledgement(tmp_path: Path) -> None:
    adapter = FakeManualInterventionAdapter()

    report = await run_manual_intervention_live_test(
        config(
            tmp_path,
            settings=live_settings(),
            dry_run=False,
            acknowledgement=True,
            manual_ack=False,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )

    assert report.final_result == "BLOCKED"
    assert report.live_attempt_count == 0
    assert adapter.submit_calls == []
    assert any("manually-cancel-or-close" in reason for reason in report.blocking_reasons)


@pytest.mark.asyncio
async def test_rejects_above_one_and_non_fok_fak(tmp_path: Path) -> None:
    above_one = await run_manual_intervention_live_test(
        config(tmp_path, max_notional=Decimal("1.01")),
        adapter=FakeManualInterventionAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )
    bad_type = await run_manual_intervention_live_test(
        config(tmp_path, order_type="GTC"),
        adapter=FakeManualInterventionAdapter(),
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )

    assert above_one.final_result == "BLOCKED"
    assert bad_type.final_result == "BLOCKED"
    assert "above 1.00" in above_one.blocking_reasons[0]
    assert "FAK or FOK" in bad_type.blocking_reasons[0]


@pytest.mark.asyncio
async def test_manual_order_cancel_detected_and_pauses(tmp_path: Path) -> None:
    adapter = FakeManualInterventionAdapter()

    report = await run_manual_intervention_live_test(
        config(
            tmp_path,
            settings=live_settings(),
            dry_run=False,
            acknowledgement=True,
            manual_ack=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )

    assert report.final_result == "MANUAL_INTERVENTION_DETECTED"
    assert report.order_submitted is True
    assert report.live_attempt_count == 1
    assert len(adapter.submit_calls) == 1
    assert report.manual_intervention_detected is True
    assert report.trading_should_pause is True
    assert report.requires_manual_acknowledgement is True
    assert report.safety_pause_activated is True
    assert "MANUAL_ORDER_CANCEL_DETECTED" in report.reconciliation_event_types
    assert report.detection_latency_seconds is not None


@pytest.mark.asyncio
async def test_manual_position_close_detected_and_no_retry(tmp_path: Path) -> None:
    adapter = FakeManualInterventionAdapter()
    adapter.response = {
        "ok": True,
        "order_id": "order-1",
        "status": "matched",
        "takingAmount": "1",
    }
    adapter.open_order_sequence = [[], []]
    adapter.position_sequence = [
        [SimpleNamespace(token_id="token-yes", size="1")],
        [],
    ]

    report = await run_manual_intervention_live_test(
        config(
            tmp_path,
            settings=live_settings(),
            dry_run=False,
            acknowledgement=True,
            manual_ack=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )

    assert report.final_result == "MANUAL_INTERVENTION_DETECTED"
    assert report.live_attempt_count == 1
    assert len(adapter.submit_calls) == 1
    assert "MANUAL_POSITION_CLOSE_DETECTED" in report.reconciliation_event_types
    assert "No retry" in report.no_retry_statement
    assert "No automatic cancel" in report.no_cancel_statement


@pytest.mark.asyncio
async def test_no_manual_intervention_detected_within_window(tmp_path: Path) -> None:
    adapter = FakeManualInterventionAdapter()
    adapter.open_order_sequence = [
        [],
        [SimpleNamespace(id="order-1", status="live", token_id="token-yes")],
        [SimpleNamespace(id="order-1", status="live", token_id="token-yes")],
        [SimpleNamespace(id="order-1", status="live", token_id="token-yes")],
    ]

    report = await run_manual_intervention_live_test(
        config(
            tmp_path,
            settings=live_settings(),
            dry_run=False,
            acknowledgement=True,
            manual_ack=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )

    assert report.final_result == "NO_MANUAL_INTERVENTION_DETECTED"
    assert report.live_attempt_count == 1
    assert len(adapter.submit_calls) == 1
    assert report.manual_intervention_detected is False
    assert report.trading_should_pause is False


@pytest.mark.asyncio
async def test_report_is_sanitized(tmp_path: Path) -> None:
    adapter = FakeManualInterventionAdapter()

    report = await run_manual_intervention_live_test(
        config(
            tmp_path,
            settings=live_settings(token="579765220468709143532104041169579525320833054219"),
            token_id="579765220468709143532104041169579525320833054219",
            dry_run=True,
        ),
        adapter=adapter,
        geoblock_check=FakeGeoblockCheck(),
        clock=fixed_clock,
        sleeper=no_sleep,
    )

    rendered = render_manual_intervention_live_test(
        report,
        "json",
    ) + render_manual_intervention_live_test(report, "markdown")
    assert "not-for-output" not in rendered
    assert "0xfunder" not in rendered
    assert "579765220468709143532104041169579525320833054219" not in rendered
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in rendered


def test_module_does_not_reference_live_cancel_or_retry() -> None:
    source = inspect.getsource(module)

    assert "cancel_order" not in source
    assert "cancel_market_orders" not in source
    assert "while True" not in source
