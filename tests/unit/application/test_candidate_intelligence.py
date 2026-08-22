from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import polysia.application.services.candidate_intelligence as intelligence_module
from polysia.application.ports.candidate_intelligence import (
    CandidatePipelineBusyError,
    CandidatePipelineLeaseLostError,
)
from polysia.application.ports.candidate_wallets import CandidateSourceReadError
from polysia.application.services.candidate_intelligence import (
    PIPELINE_LEASE_RESOURCE,
    CandidateIntelligenceError,
    CandidateIntelligenceService,
    WalletIntelligencePipelineService,
)
from polysia.application.services.candidate_wallet_sync import CandidateWalletSyncError
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository


def _dataset(
    rows: tuple[tuple[str, int, str | None], ...],
    *,
    fetched_at: datetime,
    source_id: str = "polycop",
) -> CandidateWalletDataset:
    records = []
    for address, rank, score in rows:
        metrics = {"roi": "1.25"}
        if score is not None:
            metrics["score"] = score
        records.append(
            CandidateWalletRecord(
                external_wallet_id=address,
                source_rank=rank,
                source_page=1,
                metrics=metrics,
                row_digest=hashlib.sha256(f"{address}:{rank}:{score}".encode()).hexdigest(),
            )
        )
    record_tuple = tuple(records)
    return CandidateWalletDataset(
        source_id=source_id,
        schema_version="test-v1",
        fetched_at=fetched_at,
        source_total_pages=1,
        records=record_tuple,
        dataset_digest=hashlib.sha256(
            "\n".join(record.row_digest for record in record_tuple).encode()
        ).hexdigest(),
    )


def _store_snapshot(
    repository: WalletIntelligenceRepository,
    rows: tuple[tuple[str, int, str | None], ...],
    *,
    at: datetime,
    source_id: str = "polycop",
) -> str:
    run = repository.start_run(source_id, scheduled_for=at.date(), started_at=at)
    stored = repository.complete_run(
        run,
        _dataset(rows, fetched_at=at, source_id=source_id),
        accepted_at=at,
    )
    return stored.snapshot_id


def _lease(repository: CandidateIntelligenceRepository, at: datetime, owner: str = "owner-1"):
    return repository.acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id=owner,
        acquired_at=at,
        lease_duration=timedelta(minutes=30),
    )


class _PipelineSource:
    source_id = "polycop"

    def __init__(self, dataset: CandidateWalletDataset) -> None:
        self.dataset = dataset
        self.fetch_count = 0
        self.fail = False

    async def fetch_snapshot(self) -> CandidateWalletDataset:
        self.fetch_count += 1
        if self.fail:
            raise CandidateSourceReadError("test read failure")
        return self.dataset


