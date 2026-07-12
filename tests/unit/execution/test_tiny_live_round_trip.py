from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.config.settings import AppSettings, TradingMode
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    MarketSummary,
    OrderBookLevel,
)
from polysia.execution.tiny_live_round_trip import (
    AUTHORIZATION_ID,
    RoundTripOrderManager,
    TinyLiveRoundTripConfig,
    TinyLiveRoundTripError,
    _assert_market_ready,
    normalize_exit_target,
    run_tiny_live_round_trip,
)
from polysia.monitoring.tiny_live_round_trip_report import (
    render_tiny_live_round_trip,
    write_tiny_live_round_trip_reports,
)
from polysia.risk.kill_switch import KillSwitch
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import (
    FillRepository,
    LedgerEventRepository,
    LiveEntryAttemptRepository,
    LiveOrderCheckpointRepository,
    OrderRepository,
    PositionRepository,
    StrategyRegistryRepository,
)

NOW = datetime(2026, 7, 11, 12, tzinfo=UTC)
COMMIT = "a" * 40


class FakeMarketPort:
    def __init__(self, *, minimum_size: str = "1", end_seconds: int = 600) -> None:
        self.details = market_details(end_seconds=end_seconds)
        self.books = {
            "token-up": order_book(
                "token-up",
                bid="0.58",
                ask="0.60",
                minimum_size=minimum_size,
            ),
            "token-down": order_book(
                "token-down",
                bid="0.38",
                ask="0.40",
                minimum_size=minimum_size,
            ),
        }
        self.book_calls: list[str] = []

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
        assert query == "Bitcoin Up or Down 15m"
        return [MarketSummary(**self.details.model_dump())]

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        assert slug == self.details.slug
        return self.details

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        self.book_calls.append(token_id)
        return self.books[token_id]


class StaleOnRefreshMarketPort(FakeMarketPort):
    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        book = await super().get_order_book(token_id)
        if len(self.book_calls) > 2:
            return book.model_copy(update={"timestamp": NOW - timedelta(seconds=6)})
        return book


class BookTimestampAfterRunStartMarketPort(FakeMarketPort):
    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        book = await super().get_order_book(token_id)
        return book.model_copy(update={"timestamp": NOW + timedelta(seconds=2)})


class AdvancingClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return NOW if self.calls == 1 else NOW + timedelta(seconds=2)


class CandidateFallbackMarketPort(FakeMarketPort):
    def __init__(self) -> None:
        super().__init__()
        self.first = self.details.model_copy(
            update={
                "id": "market-first",
                "slug": "btc-updown-15m-first",
                "end_date": NOW + timedelta(minutes=8),
            }
        )
        self.second = self.details.model_copy(
            update={
                "id": "market-second",
                "slug": "btc-updown-15m-second",
                "end_date": NOW + timedelta(minutes=10),
            }
        )
        self.current_slug = self.first.slug

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
        del query, page_size
        return [
            MarketSummary(**self.first.model_dump()),
            MarketSummary(**self.second.model_dump()),
        ]

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        self.current_slug = slug
        return self.first if slug == self.first.slug else self.second

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        book = await super().get_order_book(token_id)
        minimum = Decimal("20") if self.current_slug == self.first.slug else Decimal("1")
        return book.model_copy(update={"minimum_order_size": minimum})


