from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from polysia.adapters.polymarket.copytrading_source import PolymarketCopyTradingSource
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.deployment.native_session_transition import transition_native_session
from polysia.domain.copytrading import LeaderTradeAction
from polysia.monitoring.latency_intelligence.policy import LatencyPolicy
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from polysia.storage.latency_telemetry import LatencyTelemetryStore
from polysia.storage.metadata_identity_cache import MetadataIdentityCache
from tests.integration.test_continuous_shadow_portfolio import _EventSpec
from tests.integration.test_native_platform_lifecycle import native_runtime, tick
from tests.unit.storage.test_acquisition_authority import ENDPOINT, NOW, policy

__all__ = ["native_runtime"]


@pytest.mark.asyncio
async def test_native_composition_persists_across_restart_and_failed_poll(native_runtime):
    root, clock, scenario, *_ = native_runtime
    first = await tick(native_runtime)
    clock.value += timedelta(minutes=2)
    await tick(native_runtime)
    scenario.fail = True
    clock.value += timedelta(minutes=2)
    with pytest.raises(Exception, match="poll failed safely"):
        await tick(native_runtime)
    # Fresh reader, no recorder object retained between invocations.
    with sqlite3.connect(root / "native-latency.sqlite3") as reader:
        assert reader.execute("SELECT COUNT(*) FROM latency_telemetry_health").fetchone()[0] > 0
        assert (
            reader.execute(
                "SELECT COUNT(DISTINCT poll_run_id) FROM latency_spans WHERE experiment_id=?",
                (first.experiment.experiment_id,),
            ).fetchone()[0]
            == 3
        )
        assert (
            reader.execute("SELECT COUNT(*) FROM latency_spans WHERE status='error'").fetchone()[0]
            > 0
        )
        assert reader.execute("SELECT MIN(duration_ns) FROM latency_spans").fetchone()[0] >= 0
    health = json.loads((root / "native-latency.health.json").read_text())
    assert health["last_successful_flush"]
    assert health["telemetry_errors"] == 0


@pytest.mark.asyncio
async def test_native_optional_storage_failure_preserves_success_and_original_exception(
    native_runtime,
    monkeypatch,
):
    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("fixture unavailable")

    monkeypatch.setattr(LatencyTelemetryStore, "initialize", unavailable)
    first = await tick(native_runtime)
    assert first.experiment.lifecycle.value == "RUNNING"
    root, clock, scenario, *_ = native_runtime
    health = json.loads((root / "native-latency.health.json").read_text())
    assert health["telemetry_errors"] > 0
    assert health["dropped_measurements"] > 0
    scenario.fail = True
    clock.value += timedelta(minutes=2)
    with pytest.raises(Exception, match="poll failed safely") as caught:
        await tick(native_runtime)
    cause = caught.value
    while cause.__cause__ is not None:
        cause = cause.__cause__
    assert "safe source failure" in str(cause)


@pytest.mark.asyncio
async def test_native_buffer_loss_is_visible_without_changing_results(native_runtime, monkeypatch):
    from polysia.cli_support import native_research

    # Native recorder identification is only needed for health sidecar publication.
    # Use a subclass to retain the real composition's recorder contract.
    class SmallRecorder(LatencyRecorder):
        def __init__(self, *args):
            super().__init__(*args, policy=LatencyPolicy(buffer_capacity=1))

    monkeypatch.setattr(native_research, "LatencyRecorder", SmallRecorder)
    await tick(native_runtime)
    health = json.loads((native_runtime[0] / "native-latency.health.json").read_text())
    assert health["dropped_measurements"] > 0


def test_exact_rolling_retry_respects_inclusive_boundary_and_settlement(tmp_path):
    bounded = replace(
        policy(),
        maximum_requests=50,
        maximum_bytes=50_000,
        expires_at=NOW + timedelta(hours=4),
        window_maximum_bytes=2048,
    )
    authority = AcquisitionAuthority(tmp_path / "a.sqlite3", bounded)
    authority.initialize()
    one = authority.reserve(ENDPOINT, now=NOW, host="host")
    two = authority.reserve(ENDPOINT, now=NOW + timedelta(seconds=10), host="host")
    with pytest.raises(AcquisitionBlockedError) as caught:
        authority.reserve(ENDPOINT, now=NOW + timedelta(seconds=20), host="host")
    assert caught.value.retry_at == NOW + timedelta(hours=1, microseconds=1)
    authority.settle(one, response_bytes=100)
    authority.settle(two, response_bytes=100)
    assert authority.window_retry_at(now=NOW + timedelta(seconds=20)) == NOW + timedelta(seconds=20)
    authority.reserve(ENDPOINT, now=NOW + timedelta(seconds=20), host="host")
    assert authority.status()["requests_charged"] == 3


