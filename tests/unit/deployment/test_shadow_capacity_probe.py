from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.deployment.shadow_capacity_probe import probe_shadow_path
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("event_count", [0, 1])
async def test_shadow_probe_uses_isolated_writer_and_never_self_certifies(
    tmp_path: Path, event_count: int,
) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    snapshot = ContinuousSelectionSnapshot.create(
        source_id="polycop", selection_run_id="probe-selection",
        source_snapshot_id="source", feature_set_version="copyability-v0.1",
        policy_id="copyability-selection", policy_version="v0.1",
        ranking_version="percentile-alpha-stress-v0.1", published_at=now,
        candidates=(ProtectedShadowCandidate(
            "wallet-1", "0x" + "1" * 40, ("SHADOW_ALPHA",), alpha_rank=1,
        ),),
    )
    config = ContinuousShadowConfig(
        runtime_version="continuous-shadow-runtime-v2", code_sha="a" * 40,
        wallet_count=1, selection_policy="shadow-alpha-ranked-v2",
    )
    seen_paths: list[Path] = []
    polls = 0

    class Service:
        def selection_for_isolated_probe(self, _source: str) -> ContinuousSelectionSnapshot:
            return snapshot

        async def poll(self, _source: str) -> object:
            nonlocal polls
            polls += 1
            return SimpleNamespace(
                new_event_count=event_count if polls == 2 else 0,
                simulated_count=event_count if polls == 2 else 0,
                unknown_count=0,
                request_telemetry={"data:/trades": {"requests": 1}},
            )

    def factory(path: Path) -> object:
        assert path.parent != tmp_path
        seen_paths.append(path)
        return Service()

    elapsed = [0.0]

    async def sleep(seconds: float) -> None:
        elapsed[0] += seconds

    result = await probe_shadow_path(
        "polycop", factory, config=config, duration_seconds=60,
        poll_interval_seconds=30, scratch_root=tmp_path, clock=lambda: now,
        monotonic=lambda: elapsed[0], sleeper=sleep,
    )
    assert result["polls_observed"] == 2
    assert result["new_event_count"] == event_count
    assert result["persisted_event_count"] == 0
    assert result["ledger_balanced"] is True
    assert result["status"] == (
        "INSUFFICIENT_NONEMPTY_EVIDENCE" if event_count == 0 else "FAILED"
    )
    assert "PASS" not in str(result["status"])
    assert seen_paths and not seen_paths[0].exists()
