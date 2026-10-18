from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.cli_support import native_lifecycle, native_research
from polysia.domain.copytrading import LeaderTradeAction
from polysia.domain.wallet_intelligence import normalize_evm_wallet
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from tests.integration.test_continuous_shadow_portfolio import (
    _Clock,
    _EventSpec,
    _MarketPort,
    _Scenario,
    _Source,
)
from tests.unit.storage.test_acquisition_authority import ENDPOINT, NOW, policy

ADDRESS = "0x" + "1" * 40


def frozen_discovery() -> dict[str, Any]:
    result = {
        "profile": "native-recent-activity/v1", "source": "polymarket-native",
        "cutoff": NOW.isoformat(), "window_start": (NOW - timedelta(seconds=60)).isoformat(),
        "frozen_at": NOW.isoformat(), "candidates": [{
            "address": ADDRESS, "wallet_id": normalize_evm_wallet("polygon", ADDRESS)[0],
            "state": "ACTIVITY_CONFIRMED", "execution_eligibility": "ELIGIBLE_FOR_RESEARCH",
        }],
    }
    return {**result, "digest": hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()}


@pytest.fixture
def native_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clock, scenario = _Clock(NOW), _Scenario()
    market = _MarketPort(clock)
    authority = AcquisitionAuthority(tmp_path / "authority.sqlite3", replace(
        policy(), maximum_requests=200, maximum_bytes=204_800,
        expires_at=NOW + timedelta(hours=72),
    ))
    authority.initialize()
    calls = []
    faults = {"incomplete": False, "stale": False}

    class Transport:
        async def get_json(self, _base, _path, params, **_kwargs):
            calls.append(dict(params))
            request = authority.reserve(ENDPOINT, now=clock(), host="host")
            authority.settle(request, response_bytes=100)
            return {"data": [] if faults["stale"] else [{
                "proxy_wallet": ADDRESS, "timestamp": int(clock().timestamp()) - 1,
                "price": "0.5", "size": "2", "side": "BUY", "type": "TRADE",
                "condition_id": "condition-1", "asset": "token-yes",
            }], "pagination": {
                "next_cursor": "repeat" if faults["incomplete"] else None,
                "has_more": faults["incomplete"],
            }}

    monkeypatch.setattr(native_lifecycle, "BoundedPublicTransport", lambda _: Transport())
    monkeypatch.setattr(native_lifecycle, "BoundedMarketAdapter", lambda _: market)
    monkeypatch.setattr(native_research, "BoundedMarketAdapter", lambda _: market)
    monkeypatch.setattr(native_research, "PolymarketCopyTradingSource",
                        lambda leaders, **_: _Source(dict(leaders), scenario))
    discovered = frozen_discovery()
    admission = {"contract": "native-research-admission/v1", "mode": "CONTINUOUS",
                 "code_sha": "a" * 40, "cohort_digest": discovered["digest"],
                 "persisted_simulations": 2, "resource_admitted": True,
                 "expires_at": (NOW + timedelta(hours=48)).isoformat()}
    return tmp_path, clock, scenario, authority, discovered, admission, calls, faults


