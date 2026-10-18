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
        def __init__(self, standing_authority):
            self.authority = standing_authority

        async def get_json(self, _base, _path, params, **_kwargs):
            calls.append(dict(params))
            request = self.authority.reserve(ENDPOINT, now=clock(), host="host")
            self.authority.settle(request, response_bytes=100)
            return {"data": [] if faults["stale"] else [{
                "proxy_wallet": ADDRESS, "timestamp": int(clock().timestamp()) - 1,
                "price": "0.5", "size": "2", "side": "BUY", "type": "TRADE",
                "condition_id": "condition-1", "asset": "token-yes",
            }], "pagination": {
                "next_cursor": "repeat" if faults["incomplete"] else None,
                "has_more": faults["incomplete"],
            }}

    monkeypatch.setattr(native_lifecycle, "BoundedPublicTransport", Transport)
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


async def _draining_inventory(runtime, monkeypatch, *, limit="requests"):
    """Real portfolio composition; only the provider I/O is deterministic."""
    from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
    from polysia.domain.copytrading.continuous_shadow import ContinuousShadowLifecycle

    root, clock, scenario, _, discovered, admission, _, _ = runtime
    bounded = replace(
        policy(), expires_at=NOW + timedelta(hours=72),
        maximum_requests=3 if limit == "requests" else 20,
        maximum_bytes=3072, closure_request_reserve=1, closure_byte_reserve=1024,
    )
    authority = AcquisitionAuthority(root / "drain-authority.sqlite3", bounded)
    authority.initialize()
    runtime = (*runtime[:3], authority, *runtime[4:])
    first = await tick(runtime)
    wallet = discovered["candidates"][0]["wallet_id"]
    clock.value += timedelta(minutes=2)
    scenario.events[wallet] = [_EventSpec(
        "open-before-drain", LeaderTradeAction.BUY,
        clock() - timedelta(seconds=20), Decimal("0.40"),
    )]
    await tick(runtime)
    store = ContinuousShadowRepository(root / "financial.sqlite3")
    assert store.open_position_count(first.experiment.experiment_id) == 2
    for _ in range(2):
        request = authority.reserve(ENDPOINT, now=clock(), host="host")
        authority.settle(request, response_bytes=1024)
    store.transition(first.experiment.experiment_id, lifecycle=ContinuousShadowLifecycle.DRAINING,
                     transitioned_at=clock())
    market = _MarketPort(clock)
    market.closed = True
    calls = []

    def offline_read(transport, base, path, params):
        calls.append(transport._closure)
        request = transport.authority.reserve(
            ENDPOINT, now=clock(), host="host", closure=transport._closure,
        )
        transport.authority.settle(request, response_bytes=1024)
        return {}

    class ChargedMarket:
        def __init__(self, transport):
            self.transport = transport

        async def get_market_by_condition_id(self, market_id):
            await self.transport.get_json("fixture", "/market", {})
            return await market.get_market_by_condition_id(market_id)

        async def get_order_book(self, token_id):
            return await market.get_order_book(token_id)

    monkeypatch.setattr(BoundedPublicTransport, "_read", offline_read)
    monkeypatch.setattr(native_research, "BoundedMarketAdapter", ChargedMarket)
    clock.value = NOW + timedelta(hours=4, minutes=2)
    return runtime, store, first.experiment, market, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["requests", "bytes"])
async def test_stale_draining_cohort_uses_reserve_for_closure_not_entry_revalidation(
    native_runtime, monkeypatch, limit,
):
    runtime, store, original, _, calls = await _draining_inventory(
        native_runtime, monkeypatch, limit=limit,
    )
    root, clock, scenario, authority, discovered, _, discovery_calls, _ = runtime
    # A new BUY is visible in the complete source window but may not create exposure.
    wallet = discovered["candidates"][0]["wallet_id"]
    scenario.events[wallet].append(_EventSpec(
        "buy-during-drain", LeaderTradeAction.BUY, clock() - timedelta(seconds=10), Decimal("0.40"),
    ))
    before = store.results(original.experiment_id, limit=10)
    outcome = await tick(runtime)
    assert outcome.experiment.experiment_id == original.experiment_id
    assert outcome.experiment.config == original.config
    assert outcome.experiment.lifecycle.value == "DRAINING"
    assert outcome.settlement_count == 2
    assert store.open_position_count(original.experiment_id) == 0
    assert store.pending_observation_count(original.experiment_id) == 0
    assert outcome.simulated_count == 0
    assert calls == [True]
    assert discovery_calls == []
    assert not (root / "refresh.json").exists()
    assert authority.status()["requests_charged"] == 3
    assert authority.status()["bytes_charged"] == 3072
    after = store.results(original.experiment_id, limit=10)
    assert after["follower"]["initial_cash"] == before["follower"]["initial_cash"]
    # Restart cannot replenish authority. Flat completion needs no new request.
    await tick(runtime)
    assert authority.status()["requests_charged"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["stop", "admission", "policy", "total", "window"])
