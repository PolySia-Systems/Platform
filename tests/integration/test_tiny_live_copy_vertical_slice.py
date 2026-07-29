from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.application.ports.copytrading import (
    LeaderInventorySnapshot,
    LeaderMarketMetadata,
    LeaderTradeReadPage,
)
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
)
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    OrderBookLevel,
)
from polysia.execution.tiny_live_copy import TinyLiveCopyConfig, run_tiny_live_copy

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
CONDITION = "0x" + ("a" * 64)
TOKEN = "111111"
SLUG = f"btc-updown-15m-{int(NOW.timestamp())}"


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Source:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.baseline_trade_reads = 102

    async def read_inventory(self, leader_id: str) -> LeaderInventorySnapshot:
        return LeaderInventorySnapshot(
            leader_id=leader_id,
            positions={},
            observed_at=self.clock(),
            evidence_digest=f"sha256:{leader_id}",
        )

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 100,
        checkpoint: object | None = None,
    ) -> LeaderTradeReadPage:
        del start_at, end_at, page_size, checkpoint
        if self.baseline_trade_reads > 0:
            self.baseline_trade_reads -= 1
            events: tuple[LeaderTradeEvent, ...] = ()
        elif leader_id == "candidate-001":
            events = (
                LeaderTradeEvent(
                    event_id="event-1",
                    source_id="fixture",
                    leader_id=leader_id,
                    market_reference=CONDITION,
                    outcome_reference=TOKEN,
                    trade_action=LeaderTradeAction.BUY,
                    position_effect=LeaderPositionEffect.UNKNOWN,
                    executed_price=Decimal("0.50"),
                    executed_size=Decimal("5"),
                    executed_at=self.clock() - timedelta(seconds=1),
                    observed_at=self.clock(),
                    external_evidence_reference="sha256:evidence",
                ),
            )
        else:
            events = ()
        return LeaderTradeReadPage(
            events=events,
            next_checkpoint=None,
            raw_count=len(events),
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )

    def market_metadata(
        self,
        market_reference: str,
        outcome_reference: str,
    ) -> LeaderMarketMetadata:
        return LeaderMarketMetadata(
            market_reference=market_reference,
            outcome_reference=outcome_reference,
            external_slug=SLUG,
            outcome_label="Up",
            starts_at=NOW,
            ends_at=NOW + timedelta(minutes=10),
        )


class MarketPort:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.market = MarketDetails(
            id="market-1",
            slug=SLUG,
            question="Bitcoin Up or Down?",
            active=True,
            closed=False,
            accepting_orders=True,
            end_date=NOW + timedelta(minutes=10),
            outcomes=(
                MarketOutcomeSummary(
                    label="Up",
                    token_id=TOKEN,
                    price=Decimal("0.50"),
                ),
                MarketOutcomeSummary(
                    label="Down",
                    token_id="222222",
                    price=Decimal("0.50"),
                ),
            ),
            condition_id=CONDITION,
            enable_order_book=True,
            archived=False,
            start_date=NOW,
            fee_schedule=MarketFeeSchedule(enabled=False),
        )

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        assert slug == SLUG
        return self.market

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        assert token_id == TOKEN
        return MarketOrderBookSnapshot(
            token_id=TOKEN,
            market_id=CONDITION,
            timestamp=self.clock(),
            bids=(OrderBookLevel(price=Decimal("0.46"), size=Decimal("20")),),
            asks=(OrderBookLevel(price=Decimal("0.50"), size=Decimal("20")),),
            minimum_order_size=Decimal("5"),
            tick_size=Decimal("0.01"),
        )


class ExecutionPort:
    def __init__(self) -> None:
        self.connected = False
        self.entry_submitted = False
        self.entry_open = False
        self.exit_open = False
        self.limit_calls: list[dict[str, Any]] = []
        self.user_stream_probes = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def read_clock_drift(self) -> Decimal:
        return Decimal("0")

    def identity(self) -> dict[str, object]:
        return {
            "active_wallet_source": "funder",
            "funder_configured": True,
            "signature_type_matches_sdk": True,
            "signer_configured": True,
        }

    async def get_balance_allowance(self, **kwargs: Any) -> dict[str, object]:
        if kwargs["asset_type"] == "COLLATERAL":
            return {
                "allowances": {"exchange": 10_000_000},
                "balance": 4_000_000,
            }
        return {
            "allowances": {"exchange": 10_000_000},
            "balance": 5_000_000 if self.entry_submitted else 0,
        }

    async def get_open_orders(self, **kwargs: Any) -> list[Any]:
        order_id = kwargs.get("order_id")
        orders = []
        if self.entry_open:
            orders.append({"id": "entry", "token_id": TOKEN})
        if self.exit_open:
            orders.append({"id": "exit", "token_id": TOKEN})
        if order_id is None:
            return orders
        return [order for order in orders if order["id"] == order_id]

    async def get_order(self, *, order_id: str) -> Any | None:
        return {"id": order_id}

    async def list_positions(self, **kwargs: Any) -> list[Any]:
        if not self.entry_submitted:
            return []
        return [{"condition_id": CONDITION, "size": "5", "token_id": TOKEN}]

    async def list_account_trades(self, **kwargs: Any) -> list[Any]:
        if not self.entry_submitted:
            return []
        return [
            {
                "maker_orders": [
                    {
                        "matched_amount": "5",
                        "order_id": "entry",
                        "price": "0.47",
                    }
                ],
                "price": "0.47",
                "status": "CONFIRMED",
                "taker_order_id": "other",
            }
        ]

    async def place_limit_order(self, **kwargs: Any) -> dict[str, object]:
        self.limit_calls.append(dict(kwargs))
        if kwargs["side"] == "BUY":
            assert kwargs["post_only"] is True
            assert kwargs["expiration"] is not None
            self.entry_submitted = True
            self.entry_open = True
            return {"ok": True, "order_id": "entry", "status": "LIVE"}
        assert kwargs["side"] == "SELL"
        assert kwargs["price"] == Decimal("0.52")
        assert kwargs["size"] == Decimal("5")
        self.exit_open = True
        return {"ok": True, "order_id": "exit", "status": "LIVE"}

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("leader-close FOK is not expected in this slice")

    async def cancel_order(self, *, order_id: str) -> dict[str, object]:
        if order_id == "entry":
            self.entry_open = False
        elif order_id == "exit":
            self.exit_open = False
        return {"cancelled": [order_id]}

    async def cancel_all(self) -> dict[str, object]:
        self.entry_open = False
        self.exit_open = False
        return {"cancelled": True}

    async def probe_user_stream(self, *, market: str | None = None) -> None:
        del market
        self.user_stream_probes += 1