class FakeExecutionPort:
    def __init__(
        self,
        *,
        entry: Literal["reject", "no_fill", "fill", "error"] = "fill",
        exit_order: Literal["open", "reject", "fill", "partial", "error"] = "open",
        position_size: str = "16.666666",
    ) -> None:
        self.connected = False
        self.closed = False
        self.entry_mode = entry
        self.exit_mode = exit_order
        self.position_size = Decimal(position_size)
        self.entry_attempts: list[dict[str, Any]] = []
        self.exit_attempts: list[dict[str, Any]] = []
        self.entry_filled = False
        self.exit_submitted = False
        self.exit_filled_size = Decimal("0")
        self.collateral_read_count = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True
        self.connected = False

    def identity(self) -> dict[str, object]:
        return {
            "active_wallet_source": "funder",
            "configured_signature_type": 3,
            "funder_configured": True,
            "legacy_wallet_configured": False,
            "sdk_signature_type": 3,
            "signature_type_matches_sdk": True,
            "signer_configured": True,
            "wallet_type": "DEPOSIT_WALLET",
        }

    async def get_balance_allowance(
        self,
        *,
        asset_type: Literal["COLLATERAL", "CONDITIONAL"],
        token_id: str | None = None,
    ) -> dict[str, object]:
        if asset_type == "COLLATERAL":
            self.collateral_read_count += 1
            return {"balance": 20_000_000, "allowances": {"exchange": 20_000_000}}
        balance = (
            int(self.position_size * Decimal("1000000"))
            if self.entry_filled and token_id == "token-up"
            else 0
        )
        return {"balance": balance, "allowances": {"exchange": 20_000_000}}

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        del order_id, market
        if (
            self.exit_submitted
            and self.exit_mode in {"open", "partial"}
            and token_id == "token-up"
        ):
            return [
                {
                    "id": "exit-1",
                    "market": "condition-1",
                    "status": "LIVE",
                    "token_id": "token-up",
                }
            ]
        return []

    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        del market, size_threshold
        if not self.entry_filled:
            return []
        remaining = self.position_size - self.exit_filled_size
        if remaining <= 0:
            return []
        return [
            {
                "condition_id": "condition-1",
                "size": str(remaining),
                "token_id": "token-up",
            }
        ]

    async def list_account_trades(
        self,
        *,
        token_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        del market
        if self.entry_filled and token_id == "token-up":
            trades = [
                {
                    "maker_orders": [],
                    "price": "0.60",
                    "size": "16.666666",
                    "status": "CONFIRMED",
                    "taker_order_id": "entry-1",
                }
            ]
            if self.exit_filled_size > 0:
                trades.append(
                    {
                        "maker_orders": [],
                        "price": "0.66",
                        "size": str(self.exit_filled_size),
                        "status": "CONFIRMED",
                        "taker_order_id": "exit-1",
                    }
                )
            return trades
        return []

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        self.entry_attempts.append(kwargs)
        if self.entry_mode == "error":
            raise RuntimeError("unknown submit state")
        if self.entry_mode == "reject":
            return {"ok": False, "message": "venue rejected", "status": "REJECTED"}
        if self.entry_mode == "fill":
            self.entry_filled = True
        return {"ok": True, "order_id": "entry-1", "status": "MATCHED"}

    async def place_limit_order(self, **kwargs: Any) -> dict[str, object]:
        self.exit_attempts.append(kwargs)
        self.exit_submitted = True
        if self.exit_mode == "error":
            raise RuntimeError("unknown exit state")
        if self.exit_mode == "reject":
            return {"ok": False, "message": "exit rejected", "status": "REJECTED"}
        if self.exit_mode == "fill":
            self.exit_filled_size = self.position_size
            return {"ok": True, "order_id": "exit-1", "status": "MATCHED"}
        if self.exit_mode == "partial":
            self.exit_filled_size = Decimal("0.5")
            return {"ok": True, "order_id": "exit-1", "status": "LIVE"}
        return {"ok": True, "order_id": "exit-1", "status": "LIVE"}


class CrashAfterConfirmedFillExecutionPort(FakeExecutionPort):
    async def list_positions(
        self,
        *,
        market: tuple[str, ...] | None = None,
        size_threshold: float | None = None,
    ) -> list[Any]:
        if self.entry_filled:
            raise RuntimeError("simulated process interruption after confirmed fill")
        return await super().list_positions(market=market, size_threshold=size_threshold)


class FakeGeoblock:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked
        self.check_count = 0

    async def check(self) -> GeoblockStatus:
        self.check_count += 1
        return GeoblockStatus(
            status="blocked" if self.blocked else "allowed",
            checked_at=NOW,
            blocked=self.blocked,
        )


def market_details(*, end_seconds: int = 600) -> MarketDetails:
    return MarketDetails(
        id="market-1",
        slug="btc-updown-15m-123",
        question="Bitcoin Up or Down?",
        active=True,
        closed=False,
        accepting_orders=True,
        start_date=NOW - timedelta(minutes=5),
        end_date=NOW + timedelta(seconds=end_seconds),
        condition_id="condition-1",
        enable_order_book=True,
        archived=False,
        liquidity=Decimal("1000"),
        outcomes=(
            MarketOutcomeSummary(label="Up", token_id="token-up"),
            MarketOutcomeSummary(label="Down", token_id="token-down"),
        ),
        fee_schedule=MarketFeeSchedule(enabled=False, taker_only=True),
    )


def order_book(
    token_id: str,
    *,
    bid: str,
    ask: str,
    minimum_size: str,
) -> MarketOrderBookSnapshot:
    return MarketOrderBookSnapshot(
        token_id=token_id,
        market_id="condition-1",
        timestamp=NOW,
        bids=(OrderBookLevel(price=Decimal(bid), size=Decimal("5")),),
        asks=(OrderBookLevel(price=Decimal(ask), size=Decimal("25")),),
        minimum_order_size=Decimal(minimum_size),
        tick_size=Decimal("0.01"),
    )


def live_settings() -> AppSettings:
    return AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_SIGNATURE_TYPE=3,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-up",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="20",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="10",
        **{"POLYMARKET_PRIVATE_KEY": "unit-test-private-key"},
    )