async def test_close_only_keeps_authority_expiry_stop_total_and_window_gates(
    native_runtime, monkeypatch, blocker,
):
    runtime, store, original, _, calls = await _draining_inventory(native_runtime, monkeypatch)
    _, clock, _, authority, _, admission, _, _ = runtime
    before = store.results(original.experiment_id, limit=10)
    if blocker == "stop":
        authority.stop()
    elif blocker == "admission":
        admission["expires_at"] = clock().isoformat()
    elif blocker == "policy":
        clock.value = authority.policy.expires_at
    elif blocker == "total":
        authority.reserve(ENDPOINT, now=clock(), host="host", closure=True)
    else:
        # Existing two charges fall within a five-hour window; no reset on restart.
        bounded = replace(authority.policy, window_seconds=18_000, window_maximum_requests=2)
        other = AcquisitionAuthority(runtime[0] / "window-authority.sqlite3", bounded)
        other.initialize()
        for _ in range(2):
            other.reserve(ENDPOINT, now=NOW, host="host")
        runtime = (*runtime[:3], other, *runtime[4:])
        authority = other
    if blocker in {"stop", "admission", "policy"}:
        with pytest.raises(AcquisitionBlockedError):
            await tick(runtime)
    else:
        # Market failures are retained as missing evidence/backlog by the existing
        # portfolio engine. They cannot manufacture a settlement.
        outcome = await tick(runtime)
        assert outcome.settlement_count == 0
        with pytest.raises(AcquisitionBlockedError, match=(
            "request_budget_exhausted" if blocker == "total" else "request_window_exhausted"
        )):
            authority.reserve(ENDPOINT, now=clock(), host="host", closure=True)
    after = store.results(original.experiment_id, limit=10)
    assert store.open_position_count(original.experiment_id) == 2
    assert after["follower"]["cash"] == before["follower"]["cash"]
    if blocker in {"stop", "admission", "policy"}:
        assert after["polls"]["succeeded"] == before["polls"]["succeeded"]
        assert calls == []


@pytest.mark.asyncio
async def test_close_only_ambiguous_settlement_retains_inventory_without_revalidation(
    native_runtime, monkeypatch,
):
    runtime, store, original, market, calls = await _draining_inventory(native_runtime, monkeypatch)
    market.ambiguous_settlement = True
    outcome = await tick(runtime)
    assert outcome.settlement_count == 0
    assert outcome.settlement_backlog_count == 2
    assert store.open_position_count(original.experiment_id) == 2
    assert calls == [True]


@pytest.mark.asyncio
async def test_missing_retained_financial_store_never_creates_a_fresh_session(native_runtime):
    root = native_runtime[0]
    first = await tick(native_runtime)
    database = root / "financial.sqlite3"
    before = native_runtime[3].status()
    database.rename(root / "retained-financial.sqlite3")
    with pytest.raises(AcquisitionBlockedError, match="retained_financial_session_missing"):
        await tick(native_runtime)
    assert not database.exists()
    assert native_runtime[3].status() == before
    retained = json.loads((root / "financial.sqlite3.session.json").read_text())
    assert retained["experiment_id"] == first.experiment.experiment_id


@pytest.mark.asyncio
async def test_real_worker_restarts_make_close_only_progress_at_four_hours(
    native_runtime, monkeypatch,
):
    import asyncio

    from polysia.cli_commands import platform_worker as worker

    runtime, store, original, _, calls = await _draining_inventory(native_runtime, monkeypatch)
    root, clock, _, authority, discovered, admission, _, _ = runtime

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock()

    monkeypatch.setattr(worker, "datetime", Clock)
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if path.as_posix() == "/opt/polysia/BUILD_COMMIT":
            return "a" * 40
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    (root / "manifest.json").write_text(json.dumps(authority.policy.to_dict()))
    (root / "cohort.json").write_text(json.dumps({"discovery": discovered}))
    config = root / "worker.json"
    config.write_text(json.dumps({
        "database": str(root / "financial.sqlite3"), "release_commit": "a" * 40,
        "manifest": str(root / "manifest.json"), "authority": str(authority._path),
        "commands": str(root / "commands.sqlite3"), "status": str(root / "status.json"),
        "cohort": str(root / "cohort.json"), "acquisition_enabled": True, "admission": admission,
    }))
    first = await asyncio.to_thread(worker.worker_tick, config)
    assert first["status"] == "OBSERVING"
    assert first["experiment_id"] == original.experiment_id
    assert store.open_position_count(original.experiment_id) == 0
    assert calls == [True]
    assert first["authority"]["requests_charged"] == 3
    clock.value += timedelta(seconds=authority.policy.cadence_seconds)
    second = await asyncio.to_thread(worker.worker_tick, config)
    assert second["status"] == "OBSERVING"
    assert second["authority"] == first["authority"]


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
    AcquisitionAuthority(root / "worker-authority.sqlite3", changed_policy).initialize()
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
