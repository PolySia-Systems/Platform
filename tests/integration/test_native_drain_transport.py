"""Real native source/market/worker composition; only HTTP response I/O is offline."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.cli_commands import platform_worker
from polysia.cli_support import native_lifecycle
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowLifecycle
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from tests.integration.test_continuous_shadow_portfolio import _Clock
from tests.integration.test_native_platform_lifecycle import ADDRESS, frozen_discovery
from tests.unit.storage.test_acquisition_authority import ENDPOINT, NOW, policy


@pytest.fixture
def real_drain(tmp_path, monkeypatch):
    clock = _Clock(NOW)
    condition = "0x" + "a" * 64
    state = {"rows": [], "closed": False, "incomplete": False}
    calls = []

    def market():
        return {
            "id": "1",
            "conditionId": condition,
            "active": not state["closed"],
            "closed": state["closed"],
            "outcomes": '["Yes","No"]',
            "clobTokenIds": '["111111","222222"]',
            "outcomePrices": '["1","0"]' if state["closed"] else '["0.5","0.5"]',
            "feesEnabled": False,
            "startDate": NOW.isoformat(),
            "endDate": (NOW + timedelta(days=1)).isoformat(),
            "events": [{"id": "fixture-event", "slug": "native-fixture"}],
        }

    def read(transport, base, path, params):
        request = transport.authority.reserve(
            base + path,
            now=clock(),
            host="host",
            closure=transport._closure,
        )
        calls.append((path, dict(params), transport._closure))
        if path == "/v2/trades":
            payload = {
                "data": [
                    row
                    for row in state["rows"]
                    if params["start"] <= row["timestamp"] <= params["end"]
                ],
                "pagination": {
                    "has_more": state["incomplete"],
                    "next_cursor": "repeat" if state["incomplete"] else None,
                },
            }
        elif path == "/events":
            payload = [{"slug": "native-fixture", "markets": [market()]}]
        elif path == "/markets":
            payload = [market()] if params["closed"] in ("any", state["closed"]) else []
        elif path == "/book":
            payload = {
                "market": condition,
                "asset_id": "111111",
                "hash": "fixture",
                "timestamp": str(int(clock().timestamp() * 1000)),
                "bids": [{"price": "0.4", "size": "20"}],
                "asks": [{"price": "0.4", "size": "20"}],
                "min_order_size": "0.01",
                "tick_size": "0.01",
                "neg_risk": False,
            }
        else:
            raise AssertionError("unexpected provider request: " + path)
        assert len(json.dumps(payload).encode()) <= 1024
        # Conservatively charge a whole response reservation for every fixture.
        transport.authority.settle(request, response_bytes=1024)
        return payload

    monkeypatch.setattr(BoundedPublicTransport, "_read", read)
    return tmp_path, clock, state, calls, condition


async def prepare(real_drain, *, remaining=4, limit="requests"):
    root, clock, state, calls, condition = real_drain
    maximum = 20
    bounded = replace(
        policy(),
        expires_at=NOW + timedelta(hours=72),
        endpoints=(
            ENDPOINT,
            "https://data-api.polymarket.com/v2/trades",
            "https://gamma-api.polymarket.com/events",
            "https://gamma-api.polymarket.com/markets",
            "https://clob.polymarket.com/book",
        ),
        maximum_requests=maximum if limit == "requests" else 100,
        maximum_bytes=maximum * 1024,
        closure_request_reserve=remaining,
        closure_byte_reserve=remaining * 1024,
        window_maximum_requests=100,
        window_maximum_bytes=102400,
    )
    authority = AcquisitionAuthority(root / "authority.sqlite3", bounded)
    authority.initialize()
    discovery = frozen_discovery()
    admission = {
        "contract": "native-research-admission/v1",
        "mode": "CONTINUOUS",
        "code_sha": "a" * 40,
        "cohort_digest": discovery["digest"],
        "persisted_simulations": 2,
        "resource_admitted": True,
        "expires_at": (NOW + timedelta(hours=48)).isoformat(),
    }

    async def tick():
        return await native_lifecycle.native_lifecycle_poll(
            root / "financial.sqlite3",
            discovery,
            authority=authority,
            code_sha="a" * 40,
            admission=admission,
            refresh_path=root / "refresh.json",
            clock=clock,
        )

    first = await tick()
    clock.value += timedelta(minutes=2)
    state["rows"] = [
        {
            "proxy_wallet": ADDRESS,
            "condition_id": condition,
            "event_slug": "native-fixture",
            "token_id": "111111",
            "outcome": "Yes",
            "transaction_hash": "0x" + "b" * 64,
            "side": "BUY",
            "price": "0.4",
            "size": "5",
            "timestamp": int((clock() - timedelta(seconds=20)).timestamp()),
        }
    ]
    await tick()
    store = ContinuousShadowRepository(root / "financial.sqlite3")
    assert store.open_position_count(first.experiment.experiment_id) == 2
    clock.value += timedelta(minutes=1)
    await tick()  # Complete history; advance the watermark beyond the opening trade.
    while authority.status()["requests_charged"] < maximum - remaining:
        request = authority.reserve(ENDPOINT, now=clock(), host="host")
        authority.settle(request, response_bytes=1024)
    store.transition(
        first.experiment.experiment_id,
        lifecycle=ContinuousShadowLifecycle.DRAINING,
        transitioned_at=clock(),
    )
    clock.value = NOW + timedelta(hours=4, minutes=2)
    state["closed"] = True
    calls.clear()
    return tick, store, first.experiment, authority, discovery, admission


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["requests", "bytes"])
async def test_real_adapters_close_under_exhausted_ordinary_authority(real_drain, limit):
    tick, store, original, authority, _, _ = await prepare(real_drain, limit=limit)
    root, clock, _, calls, _ = real_drain
    before = store.results(original.experiment_id, limit=10)
    outcome = await tick()
    assert outcome.experiment.experiment_id == original.experiment_id
    assert outcome.experiment.config == original.config
    assert outcome.settlement_count == 2
    assert store.open_position_count(original.experiment_id) == 0
    assert [(path, params.get("closed"), closure) for path, params, closure in calls] == [
        ("/v2/trades", None, True),
        ("/markets", False, True),
        ("/markets", True, True),
    ]
    assert authority.status()["requests_charged"] == 19
    assert not (root / "refresh.json").exists()
    assert (
        store.results(original.experiment_id, limit=10)["follower"]["initial_cash"]
        == (before["follower"]["initial_cash"])
    )
    clock.value += timedelta(minutes=1)
    calls.clear()
    await tick()
    assert [(path, closure) for path, _, closure in calls] == [("/v2/trades", True)]
    assert authority.status()["requests_charged"] == 20  # Flat polls still need source evidence.


@pytest.mark.asyncio
async def test_one_remaining_request_cannot_invent_settlement_evidence(real_drain):
    tick, store, original, authority, _, _ = await prepare(real_drain, remaining=1)
    before = store.results(original.experiment_id, limit=10)
    outcome = await tick()
    assert outcome.settlement_count == 0
    assert store.open_position_count(original.experiment_id) == 2
    assert (
        store.results(original.experiment_id, limit=10)["follower"]["cash"]
        == (before["follower"]["cash"])
    )
    assert authority.status()["requests_charged"] == 20


@pytest.mark.asyncio
async def test_incomplete_real_cursor_walk_keeps_inventory_pending_and_watermark(real_drain):
    from polysia.application.services.continuous_shadow import ContinuousShadowError

    tick, store, original, authority, _, _ = await prepare(real_drain)
    _, clock, state, calls, _ = real_drain
    state["rows"][0]["timestamp"] = int((clock() - timedelta(seconds=20)).timestamp())
    state["rows"][0]["transaction_hash"] = "0x" + "c" * 64
    state["incomplete"] = True
    before = store.results(original.experiment_id, limit=10)
    watermark = store.watermark(original.experiment_id)
    with pytest.raises(ContinuousShadowError):
        await tick()
    assert store.watermark(original.experiment_id) == watermark
    assert store.pending_observation_count(original.experiment_id) == 1
    assert store.open_position_count(original.experiment_id) == 2
    assert (
        store.results(original.experiment_id, limit=10)["follower"]["cash"]
        == (before["follower"]["cash"])
    )
    assert all(path == "/v2/trades" and closure for path, _, closure in calls)
    assert authority.status()["requests_charged"] <= 20


@pytest.mark.asyncio
async def test_real_worker_close_progress_survives_restart(real_drain, monkeypatch):
    _, store, original, authority, discovery, admission = await prepare(real_drain)
    root, clock, _, _, _ = real_drain

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock()

    monkeypatch.setattr(platform_worker, "datetime", Clock)
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        return (
            "a" * 40
            if path.as_posix() == "/opt/polysia/BUILD_COMMIT"
            else original_read(
                path,
                *args,
                **kwargs,
            )
        )

    monkeypatch.setattr(Path, "read_text", read)
    (root / "manifest.json").write_text(json.dumps(authority.policy.to_dict()))
    (root / "cohort.json").write_text(json.dumps({"discovery": discovery}))
    config = root / "worker.json"
    config.write_text(
        json.dumps(
            {
                "database": str(root / "financial.sqlite3"),
                "release_commit": "a" * 40,
                "manifest": str(root / "manifest.json"),
                "authority": str(root / "authority.sqlite3"),
                "commands": str(root / "commands.sqlite3"),
                "status": str(root / "status.json"),
                "cohort": str(root / "cohort.json"),
                "acquisition_enabled": True,
                "admission": admission,
            }
        )
    )
    ConsoleCommandStore(root / "commands.sqlite3").initialize()
    first = await asyncio.to_thread(platform_worker.worker_tick, config)
    assert first["status"] == "OBSERVING"
    assert store.open_position_count(original.experiment_id) == 0
    clock.value += timedelta(minutes=1)
    second = await asyncio.to_thread(platform_worker.worker_tick, config)
    assert second["status"] == "OBSERVING"
    assert second["authority"]["requests_charged"] == 20
