from __future__ import annotations

import base64
import gzip
import hashlib
import random
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from polysia.application.ports.candidate_wallets import (
    CandidateSourceReadError,
    CandidateSourceSchemaError,
)
from polysia.application.services.candidate_wallet_sync import (
    CandidateHealthLevel,
    CandidateWalletSyncError,
    CandidateWalletSyncService,
)
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord
from polysia.storage.wallet_intelligence import WalletIntelligenceRepository


class FakeSource:
    source_id = "polycop"

    def __init__(self, result: CandidateWalletDataset | Exception) -> None:
        self.result = result
        self.call_count = 0

    async def fetch_snapshot(self) -> CandidateWalletDataset:
        self.call_count += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeReadError(CandidateSourceReadError):
    error_code = "test_read_failed"


def _dataset(now: datetime, address: str = "0x" + "1" * 40) -> CandidateWalletDataset:
    row_digest = hashlib.sha256(address.encode()).hexdigest()
    return CandidateWalletDataset(
        source_id="polycop",
        schema_version="test-v1",
        fetched_at=now,
        source_total_pages=1,
        records=(
            CandidateWalletRecord(
                external_wallet_id=address,
                source_rank=1,
                source_page=1,
                metrics={"score": "99"},
                row_digest=row_digest,
            ),
        ),
        dataset_digest=hashlib.sha256(row_digest.encode()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_service_reuses_successful_schedule_without_another_network_read(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    source = FakeSource(_dataset(now))
    service = CandidateWalletSyncService(
        source,
        WalletIntelligenceRepository(tmp_path / "wallet-intelligence.sqlite3"),
        clock=lambda: now,
    )

    first = await service.sync(scheduled_for=date(2026, 8, 22))
    replay = await service.sync(scheduled_for=date(2026, 8, 22))

    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert source.call_count == 1


@pytest.mark.asyncio
async def test_schema_change_is_redacted_and_quarantined_without_current_promotion(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    address = "0x" + "a" * 40
    source = FakeSource(
        CandidateSourceSchemaError(
            "row_fields_changed",
            {
                "address": address,
                address: "protected-key",
                "embedded": f"prefix:{address.upper()}",
                "new_field": 1,
            },
            "f" * 64,
        )
    )
    database = tmp_path / "wallet-intelligence.sqlite3"
    service = CandidateWalletSyncService(
        source,
        WalletIntelligenceRepository(database),
        clock=lambda: now,
    )

    with pytest.raises(CandidateWalletSyncError) as raised:
        await service.sync(scheduled_for=now.date())

    assert raised.value.error_code == "source_schema_changed"
    connection = sqlite3.connect(database)
    try:
        status = connection.execute("SELECT status FROM candidate_source_runs").fetchone()[0]
        sample = connection.execute(
            "SELECT sample_gzip FROM candidate_source_quarantines"
        ).fetchone()[0]
        current_count = connection.execute(
            "SELECT COUNT(*) FROM candidate_current_snapshots"
        ).fetchone()[0]
    finally:
        connection.close()
    assert status == "quarantined"
    decompressed = gzip.decompress(sample).lower()
    assert address.encode() not in decompressed
    assert current_count == 0


@pytest.mark.asyncio
async def test_oversized_quarantine_sample_uses_bounded_fallback_and_closes_run(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    payload = base64.b64encode(random.Random(0).randbytes(85_000)).decode("ascii")
    database = tmp_path / "wallet-intelligence.sqlite3"
    service = CandidateWalletSyncService(
        FakeSource(CandidateSourceSchemaError("changed", {"payload": payload}, "f" * 64)),
        WalletIntelligenceRepository(database),
        clock=lambda: now,
    )

    with pytest.raises(CandidateWalletSyncError, match="quarantined"):
        await service.sync(scheduled_for=now.date())

    connection = sqlite3.connect(database)
    try:
        status = connection.execute("SELECT status FROM candidate_source_runs").fetchone()[0]
        sample = connection.execute(
            "SELECT sample_gzip FROM candidate_source_quarantines"
        ).fetchone()[0]
    finally:
        connection.close()
    assert status == "quarantined"
    assert b'"sample_omitted":true' in gzip.decompress(sample)
    assert len(sample) <= 65_536


@pytest.mark.asyncio
async def test_read_failure_marks_run_and_health_becomes_warning_with_fresh_last_good(
    tmp_path: Path,
) -> None:
    first_time = datetime(2026, 8, 22, tzinfo=UTC)
    clock_value = [first_time]
    database = tmp_path / "wallet-intelligence.sqlite3"
    repository = WalletIntelligenceRepository(database)
    good_source = FakeSource(_dataset(first_time))
    good_service = CandidateWalletSyncService(
        good_source,
        repository,
        clock=lambda: clock_value[0],
    )
    await good_service.sync(scheduled_for=first_time.date())
    clock_value[0] = first_time + timedelta(days=1)
    failing_service = CandidateWalletSyncService(
        FakeSource(FakeReadError("unsafe 0x" + "a" * 40)),
        repository,
        clock=lambda: clock_value[0],
    )

    with pytest.raises(CandidateWalletSyncError) as raised:
        await failing_service.sync(scheduled_for=clock_value[0].date())
    health = failing_service.health()

    assert health.level is CandidateHealthLevel.WARNING
    assert "latest_run_failed" in health.reasons
    assert health.state.current_record_count == 1
    assert "0x" not in str(raised.value).lower()


@pytest.mark.asyncio
async def test_quarantine_retention_runs_during_persistent_schema_failures(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    clock_value = [start]
    database = tmp_path / "wallet-intelligence.sqlite3"
    service = CandidateWalletSyncService(
        FakeSource(CandidateSourceSchemaError("changed", {"field": 1}, "f" * 64)),
        WalletIntelligenceRepository(database),
        clock=lambda: clock_value[0],
    )

    for day_offset in range(10):
        clock_value[0] = start + timedelta(days=day_offset)
        with pytest.raises(CandidateWalletSyncError):
            await service.sync(scheduled_for=clock_value[0].date(), quarantine_days=7)

    connection = sqlite3.connect(database)
    try:
        count, oldest = connection.execute(
            "SELECT COUNT(*), MIN(captured_at) FROM candidate_source_quarantines"
        ).fetchone()
    finally:
        connection.close()
    assert count == 8
    assert datetime.fromisoformat(oldest) >= start + timedelta(days=2)


def test_health_escalates_at_36_and_72_hours(tmp_path: Path) -> None:
    accepted = datetime(2026, 8, 20, tzinfo=UTC)
    clock_value = [accepted]
    source = FakeSource(_dataset(accepted))
    service = CandidateWalletSyncService(
        source,
        WalletIntelligenceRepository(tmp_path / "wallet-intelligence.sqlite3"),
        clock=lambda: clock_value[0],
    )
    import asyncio

    asyncio.run(service.sync(scheduled_for=accepted.date()))
    clock_value[0] = accepted + timedelta(hours=37)
    assert service.health().level is CandidateHealthLevel.WARNING
    clock_value[0] = accepted + timedelta(hours=73)
    assert service.health().level is CandidateHealthLevel.CRITICAL


@pytest.mark.asyncio
async def test_storage_serialization_failure_cannot_publish_partial_snapshot(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    address = "0x" + "1" * 40
    row_digest = hashlib.sha256(address.encode()).hexdigest()
    invalid_dataset = CandidateWalletDataset(
        source_id="polycop",
        schema_version="test-v1",
        fetched_at=now,
        source_total_pages=1,
        records=(
            CandidateWalletRecord(
                external_wallet_id=address,
                source_rank=1,
                source_page=1,
                metrics={"invalid": {"not-json"}},  # type: ignore[dict-item]
                row_digest=row_digest,
            ),
        ),
        dataset_digest=hashlib.sha256(row_digest.encode()).hexdigest(),
    )
    database = tmp_path / "wallet-intelligence.sqlite3"
    service = CandidateWalletSyncService(
        FakeSource(invalid_dataset),
        WalletIntelligenceRepository(database),
        clock=lambda: now,
    )

    with pytest.raises(CandidateWalletSyncError) as raised:
        await service.sync(scheduled_for=now.date())

    assert raised.value.error_code == "internal_ingestion_error"
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM candidate_wallet_snapshots"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM candidate_wallet_snapshot_rows"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM candidate_source_runs"
        ).fetchone()[0] == "failed"
    finally:
        connection.close()