def config(
    tmp_path: Path,
    *,
    dry_run: bool,
    run_id: str,
) -> TinyLiveRoundTripConfig:
    return TinyLiveRoundTripConfig(
        settings=live_settings(),
        project_root=tmp_path,
        output_dir=tmp_path / "evidence" / run_id,
        database_path=tmp_path / "round-trip.sqlite3",
        dry_run=dry_run,
        acknowledgement=not dry_run,
        verified_ci_commit=COMMIT if not dry_run else None,
        run_id=run_id,
        fill_poll_attempts=1,
        fill_poll_interval_seconds=0,
    )


def fake_git(root: Path, command: tuple[str, ...]) -> str:
    del root
    values = {
        ("git", "rev-parse", "HEAD"): COMMIT,
        ("git", "branch", "--show-current"): "main",
        ("git", "rev-parse", "origin/main"): COMMIT,
        ("git", "status", "--porcelain", "--untracked-files=no"): "",
    }
    return values[command]


@pytest.mark.asyncio
async def test_dry_run_reads_preflight_and_never_submits(tmp_path: Path) -> None:
    adapter = FakeExecutionPort()
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=True, run_id="dry-run"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "NO_TRADE"
    assert report.risk_decision["approved"] is True
    assert report.account_snapshot["available_balance"] == "20"
    assert report.live_entry_attempt_count == 0
    assert adapter.entry_attempts == []
    assert adapter.exit_attempts == []


@pytest.mark.asyncio
async def test_real_entry_fill_places_one_actual_position_sized_exit(tmp_path: Path) -> None:
    adapter = FakeExecutionPort()
    geoblock = FakeGeoblock()
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="filled"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=geoblock,
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "ENTRY_FILLED_EXIT_OPEN"
    assert report.live_entry_attempt_count == 1
    assert report.entry_order["client_order_id"] == "filled:entry"
    assert report.exit_order["client_order_id"] == "filled:exit"
    assert len(adapter.entry_attempts) == 1
    assert adapter.collateral_read_count == 2
    assert geoblock.check_count == 2
    assert adapter.entry_attempts[0]["amount"] == Decimal("10.00")
    assert adapter.entry_attempts[0]["max_spend"] == Decimal("10.00")
    assert adapter.entry_attempts[0]["order_type"] == "FOK"
    assert len(adapter.exit_attempts) == 1
    assert adapter.exit_attempts[0]["size"] == Decimal("16.666666")
    assert adapter.exit_attempts[0]["price"] == Decimal("0.66")
    assert report.reconciliation["status"] == "ready"
    assert len(report.ledger_entries) == 2

    with SQLiteDatabase(tmp_path / "round-trip.sqlite3") as database:
        events = LedgerEventRepository(database.connection).list_for_run("filled")
        assert len(events) == 2
        attempt = LiveEntryAttemptRepository(database.connection).get(AUTHORIZATION_ID)
        assert attempt is not None
        assert attempt["state"] == "ENTRY_FILLED_EXIT_OPEN"
        checkpoints = LiveOrderCheckpointRepository(database.connection).list_for_run(
            "filled"
        )
        assert {item["phase"] for item in checkpoints} >= {
            "ENTRY_RESPONSE",
            "ENTRY_FILL_CONFIRMED",
            "ENTRY_POSITION_RECONCILED",
            "EXIT_RESPONSE",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry_mode", "expected"),
    [("reject", "ENTRY_NOT_FILLED"), ("no_fill", "ENTRY_NOT_FILLED")],
)
async def test_entry_rejection_or_no_fill_never_retries_or_exits(
    tmp_path: Path,
    entry_mode: Literal["reject", "no_fill"],
    expected: str,
) -> None:
    adapter = FakeExecutionPort(entry=entry_mode)
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id=entry_mode),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == expected
    assert report.live_entry_attempt_count == 1
    assert len(adapter.entry_attempts) == 1
    assert adapter.exit_attempts == []
    assert report.reconciliation["status"] == "ready"


