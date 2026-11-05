"""Real persistent native service with deterministic provider boundaries; no time credit."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from polysia.cli_support import native_lifecycle
from polysia.cli_support.native_research import NativeSnapshotPort, observation_watch
from polysia.domain.copytrading import LeaderTradeAction
from polysia.domain.copytrading.native_health import ADMISSION, PURPOSE, RUNTIME
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from tests.integration import test_native_platform_lifecycle as provider_fixture
from tests.integration.test_continuous_shadow_portfolio import _EventSpec
from tests.integration.test_native_platform_lifecycle import ADDRESS, tick

native_runtime = provider_fixture.native_runtime


def health_runtime(runtime):
    root, clock, scenario, old, _, _, calls, faults = runtime
    authority = AcquisitionAuthority(root / "health-authority.sqlite3", replace(
        old.policy, purpose=PURPOSE,
    ))
    authority.initialize()
    watch = observation_watch([(ADDRESS, "b" * 64)], observed_at=clock())
    admission = {"contract": ADMISSION, "purpose": PURPOSE, "mode": "CONTINUOUS",
                 "code_sha": "a" * 40, "cohort_digest": watch["digest"],
                 "policy_digest": authority.policy.digest, "resource_admitted": True,
                 "expires_at": authority.policy.expires_at.isoformat(),
                 "financial_authority": False}
    return root, clock, scenario, authority, watch, admission, calls, faults


@pytest.mark.asyncio
async def test_quiet_start_and_expired_entry_continue_same_period(native_runtime):
    runtime = health_runtime(native_runtime)
    root, clock, scenario, authority, watch, _, calls, faults = runtime
    faults["stale"] = True
    first = await tick(runtime)
    assert first.experiment.config.runtime_version == RUNTIME
    assert first.simulated_count == 0
    assert "persisted_simulations" not in first.experiment.config.capacity_evidence
    first_check = json.loads((root / "refresh.json").read_bytes())
    assert first_check["outcome"] == "HEALTHY_EMPTY"
    assert first_check["eligibility"] is None
    for hours in (3, 4, 7):
        clock.value = first.experiment.started_at + timedelta(hours=hours)
        outcome = await tick(runtime)
        assert outcome.experiment.experiment_id == first.experiment.experiment_id
        assert outcome.simulated_count == 0
    assert len(calls) == 3  # first, 3h, 7h; quiet never refreshes entry evidence
    assert authority.status()["uncertain_requests"] == 0
    assert authority.status()["stopped"] is False
    assert ContinuousShadowRepository(root / "financial.sqlite3").watermark(
        first.experiment.experiment_id,
    ) == clock().replace(microsecond=0)
    assert not NativeSnapshotPort(watch).exposure_increase_allowed(
        watch["candidates"][0]["wallet_id"], at=clock(),
    )


@pytest.mark.asyncio
async def test_real_revalidation_recovers_entry_and_restart_deduplicates(native_runtime):
    runtime = health_runtime(native_runtime)
    root, clock, scenario, _, watch, _, _, faults = runtime
    faults["stale"] = True
    first = await tick(runtime)
    wallet = watch["candidates"][0]["wallet_id"]
    clock.value += timedelta(hours=3)
    faults["stale"] = False
    scenario.events[wallet] = [_EventSpec(
        "health-real-path", LeaderTradeAction.BUY,
        clock() - timedelta(seconds=20), Decimal("0.40"),
    )]
    outcome = await tick(runtime)
    assert outcome.simulated_count == 2  # the two existing virtual portfolios
    evidence = json.loads((root / "refresh.json").read_bytes())["eligibility"]
    port = NativeSnapshotPort(watch, eligibility=evidence)
    assert port.exposure_increase_allowed(wallet, at=clock())
    assert not port.exposure_increase_allowed(wallet, at=clock() + timedelta(hours=4, seconds=1))
    clock.value += timedelta(minutes=2)
    again = await tick(runtime)
    assert again.experiment.experiment_id == first.experiment.experiment_id
    assert again.simulated_count == 0
    store = ContinuousShadowRepository(root / "financial.sqlite3")
    assert store.open_position_count(first.experiment.experiment_id) == 2
    assert store.invariant_report(first.experiment.experiment_id).accounting_passed


@pytest.mark.asyncio
async def test_incomplete_revalidation_never_becomes_entry_evidence(native_runtime):
    runtime = health_runtime(native_runtime)
    root, _, _, _, _, _, _, faults = runtime
    faults["incomplete"] = True
    outcome = await tick(runtime)  # independent complete poll may continue observation
    assert outcome.simulated_count == 0
    receipt = json.loads((root / "refresh.json").read_bytes())
    assert receipt["outcome"] == "SOURCE_INCOMPLETE"
    assert receipt["eligibility"] is None


@pytest.mark.asyncio
async def test_cross_purpose_and_forged_simulation_admission_rejected(native_runtime):
    runtime = health_runtime(native_runtime)
    root, clock, _, authority, watch, admission, _, _ = runtime
    for changed in ({"purpose": "PUBLIC_RESEARCH"}, {"persisted_simulations": 42},
                    {"financial_authority": True}, {"policy_digest": "f" * 64}):
        with pytest.raises(AcquisitionBlockedError, match="native_health_admission_invalid"):
            native_lifecycle.validate_native_admission(
                watch, {**admission, **changed}, code_sha="a" * 40, now=clock(),
                authority=authority,
            )
    assert not (root / "financial.sqlite3").exists()
    assert authority.status()["requests_charged"] == 0


@pytest.mark.asyncio
async def test_expired_entry_cannot_increase_exposure_but_observation_advances(native_runtime):
    runtime = health_runtime(native_runtime)
    root, clock, scenario, _, watch, _, _, faults = runtime
    first = await tick(runtime)  # actual deterministic qualified check at original time
    clock.value += timedelta(hours=3)
    faults["stale"] = True
    await tick(runtime)  # quiet does not replace the original qualified evidence
    clock.value += timedelta(hours=1, minutes=1)
    wallet = watch["candidates"][0]["wallet_id"]
    scenario.events[wallet] = [_EventSpec(
        "expired-watch-buy", LeaderTradeAction.BUY, clock() - timedelta(seconds=20),
        Decimal("0.40"),
    )]
    outcome = await tick(runtime)
    assert outcome.simulated_count == 0
    assert ContinuousShadowRepository(root / "financial.sqlite3").watermark(
        first.experiment.experiment_id,
    ) == clock().replace(microsecond=0)


def test_stock_worker_wires_health_tick_and_admission_without_research_simulations(
    native_runtime, monkeypatch,
):
    from pathlib import Path

    from polysia.cli_commands import platform_worker as worker
    from polysia.monitoring.nonlive_campaign import configuration_digest
    from polysia.monitoring.technical_health import ACCEPTANCE, CONTRACT

    runtime = health_runtime(native_runtime)
    root, clock, _, old, watch, admission, _, faults = runtime
    old.stop()
    new = replace(old.policy, policy_id="worker-health-grant", maximum_requests=2000,
                  maximum_bytes=268_435_456, minimum_free_disk_bytes=9_663_676_416)
    authority = old.grant_finite_campaign(
        new, now=clock(), authorization_reference="owner-health-worker-test",
        additional_requests=2000, additional_bytes=268_435_456,
    )
    authority.resume(now=clock(), host="host")
    admission["policy_digest"] = new.digest
    faults["stale"] = True
    commands = ConsoleCommandStore(root / "commands.sqlite3")
    commands.initialize()
    config = {"database": str(root / "financial.sqlite3"), "release_commit": "a" * 40,
              "authority": str(authority.path), "manifest": str(root / "manifest.json"),
              "commands": str(commands._path), "status": str(root / "status.json"),
              "cohort": str(root / "cohort.json"), "cohort_refresh": str(root / "refresh.json"),
              "acquisition_enabled": True, "admission": admission,
              "campaign": str(root / "campaign.json")}
    (root / "manifest.json").write_text(json.dumps(new.to_dict()))
    (root / "cohort.json").write_text(json.dumps({"discovery": watch}))
    plan = {"contract": CONTRACT, "purpose": PURPOSE, "campaign_id": "unit-worker-health",
            "scheduled_poll_slot_seconds": 60,
            "acceptance": ACCEPTANCE, "release_commit": "a" * 40, "image": "sha256:" + "b" * 64,
            "policy_digest": new.digest, "cohort_digest": watch["digest"],
            "starts_at": new.starts_at.isoformat(), "expires_at": new.expires_at.isoformat(),
            "configuration_digest": configuration_digest(config),
            "period_capacity": {"contract": "native-period-capacity/v1",
                                "period_max_events": 10000,
                                "period_max_storage_bytes": 67_108_864}}
    (root / "campaign.json").write_text(json.dumps(plan))
    (root / "worker.json").write_text(json.dumps(config))
    original = Path.read_text

    def read(path, *args, **kwargs):
        return "a" * 40 if path.as_posix() == "/opt/polysia/BUILD_COMMIT" else original(
            path, *args, **kwargs,
        )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return clock()

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(worker, "datetime", Clock)
    result = worker.worker_tick(root / "worker.json")
    assert result["status"] == "OBSERVING"
    assert result["campaign"]["phase"] == "PREPARING"  # no manufactured operational proofs
    assert result["acquisition_purpose"] == PURPOSE
    assert result["observation"]["wallets"][0]["entry"] == "BLOCKED_NO_CURRENT_ELIGIBILITY"
    import sqlite3

    with sqlite3.connect(authority.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM technical_health_ticks").fetchone()[0] == 1
    assert result["authority"]["requests_charged"] == 1
