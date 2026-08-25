from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.application.ports.copytrading import LeaderTradeReadPage
from polysia.application.services.candidate_intelligence import (
    PIPELINE_LEASE_RESOURCE,
    CandidateIntelligenceService,
)
from polysia.application.services.continuous_shadow import (
    ContinuousShadowError,
    ContinuousShadowService,
)
from polysia.application.services.copyability_selection import CopyabilitySelectionService
from polysia.deployment.wallet_intelligence_backup import (
    backup_wallet_intelligence_database,
    rehearse_wallet_intelligence_restore,
)
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
)
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    OrderBookLevel,
)
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.dynamic_shadow import DynamicShadowRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
ADDRESSES = ("0x" + "1" * 40, "0x" + "2" * 40)


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@dataclass(frozen=True, slots=True)
class _EventSpec:
    event_id: str
    action: LeaderTradeAction
    executed_at: datetime
    price: Decimal
    size: Decimal = Decimal("5")


class _Scenario:
    def __init__(self) -> None:
        self.events: dict[str, list[_EventSpec]] = {}
        self.fail = False


class _Source:
    def __init__(self, leaders: dict[str, str], scenario: _Scenario) -> None:
        self.leaders = leaders
        self.scenario = scenario
        self.request_count = 0

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        **_: Any,
    ) -> LeaderTradeReadPage:
        if self.scenario.fail:
            raise RuntimeError("safe source failure")
        self.request_count += 1
        events = tuple(
            LeaderTradeEvent(
                event_id=spec.event_id,
                source_id="polymarket:data-api",
                leader_id=leader_id,
                market_reference="condition-1",
                outcome_reference="token-yes",
                trade_action=spec.action,
                position_effect=LeaderPositionEffect.UNKNOWN,
                executed_price=spec.price,
                executed_size=spec.size,
                executed_at=spec.executed_at,
                observed_at=spec.executed_at + timedelta(seconds=2),
                external_evidence_reference=f"sha256:{spec.event_id}",
            )
            for spec in self.scenario.events.get(leader_id, ())
            if start_at <= spec.executed_at <= end_at
        )
        return LeaderTradeReadPage(
            events=events,
            next_checkpoint=None,
            raw_count=len(events),
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )

    def request_telemetry(self) -> dict[str, object]:
        return {"data:/trades": {"requests": self.request_count}}


class _MarketPort:
    def __init__(self, clock: _Clock, *, book_size: Decimal = Decimal("20")) -> None:
        self.clock = clock
        self.closed = False
        self.book_size = book_size
        self.fail_book = False

    async def get_market_by_condition_id(self, market_id: str) -> MarketDetails:
        assert market_id == "condition-1"
        return MarketDetails(
            id="market-1",
            condition_id=market_id,
            closed=self.closed,
            active=not self.closed,
            fee_schedule=MarketFeeSchedule(
                enabled=True,
                rate=Decimal("0.04"),
                exponent=Decimal("1"),
                taker_only=True,
            ),
            outcomes=(
                MarketOutcomeSummary(
                    label="Yes",
                    token_id="token-yes",
                    price=Decimal("1") if self.closed else Decimal("0.50"),
                ),
                MarketOutcomeSummary(
                    label="No",
                    token_id="token-no",
                    price=Decimal("0") if self.closed else Decimal("0.50"),
                ),
            ),
        )

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        assert token_id == "token-yes"
        if self.fail_book:
            raise RuntimeError("order book unavailable")
        return MarketOrderBookSnapshot(
            token_id=token_id,
            market_id="condition-1",
            timestamp=self.clock.value,
            bids=(OrderBookLevel(price=Decimal("0.59"), size=self.book_size),),
            asks=(OrderBookLevel(price=Decimal("0.41"), size=self.book_size),),
            minimum_order_size=Decimal("1"),
            tick_size=Decimal("0.01"),
        )


def _dataset() -> CandidateWalletDataset:
    records = tuple(
        CandidateWalletRecord(
            external_wallet_id=address,
            source_rank=rank,
            source_page=1,
            metrics={
                "actual_pnl": str(100 - rank),
                "copy_backtest_pnl": str(50 - rank),
                "markets_traded": 20 + rank,
                "trading_days": 10 + rank,
                "trading_volume": "1000",
            },
            row_digest=hashlib.sha256(f"{address}:{rank}".encode()).hexdigest(),
        )
        for rank, address in enumerate(ADDRESSES, start=1)
    )
    return CandidateWalletDataset(
        source_id="polycop",
        schema_version="test-v1",
        fetched_at=NOW,
        source_total_pages=1,
        records=records,
        dataset_digest=hashlib.sha256(
            "\n".join(item.row_digest for item in records).encode()
        ).hexdigest(),
    )


def _seed_stage3(database: Path) -> None:
    stage1 = WalletIntelligenceRepository(database)
    stage1.initialize()
    source_run = stage1.start_run("polycop", scheduled_for=NOW.date(), started_at=NOW)
    snapshot = stage1.complete_run(source_run, _dataset(), accepted_at=NOW)
    stage2 = CandidateIntelligenceRepository(database)
    stage2.initialize()
    lease = stage2.acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="test-pipeline",
        acquired_at=NOW,
        lease_duration=timedelta(minutes=30),
    )
    stage2_run = CandidateIntelligenceService(
        stage2,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: NOW,
    ).process_snapshot("polycop", snapshot.snapshot_id, lease=lease)
    CopyabilitySelectionService(
        CopyabilitySelectionRepository(database),
        clock=lambda: NOW,
    ).process_stage2_run("polycop", stage2_run.pool.run_id, lease=lease)
    stage2.release_lease(lease)