@pytest.mark.asyncio
async def test_exit_rejection_preserves_and_reconciles_position(tmp_path: Path) -> None:
    adapter = FakeExecutionPort(exit_order="reject")
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="exit-reject"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "ENTRY_FILLED_EXIT_REJECTED"
    assert report.position_state["available_size"] == "16.666666"
    assert report.reconciliation["status"] == "ready"
    assert len(adapter.exit_attempts) == 1


@pytest.mark.asyncio
async def test_immediate_exit_fill_records_completed_round_trip(tmp_path: Path) -> None:
    adapter = FakeExecutionPort(exit_order="fill")
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="completed"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "COMPLETED_ROUND_TRIP"
    assert report.position_state["available_size"] == "0"
    assert report.exit_order["actual_fill"] is not None
    assert report.fees["actual_total_fees"] == "0.00000"
    assert len(report.ledger_entries) == 4

    with SQLiteDatabase(tmp_path / "round-trip.sqlite3") as database:
        assert len(LedgerEventRepository(database.connection).list_for_run("completed")) == 4
        performance = StrategyRegistryRepository(database.connection).get_performance(
            "btc-15m-favorite-take-profit",
            "0.4.0",
        )
        assert performance is not None
        assert performance.trade_count == 2
        assert performance.fees == Decimal("0.00000")


@pytest.mark.asyncio
async def test_partial_exit_fill_retains_remaining_position_and_open_order(
    tmp_path: Path,
) -> None:
    adapter = FakeExecutionPort(exit_order="partial")
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="partial-exit"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "ENTRY_FILLED_EXIT_OPEN"
    assert report.position_state["available_size"] == "16.166666"
    assert report.position_state["exit_filled_size"] == "0.5"
    assert report.exit_order["status"] == "PARTIALLY_FILLED_OPEN"
    assert report.reconciliation["status"] == "ready"
    assert len(report.ledger_entries) == 4

    with SQLiteDatabase(tmp_path / "round-trip.sqlite3") as database:
        position = PositionRepository(database.connection).get("token-up")
        assert position is not None
        assert position.size == Decimal("16.166666")
        assert position.realized_pnl == Decimal("0.03")
        assert len(LedgerEventRepository(database.connection).list_for_run("partial-exit")) == 4


@pytest.mark.asyncio
async def test_persistent_authorization_claim_blocks_second_entry_attempt(tmp_path: Path) -> None:
    first_adapter = FakeExecutionPort(entry="reject")
    await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="first"),
        market_port=FakeMarketPort(),
        execution_port=first_adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )
    second_adapter = FakeExecutionPort(entry="fill")
    second = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="second"),
        market_port=FakeMarketPort(),
        execution_port=second_adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert second.final_result == "NO_TRADE"
    assert "one-entry-attempt" in str(second.stop_reason)
    assert second_adapter.entry_attempts == []


