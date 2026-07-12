from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

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
    TinyLiveRoundTripConfig,
    run_tiny_live_round_trip,
)
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import (
    LedgerEventRepository,
    OrderRepository,
    PositionRepository,
    StrategyRegistryRepository,
)

NOW = datetime(2026, 7, 11, 12, tzinfo=UTC)
COMMIT = "b" * 40


class MarketPort:
    def __init__(self) -> None:
        self.market = MarketDetails(
            id="market",
            slug="btc-updown-15m-integration",
            question="Bitcoin Up or Down?",
            active=True,
            closed=False,
            accepting_orders=True,
            start_date=NOW - timedelta(minutes=5),
            end_date=NOW + timedelta(minutes=10),
            condition_id="condition",
            enable_order_book=True,
            archived=False,
            outcomes=(
                MarketOutcomeSummary(label="Up", token_id="up"),
                MarketOutcomeSummary(label="Down", token_id="down"),
            ),
            fee_schedule=MarketFeeSchedule(enabled=False),
        )
        self.books = {
            "up": self._book("up", "0.58", "0.60"),
            "down": self._book("down", "0.38", "0.40"),
        }

    async def search_markets(self, query: str, page_size: int = 20) -> list[MarketSummary]:
        del query, page_size
        return [MarketSummary(**self.market.model_dump())]

    async def get_market_by_slug(self, slug: str) -> MarketDetails:
        assert slug == self.market.slug
        return self.market

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        return self.books[token_id]

    @staticmethod
    def _book(token_id: str, bid: str, ask: str) -> MarketOrderBookSnapshot:
        return MarketOrderBookSnapshot(
            token_id=token_id,
            market_id="condition",
            timestamp=NOW,
            bids=(OrderBookLevel(price=Decimal(bid), size=Decimal("5")),),
            asks=(OrderBookLevel(price=Decimal(ask), size=Decimal("5")),),
            minimum_order_size=Decimal("1"),
            tick_size=Decimal("0.01"),
        )


class ExecutionPort:
    def __init__(self) -> None:
        self.connected = False
        self.filled = False
        self.exit_open = False
        self.entry_calls = 0
        self.exit_calls = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
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

    async def get_balance_allowance(self, **kwargs: Any) -> dict[str, object]:
        if kwargs["asset_type"] == "COLLATERAL":
            return {"balance": 2_000_000, "allowances": {"exchange": 2_000_000}}
        balance = 1_666_666 if self.filled and kwargs.get("token_id") == "up" else 0
        return {"balance": balance, "allowances": {"exchange": 2_000_000}}

    async def get_open_orders(self, **kwargs: Any) -> list[Any]:
        if self.exit_open and kwargs.get("token_id") == "up":
            return [{"id": "exit", "status": "LIVE", "token_id": "up"}]
        return []

    async def list_positions(self, **kwargs: Any) -> list[Any]:
        if not self.filled:
            return []
        return [{"condition_id": "condition", "size": "1.666666", "token_id": "up"}]

    async def list_account_trades(self, **kwargs: Any) -> list[Any]:
        if not self.filled:
            return []
        return [
            {
                "maker_orders": [],
                "price": "0.60",
                "size": "1.666666",
                "status": "CONFIRMED",
                "taker_order_id": "entry",
            }
        ]

    async def place_market_order(self, **kwargs: Any) -> dict[str, object]:
        assert kwargs["max_spend"] == Decimal("1.00")
        self.entry_calls += 1
        self.filled = True
        return {"ok": True, "order_id": "entry", "status": "MATCHED"}

    async def place_limit_order(self, **kwargs: Any) -> dict[str, object]:
        assert kwargs["price"] == Decimal("0.66")
        assert kwargs["size"] == Decimal("1.666666")
        self.exit_calls += 1
        self.exit_open = True
        return {"ok": True, "order_id": "exit", "status": "LIVE"}


class Geoblock:
    async def check(self) -> GeoblockStatus:
        return GeoblockStatus(status="allowed", checked_at=NOW, blocked=False)


def git_reader(root: Path, command: tuple[str, ...]) -> str:
    del root
    return {
        ("git", "rev-parse", "HEAD"): COMMIT,
        ("git", "branch", "--show-current"): "main",
        ("git", "rev-parse", "origin/main"): COMMIT,
        ("git", "status", "--porcelain", "--untracked-files=no"): "",
    }[command]


@pytest.mark.asyncio
async def test_full_registered_risked_persisted_round_trip_slice(tmp_path: Path) -> None:
    database_path = tmp_path / "integration.sqlite3"
    adapter = ExecutionPort()
    settings = AppSettings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0x1111111111111111111111111111111111111111",
        POLYMARKET_SIGNATURE_TYPE=3,
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="up",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="2",
        **{"POLYMARKET_PRIVATE_KEY": "integration-key"},
    )

    report = await run_tiny_live_round_trip(
        TinyLiveRoundTripConfig(
            settings=settings,
            project_root=tmp_path,
            output_dir=tmp_path / "evidence",
            database_path=database_path,
            dry_run=False,
            acknowledgement=True,
            verified_ci_commit=COMMIT,
            run_id="integration-run",
            fill_poll_attempts=1,
            fill_poll_interval_seconds=0,
        ),
        market_port=MarketPort(),
        execution_port=adapter,
        geoblock_port=Geoblock(),
        clock=lambda: NOW,
        git_reader=git_reader,
    )

    assert report.final_result == "ENTRY_FILLED_EXIT_OPEN"
    assert adapter.entry_calls == 1
    assert adapter.exit_calls == 1
    assert report.risk_decision["approved"] is True
    assert report.reconciliation["status"] == "ready"

    with SQLiteDatabase(database_path) as database:
        definitions = StrategyRegistryRepository(database.connection).list_definitions()
        assert definitions[0].strategy_id == "btc-15m-favorite-take-profit"
        assert OrderRepository(database.connection).get("entry") is not None
        assert PositionRepository(database.connection).get("up") is not None
        assert len(LedgerEventRepository(database.connection).list_for_run("integration-run")) == 2