def test_concurrent_reservations_do_not_overspend_and_no_retry_beyond_expiry(tmp_path):
    bounded = replace(
        policy(),
        starts_at=NOW - timedelta(hours=1),
        maximum_requests=50,
        maximum_bytes=50_000,
        window_maximum_requests=1,
    )
    authority = AcquisitionAuthority(tmp_path / "a.sqlite3", bounded)
    authority.initialize()

    def attempt(_):
        try:
            return authority.reserve(ENDPOINT, now=NOW, host="host")
        except AcquisitionBlockedError as error:
            assert error.retry_at is None
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(value is not None for value in pool.map(attempt, range(4))) == 1
    assert authority.status()["uncertain_requests"] == 1
    with pytest.raises(AcquisitionBlockedError, match="clock_regressed"):
        authority.reserve(ENDPOINT, now=NOW - timedelta(seconds=1), host="host")


def test_separate_campaign_preserves_history_stop_and_rejects_renewal(tmp_path):
    original = replace(policy(), minimum_free_disk_bytes=9_663_676_416)
    authority = AcquisitionAuthority(tmp_path / "a.sqlite3", original)
    authority.initialize()
    authority.reserve(ENDPOINT, now=NOW, host="host")
    authority.stop()
    replacement = replace(
        original,
        policy_id="n1-finite",
        starts_at=NOW + timedelta(hours=2),
        expires_at=NOW + timedelta(hours=74),
        maximum_requests=103,
        maximum_bytes=101_024,
    )
    continued = authority.grant_finite_campaign(
        replacement,
        now=NOW + timedelta(hours=2),
        authorization_reference="owner-n1-campaign",
        additional_requests=102,
        additional_bytes=100_000,
    )
    assert continued.status()["stopped"] is True
    assert continued.status()["bytes_charged"] == 1024
    assert continued.status()["uncertain_requests"] == 1
    with pytest.raises(AcquisitionBlockedError, match="already_granted"):
        continued.grant_finite_campaign(
            replace(replacement, policy_id="another"),
            now=replacement.starts_at,
            authorization_reference="owner-n1-campaign",
            additional_requests=102,
            additional_bytes=100_000,
        )


@pytest.mark.asyncio
async def test_transition_preserves_nonflat_ledger_and_historical_opportunity_bindings(
    native_runtime,
):
    root, clock, scenario, authority, discovered, admission, *_ = native_runtime
    first = await tick(native_runtime)
    wallet = discovered["candidates"][0]["wallet_id"]
    clock.value += timedelta(minutes=2)
    scenario.events[wallet] = [
        _EventSpec(
            "retained-position",
            LeaderTradeAction.BUY,
            clock() - timedelta(seconds=10),
            Decimal("0.4"),
        )
    ]
    await tick(native_runtime)
    store = ContinuousShadowRepository(root / "financial.sqlite3")
    before = store.results(first.experiment.experiment_id, limit=100)
    assert store.open_position_count(first.experiment.experiment_id) == 2
    authority.stop()
    target = "b" * 40
    updated = {**admission, "code_sha": target}
    kwargs = dict(
        authority=root / "authority.sqlite3",
        expected_source="a" * 40,
        target_source=target,
        admission=updated,
        authorization_reference="owner-n1-upgrade",
        now=clock(),
    )
    receipt = transition_native_session(root / "financial.sqlite3", **kwargs)
    assert transition_native_session(root / "financial.sqlite3", **kwargs) == receipt
    assert (
        store.results(first.experiment.experiment_id, limit=100)["follower"] == before["follower"]
    )
    assert store.open_position_count(first.experiment.experiment_id) == 2
    # Reading the canonical report verifies every historical digest after transition.
    from polysia.application.services.shadow_reporting import ShadowReportingService

    assert ShadowReportingService(root / "financial.sqlite3").report(first.experiment.experiment_id)