@pytest.mark.asyncio
async def test_market_minimum_above_cap_is_no_trade_without_account_or_order(
    tmp_path: Path,
) -> None:
    adapter = FakeExecutionPort()
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="minimum"),
        market_port=FakeMarketPort(minimum_size="20"),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "NO_TRADE"
    assert "minimum order size" in str(report.stop_reason)
    assert adapter.entry_attempts == []
    assert adapter.connected is False


@pytest.mark.asyncio
async def test_geoblock_denial_stops_before_entry(tmp_path: Path) -> None:
    adapter = FakeExecutionPort()
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="geoblocked"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(blocked=True),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "NO_TRADE"
    assert "geoblock" in str(report.stop_reason)
    assert adapter.entry_attempts == []


@pytest.mark.asyncio
async def test_partial_or_unavailable_filled_position_activates_safety_stop(
    tmp_path: Path,
) -> None:
    adapter = FakeExecutionPort(position_size="1.5")
    kill_switch = KillSwitch()
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="position-mismatch"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        kill_switch=kill_switch,
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "SAFETY_STOP"
    assert report.reconciliation["status"] == "blocked"
    assert report.reconciliation["safety_pause_activated"] is True
    assert kill_switch.is_active() is True
    assert adapter.exit_attempts == []


@pytest.mark.asyncio
async def test_non_allowlisted_dynamic_token_is_rejected_by_risk(tmp_path: Path) -> None:
    base = config(tmp_path, dry_run=False, run_id="allowlist")
    settings = live_settings().model_copy(
        update={"polymarket_live_token_allowlist": ("different-token",)}
    )
    adapter = FakeExecutionPort()
    report = await run_tiny_live_round_trip(
        replace(base, settings=settings),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "NO_TRADE"
    assert "allowlisted" in str(report.stop_reason)
    assert adapter.entry_attempts == []


@pytest.mark.asyncio
async def test_refresh_rejects_books_that_became_stale_during_preflight(
    tmp_path: Path,
) -> None:
    adapter = FakeExecutionPort()
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="refresh-stale"),
        market_port=StaleOnRefreshMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "NO_TRADE"
    assert "stale" in str(report.stop_reason)
    assert adapter.entry_attempts == []


@pytest.mark.asyncio
async def test_discovery_uses_fresh_time_for_books_fetched_after_run_start(
    tmp_path: Path,
) -> None:
    clock = AdvancingClock()
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=True, run_id="fresh-discovery-clock"),
        market_port=BookTimestampAfterRunStartMarketPort(),
        execution_port=FakeExecutionPort(),
        geoblock_port=FakeGeoblock(),
        clock=clock,
        git_reader=fake_git,
    )

    assert report.strategy_decision["status"] == "TRADE"
    assert report.risk_decision["approved"] is True
    assert clock.calls > 1


@pytest.mark.asyncio
async def test_discovery_skips_invalid_candidate_before_selecting_one_market(
    tmp_path: Path,
) -> None:
    adapter = FakeExecutionPort(entry="reject")
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="candidate-fallback"),
        market_port=CandidateFallbackMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.market_snapshot["market_id"] == "market-second"
    assert len(adapter.entry_attempts) == 1


