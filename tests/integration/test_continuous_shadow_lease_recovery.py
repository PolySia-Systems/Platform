from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from polysia.application.ports.candidate_intelligence import (
    CandidatePipelineBusyError,
    CandidatePipelineLeaseLostError,
)
from polysia.application.services.continuous_shadow import (
    CONTINUOUS_SHADOW_LEASE_RESOURCE,
    ContinuousShadowError,
    ContinuousShadowService,
)
from polysia.application.services.continuous_shadow_failures import (
    FAILURE_CATEGORY_SQLITE_BUSY,
    FAILURE_STAGE_PERSIST,
    FAILURE_STAGE_RELEASE_LEASE,
)
from polysia.storage.continuous_shadow import (
    ContinuousShadowLeaseRepository,
    ContinuousShadowRepository,
)
from polysia.storage.dynamic_shadow import DynamicShadowRepository
from tests.integration.test_continuous_shadow_portfolio import (
    NOW,
    _add_alpha_membership_for_first_wallet,
    _Clock,
    _MarketPort,
    _Scenario,
    _seed_stage3,
    _service,
    _shadow_database,
    _Source,
)


class _ReleaseBusyOnce:
    def __init__(self, inner: ContinuousShadowLeaseRepository) -> None:
        self._inner = inner
        self.remaining = 1

    def initialize(self) -> None:
        self._inner.initialize()

    def acquire_lease(self, *args: object, **kwargs: object):
        return self._inner.acquire_lease(*args, **kwargs)

    def renew_lease(self, *args: object, **kwargs: object):
        return self._inner.renew_lease(*args, **kwargs)

    def release_lease(self, lease: object) -> None:
        if self.remaining:
            self.remaining -= 1
            raise sqlite3.OperationalError("database is locked")
        self._inner.release_lease(lease)


class _PersistBusyOnce:
    def __init__(self, inner: ContinuousShadowRepository) -> None:
        self._inner = inner
        self.remaining = 1

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def complete_poll(self, *args: object, **kwargs: object):
        if self.remaining:
            self.remaining -= 1
            raise sqlite3.OperationalError("database is locked")
        return self._inner.complete_poll(*args, **kwargs)


class _PersistAndFailPollBusyOnce(_PersistBusyOnce):
    def __init__(self, inner: ContinuousShadowRepository) -> None:
        super().__init__(inner)
        self.fail_remaining = 1

    def fail_poll(self, *args: object, **kwargs: object) -> None:
        if self.fail_remaining:
            self.fail_remaining -= 1
            raise sqlite3.OperationalError("database is locked")
        self._inner.fail_poll(*args, **kwargs)