def test_cold_start_is_ready_but_windowed_features_remain_null(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    captured_at = datetime.now(UTC) - timedelta(minutes=5)
    address = "0x" + "A" * 40
    snapshot_id = _store_snapshot(
        source_store,
        ((address, 1, "88.5"),),
        at=captured_at,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    now = captured_at + timedelta(minutes=5)
    outcome = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now,
    ).process_snapshot("polycop", snapshot_id, lease=_lease(store, now))

    assert outcome.idempotent_replay is False
    assert outcome.pool.selected_count == 1
    pool = store.current_pool("polycop", selected_only=True)
    assert pool[0].candidate_rank == 1
    assert pool[0].data_readiness_status.value == "READY"
    connection = sqlite3.connect(database)
    try:
        feature = connection.execute(
            "SELECT rank_delta_1d, rank_delta_7d, rank_delta_30d, rank_volatility, "
            "score_volatility FROM candidate_trading_pool_current"
        ).fetchone()
        canonical = connection.execute(
            "SELECT normalized_address FROM canonical_wallets"
        ).fetchone()[0]
    finally:
        connection.close()
    assert feature == (None, None, None, None, None)
    assert canonical == address.lower()


def test_point_in_time_deltas_persistence_and_deterministic_ranking(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    current_at = datetime.now(UTC) - timedelta(minutes=1)
    first = current_at - timedelta(days=33)
    address_a = "0x" + "1" * 40
    address_b = "0x" + "2" * 40
    _store_snapshot(
        source_store,
        ((address_a, 1, "70"), (address_b, 2, "70")),
        at=first,
    )
    _store_snapshot(
        source_store,
        ((address_b, 1, "75"), (address_a, 2, "75")),
        at=first + timedelta(days=25),
    )
    snapshot_id = _store_snapshot(
        source_store,
        ((address_a, 1, "80"), (address_b, 2, "80")),
        at=current_at,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    now = current_at + timedelta(minutes=1)
    service = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now,
    )
    lease = _lease(store, now)
    first_outcome = service.process_snapshot("polycop", snapshot_id, lease=lease)
    replay = service.process_snapshot("polycop", snapshot_id, lease=lease)

    assert replay.idempotent_replay is True
    assert replay.pool.run_id == first_outcome.pool.run_id
    pool = store.current_pool("polycop", selected_only=True)
    assert [row.source_rank for row in pool] == [1, 2]
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT source_rank, observation_count, eligible_snapshot_count, "
            "presence_ratio, rank_delta_7d, rank_delta_30d, score_delta_7d, "
            "score_delta_30d, rank_volatility FROM candidate_trading_pool_current "
            "ORDER BY source_rank"
        ).fetchall()
    finally:
        connection.close()
    assert rows[0][1:4] == (3, 3, "1")
    assert rows[0][4:8] == (1, 0, "5", "10")
    assert rows[0][8] is not None


def test_readiness_is_separate_from_policy_and_missing_score_is_watchlisted(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    captured_at = datetime.now(UTC) - timedelta(minutes=1)
    snapshot_id = _store_snapshot(
        source_store,
        (("0x" + "1" * 40, 1, "90"), ("0x" + "2" * 40, 2, None)),
        at=captured_at,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    now = captured_at + timedelta(minutes=1)
    CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now,
    ).process_snapshot("polycop", snapshot_id, lease=_lease(store, now))

    rows = store.current_pool("polycop")
    assert [(row.data_readiness_status.value, row.candidate_status.value) for row in rows] == [
        ("READY", "SELECTED"),
        ("PARTIAL", "WATCHLIST"),
    ]
    assert rows[0].candidate_rank == 1
    assert rows[1].candidate_rank is None


def test_stale_evidence_is_watchlisted_without_destroying_feature_values(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    captured_at = datetime.now(UTC) - timedelta(hours=40)
    snapshot_id = _store_snapshot(
        source_store,
        (("0x" + "1" * 40, 1, "90"),),
        at=captured_at,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    now = captured_at + timedelta(hours=40)
    outcome = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now,
    ).process_snapshot("polycop", snapshot_id, lease=_lease(store, now))

    assert outcome.pool.stale_count == 1
    assert outcome.pool.watchlist_count == 1
    row = store.current_pool("polycop")[0]
    assert row.source_score is not None
    assert row.candidate_rank is None


def test_idempotent_replay_keeps_history_immutable_but_pool_expires_in_real_time(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    wall_now = datetime.now(UTC)
    captured_at = wall_now - timedelta(hours=40)
    snapshot_id = _store_snapshot(
        source_store,
        (("0x" + "1" * 40, 1, "90"),),
        at=captured_at,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    clock = [captured_at + timedelta(minutes=1)]
    service = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: clock[0],
    )
    lease = _lease(store, clock[0])

    first = service.process_snapshot("polycop", snapshot_id, lease=lease)
    clock[0] = wall_now
    replay = service.process_snapshot("polycop", snapshot_id, lease=lease)

    assert first.pool.ready_count == 1
    assert first.pool.selected_count == 1
    assert replay.idempotent_replay is True
    assert replay.pool.run_id == first.pool.run_id
    assert store.current_pool("polycop", selected_only=True) == ()
    effective = store.current_pool("polycop")[0]
    assert effective.data_readiness_status.value == "STALE"
    assert effective.candidate_status.value == "WATCHLIST"
    assert effective.candidate_rank is None
    assert effective.data_age_seconds >= 40 * 60 * 60 - 10
    connection = sqlite3.connect(database)
    try:
        calculated = connection.execute(
            "SELECT calculated_data_readiness_status, calculated_candidate_status, "
            "calculated_candidate_rank FROM candidate_trading_pool_current"
        ).fetchone()
    finally:
        connection.close()
    assert calculated == ("READY", "SELECTED", 1)


def test_policy_version_change_creates_new_immutable_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    snapshot_id = _store_snapshot(
        source_store,
        (("0x" + "1" * 40, 1, "90"),),
        at=now,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    lease = _lease(store, now + timedelta(minutes=1))
    service = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now + timedelta(minutes=1),
    )
    first = service.process_snapshot("polycop", snapshot_id, lease=lease)
    monkeypatch.setattr(intelligence_module, "CANDIDATE_POLICY_VERSION", "v2-test")
    second = service.process_snapshot("polycop", snapshot_id, lease=lease)

    assert second.idempotent_replay is False
    assert second.pool.run_id != first.pool.run_id
    assert second.pool.key.policy_version == "v2-test"
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM candidate_intelligence_runs WHERE status = 'succeeded'"
        ).fetchone() == (2,)
    finally:
        connection.close()


def test_same_wallet_from_two_sources_maps_to_one_canonical_identity(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    address = "0x" + "A" * 40
    first_snapshot = _store_snapshot(
        source_store,
        ((address, 1, "90"),),
        at=now,
        source_id="polycop",
    )
    second_snapshot = _store_snapshot(
        source_store,
        ((address.lower(), 1, "91"),),
        at=now,
        source_id="second-source",
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    service = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon", "second-source": "polygon"},
        clock=lambda: now + timedelta(minutes=1),
    )
    first_lease = _lease(store, now + timedelta(minutes=1))
    service.process_snapshot("polycop", first_snapshot, lease=first_lease)
    store.release_lease(first_lease)
    second_lease = _lease(store, now + timedelta(minutes=2), owner="owner-2")
    service.process_snapshot("second-source", second_snapshot, lease=second_lease)

    connection = sqlite3.connect(database)
    try:
        canonical_count = connection.execute("SELECT COUNT(*) FROM canonical_wallets").fetchone()[0]
        link_count = connection.execute("SELECT COUNT(*) FROM wallet_source_links").fetchone()[0]
    finally:
        connection.close()
    assert canonical_count == 1
    assert link_count == 2


def test_database_lease_serializes_processes_and_fences_stale_owner(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    snapshot_id = _store_snapshot(
        source_store,
        (("0x" + "1" * 40, 1, "90"),),
        at=now,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    old = store.acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="old-owner",
        acquired_at=now,
        lease_duration=timedelta(seconds=10),
    )
    with pytest.raises(CandidatePipelineBusyError):
        store.acquire_lease(
            PIPELINE_LEASE_RESOURCE,
            owner_id="concurrent-owner",
            acquired_at=now + timedelta(seconds=5),
            lease_duration=timedelta(seconds=10),
        )
    replacement = store.acquire_lease(
        PIPELINE_LEASE_RESOURCE,
        owner_id="replacement-owner",
        acquired_at=now + timedelta(seconds=11),
        lease_duration=timedelta(minutes=30),
    )
    assert replacement.fencing_token == old.fencing_token + 1
    with pytest.raises(CandidatePipelineLeaseLostError):
        store.renew_lease(
            old,
            renewed_at=now + timedelta(seconds=12),
            lease_duration=timedelta(minutes=30),
        )
    service = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now + timedelta(seconds=12),
    )
    with pytest.raises(CandidatePipelineLeaseLostError):
        service.process_snapshot("polycop", snapshot_id, lease=old)
    assert store.current_run("polycop") is None


def test_released_lease_preserves_monotonic_fencing_token(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    first = _lease(store, now, owner="first-owner")

    store.release_lease(first)
    second = _lease(store, now, owner="second-owner")

    assert second.fencing_token == first.fencing_token + 1


def test_stage2_failure_preserves_last_known_good_pool(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    first_snapshot = _store_snapshot(
        source_store,
        (("0x" + "1" * 40, 1, "90"),),
        at=now,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    service = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now + timedelta(minutes=1),
    )
    first_lease = _lease(store, now + timedelta(minutes=1))
    healthy = service.process_snapshot("polycop", first_snapshot, lease=first_lease)
    store.release_lease(first_lease)
    bad_snapshot = _store_snapshot(
        source_store,
        (("not-an-address", 1, "91"),),
        at=now + timedelta(days=1),
    )
    failed_lease = _lease(store, now + timedelta(days=1, minutes=1), owner="owner-2")
    with pytest.raises(CandidateIntelligenceError):
        service = CandidateIntelligenceService(
            store,
            chain_by_source={"polycop": "polygon"},
            clock=lambda: now + timedelta(days=1, minutes=1),
        )
        service.process_snapshot("polycop", bad_snapshot, lease=failed_lease)

    assert store.current_run("polycop").run_id == healthy.pool.run_id  # type: ignore[union-attr]
    assert len(store.current_pool("polycop")) == 1


def test_oversized_current_snapshot_fails_before_loading_retained_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    source_store = WalletIntelligenceRepository(database)
    source_store.initialize()
    now = datetime(2026, 8, 22, tzinfo=UTC)
    healthy_snapshot = _store_snapshot(
        source_store,
        (("0x" + "1" * 40, 1, "90"),),
        at=now,
    )
    store = CandidateIntelligenceRepository(database)
    store.initialize()
    healthy_lease = _lease(store, now + timedelta(minutes=1))
    healthy = CandidateIntelligenceService(
        store,
        chain_by_source={"polycop": "polygon"},
        clock=lambda: now + timedelta(minutes=1),
    ).process_snapshot("polycop", healthy_snapshot, lease=healthy_lease)
    store.release_lease(healthy_lease)
    oversized_snapshot = _store_snapshot(
        source_store,
        (("0x" + "2" * 40, 1, "91"), ("0x" + "3" * 40, 2, "89")),
        at=now + timedelta(days=1),
    )
    oversized_lease = _lease(
        store,
        now + timedelta(days=1, minutes=1),
        owner="oversized-owner",
    )
    history_loaded = False

    def unexpected_history_load(
        source_id: str,
        source_snapshot_id: str,
        wallet_keys: tuple[str, ...],
    ) -> dict[str, object]:
        nonlocal history_loaded
        history_loaded = True
        raise AssertionError("retained history must not load after the current-wallet guard")

    monkeypatch.setattr(intelligence_module, "MAX_CURRENT_WALLETS", 1)
    monkeypatch.setattr(store, "load_wallet_histories", unexpected_history_load)
    with pytest.raises(CandidateIntelligenceError, match="wallet limit"):
        CandidateIntelligenceService(
            store,
            chain_by_source={"polycop": "polygon"},
            clock=lambda: now + timedelta(days=1, minutes=1),
        ).process_snapshot("polycop", oversized_snapshot, lease=oversized_lease)

    assert history_loaded is False
    assert store.current_run("polycop").run_id == healthy.pool.run_id  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_pipeline_fetches_on_first_start_then_reuses_fresh_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    now = datetime(2026, 8, 22, tzinfo=UTC)
    source = _PipelineSource(
        _dataset((("0x" + "1" * 40, 1, "90"),), fetched_at=now)
    )
    clock = [now]
    source_store = WalletIntelligenceRepository(database)
    intelligence_store = CandidateIntelligenceRepository(database)
    pipeline = WalletIntelligencePipelineService(
        source,
        source_store,
        intelligence_store,
        chain="polygon",
        clock=lambda: clock[0],
    )

    first = await pipeline.ensure(scheduled_for=now.date())
    clock[0] += timedelta(hours=1)
    second = await pipeline.ensure(scheduled_for=now.date())

    assert source.fetch_count == 1
    assert first.source_refreshed is True
    assert second.source_refreshed is False
    assert second.intelligence_idempotent_replay is True
    assert second.pool.run_id == first.pool.run_id


@pytest.mark.asyncio
async def test_stage1_refresh_failure_preserves_last_known_good_candidate_pool(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    now = datetime(2026, 8, 22, tzinfo=UTC)
    source = _PipelineSource(
        _dataset((("0x" + "1" * 40, 1, "90"),), fetched_at=now)
    )
    clock = [now]
    source_store = WalletIntelligenceRepository(database)
    intelligence_store = CandidateIntelligenceRepository(database)
    pipeline = WalletIntelligencePipelineService(
        source,
        source_store,
        intelligence_store,
        chain="polygon",
        clock=lambda: clock[0],
    )
    healthy = await pipeline.ensure(scheduled_for=now.date())
    source.fail = True
    clock[0] += timedelta(days=2)

    with pytest.raises(CandidateWalletSyncError):
        await pipeline.ensure(scheduled_for=clock[0].date())

    current = intelligence_store.current_run("polycop")
    assert current is not None
    assert current.run_id == healthy.pool.run_id
    assert len(intelligence_store.current_pool("polycop")) == 1