async def tick(runtime):
    root, clock, _, authority, discovered, admission, _, _ = runtime
    return await native_lifecycle.native_lifecycle_poll(
        root / "financial.sqlite3", discovered, authority=authority, code_sha="a" * 40,
        admission=admission, refresh_path=root / "refresh.json", clock=clock,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("keep_inventory", [False, True])
async def test_actual_native_composition_crosses_four_hours_midnight_and_25_hours(
    native_runtime, keep_inventory: bool,
):
    root, clock, scenario, authority, discovered, admission, calls, _ = native_runtime
    first = await tick(native_runtime)
    experiment_id = first.experiment.experiment_id
    wallet = discovered["candidates"][0]["wallet_id"]
    for index, delta in enumerate([timedelta(minutes=2), timedelta(hours=4, minutes=2),
                                   timedelta(hours=12, minutes=2), timedelta(hours=24, minutes=2),
                                   timedelta(hours=25, minutes=2)]):
        clock.value = NOW + delta
        scenario.events[wallet] = [_EventSpec(
            f"native-buy-{index}", LeaderTradeAction.BUY, clock() - timedelta(seconds=20),
            Decimal("0.40"),
        )]
        if not keep_inventory:
            scenario.events[wallet].append(_EventSpec(
                f"native-sell-{index}", LeaderTradeAction.SELL,
                clock() - timedelta(seconds=10), Decimal("0.60"),
            ))
        outcome = await tick(native_runtime)  # Fresh composition on every tick/restart.
        assert outcome.experiment.experiment_id == experiment_id
        assert outcome.simulated_count > 0
        assert outcome.experiment.lifecycle.value == "RUNNING"
    store = ContinuousShadowRepository(root / "financial.sqlite3")
    assert (store.open_position_count(experiment_id) > 0) is keep_inventory
    before = store.results(experiment_id, limit=10)
    clock.value += timedelta(seconds=1)
    duplicate = await tick(native_runtime)
    assert duplicate.simulated_count == 0
    assert store.results(experiment_id, limit=10)["follower"]["cash"] == before["follower"]["cash"]
    assert len(calls) == 3  # Successful revalidation is cached across restarts.
    assert authority.status()["requests_charged"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["admission", "authority", "stale", "incomplete", "new_cohort"])
async def test_expired_or_incomplete_evidence_never_advances_financial_state(
    native_runtime, failure: str,
):
    from polysia.adapters.polymarket.data_api_v2 import IncompleteWalletWindowError

    root, clock, _, authority, _, admission, calls, faults = native_runtime
    first = await tick(native_runtime)
    store = ContinuousShadowRepository(root / "financial.sqlite3")
    before = store.results(first.experiment.experiment_id, limit=10)
    clock.value = NOW + timedelta(hours=4, minutes=2)
    if failure == "admission":
        admission["expires_at"] = clock().isoformat()
    elif failure == "authority":
        authority.stop()
    elif failure == "new_cohort":
        discovered = native_runtime[4]
        discovered["candidates"][0]["address"] = "0x" + "2" * 40
        discovered["candidates"][0]["wallet_id"] = normalize_evm_wallet(
            "polygon", discovered["candidates"][0]["address"],
        )[0]
        unsigned = {key: value for key, value in discovered.items() if key != "digest"}
        discovered["digest"] = hashlib.sha256(json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        admission["cohort_digest"] = discovered["digest"]
    else:
        faults[failure] = True
    with pytest.raises((AcquisitionBlockedError, IncompleteWalletWindowError)):
        await tick(native_runtime)
    after = store.results(first.experiment.experiment_id, limit=10)
    assert after["polls"]["succeeded"] == before["polls"]["succeeded"]
    assert after["follower"]["cash"] == before["follower"]["cash"]
    assert not (root / "refresh.json").exists()
    if failure in {"admission", "authority", "new_cohort"}:
        assert calls == []


def test_real_worker_composition_obeys_cadence_across_restarts(
    native_runtime, monkeypatch: pytest.MonkeyPatch,
):
    from polysia.cli_commands import platform_worker as worker

    root, clock, _, authority, discovered, admission, calls, _ = native_runtime

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock()

    monkeypatch.setattr(worker, "datetime", Clock)
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path.as_posix() == "/opt/polysia/BUILD_COMMIT":
            return "a" * 40
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    changed_policy = replace(authority.policy, cadence_seconds=300)
    # Use a new test-only authority, never reset an existing charged policy.
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(changed_policy.to_dict()))
    cohort = root / "cohort.json"
    cohort.write_text(json.dumps({"discovery": discovered}))
    config = root / "worker.json"
    config.write_text(json.dumps({
        "database": str(root / "financial.sqlite3"), "release_commit": "a" * 40,
        "manifest": str(manifest), "authority": str(root / "worker-authority.sqlite3"),
        "commands": str(root / "commands.sqlite3"), "status": str(root / "status.json"),
        "cohort": str(cohort), "acquisition_enabled": True, "admission": admission,
    }))
    first = worker.worker_tick(config)
    assert first["status"] == "OBSERVING"
    assert worker.worker_tick(config)["status"] == "WAITING_CADENCE"
    clock.value += timedelta(seconds=299)
    assert worker.worker_tick(config)["status"] == "WAITING_CADENCE"
    store = ContinuousShadowRepository(root / "financial.sqlite3")
    assert store.results(first["experiment_id"], limit=10)["polls"]["succeeded"] == 1
    clock.value += timedelta(seconds=1)
    assert worker.worker_tick(config)["status"] == "OBSERVING"
    assert store.results(first["experiment_id"], limit=10)["polls"]["succeeded"] == 2
    assert calls == []


@pytest.mark.asyncio
async def test_polycop_and_native_share_identity_but_keep_policy_and_provenance(
    native_runtime, monkeypatch: pytest.MonkeyPatch,
):
    import tests.integration.test_continuous_shadow_portfolio as fixtures
    from polysia.adapters.polycop.candidate_wallet_source import PolyCopCandidateWalletSource
    from polysia.application.services.shadow_reporting import ShadowReportingService
    from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
    from polysia.storage.dynamic_shadow import DynamicShadowRepository
    from tests.unit.adapters.test_polycop_candidate_wallet_source import FakeTransport, _page, _row

    root, clock, scenario, _, discovered, _, _, _ = native_runtime
    row = _row(1)
    row["address"] = ADDRESS
    row["last_active"] = NOW.replace(tzinfo=None).isoformat()
    page = _page(1, 1, [row])
    source = PolyCopCandidateWalletSource(
        transport=FakeTransport({1: [page, page]}), clock=clock,
        page_delay_seconds=0, consistency_attempts=1,
    )
    dataset = await source.fetch_snapshot()
    monkeypatch.setattr(fixtures, "_dataset", lambda: dataset)
    monkeypatch.setattr(fixtures, "NOW", NOW)
    polycop_database = root / "polycop.sqlite3"
    fixtures._seed_stage3(polycop_database)
    port = DynamicShadowRepository(polycop_database)
    selection = port.current_snapshot("polycop")
    native_wallet = discovered["candidates"][0]["wallet_id"]
    assert selection.candidates[0].wallet_id == native_wallet
    assert "NATIVE_RESEARCH" not in selection.candidates[0].pools
    polycop = fixtures._service(polycop_database, scenario, _MarketPort(clock), clock,
                               config=ContinuousShadowConfig(code_sha="b" * 40))
    polycop_experiment = polycop.start("polycop")
    native_experiment = (await tick(native_runtime)).experiment
    scenario.events[native_wallet] = [_EventSpec(
        "shared-source-event", LeaderTradeAction.BUY,
        NOW + timedelta(seconds=100), Decimal("0.40"),
    )]
    clock.value = NOW + timedelta(minutes=2)
    assert (await polycop.poll("polycop")).simulated_count > 0
    assert (await tick(native_runtime)).simulated_count > 0
    clock.value += timedelta(seconds=1)
    assert (await polycop.poll("polycop")).simulated_count == 0
    assert (await tick(native_runtime)).simulated_count == 0
    native_store = ContinuousShadowRepository(root / "financial.sqlite3")
    polycop_store = ContinuousShadowRepository(fixtures._shadow_database(polycop_database))
    native_state = native_store.results(native_experiment.experiment_id, limit=10)
    polycop_state = polycop_store.results(polycop_experiment.experiment_id, limit=10)
    assert native_state["follower"]["cash"] == polycop_state["follower"]["cash"]
    assert Decimal(native_state["follower"]["cash"]) < native_experiment.config.follower_bankroll
    native_report = ShadowReportingService(root / "financial.sqlite3").report(
        native_experiment.experiment_id,
    )
    polycop_report = ShadowReportingService(fixtures._shadow_database(polycop_database)).report(
        polycop_experiment.experiment_id,
    )
    assert native_report["provider_calls"] == polycop_report["provider_calls"] == 0
    assert native_report["analytical_digest"] != polycop_report["analytical_digest"]
    # Different source/config/code identities do not require equal metadata hashes.
    assert native_report["analytical"]["financial_state"] == (
        polycop_report["analytical"]["financial_state"]
    )
