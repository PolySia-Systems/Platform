from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from polysia.deployment.wallet_capacity_probe import probe_wallet_workload


class _SlowSource:
    async def run(self, *, run_id: str, deadline: datetime):
        del run_id, deadline
        await asyncio.sleep(30)
        if False:
            yield None

    def health_snapshot(self) -> dict[str, object]:
        return {"status": "not_complete"}


@pytest.mark.asyncio
async def test_capacity_probe_enforces_hard_timeout_without_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysia.deployment.wallet_capacity_probe as module

    original_timeout = asyncio.timeout
    monkeypatch.setattr(module.asyncio, "timeout", lambda _seconds: original_timeout(0.01))
    result = await probe_wallet_workload(
        (_SlowSource(),), {"wallet_count": 5}, requested_count=5,
        duration_seconds=30, clock=lambda: datetime(2026, 9, 28, tzinfo=UTC),
    )
    assert result["timed_out"] is True
    assert result["status"] == "CANDIDATE_ONLY"
    assert result["source_results"] == []