def _seeded_service(tmp_path: Path) -> tuple[Path, ContinuousShadowService, _Clock, _Scenario]:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    _add_alpha_membership_for_first_wallet(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    service = _service(database, scenario, _MarketPort(clock), clock)
    service.start("polycop")
    return database, service, clock, scenario


def _health(database: Path, clock: _Clock):
    return ContinuousShadowRepository(_shadow_database(database)).health(
        "polycop",
        now=clock.value,
        poll_interval_seconds=60,
    )


@pytest.mark.asyncio
async def test_release_lease_sqlite_busy_same_owner_recovers_before_expiry(
    tmp_path: Path,
) -> None:
    database, service, clock, scenario = _seeded_service(tmp_path)
    owner = service.lease_owner_id
    service._lease_port = _ReleaseBusyOnce(
        ContinuousShadowLeaseRepository(_shadow_database(database))
    )
    other = _service(database, scenario, _MarketPort(clock), clock)

    with pytest.raises(ContinuousShadowError) as raised:
        await service.poll("polycop")
    assert raised.value.error_code == FAILURE_CATEGORY_SQLITE_BUSY
    assert raised.value.processing_stage == FAILURE_STAGE_RELEASE_LEASE
    assert service.lease_owner_id == owner

    with pytest.raises(CandidatePipelineBusyError):
        await other.poll("polycop")

    clock.value = NOW + timedelta(minutes=5)
    recovered = await service.poll("polycop")
    assert service.lease_owner_id == owner
    assert recovered.duplicate_count >= 0
    health = _health(database, clock)
    assert health.ledger_balanced is True
    assert health.duplicate_processing_count == 0


@pytest.mark.asyncio
async def test_other_worker_cannot_steal_valid_lease_until_expiry(tmp_path: Path) -> None:
    database, service, clock, scenario = _seeded_service(tmp_path)
    service._lease_port = _ReleaseBusyOnce(
        ContinuousShadowLeaseRepository(_shadow_database(database))
    )
    with pytest.raises(ContinuousShadowError):
        await service.poll("polycop")
    other = _service(database, scenario, _MarketPort(clock), clock)
    with pytest.raises(CandidatePipelineBusyError):
        await other.poll("polycop")
    clock.value = NOW + timedelta(minutes=31)
    taken = await other.poll("polycop")
    assert taken is not None
    health = _health(database, clock)
    assert health.ledger_balanced is True
    assert health.duplicate_processing_count == 0


@pytest.mark.asyncio
async def test_persist_sqlite_busy_keeps_prior_ledger_and_next_poll_succeeds(
    tmp_path: Path,
) -> None:
    database, service, clock, _scenario = _seeded_service(tmp_path)
    service._store = _PersistBusyOnce(
        ContinuousShadowRepository(_shadow_database(database))
    )
    with pytest.raises(ContinuousShadowError) as raised:
        await service.poll("polycop")
    assert raised.value.error_code == FAILURE_CATEGORY_SQLITE_BUSY
    assert raised.value.processing_stage == FAILURE_STAGE_PERSIST
    clock.value = NOW + timedelta(minutes=1)
    recovered = await service.poll("polycop")
    assert recovered is not None
    health = _health(database, clock)
    assert health.ledger_balanced is True
    assert health.duplicate_processing_count == 0


@pytest.mark.asyncio
async def test_orphaned_poll_is_recovered_by_the_next_fenced_poll(
    tmp_path: Path,
) -> None:
    database, service, clock, _scenario = _seeded_service(tmp_path)
    service._store = _PersistAndFailPollBusyOnce(
        ContinuousShadowRepository(_shadow_database(database))
    )
    service._lease_port = _ReleaseBusyOnce(
        ContinuousShadowLeaseRepository(_shadow_database(database))
    )

    with pytest.raises(ContinuousShadowError) as raised:
        await service.poll("polycop")
    assert raised.value.error_code == FAILURE_CATEGORY_SQLITE_BUSY
    assert raised.value.processing_stage == FAILURE_STAGE_RELEASE_LEASE

    connection = sqlite3.connect(_shadow_database(database))
    try:
        running = connection.execute(
            "SELECT poll_run_id FROM continuous_shadow_poll_runs WHERE status = 'running'"
        ).fetchone()
    finally:
        connection.close()
    assert running is not None

    clock.value = NOW + timedelta(minutes=1)
    recovered = await service.poll("polycop")
    assert recovered is not None

    connection = sqlite3.connect(_shadow_database(database))
    try:
        orphan = connection.execute(
            "SELECT status, last_error_code FROM continuous_shadow_poll_runs "
            "WHERE poll_run_id = ?",
            (str(running[0]),),
        ).fetchone()
    finally:
        connection.close()
    assert orphan == ("failed", "orphaned_poll")
    health = _health(database, clock)
    assert health.ledger_balanced is True
    assert health.duplicate_processing_count == 0


def test_expired_lease_cannot_recover_or_start_a_poll(tmp_path: Path) -> None:
    database, _service_instance, _clock, _scenario = _seeded_service(tmp_path)
    shadow_database = _shadow_database(database)
    lease_store = ContinuousShadowLeaseRepository(shadow_database)
    lease = lease_store.acquire_lease(
        CONTINUOUS_SHADOW_LEASE_RESOURCE,
        owner_id="continuous-shadow-expired",
        acquired_at=NOW,
        lease_duration=timedelta(minutes=1),
    )
    store = ContinuousShadowRepository(shadow_database)
    experiment = store.active_experiment("polycop")
    assert experiment is not None

    with pytest.raises(CandidatePipelineLeaseLostError):
        store.start_poll(
            lease=lease,
            experiment_id=experiment.experiment_id,
            selection=store.selection_snapshot(experiment.selection_run_id),
            selection_fresh=True,
            window_start=NOW,
            window_end=NOW + timedelta(minutes=1),
            started_at=NOW + timedelta(minutes=2),
        )

    connection = sqlite3.connect(shadow_database)
    try:
        running_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM continuous_shadow_poll_runs WHERE status = 'running'"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert running_count == 0


@pytest.mark.asyncio
async def test_process_local_guard_rejects_overlapping_polls(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    _seed_stage3(database)
    _add_alpha_membership_for_first_wallet(database)
    clock = _Clock(NOW)
    scenario = _Scenario()
    started = asyncio.Event()

    class _SlowSource(_Source):
        async def read_page(self, leader_id: str, *, start_at, end_at, **_: object):
            started.set()
            await asyncio.sleep(0.2)
            return await super().read_page(
                leader_id,
                start_at=start_at,
                end_at=end_at,
            )

    service = ContinuousShadowService(
        ContinuousShadowRepository(_shadow_database(database)),
        DynamicShadowRepository(database),
        ContinuousShadowLeaseRepository(_shadow_database(database)),
        lambda leaders: _SlowSource(dict(leaders), scenario),
        _MarketPort(clock),
        clock=clock,
    )
    service.start("polycop")
    first = asyncio.create_task(service.poll("polycop"))
    await started.wait()
    with pytest.raises(CandidatePipelineBusyError):
        await service.poll("polycop")
    await first
    second = await service.poll("polycop")
    assert second is not None


def test_expired_lease_takeover_increments_fencing_token(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    repo = ContinuousShadowLeaseRepository(database)
    repo.initialize()
    first = repo.acquire_lease(
        CONTINUOUS_SHADOW_LEASE_RESOURCE,
        owner_id="continuous-shadow-aaaa",
        acquired_at=NOW,
        lease_duration=timedelta(minutes=30),
    )
    second = repo.acquire_lease(
        CONTINUOUS_SHADOW_LEASE_RESOURCE,
        owner_id="continuous-shadow-bbbb",
        acquired_at=NOW + timedelta(minutes=31),
        lease_duration=timedelta(minutes=30),
    )
    assert second.fencing_token == first.fencing_token + 1
    with pytest.raises(CandidatePipelineLeaseLostError):
        repo.renew_lease(
            first,
            renewed_at=NOW + timedelta(minutes=32),
            lease_duration=timedelta(minutes=30),
        )


def test_each_service_gets_a_distinct_stable_owner_id(tmp_path: Path) -> None:
    database, service, clock, scenario = _seeded_service(tmp_path)
    first = service.lease_owner_id
    other = _service(database, scenario, _MarketPort(clock), clock)
    assert first.startswith("continuous-shadow-")
    assert first == service.lease_owner_id
    assert other.lease_owner_id != first