@pytest.mark.asyncio
async def test_exact_identity_cache_restarts_coalesces_and_never_renews_observation(tmp_path):
    condition = "0x" + "1" * 64
    calls = []

    class Transport:
        async def get_json(self, base, path, params, **kwargs):
            calls.append((path, params))
            await asyncio.sleep(0)
            return [
                {
                    "conditionId": condition,
                    "outcomes": '["Yes","No"]',
                    "clobTokenIds": '["1","2"]',
                    "startDate": NOW.isoformat(),
                    "endDate": (NOW + timedelta(days=1)).isoformat(),
                    "events": [{"slug": "event"}],
                }
            ]

    def source(now):
        return PolymarketCopyTradingSource(
            {"leader": "0x" + "1" * 40},
            transport=Transport(),
            clock=lambda: now,
            identity_cache=MetadataIdentityCache(tmp_path / "cache.sqlite3"),
        )

    async def load(src):
        return await src._verified_event_markets(
            "event",
            purpose=LeaderReadPurpose.DISCOVERY,
            conditions=frozenset({condition}),
        )

    src = source(NOW)
    one, two = await asyncio.gather(load(src), load(src))
    assert one == two and len(calls) == 1
    assert calls[0] == ("/markets", {"condition_ids": condition, "closed": "any", "limit": 2})
    assert await load(source(NOW + timedelta(hours=2))) == one
    assert len(calls) == 1
    await load(source(NOW + timedelta(hours=3)))
    assert len(calls) == 2
    with sqlite3.connect(tmp_path / "cache.sqlite3") as connection:
        connection.execute("UPDATE identity_cache SET digest='corrupt'")
    await load(source(NOW + timedelta(hours=3, minutes=1)))
    assert len(calls) == 3


def test_historical_settlement_cannot_expand_additional_campaign_bytes(tmp_path):
    original = replace(policy(), minimum_free_disk_bytes=9_663_676_416)
    authority = AcquisitionAuthority(tmp_path / "a.sqlite3", original)
    authority.initialize()
    old = authority.reserve(ENDPOINT, now=NOW, host="host")
    authority.stop()
    replacement = replace(
        original,
        policy_id="campaign",
        maximum_requests=101,
        starts_at=NOW + timedelta(hours=2),
        expires_at=NOW + timedelta(hours=3),
    )
    new = authority.grant_finite_campaign(
        replacement,
        now=replacement.starts_at,
        additional_requests=100,
        additional_bytes=2048,
        authorization_reference="owner-cumulative-test",
    )
    new.settle(old, response_bytes=0)
    new.resume(now=replacement.starts_at, host="host")
    for _ in range(2):
        new.reserve(ENDPOINT, now=replacement.starts_at, host="host")
    with pytest.raises(AcquisitionBlockedError, match="byte_budget_exhausted"):
        new.reserve(ENDPOINT, now=replacement.starts_at, host="host")
    assert new.status()["campaign"]["bytes_remaining"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "duplicate", "extra", "partial", "linkage"])
async def test_exact_requested_market_never_accepts_unverified_response(tmp_path, fault):
    condition = "0x" + "c" * 64
    market = {
        "conditionId": condition,
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["1","2"]',
        "startDate": NOW.isoformat(),
        "endDate": (NOW + timedelta(days=1)).isoformat(),
        "closed": True,
        "events": [{"slug": "event", "markets": [{"conditionId": "unlaunched"}]}],
    }
    payload = [market]
    if fault == "missing":
        payload = []
    elif fault in {"duplicate", "extra"}:
        payload.append({**market, "conditionId": condition if fault == "duplicate" else "other"})
    elif fault == "partial":
        market.pop("clobTokenIds")
    else:
        market["events"] = [{"slug": "other"}]

    class Transport:
        async def get_json(self, *_args, **_kwargs):
            return payload

    source = PolymarketCopyTradingSource(
        {"leader": "0x" + "1" * 40},
        transport=Transport(),
        clock=lambda: NOW,
        identity_cache=MetadataIdentityCache(tmp_path / "cache.sqlite3"),
    )
    with pytest.raises(ValueError):
        await source._verified_event_markets(
            "event", purpose=LeaderReadPurpose.DISCOVERY, conditions=frozenset({condition})
        )
