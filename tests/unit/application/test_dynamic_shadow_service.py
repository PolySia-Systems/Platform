from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.application.ports.candidate_intelligence import CandidatePipelineBusyError
from polysia.application.ports.copytrading import LeaderTradeCheckpoint, LeaderTradeReadPage
from polysia.application.services.candidate_intelligence import (
    PIPELINE_LEASE_RESOURCE,
    CandidateIntelligenceService,
)
from polysia.application.services.copyability_selection import CopyabilitySelectionService
from polysia.application.services.dynamic_shadow import DynamicShadowError, DynamicShadowService
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
)
from polysia.domain.copytrading.dynamic_shadow import DynamicShadowMode
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.dynamic_shadow import DynamicShadowRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
ADDRESSES = ("0x" + "1" * 40, "0x" + "2" * 40)


def test_dynamic_repository_verifies_shared_database_integrity_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        WalletIntelligenceRepository,
        "_require_integrity",
        staticmethod(lambda _connection: calls.append("wallet")),
    )
    monkeypatch.setattr(
        CandidateIntelligenceRepository,
        "_require_integrity",
        staticmethod(lambda _connection: calls.append("candidate")),
    )
    monkeypatch.setattr(
        CopyabilitySelectionRepository,
        "_require_integrity",
        staticmethod(lambda _connection: calls.append("selection")),
    )
    monkeypatch.setattr(
        DynamicShadowRepository,
        "_require_integrity",
        staticmethod(lambda _connection: calls.append("dynamic")),
    )

    DynamicShadowRepository(tmp_path / "wallet-intelligence.sqlite3").initialize()

    assert calls == ["dynamic"]


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


def _event(
    leader_id: str,
    event_id: str,
    action: LeaderTradeAction,
    minute: int,
) -> LeaderTradeEvent:
    return LeaderTradeEvent(
        event_id=event_id,
        source_id="polymarket:data-api",
        leader_id=leader_id,
        market_reference="condition-1",
        outcome_reference="token-1",
        trade_action=action,
        position_effect=LeaderPositionEffect.UNKNOWN,
        executed_price=Decimal("0.40" if action is LeaderTradeAction.BUY else "0.60"),
        executed_size=Decimal("5"),
        executed_at=NOW - timedelta(minutes=minute),
        observed_at=NOW - timedelta(minutes=minute) + timedelta(seconds=2),
        external_evidence_reference="sha256:evidence",
    )


class _Source:
    def __init__(
        self,
        leaders: dict[str, str],
        *,
        fail: bool = False,
        outside_window: bool = False,
    ) -> None:
        self.leaders = leaders
        self.fail = fail
        self.outside_window = outside_window

    async def read_page(self, leader_id: str, **_: Any) -> LeaderTradeReadPage:
        if self.fail:
            raise RuntimeError("safe fixture failure")
        events = (
            _event(leader_id, f"{leader_id}-buy", LeaderTradeAction.BUY, 10),
            _event(leader_id, f"{leader_id}-sell", LeaderTradeAction.SELL, 5),
        )
        if self.outside_window:
            events = (_event(leader_id, f"{leader_id}-future", LeaderTradeAction.BUY, -10),)
        return LeaderTradeReadPage(
            events=events,
            next_checkpoint=None,
            raw_count=2,
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )

    def request_telemetry(self) -> dict[str, object]:
        return {"trades:discovery": {"requests": len(self.leaders)}}

    def trades_circuit(self) -> dict[str, object]:
        return {"open": False}


