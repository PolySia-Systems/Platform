from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysia.application.ports.candidate_intelligence import CandidatePipelineLeaseLostError
from polysia.application.services.candidate_intelligence import (
    PIPELINE_LEASE_RESOURCE,
    CandidateIntelligenceService,
    WalletIntelligencePipelineService,
)
from polysia.application.services.copyability_selection import (
    CopyabilitySelectionError,
    CopyabilitySelectionService,
)
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.domain.wallet_intelligence.copyability_selection import (
    SelectionPoolId,
    SelectionStatus,
)
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.copyability_selection import CopyabilitySelectionRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository


def _dataset(
    rows: tuple[tuple[str, int, dict[str, object]], ...],
    *,
    fetched_at: datetime,
) -> CandidateWalletDataset:
    records = []
    for address, rank, metrics in rows:
        records.append(
            CandidateWalletRecord(
                external_wallet_id=address,
                source_rank=rank,
                source_page=1,
                metrics=metrics,
                row_digest=hashlib.sha256(f"{address}:{rank}".encode()).hexdigest(),
            )
        )
    record_tuple = tuple(records)
    return CandidateWalletDataset(
        source_id="polycop",
        schema_version="test-v1",
        fetched_at=fetched_at,
        source_total_pages=1,
        records=record_tuple,
        dataset_digest=hashlib.sha256(
            "\n".join(record.row_digest for record in record_tuple).encode()
        ).hexdigest(),
    )


def _seed_stage2(
    database: Path,
    rows: tuple[tuple[str, int, dict[str, object]], ...],
    at: datetime,
) -> str:
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    run = source_store.start_run("polycop", scheduled_for=at.date(), started_at=at)
    stored = source_store.complete_run(run, _dataset(rows, fetched_at=at), accepted_at=at)
    intelligence = CandidateIntelligenceRepository(database)
    intelligence.initialize()
    lease = intelligence.acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="owner-1",
        acquired_at=at,
        lease_duration=timedelta(minutes=30),
    )
    outcome = CandidateIntelligenceService(
        intelligence,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: at,
    ).process_snapshot("polycop", stored.snapshot_id, lease=lease)
    intelligence.release_lease(lease)
    return outcome.pool.run_id


def test_stage3_is_idempotent_and_keeps_live_review_empty(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    at = datetime(2026, 8, 24, tzinfo=UTC)
    stage2_run_id = _seed_stage2(
        database,
        (
            (
                "0x" + "1" * 40,
                1,
                {
                    "copy_backtest_pnl": "40",
                    "actual_pnl": "12",
                    "markets_traded": 8,
                    "trading_days": 10,
                    "trading_volume": "500",
                },
            ),
        ),
        at,
    )
    store = CopyabilitySelectionRepository(database)
    store.initialize()
    service = CopyabilitySelectionService(store, clock=lambda: at + timedelta(minutes=1))
    lease = CandidateIntelligenceRepository(database).acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="stage3",
        acquired_at=at + timedelta(minutes=1),
        lease_duration=timedelta(minutes=30),
    )
    first = service.process_stage2_run("polycop", stage2_run_id, lease=lease)
    second = service.process_stage2_run("polycop", stage2_run_id, lease=lease)
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.selection.run_id == first.selection.run_id
    assert first.selection.live_review_count == 0
    assert store.current_pool("polycop", SelectionPoolId.LIVE_REVIEW_CANDIDATE) == ()


def test_missing_stage2_preserves_previous_pools_and_stage2(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    at = datetime(2026, 8, 24, tzinfo=UTC)
    stage2_run_id = _seed_stage2(
        database,
        (("0x" + "2" * 40, 1, {"copy_backtest_pnl": "15", "markets_traded": 4}),),
        at,
    )
    store = CopyabilitySelectionRepository(database)
    store.initialize()
    service = CopyabilitySelectionService(store, clock=lambda: at + timedelta(minutes=1))
    lease = CandidateIntelligenceRepository(database).acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="stage3",
        acquired_at=at + timedelta(minutes=1),
        lease_duration=timedelta(minutes=30),
    )
    published = service.process_stage2_run("polycop", stage2_run_id, lease=lease)
    with pytest.raises(CopyabilitySelectionError):
        service.process_stage2_run("polycop", "missing-stage2", lease=lease)
    current = store.current_run("polycop")
    assert current is not None
    assert current.run_id == published.selection.run_id
    assert CandidateIntelligenceRepository(database).current_run("polycop") is not None