def _service(
    database: Path,
    scenario: _Scenario,
    market: _MarketPort,
    clock: _Clock,
) -> ContinuousShadowService:
    return ContinuousShadowService(
        ContinuousShadowRepository(database),
        DynamicShadowRepository(database),
        CandidateIntelligenceRepository(database),
        lambda leaders: _Source(dict(leaders), scenario),
        market,
        config=ContinuousShadowConfig(maximum_quote_age_ms=60_000),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_continuous_portfolio_deduplicates_persists_and_reconciles_after_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    leader_id = candidates[0].wallet_id
    buy = _EventSpec(
        "buy-1",
        LeaderTradeAction.BUY,
        NOW + timedelta(seconds=100),
        Decimal("0.40"),
    )
    scenario.events[leader_id] = [buy]

    clock.value = NOW + timedelta(minutes=2)
    first = await service.poll("polycop")

    assert first.new_event_count == 1
    assert first.simulated_count == 2
    assert first.unknown_count == 0
    assert first.follower_exposure > 0

    scenario.events[leader_id].append(
        _EventSpec(
            "sell-1",
            LeaderTradeAction.SELL,
            NOW + timedelta(seconds=150),
            Decimal("0.60"),
        )
    )
    clock.value = NOW + timedelta(minutes=3)
    second = await service.poll("polycop")

    assert second.new_event_count == 1
    assert second.duplicate_count == 1
    assert second.simulated_count == 2
    assert second.realized_pnl_delta > 0
    assert second.follower_exposure == 0

    restarted = _service(database, scenario, market, clock)
    clock.value = NOW + timedelta(minutes=4)
    third = await restarted.poll("polycop")
    results = ContinuousShadowRepository(database).results(
        experiment.experiment_id,
        limit=10,
    )

    assert third.new_event_count == 0
    assert third.duplicate_count == 1
    assert Decimal(results["accounting"]["identity_delta"]) == 0
    assert results["accounting"]["ledger_balanced"] is True
    assert results["polls"]["new_event_count"] == 2
    assert results["polls"]["duplicate_count"] == 2

    backup = backup_wallet_intelligence_database(
        database,
        tmp_path / "backups",
        now=clock.value,
    )
    restored = rehearse_wallet_intelligence_restore(
        backup.backup_path,
        working_directory=tmp_path / "restore",
    )
    assert restored.validation.continuous_shadow_schema_version == 2
    assert restored.validation.continuous_shadow_experiment_count == 1
    assert restored.validation.continuous_shadow_poll_count == 3
    assert restored.validation.continuous_shadow_event_count == 2
    assert restored.validation.continuous_shadow_ledger_count == 4


@pytest.mark.asyncio
async def test_verified_settlement_closes_cross_run_positions_and_allows_finalization(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "settle-buy",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.40"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    service.drain("polycop")
    market.closed = True

    clock.value = NOW + timedelta(minutes=3)
    settled = await service.poll("polycop")
    finalized = service.finalize("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert settled.settlement_count == 2
    assert finalized.lifecycle.value == "FINALIZED"
    assert results["open_position_count"] == 0
    assert results["accounting"]["ledger_balanced"] is True


@pytest.mark.asyncio
async def test_combined_follower_does_not_reuse_liquidity_across_wallets(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock, book_size=Decimal("5"))
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    for index, candidate in enumerate(candidates):
        scenario.events[candidate.wallet_id] = [
            _EventSpec(
                f"shared-{index}",
                LeaderTradeAction.BUY,
                NOW + timedelta(seconds=100),
                Decimal("0.40"),
            )
        ]

    clock.value = NOW + timedelta(minutes=2)
    outcome = await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert outcome.new_event_count == 2
    assert outcome.simulated_count == 3
    assert outcome.rejected_count == 1
    assert results["accounting"]["ledger_balanced"] is True


@pytest.mark.asyncio
async def test_ledger_reconciliation_detects_a_missing_persisted_position(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "missing-position-buy",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.40"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM continuous_shadow_positions "
            "WHERE experiment_id = ? AND portfolio_id = 'follower'",
            (experiment.experiment_id,),
        )

    results = ContinuousShadowRepository(database).results(
        experiment.experiment_id,
        limit=10,
    )

    assert results["accounting"]["ledger_balanced"] is False


@pytest.mark.asyncio
async def test_failed_poll_keeps_last_known_good_portfolio_and_recovers(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "lkg-buy",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.40"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    before = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    scenario.fail = True
    clock.value = NOW + timedelta(minutes=3)
    with pytest.raises(ContinuousShadowError, match="durable prior state was kept"):
        await service.poll("polycop")
    after_failure = ContinuousShadowRepository(database).results(
        experiment.experiment_id,
        limit=10,
    )

    assert after_failure["follower"] == before["follower"]
    assert after_failure["polls"]["succeeded"] == 1

    scenario.fail = False
    clock.value = NOW + timedelta(minutes=4)
    recovered = await service.poll("polycop")
    assert recovered.new_event_count == 0


@pytest.mark.asyncio
async def test_last_known_good_mark_is_retained_and_visible_in_health(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "lkg-mark-buy",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.40"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")

    market.fail_book = True
    clock.value = NOW + timedelta(minutes=3)
    await service.poll("polycop")
    health = ContinuousShadowRepository(database).health(
        "polycop",
        now=clock.value,
        poll_interval_seconds=60,
    )

    assert health.unmarked_position_count == 2
    assert "continuous_shadow_positions_unmarked" in health.reasons
