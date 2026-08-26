from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.application.ports.candidate_intelligence import (
    CandidatePipelineLeaseLostError,
)
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
from polysia.storage.continuous_shadow import (
    ContinuousShadowRepository,
    ContinuousShadowStoreError,
)
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
    outcome_reference: str = "token-yes"


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
            raise RuntimeError(f"safe source failure for {next(iter(self.leaders.values()))}")
        self.request_count += 1
        events = tuple(
            LeaderTradeEvent(
                event_id=spec.event_id,
                source_id="polymarket:data-api",
                leader_id=leader_id,
                market_reference="condition-1",
                outcome_reference=spec.outcome_reference,
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
        self.ambiguous_settlement = False
        self.book_size = book_size
        self.fail_book = False
        self.no_bids = False
        self.book_requests = 0
        self.missing_tokens: set[str] = set()

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
                    price=(
                        Decimal("0.50")
                        if self.closed and self.ambiguous_settlement
                        else Decimal("1") if self.closed else Decimal("0.50")
                    ),
                ),
                MarketOutcomeSummary(
                    label="No",
                    token_id="token-no",
                    price=(
                        Decimal("0.50")
                        if self.closed and self.ambiguous_settlement
                        else Decimal("0") if self.closed else Decimal("0.50")
                    ),
                ),
            ),
        )

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        assert token_id in {"token-yes", "token-no"}
        self.book_requests += 1
        if self.fail_book:
            raise RuntimeError("order book unavailable")
        if token_id in self.missing_tokens:
            error = RuntimeError("order book not found")
            error.diagnostic = type("D", (), {"status_code": 404})()
            raise error
        return MarketOrderBookSnapshot(
            token_id=token_id,
            market_id="condition-1",
            timestamp=self.clock.value,
            bids=(
                ()
                if self.no_bids
                else (OrderBookLevel(price=Decimal("0.59"), size=self.book_size),)
            ),
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


def _add_alpha_membership_for_first_wallet(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        run_id = connection.execute(
            "SELECT run_id FROM copyability_selection_current WHERE source_id = 'polycop'"
        ).fetchone()[0]
        wallet_id = connection.execute(
            "SELECT wallet_id FROM copyability_wallet_scores WHERE run_id = ? "
            "ORDER BY wallet_id LIMIT 1",
            (run_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO copyability_pool_memberships "
            "(run_id, pool_id, wallet_id, pool_rank, reasons_json) "
            "VALUES (?, 'SHADOW_ALPHA', ?, 1, '[]')",
            (run_id, wallet_id),
        )


def _split_first_wallet_from_stress_into_alpha(database: Path) -> None:
    _add_alpha_membership_for_first_wallet(database)
    with sqlite3.connect(database) as connection:
        run_id = connection.execute(
            "SELECT run_id FROM copyability_selection_current WHERE source_id = 'polycop'"
        ).fetchone()[0]
        wallet_id = connection.execute(
            "SELECT wallet_id FROM copyability_pool_memberships "
            "WHERE run_id = ? AND pool_id = 'SHADOW_ALPHA'",
            (run_id,),
        ).fetchone()[0]
        connection.execute(
            "DELETE FROM copyability_pool_memberships "
            "WHERE run_id = ? AND pool_id = 'SHADOW_STRESS' AND wallet_id = ?",
            (run_id, wallet_id),
        )


def _service(
    database: Path,
    scenario: _Scenario,
    market: _MarketPort,
    clock: _Clock,
    *,
    config: ContinuousShadowConfig | None = None,
) -> ContinuousShadowService:
    return ContinuousShadowService(
        ContinuousShadowRepository(database),
        DynamicShadowRepository(database),
        CandidateIntelligenceRepository(database),
        lambda leaders: _Source(dict(leaders), scenario),
        market,
        config=config or ContinuousShadowConfig(maximum_quote_age_ms=60_000),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_continuous_portfolio_deduplicates_persists_and_reconciles_after_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    _add_alpha_membership_for_first_wallet(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    assert experiment.lifecycle.value == "RUNNING"
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
    assert first.simulated_count == 4
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
    assert second.simulated_count == 4
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
    assert results["accounting"]["identity_status"] == "VERIFIED"
    assert Decimal(results["accounting"]["unmarked_adjusted_identity_delta"]) == 0
    assert results["accounting"]["ledger_balanced"] is True
    assert results["polls"]["new_event_count"] == 2
    assert results["polls"]["duplicate_count"] == 2
    assert results["event_journal"]["duplicate_processing_count"] == 0
    assert results["event_journal"]["processing_status"] == {"PROCESSED": 2}
    assert results["event_journal"]["first_source_event_at"] == buy.executed_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert results["event_outcomes"]["simulated"] == 2
    assert results["follower_activity"]["delay_distribution_ms"][
        "source_api_observation_lag"
    ]["p50"] == 2_000
    assert results["follower_activity"]["delay_distribution_ms"]["signal_delay"][
        "p50"
    ] > 2_000
    assert results["follower_closes"]["winning"] == 1
    assert results["operator_summary"]["real_orders"] is False
    assert results["decision_readiness"]["live_promotion"] is False
    assert results["policy_experiments"]["look_ahead"] is False
    assert results["latency"]["median"] is not None
    assert results["follower_portfolios"]["SHADOW_ALPHA"]["activity"]["event_outcomes"][
        "simulated"
    ] == 2
    assert results["wallet_market_attribution"]["unattributed_net"] == "0"
    assert results["pool_results"]["SHADOW_ALPHA"]["activity"]["event_outcomes"][
        "simulated"
    ] == 2
    assert results["pool_results"]["SHADOW_STRESS"]["activity"]["event_outcomes"][
        "simulated"
    ] == 2

    backup = backup_wallet_intelligence_database(
        database,
        tmp_path / "backups",
        now=clock.value,
    )
    restored = rehearse_wallet_intelligence_restore(
        backup.backup_path,
        working_directory=tmp_path / "restore",
    )
    assert restored.validation.continuous_shadow_schema_version == 4
    assert restored.validation.continuous_shadow_experiment_count == 1
    assert restored.validation.continuous_shadow_poll_count == 3
    assert restored.validation.continuous_shadow_event_count == 2
    assert restored.validation.continuous_shadow_ledger_count == 8


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
    draining = service.drain("polycop")
    assert draining.lifecycle.value == "DRAINING"
    market.closed = True

    clock.value = NOW + timedelta(minutes=3)
    settled = await service.poll("polycop")
    finalized = service.finalize("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert settled.settlement_count == 3
    assert finalized.lifecycle.value == "FINALIZED"
    assert results["open_position_count"] == 0
    assert results["accounting"]["ledger_balanced"] is True


@pytest.mark.asyncio
async def test_reporting_records_partial_fill_without_reusing_follower_depth(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock, book_size=Decimal("7"))
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    for index, candidate in enumerate(candidates):
        scenario.events[candidate.wallet_id] = [
            _EventSpec(
                f"partial-{index}",
                LeaderTradeAction.BUY,
                NOW + timedelta(seconds=100),
                Decimal("0.40"),
            )
        ]

    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert results["follower_activity"]["partial_fill_evaluations"] == 1
    assert results["follower_activity"]["event_outcomes"]["partial"] == 1
    assert Decimal(results["follower_activity"]["filled_size"]) == Decimal("7")


@pytest.mark.asyncio
async def test_follower_cash_and_exposure_limits_reject_without_partial_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    config = ContinuousShadowConfig(
        follower_bankroll=Decimal("2"),
        maximum_event_notional=Decimal("1"),
        follower_maximum_exposure=Decimal("1"),
        follower_maximum_wallet_exposure=Decimal("1"),
        follower_maximum_market_exposure=Decimal("1"),
        maximum_quote_age_ms=60_000,
    )
    service = _service(database, scenario, market, clock, config=config)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    leader_id = candidates[0].wallet_id
    scenario.events[leader_id] = [
        _EventSpec("limit-1", LeaderTradeAction.BUY, NOW + timedelta(seconds=100), Decimal("0.4")),
        _EventSpec("limit-2", LeaderTradeAction.BUY, NOW + timedelta(seconds=101), Decimal("0.4")),
    ]

    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    follower_reasons = results["follower_activity"]["reasons"]
    assert follower_reasons["synthetic_capital_limit_reached"] == 1
    assert Decimal(results["follower"]["exposure"]) <= Decimal("1")
    assert Decimal(results["follower"]["cash"]) >= 0


@pytest.mark.asyncio
async def test_verified_fee_cannot_push_synthetic_cash_negative(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    config = ContinuousShadowConfig(
        follower_bankroll=Decimal("1"),
        maximum_event_notional=Decimal("1"),
        follower_maximum_exposure=Decimal("1"),
        follower_maximum_wallet_exposure=Decimal("1"),
        follower_maximum_market_exposure=Decimal("1"),
        maximum_quote_age_ms=60_000,
    )
    service = _service(database, scenario, market, clock, config=config)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "cash-fee",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.4"),
        )
    ]

    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert results["follower_activity"]["reasons"][
        "synthetic_cash_limit_reached_after_verified_fee"
    ] == 1
    assert Decimal(results["follower"]["cash"]) == Decimal("1")
    assert Decimal(results["follower"]["exposure"]) == 0


@pytest.mark.asyncio
async def test_alpha_and_stress_reporting_remains_distinct(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    _split_first_wallet_from_stress_into_alpha(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    assert len(candidates) == 2
    for index, candidate in enumerate(candidates):
        scenario.events[candidate.wallet_id] = [
            _EventSpec(
                f"pool-{index}",
                LeaderTradeAction.BUY,
                NOW + timedelta(seconds=100 + index),
                Decimal("0.4"),
            )
        ]

    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    alpha = results["pool_results"]["SHADOW_ALPHA"]
    stress = results["pool_results"]["SHADOW_STRESS"]
    assert alpha["membership_count"] == 1
    assert stress["membership_count"] == 1
    assert results["pool_results"]["overlap_wallet_count"] == 0
    assert alpha["activity"]["event_outcomes"]["unique_evaluated"] == 1
    assert stress["activity"]["event_outcomes"]["unique_evaluated"] == 1


@pytest.mark.asyncio
async def test_opposing_outcome_is_rejected_as_a_conflicting_signal(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    leader_id = candidates[0].wallet_id
    scenario.events[leader_id] = [
        _EventSpec(
            "conflict-yes",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.4"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    scenario.events[leader_id].append(
        _EventSpec(
            "conflict-no",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=150),
            Decimal("0.4"),
            outcome_reference="token-no",
        )
    )
    clock.value = NOW + timedelta(minutes=3)
    await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert results["follower_activity"]["reasons"][
        "conflicting_market_outcome_exposure"
    ] == 1


@pytest.mark.asyncio
async def test_mid_publication_failure_rolls_back_journal_and_checkpoint(tmp_path: Path) -> None:
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
            "atomic-failure",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.4"),
        )
    ]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER force_evaluation_failure BEFORE INSERT ON "
            "continuous_shadow_evaluations BEGIN "
            "SELECT RAISE(ABORT, 'forced evaluation failure'); END"
        )

    clock.value = NOW + timedelta(minutes=2)
    with pytest.raises(ContinuousShadowError, match="durable prior state was kept"):
        await service.poll("polycop")
    with sqlite3.connect(database) as connection:
        journal_count = connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_event_journal"
        ).fetchone()[0]
        checkpoint_count = connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_checkpoint WHERE experiment_id = ?",
            (experiment.experiment_id,),
        ).fetchone()[0]
        failed_count = connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_poll_runs WHERE status = 'failed'"
        ).fetchone()[0]

    assert journal_count == 0
    assert checkpoint_count == 0
    assert failed_count == 1


@pytest.mark.asyncio
async def test_ambiguous_closed_market_is_reported_as_settlement_backlog(tmp_path: Path) -> None:
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
            "backlog-buy",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.4"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    market.closed = True
    market.ambiguous_settlement = True
    clock.value = NOW + timedelta(minutes=3)
    outcome = await service.poll("polycop")
    health = ContinuousShadowRepository(database).health(
        "polycop", now=clock.value, poll_interval_seconds=60
    )

    assert outcome.settlement_backlog_count == 3
    assert health.settlement_backlog_count == 3
    assert "continuous_shadow_settlement_backlog" in health.reasons


@pytest.mark.asyncio
async def test_missing_exit_bid_labels_nav_partial_without_breaking_ledger(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    market.no_bids = True
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "no-exit-bid",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.4"),
        )
    ]

    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert results["accounting"]["ledger_balanced"] is True
    assert results["accounting"]["identity_status"] == "INCOMPLETE_MARKS"
    assert Decimal(results["accounting"]["unmarked_cost_basis"]) > 0
    assert Decimal(results["accounting"]["unmarked_adjusted_identity_delta"]) == 0
    assert results["follower"]["total_pnl_status"] == "PARTIAL_OR_LAST_KNOWN_GOOD"
    assert results["confidence"]["level"] == "LOW"


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
    assert outcome.simulated_count == 4
    assert outcome.rejected_count == 2
    assert Decimal(results["follower_activity"]["filled_size"]) <= Decimal("5")
    assert Decimal(results["follower_activity"]["filled_size"]) > 0
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
    with pytest.raises(ContinuousShadowError, match="durable prior state was kept") as failed:
        await service.poll("polycop")
    after_failure = ContinuousShadowRepository(database).results(
        experiment.experiment_id,
        limit=10,
    )

    assert failed.value.error_code == "source_unavailable"
    assert failed.value.processing_stage == "collect_events"
    assert after_failure["follower"] == before["follower"]
    assert after_failure["polls"]["succeeded"] == 1
    health = ContinuousShadowRepository(database).health(
        "polycop",
        now=clock.value,
        poll_interval_seconds=60,
    )
    assert health.last_failure_code == "source_unavailable"
    assert health.last_failure_stage == "collect_events"
    assert ADDRESSES[0] not in json.dumps(health.to_dict())

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

    assert health.unmarked_position_count == 3
    assert health.stale_last_known_good_mark_count == 3
    assert health.missing_mark_count == 0
    assert health.fresh_verified_mark_count == 0
    assert "continuous_shadow_positions_unmarked" in health.reasons
    payload = health.to_dict()
    assert payload["operator_summary"]["MIXED_BASELINE"]["open_position_count"] >= 1
    assert "nav" in payload["operator_summary"]["MIXED_BASELINE"]
    results = ContinuousShadowRepository(database).results(
        health.experiment.experiment_id,
        limit=10,
    )
    assert results["mark_freshness"]["stale_last_known_good_count"] >= 1
    assert results["confidence"]["level"] == "LOW"
    assert "portfolio_valuation_not_fully_current" in results["confidence"]["limitations"]


@pytest.mark.asyncio
async def test_settlement_keeps_wallet_and_pool_attribution(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    _split_first_wallet_from_stress_into_alpha(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    service = _service(database, scenario, market, clock)
    experiment = service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    alpha = next(item for item in candidates if item.alpha_rank is not None)
    scenario.events[alpha.wallet_id] = [
        _EventSpec(
            "attr-buy",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.40"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    await service.poll("polycop")
    market.closed = True
    clock.value = NOW + timedelta(minutes=3)
    await service.poll("polycop")
    results = ContinuousShadowRepository(database).results(experiment.experiment_id, limit=10)

    assert results["wallet_market_attribution"]["unattributed_net"] == "0"
    assert results["pnl_decomposition"]["settlement_realized_pnl"] != "0"
    assert alpha.wallet_id in results["wallet_market_attribution"]["wallets"]
    assert results["follower_portfolios"]["SHADOW_ALPHA"]["closes"]["settlements"] == 1
    assert results["follower_portfolios"]["SHADOW_STRESS"]["closes"]["settlements"] == 0


@pytest.mark.asyncio
async def test_terminal_order_book_404_is_negatively_cached(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    market = _MarketPort(clock)
    market.missing_tokens.add("token-yes")
    service = _service(database, scenario, market, clock)
    service.start("polycop")
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "missing-book",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.40"),
        )
    ]
    clock.value = NOW + timedelta(minutes=2)
    first = await service.poll("polycop")
    first_requests = market.book_requests
    clock.value = NOW + timedelta(minutes=3)
    second = await service.poll("polycop")

    assert first.unknown_count > 0
    assert second.new_event_count == 0
    assert market.book_requests == first_requests


def _started_service(
    tmp_path: Path,
    *,
    name: str = "wallet-intelligence",
) -> tuple[Path, ContinuousShadowService, _Clock, _Scenario]:
    database = tmp_path / f"{name}.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    service = _service(database, scenario, _MarketPort(clock), clock)
    service.start("polycop")
    return database, service, clock, scenario


@pytest.mark.asyncio
async def test_fail_poll_recording_error_preserves_original_failure_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, service, clock, scenario = _started_service(tmp_path)
    scenario.fail = True
    clock.value = NOW + timedelta(minutes=2)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ContinuousShadowRepository, "fail_poll", boom)
    with pytest.raises(ContinuousShadowError) as failed:
        await service.poll("polycop")

    assert failed.value.error_code == "source_unavailable"
    assert "0x" not in str(failed.value)
    assert ADDRESSES[0] not in str(failed.value)


@pytest.mark.asyncio
async def test_injected_failures_record_distinct_sanitized_categories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def market_boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ContinuousShadowError(
            "Market metadata was unavailable.",
            error_code="market_read_failed",
            processing_stage="market_read",
        )

    def persist_boom(*_args: object, **_kwargs: object) -> object:
        raise ContinuousShadowStoreError("Continuous Shadow persistence failed.")

    def busy_boom(*_args: object, **_kwargs: object) -> object:
        raise sqlite3.OperationalError("database is locked")

    def lease_boom(*_args: object, **_kwargs: object) -> object:
        raise CandidatePipelineLeaseLostError("lease lost")

    cases = (
        ("_markets", market_boom, "market_read_failed", "market_read"),
        ("complete_poll", persist_boom, "persistence_failed", "persist"),
        ("complete_poll", busy_boom, "sqlite_busy", "persist"),
        ("renew_lease", lease_boom, "lease_failed", "renew_lease"),
    )
    for target, boom, category, stage in cases:
        database, service, clock, _scenario = _started_service(tmp_path, name=category)
        clock.value = NOW + timedelta(minutes=2)
        if target == "_markets":
            monkeypatch.setattr(service, "_markets", boom)
        elif target == "complete_poll":
            monkeypatch.setattr(ContinuousShadowRepository, "complete_poll", boom)
        else:
            monkeypatch.setattr(CandidateIntelligenceRepository, "renew_lease", boom)
        with pytest.raises(ContinuousShadowError) as failed:
            await service.poll("polycop")
        assert failed.value.error_code == category
        assert failed.value.processing_stage == stage
        health = ContinuousShadowRepository(database).health(
            "polycop",
            now=clock.value,
            poll_interval_seconds=60,
        )
        assert health.last_failure_code == category
        assert health.last_failure_stage == stage
        monkeypatch.undo()