def test_lost_lease_does_not_replace_published_pools(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    first_at = datetime(2026, 8, 24, tzinfo=UTC)
    first_stage2 = _seed_stage2(
        database,
        (("0x" + "a" * 40, 1, {"copy_backtest_pnl": "20", "markets_traded": 5}),),
        first_at,
    )
    store = CopyabilitySelectionRepository(database)
    store.initialize()
    live_lease = CandidateIntelligenceRepository(database).acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="stage3-live",
        acquired_at=first_at + timedelta(minutes=1),
        lease_duration=timedelta(minutes=30),
    )
    published = CopyabilitySelectionService(
        store,
        clock=lambda: first_at + timedelta(minutes=1),
    ).process_stage2_run("polycop", first_stage2, lease=live_lease)
    CandidateIntelligenceRepository(database).release_lease(live_lease)
    second_at = first_at + timedelta(days=1)
    second_stage2 = _seed_stage2(
        database,
        (("0x" + "b" * 40, 1, {"copy_backtest_pnl": "30", "markets_traded": 8}),),
        second_at,
    )
    expired = CandidateIntelligenceRepository(database).acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="expired",
        acquired_at=second_at + timedelta(minutes=1),
        lease_duration=timedelta(seconds=10),
    )
    CandidateIntelligenceRepository(database).release_lease(expired)
    with pytest.raises((CopyabilitySelectionError, CandidatePipelineLeaseLostError)):
        CopyabilitySelectionService(
            store,
            clock=lambda: second_at + timedelta(minutes=2),
        ).process_stage2_run("polycop", second_stage2, lease=expired)
    current = store.current_run("polycop")
    assert current is not None
    assert current.run_id == published.selection.run_id


@pytest.mark.asyncio
async def test_pipeline_ensure_runs_stage3_and_replays(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    now = datetime(2026, 8, 24, tzinfo=UTC)
    metrics = {
        "copy_backtest_pnl": "22",
        "actual_pnl": "9",
        "markets_traded": 6,
        "trading_days": 12,
        "trading_volume": "800",
    }
    source = _PipelineSource(_dataset((("0x" + "3" * 40, 1, metrics),), fetched_at=now))
    clock = [now]
    pipeline = WalletIntelligencePipelineService(
        source,
        WalletIntelligenceRepository(database),
        CandidateIntelligenceRepository(database),
        chain="polygon",
        clock=lambda: clock[0],
        selection_store=CopyabilitySelectionRepository(database),
    )
    first = await pipeline.ensure(scheduled_for=now.date())
    clock[0] += timedelta(hours=1)
    second = await pipeline.ensure(scheduled_for=now.date())
    assert source.fetch_count == 1
    assert first.selection is not None
    assert second.selection is not None
    assert second.selection_idempotent_replay is True
    assert second.intelligence_idempotent_replay is True
    assert first.selection.live_review_count == 0
    rows = CopyabilitySelectionRepository(database).current_status_rows(
        "polycop",
        SelectionStatus.WATCHLIST,
        limit=10,
    )
    assert all(len(row.wallet_id) == 64 for row in rows)
    assert all(not row.wallet_id.startswith("0x") for row in rows)
    CopyabilitySelectionRepository(database).prune_history(
        cutoff=now + timedelta(days=400)
    )
    assert CopyabilitySelectionRepository(database).current_run("polycop") is not None


class _PipelineSource:
    source_id = "polycop"

    def __init__(self, dataset: CandidateWalletDataset) -> None:
        self.dataset = dataset
        self.fetch_count = 0

    async def fetch_snapshot(self) -> CandidateWalletDataset:
        self.fetch_count += 1
        return self.dataset
