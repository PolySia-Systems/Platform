from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.bus.events import MarketDataEvent
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.market import MarketDetails, MarketOutcomeSummary, MarketSummary
from polysia.execution.intents import OrderIntent
from polysia.monitoring.real_data_shadow_run import (
    RealDataShadowRunConfig,
    build_real_data_shadow_run,
    render_real_data_shadow_run,
    render_real_data_shadow_run_events_jsonl,
)
from polysia.risk.checks import RiskContext, RiskDecision, RiskEngine


class FakePublicAdapter:
    def __init__(self) -> None:
        self.search_calls = 0
        self.get_calls: list[str] = []

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
        self.search_calls += 1
        return [
            MarketSummary(
                id="market-1",
                slug="btc-updown-5m-1783000000",
                active=True,
                closed=False,
                accepting_orders=True,
                end_date=None,
            )
        ]

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        self.get_calls.append(slug)
        return market_details(slug=slug)


class SpyRiskEngine(RiskEngine):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def evaluate(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        self.calls += 1
        return super().evaluate(intent, context)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def settings(*, live_enabled: bool = False) -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.DATA_ONLY,
        LIVE_TRADING_ENABLED=live_enabled,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        POLYMARKET_FUNDER_ADDRESS="0x3333333333333333333333333333333333333333",
        POLYMARKET_WALLET_ADDRESS="0x2222222222222222222222222222222222222222",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )


def config(tmp_path: Path, *, max_events: int = 3) -> RealDataShadowRunConfig:
    return RealDataShadowRunConfig(
        settings=settings(),
        project_root=tmp_path,
        output_dir=tmp_path,
        market_slug="btc-updown-5m-1783000000",
        max_events=max_events,
        strategy="stale-price",
    )


@pytest.mark.asyncio
async def test_real_data_shadow_run_exercises_public_paper_workflow(
    tmp_path: Path,
) -> None:
    risk_engine = SpyRiskEngine()

    report = await build_real_data_shadow_run(
        config(tmp_path),
        public_adapter=FakePublicAdapter(),
        event_source=event_source,
        risk_engine=risk_engine,
        clock=fixed_clock,
    )

    assert report.final_result == "REAL_DATA_SHADOW_HEALTHY"
    assert report.metrics.event_count == 3
    assert report.metrics.orderbook_updates == 3
    assert report.metrics.strategy_intent_count > 0
    assert report.metrics.risk_approval_count > 0
    assert report.metrics.paper_order_count > 0
    assert report.metrics.paper_fill_count > 0
    assert report.metrics.live_broker_used is False
    assert risk_engine.calls > 0


@pytest.mark.asyncio
async def test_real_data_shadow_run_auto_btc_5m_selects_market(tmp_path: Path) -> None:
    adapter = FakePublicAdapter()

    report = await build_real_data_shadow_run(
        RealDataShadowRunConfig(
            settings=settings(),
            project_root=tmp_path,
            output_dir=tmp_path,
            auto_btc_5m=True,
            max_events=1,
            strategy="passive-market-maker",
        ),
        public_adapter=adapter,
        event_source=event_source,
        clock=fixed_clock,
    )

    assert adapter.search_calls == 1
    assert adapter.get_calls == ["btc-updown-5m-1783000000"]
    assert report.metrics.selected_market_slug == "btc-updown-5m-1783000000"
    assert report.metrics.selected_token_configured is True


@pytest.mark.asyncio
async def test_real_data_shadow_run_timeout_warning_does_not_crash(
    tmp_path: Path,
) -> None:
    async def warning_source(
        token_id: str,
        max_events: int,
    ) -> tuple[tuple[MarketDataEvent, ...], tuple[str, ...]]:
        return (), ("Public stream timed out before max-events was reached.",)

    report = await build_real_data_shadow_run(
        config(tmp_path),
        public_adapter=FakePublicAdapter(),
        event_source=warning_source,
        clock=fixed_clock,
    )

    assert report.final_result == "REAL_DATA_SHADOW_WARNING"
    assert report.warnings == ("Public stream timed out before max-events was reached.",)


