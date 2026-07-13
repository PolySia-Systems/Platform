from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polysia.adapters.polymarket.geoblock import GeoblockStatus
from polysia.adapters.polymarket.lifecycle_monitoring import (
    PolymarketLifecycleHealthReader,
    PolymarketServerTimeError,
    PolymarketServerTimeReader,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class FakeServerTimeReader:
    def __init__(self, drift: Decimal | None = Decimal("0.25")) -> None:
        self.drift = drift

    async def read_clock_drift(self) -> Decimal:
        if self.drift is None:
            raise PolymarketServerTimeError("unavailable")
        return self.drift


class FakeGeoblockCheck:
    def __init__(self, status: GeoblockStatus) -> None:
        self.status = status

    async def check(self) -> GeoblockStatus:
        return self.status


def test_server_time_reader_uses_request_midpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    moments = iter(
        (
            datetime.fromtimestamp(1000, tz=UTC),
            datetime.fromtimestamp(1000.2, tz=UTC),
        )
    )
    monkeypatch.setattr(
        "polysia.adapters.polymarket.lifecycle_monitoring.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"1001"),
    )

    drift = PolymarketServerTimeReader(clock=lambda: next(moments)).read_clock_drift_sync()

    assert drift == Decimal("0.9")


def test_server_time_reader_rejects_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "polysia.adapters.polymarket.lifecycle_monitoring.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"not-a-timestamp"),
    )

    with pytest.raises(PolymarketServerTimeError, match="invalid"):
        PolymarketServerTimeReader().read_clock_drift_sync()


@pytest.mark.asyncio
async def test_lifecycle_health_reader_reports_clock_and_geoblock() -> None:
    checked_at = datetime(2026, 7, 13, 10, tzinfo=UTC)
    reader = PolymarketLifecycleHealthReader(
        server_time_reader=FakeServerTimeReader(Decimal("-1.25")),  # type: ignore[arg-type]
        geoblock_check=FakeGeoblockCheck(  # type: ignore[arg-type]
            GeoblockStatus(
                status="allowed",
                checked_at=checked_at,
                blocked=False,
            )
        ),
        clock=lambda: checked_at,
    )

    health = await reader.read_health()

    assert health.server_time_readable is True
    assert health.clock_drift_seconds == Decimal("-1.25")
    assert health.geoblock_status == "allowed"
    assert health.geoblocked is False
    assert health.error_types == ()


@pytest.mark.asyncio
async def test_lifecycle_health_reader_sanitizes_degraded_reads() -> None:
    checked_at = datetime(2026, 7, 13, 10, tzinfo=UTC)
    reader = PolymarketLifecycleHealthReader(
        server_time_reader=FakeServerTimeReader(None),  # type: ignore[arg-type]
        geoblock_check=FakeGeoblockCheck(  # type: ignore[arg-type]
            GeoblockStatus(
                status="error",
                checked_at=checked_at,
                blocked=None,
                error_type="TimeoutError",
            )
        ),
        clock=lambda: checked_at,
    )

    health = await reader.read_health()

    assert health.server_time_readable is False
    assert health.clock_drift_seconds is None
    assert health.geoblock_status == "error"
    assert set(health.error_types) == {"PolymarketServerTimeError", "TimeoutError"}