class UnfilledExecutionPort(ExecutionPort):
    async def list_positions(self, **kwargs: Any) -> list[Any]:
        del kwargs
        return []

    async def list_account_trades(self, **kwargs: Any) -> list[Any]:
        del kwargs
        return []


class Geoblock:
    async def check(self) -> GeoblockStatus:
        return GeoblockStatus(status="allowed", checked_at=NOW, blocked=False)


def _candidate_file(path: Path) -> Path:
    candidate_path = path / "candidates.txt"
    candidate_path.write_text(
        "\n".join(f"0x{index:040x}" for index in range(1, 103)) + "\n",
        encoding="utf-8",
    )
    return candidate_path


@pytest.mark.asyncio
async def test_complete_fixture_dry_run_never_submits_an_order(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    source = Source(clock)
    market = MarketPort(clock)
    execution = ExecutionPort()
    settings = AppSettings(
        _env_file=None,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id="tiny-live-copy-20260729T115959Z",
            dry_run=True,
            maximum_poll_cycles=1,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.classification == "DRY_RUN_BOUNDED_COMPLETE"
    assert report.total_entry_attempts == 0
    assert execution.limit_calls == []


@pytest.mark.asyncio
async def test_fixture_vertical_slice_proves_risk_execution_partial_fill_and_tp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    source = Source(clock)
    market = MarketPort(clock)
    execution = ExecutionPort()
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )

    report = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=_candidate_file(tmp_path),
            run_id="tiny-live-copy-20260729T120000Z",
            dry_run=False,
            acknowledgement=True,
            verified_ci_commit="a" * 40,
            maximum_poll_cycles=2,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report.classification == "DRY_RUN_BOUNDED_COMPLETE"
    assert report.total_entry_attempts == 1
    assert report.completed_live_cycles == 0
    assert report.state == "EXIT_PENDING"
    assert [call["side"] for call in execution.limit_calls] == ["BUY", "SELL"]
    assert execution.limit_calls[0]["post_only"] is True
    assert execution.limit_calls[0]["size"] == Decimal("5")
    assert execution.limit_calls[1]["size"] == Decimal("5")
    assert execution.user_stream_probes >= 2
    assert "0x0000000000000000000000000000000000000001" not in str(
        report.to_dict()
    )

    restarted = await run_tiny_live_copy(
        TinyLiveCopyConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            database_path=tmp_path / "state.sqlite3",
            candidate_file=tmp_path / "candidates.txt",
            run_id="tiny-live-copy-20260729T120000Z",
            dry_run=False,
            acknowledgement=True,
            verified_ci_commit="a" * 40,
            maximum_poll_cycles=1,
            delete_candidate_file_on_terminal=False,
        ),
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert restarted.state == "EXIT_PENDING", restarted.to_dict()
    assert restarted.total_entry_attempts == 1
    assert [call["side"] for call in execution.limit_calls] == ["BUY", "SELL"]


@pytest.mark.asyncio
async def test_pending_entry_restart_never_submits_a_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polysia.execution.tiny_live_copy._assert_synchronized_main",
        lambda config, git_commit: None,
    )
    clock = MutableClock()
    source = Source(clock)
    market = MarketPort(clock)
    execution = UnfilledExecutionPort()
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_PRIVATE_KEY="fixture-key",
        POLYMARKET_SIGNATURE_TYPE=3,
    )
    config = TinyLiveCopyConfig(
        settings=settings,
        project_root=tmp_path,
        output_dir=tmp_path / "reports",
        database_path=tmp_path / "state.sqlite3",
        candidate_file=_candidate_file(tmp_path),
        run_id="tiny-live-copy-20260729T120001Z",
        dry_run=False,
        acknowledgement=True,
        verified_ci_commit="a" * 40,
        maximum_poll_cycles=1,
        delete_candidate_file_on_terminal=False,
    )

    first = await run_tiny_live_copy(
        config,
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )
    restarted = await run_tiny_live_copy(
        config,
        source=source,
        market_port=market,
        execution_port=execution,
        geoblock_port=Geoblock(),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert first.state == "ENTRY_PENDING"
    assert restarted.state == "ENTRY_PENDING"
    assert restarted.total_entry_attempts == 1
    assert [call["side"] for call in execution.limit_calls] == ["BUY"]