class _DenseSource:
    def __init__(self, leaders: dict[str, str]) -> None:
        self.leaders = leaders
        self.call_count = 0

    async def read_page(
        self,
        leader_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        checkpoint: LeaderTradeCheckpoint | None = None,
        **_: Any,
    ) -> LeaderTradeReadPage:
        self.call_count += 1
        if end_at - start_at > timedelta(minutes=30):
            index = 0 if checkpoint is None else int(checkpoint.value)
            return LeaderTradeReadPage(
                events=(),
                next_checkpoint=LeaderTradeCheckpoint(str(index + 1)),
                raw_count=500,
                filtered_count=0,
                rejected_count=0,
                duplicate_count=0,
            )
        executed_at = start_at + (end_at - start_at) / 2
        event = LeaderTradeEvent(
            event_id=f"{leader_id}-{int(executed_at.timestamp())}",
            source_id="polymarket:data-api",
            leader_id=leader_id,
            market_reference="condition-1",
            outcome_reference="token-1",
            trade_action=LeaderTradeAction.BUY,
            position_effect=LeaderPositionEffect.UNKNOWN,
            executed_price=Decimal("0.40"),
            executed_size=Decimal("1"),
            executed_at=executed_at,
            observed_at=executed_at + timedelta(seconds=2),
            external_evidence_reference="sha256:evidence",
        )
        return LeaderTradeReadPage(
            events=(event,),
            next_checkpoint=None,
            raw_count=1,
            filtered_count=0,
            rejected_count=0,
            duplicate_count=0,
        )

    def request_telemetry(self) -> dict[str, object]:
        return {"requests": self.call_count}

    def trades_circuit(self) -> dict[str, object]:
        return {"open": False}