@pytest.mark.asyncio
async def test_confirmed_fill_is_durable_before_next_external_read(
    tmp_path: Path,
) -> None:
    adapter = CrashAfterConfirmedFillExecutionPort()
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        await run_tiny_live_round_trip(
            config(tmp_path, dry_run=False, run_id="crash-checkpoint"),
            market_port=FakeMarketPort(),
            execution_port=adapter,
            geoblock_port=FakeGeoblock(),
            clock=lambda: NOW,
            git_reader=fake_git,
        )

    with SQLiteDatabase(tmp_path / "round-trip.sqlite3") as database:
        assert OrderRepository(database.connection).get("entry-1") is not None
        assert FillRepository(database.connection).get("crash-checkpoint:entry") is not None
        assert (
            len(
                LedgerEventRepository(database.connection).list_for_run(
                    "crash-checkpoint"
                )
            )
            == 2
        )
        phases = {
            item["phase"]
            for item in LiveOrderCheckpointRepository(database.connection).list_for_run(
                "crash-checkpoint"
            )
        }
        assert {"ENTRY_RESPONSE", "ENTRY_FILL_CONFIRMED"} <= phases

    restarted_adapter = FakeExecutionPort()
    restarted_report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id="crash-checkpoint"),
        market_port=FakeMarketPort(),
        execution_port=restarted_adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert restarted_report.final_result == "NO_TRADE"
    assert "one-entry-attempt limit reached" in str(restarted_report.stop_reason)
    assert restarted_adapter.entry_attempts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry_mode", "exit_mode"),
    [("error", "open"), ("fill", "error")],
)
async def test_unknown_submission_state_stops_without_retry(
    tmp_path: Path,
    entry_mode: Literal["error", "fill"],
    exit_mode: Literal["open", "error"],
) -> None:
    adapter = FakeExecutionPort(entry=entry_mode, exit_order=exit_mode)
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=False, run_id=f"{entry_mode}-{exit_mode}"),
        market_port=FakeMarketPort(),
        execution_port=adapter,
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )

    assert report.final_result == "SAFETY_STOP"
    assert report.live_entry_attempt_count == 1
    assert len(adapter.entry_attempts) == 1
    assert len(adapter.exit_attempts) <= 1
    assert report.reconciliation["status"] == "ready"


def test_target_rounding_and_maximum_price_rejection() -> None:
    assert normalize_exit_target(Decimal("0.55"), tick_size=Decimal("0.01")) == Decimal(
        "0.61"
    )
    assert normalize_exit_target(Decimal("0.91"), tick_size=Decimal("0.01")) is None


def test_market_near_expiry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TinyLiveRoundTripError, match="remaining time"):
        _assert_market_ready(
            market_details(end_seconds=179),
            config=config(tmp_path, dry_run=True, run_id="expiry"),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_report_writer_redacts_sensitive_values(tmp_path: Path) -> None:
    report = await run_tiny_live_round_trip(
        config(tmp_path, dry_run=True, run_id="redaction"),
        market_port=FakeMarketPort(),
        execution_port=FakeExecutionPort(),
        geoblock_port=FakeGeoblock(),
        clock=lambda: NOW,
        git_reader=fake_git,
    )
    unsafe = replace(
        report,
        entry_order={
            "private_key": "unit-test-private-key",
            "wallet_address": "0x1111111111111111111111111111111111111111",
        },
    )
    rendered = render_tiny_live_round_trip(unsafe, "json")
    paths = write_tiny_live_round_trip_reports(unsafe, tmp_path / "reports")

    assert "unit-test-private-key" not in rendered
    assert "0x1111111111111111111111111111111111111111" not in rendered
    assert "<redacted>" in rendered
    assert paths["json"].is_file()
    assert paths["markdown"].is_file()


@pytest.mark.asyncio
async def test_order_manager_claim_is_written_before_adapter_submission(tmp_path: Path) -> None:
    adapter = FakeExecutionPort(entry="reject")
    with SQLiteDatabase(tmp_path / "claim.sqlite3") as database:
        attempts = LiveEntryAttemptRepository(database.connection)
        manager = RoundTripOrderManager(
            adapter=adapter,
            attempts=attempts,
            checkpoints=LiveOrderCheckpointRepository(database.connection),
            authorization_id="auth",
            run_id="run",
            strategy_id="strategy",
            market_id="market",
            clock=lambda: NOW,
        )
        from polysia.execution.intents import OrderIntent

        await manager.submit_entry(
            OrderIntent(
                strategy_id="strategy",
                token_id="token-up",
                side="BUY",
                price=Decimal("0.60"),
                size=Decimal("1"),
                reason="test",
                confidence=Decimal("1"),
            )
        )
        assert attempts.get("auth") is not None
        with pytest.raises(TinyLiveRoundTripError, match="one-entry-attempt"):
            await manager.submit_entry(
                OrderIntent(
                    strategy_id="strategy",
                    token_id="token-up",
                    side="BUY",
                    price=Decimal("0.60"),
                    size=Decimal("1"),
                    reason="test",
                    confidence=Decimal("1"),
                )
            )