@pytest.mark.asyncio
async def test_real_data_shadow_run_max_events_stops_correctly(tmp_path: Path) -> None:
    async def noisy_source(
        token_id: str,
        max_events: int,
    ) -> tuple[tuple[MarketDataEvent, ...], tuple[str, ...]]:
        return sample_events(token_id, count=5), ()

    report = await build_real_data_shadow_run(
        config(tmp_path, max_events=2),
        public_adapter=FakePublicAdapter(),
        event_source=noisy_source,
        clock=fixed_clock,
    )

    assert report.metrics.event_count == 2
    assert len(report.events) == 2


@pytest.mark.asyncio
async def test_real_data_shadow_run_blocks_live_enabled(tmp_path: Path) -> None:
    report = await build_real_data_shadow_run(
        RealDataShadowRunConfig(
            settings=settings(live_enabled=True),
            project_root=tmp_path,
            output_dir=tmp_path,
            market_slug="btc-updown-5m-1783000000",
            max_events=1,
        ),
        public_adapter=FakePublicAdapter(),
        event_source=event_source,
        clock=fixed_clock,
    )

    assert report.final_result == "REAL_DATA_SHADOW_FAILED"
    assert "LIVE_TRADING_ENABLED" in report.reasons[0]


@pytest.mark.asyncio
async def test_real_data_shadow_run_reports_are_sanitized(tmp_path: Path) -> None:
    report = await build_real_data_shadow_run(
        config(tmp_path),
        public_adapter=FakePublicAdapter(),
        event_source=event_source,
        clock=fixed_clock,
    )

    rendered = (
        render_real_data_shadow_run(report, "json")
        + render_real_data_shadow_run(report, "markdown")
        + render_real_data_shadow_run_events_jsonl(report)
    )

    assert "not-for-output" not in rendered
    assert "token-secret" not in rendered
    assert "0x2222222222222222222222222222222222222222" not in rendered
    assert "0x3333333333333333333333333333333333333333" not in rendered
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in rendered
    assert "selected_token" in rendered


def test_real_data_shadow_run_event_capture_is_jsonl() -> None:
    event = sample_events("token-secret", count=1)[0]
    report_dict: dict[str, Any] = {
        "event_index": 0,
        "event_type": event.event_type,
        "received_at": event.received_at.isoformat(),
        "selected_token": True,
    }

    line = json.dumps(report_dict, sort_keys=True)

    assert json.loads(line)["selected_token"] is True
    assert "token-secret" not in line


async def event_source(
    token_id: str,
    max_events: int,
) -> tuple[tuple[MarketDataEvent, ...], tuple[str, ...]]:
    return sample_events(token_id, count=max_events), ()


def sample_events(token_id: str, *, count: int) -> tuple[MarketDataEvent, ...]:
    events: list[MarketDataEvent] = []
    for index in range(count):
        if index == 0:
            payload = {
                "asks": [{"price": "0.55", "size": "4"}],
                "bids": [{"price": "0.45", "size": "100"}],
            }
            event_type = "book"
        else:
            payload = {
                "price_change": {
                    "price": str(Decimal("0.55") - Decimal(index) * Decimal("0.001")),
                    "side": "SELL",
                    "size": "100",
                }
            }
            event_type = "price_change"
        events.append(
            MarketDataEvent(
                source="polymarket",
                event_type=event_type,
                token_id=token_id,
                received_at=fixed_clock(),
                exchange_ts=fixed_clock(),
                payload=payload,
                raw_payload={
                    "token_id": token_id,
                    "transaction_hash": (
                        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    ),
                },
            )
        )
    return tuple(events)


def market_details(*, slug: str) -> MarketDetails:
    return MarketDetails(
        id="market-1",
        slug=slug,
        active=True,
        closed=False,
        accepting_orders=True,
        outcomes=(
            MarketOutcomeSummary(label="Up", token_id="token-secret"),
            MarketOutcomeSummary(label="Down", token_id="token-no"),
        ),
    )