@pytest.mark.asyncio
async def test_dynamic_stage3_candidates_are_deduplicated_versioned_and_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    created: list[_Source] = []

    def factory(leaders: dict[str, str]) -> _Source:
        source = _Source(leaders)
        created.append(source)
        return source

    repository = DynamicShadowRepository(database)
    service = DynamicShadowService(
        repository,
        CandidateIntelligenceRepository(database),
        factory,
        clock=lambda: NOW,
    )
    first = await service.run(
        "polycop",
        mode=DynamicShadowMode.HISTORICAL,
        lookback=timedelta(hours=1),
        as_of=NOW,
    )
    replay = await service.run(
        "polycop",
        mode=DynamicShadowMode.HISTORICAL,
        lookback=timedelta(hours=1),
        as_of=NOW,
    )

    assert first.candidate_count == 2
    assert first.candidate_count == first.alpha_count + first.stress_count - first.overlap_count
    assert first.event_count == 4
    assert first.simulated_count == 4
    assert first.realized_pnl > Decimal("0")
    assert replay.idempotent_replay is True
    assert replay.run.run_id == first.run.run_id
    assert replay.realized_pnl == first.realized_pnl
    current_run = repository.current_run(
        "polycop",
        mode=DynamicShadowMode.HISTORICAL,
    )
    assert current_run is not None
    assert current_run.run_id == first.run.run_id
    assert len(created) == 1
    assert set(created[0].leaders.values()) == set(ADDRESSES)
    assert all("0x" not in item for item in first.to_dict().values() if isinstance(item, str))
    results = repository.current_wallet_results(
        "polycop",
        mode=DynamicShadowMode.HISTORICAL,
    )
    assert len(results) == 2
    assert all(len(item.wallet_id) == 64 for item in results)
    assert all("0x" not in str(item.to_dict()) for item in results)

    connection = sqlite3.connect(database)
    try:
        columns = {
            str(row[1])
            for table in (
                "dynamic_shadow_candidates",
                "dynamic_shadow_evaluations",
                "dynamic_shadow_wallet_summaries",
            )
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        wallets = connection.execute(
            "SELECT wallet_id, pools_json FROM dynamic_shadow_candidates"
        ).fetchall()
    finally:
        connection.close()
    assert "address" not in columns
    assert len(wallets) == 2
    assert all(len(str(row[0])) == 64 for row in wallets)


@pytest.mark.asyncio
async def test_failed_refresh_preserves_last_known_good_shadow_run(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    repository = DynamicShadowRepository(database)
    good = DynamicShadowService(
        repository,
        CandidateIntelligenceRepository(database),
        lambda leaders: _Source(dict(leaders)),
        clock=lambda: NOW,
    )
    published = await good.run(
        "polycop",
        mode=DynamicShadowMode.HISTORICAL,
        lookback=timedelta(hours=1),
        as_of=NOW,
    )
    failing = DynamicShadowService(
        repository,
        CandidateIntelligenceRepository(database),
        lambda leaders: _Source(dict(leaders), fail=True),
        clock=lambda: NOW + timedelta(hours=1),
    )

    with pytest.raises(DynamicShadowError):
        await failing.run(
            "polycop",
            mode=DynamicShadowMode.HISTORICAL,
            lookback=timedelta(hours=1),
            as_of=NOW + timedelta(hours=1),
        )

    health = repository.health("polycop", now=NOW + timedelta(hours=1))
    assert health.current_run is not None
    assert health.current_run.run_id == published.run.run_id
    assert health.last_run is not None
    assert health.last_run.status == "failed"
    assert "latest_dynamic_shadow_failed" in health.reasons


def test_shadow_compose_service_is_data_only_and_has_no_live_profile() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    section = compose.split("  wallet-intelligence-shadow:", maxsplit=1)[1].split(
        "  wallet-intelligence-handoff:", maxsplit=1
    )[0]

    assert 'LIVE_TRADING_ENABLED: "false"' in section
    assert "TRADING_MODE: DATA_ONLY" in section
    assert "live-experiment" not in section
    assert "tiny-copy" not in section
    assert "--submit" not in section


def test_dynamic_handoff_service_is_offline_data_only_and_cannot_submit() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    section = compose.split("  wallet-intelligence-handoff:", maxsplit=1)[1].split(
        "  copy-experiment:", maxsplit=1
    )[0]

    assert 'LIVE_TRADING_ENABLED: "false"' in section
    assert "TRADING_MODE: DATA_ONLY" in section
    assert 'POLYMARKET_LIVE_TOKEN_ALLOWLIST: ""' in section
    assert "network_mode: none" in section
    assert "runtime-bank" in section
    assert "read_only: true" in section
    assert "live-experiment" not in section
    assert "--submit" not in section


@pytest.mark.asyncio
async def test_shared_pipeline_lease_blocks_concurrent_shadow_read(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    lease_store = CandidateIntelligenceRepository(database)
    lease_store.acquire_lease(
        "wallet-intelligence-pipeline",
        owner_id="other-process",
        acquired_at=NOW,
        lease_duration=timedelta(minutes=30),
    )
    factory_called = False

    def factory(leaders: dict[str, str]) -> _Source:
        nonlocal factory_called
        factory_called = True
        return _Source(leaders)

    service = DynamicShadowService(
        DynamicShadowRepository(database),
        lease_store,
        factory,
        clock=lambda: NOW,
    )

    with pytest.raises(CandidatePipelineBusyError):
        await service.run(
            "polycop",
            mode=DynamicShadowMode.HISTORICAL,
            lookback=timedelta(hours=1),
            as_of=NOW,
        )
    assert factory_called is False


@pytest.mark.asyncio
async def test_source_event_outside_requested_window_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    repository = DynamicShadowRepository(database)
    service = DynamicShadowService(
        repository,
        CandidateIntelligenceRepository(database),
        lambda leaders: _Source(dict(leaders), outside_window=True),
        clock=lambda: NOW,
    )

    with pytest.raises(DynamicShadowError):
        await service.run(
            "polycop",
            mode=DynamicShadowMode.HISTORICAL,
            lookback=timedelta(hours=1),
            as_of=NOW,
        )

    health = repository.health("polycop", now=NOW)
    assert health.current_run is None
    assert health.last_run is not None
    assert health.last_run.status == "failed"


@pytest.mark.asyncio
async def test_dense_history_splits_time_window_before_offset_cap(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    source_holder: list[_DenseSource] = []

    def factory(leaders: dict[str, str]) -> _DenseSource:
        source = _DenseSource(leaders)
        source_holder.append(source)
        return source

    service = DynamicShadowService(
        DynamicShadowRepository(database),
        CandidateIntelligenceRepository(database),
        factory,
        clock=lambda: NOW,
    )

    outcome = await service.run(
        "polycop",
        mode=DynamicShadowMode.HISTORICAL,
        lookback=timedelta(hours=1),
        as_of=NOW,
    )

    assert outcome.event_count == 4
    assert outcome.simulated_count == 4
    assert source_holder[0].call_count == 44
