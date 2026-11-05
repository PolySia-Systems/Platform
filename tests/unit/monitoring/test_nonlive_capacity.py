from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from polysia.domain.copytrading.native_run_limits import NativeRunLimits
from polysia.monitoring.nonlive_campaign import campaign_check
from tests.unit.monitoring.test_nonlive_campaign import campaign, observations
from tests.unit.monitoring.test_nonlive_readiness import CONTROLS, health
from tests.unit.storage.test_acquisition_authority import NOW

__all__ = ["campaign"]


@pytest.fixture
def fresh(campaign, monkeypatch):
    _, authority, plan, database = campaign
    with sqlite3.connect(authority._path) as reader:
        request = reader.execute("SELECT request_id FROM reservations").fetchone()[0]
    authority.settle(request, response_bytes=85)
    plan.update(contract="nonlive-campaign/v2", release_commit="b" * 40,
                period_capacity=NativeRunLimits(20_000, 134_217_728).to_dict(),
                maximum_useful_observation_gap_seconds=900)
    usage = [0, 233_472]
    monkeypatch.setattr("polysia.monitoring.nonlive_campaign._period_capacity",
                        lambda *_: tuple(usage))
    return authority, plan, database, usage


def check(fresh, previous, now, controls=CONTROLS):
    authority, plan, database, _ = fresh
    return campaign_check(plan, previous, database=database, authority=authority,
                          now=now, controls=controls)


def start(fresh):
    _, _, database, _ = fresh
    now = NOW + timedelta(hours=3)
    assert check(fresh, {}, now)["phase"] == "PREPARING"
    observations(database, now - timedelta(minutes=1), 1)
    health(database, now)
    assert check(fresh, {}, now, {})["phase"] == "PREPARING"
    state = check(fresh, {}, now)
    assert state["phase"] == "CANARY"
    assert state["canary_started_at"] == now.isoformat()
    return now, state


def test_new_campaign_has_no_preparation_credit_and_needs_two_real_windows(fresh):
    _, _, database, usage = fresh
    now, state = start(fresh)
    observations(database, now, 120)
    usage[:] = [100, 1_000_000]
    assert check(fresh, state, now + timedelta(minutes=119))["phase"] == "CANARY"
    promoted = check(fresh, state, now + timedelta(hours=2))
    assert promoted["phase"] == "OBSERVING"
    assert promoted["observation_started_at"] == (now + timedelta(hours=2)).isoformat()
    assert promoted["capacity_projection"]["total_events"] == 3100
    assert promoted["capacity_projection"]["headroom_ratio"] == "1.25"


@pytest.mark.parametrize("kind,reason", [
    ("events", "measured_event_growth_cannot_fit_period_limit"),
    ("storage", "measured_storage_growth_cannot_fit_period_limit"),
    ("requests", "measured_workload_cannot_fit_remaining_allowance"),
])
def test_observed_growth_stops_predictably_infeasible_run(fresh, kind, reason):
    authority, _, database, usage = fresh
    now, state = start(fresh)
    observations(database, now, 15)
    if kind == "events":
        usage[0] = 200
    elif kind == "storage":
        usage[1] = 2_000_000
    else:
        for _ in range(8):
            from tests.unit.storage.test_acquisition_authority import ENDPOINT

            request = authority.reserve(ENDPOINT, now=now, host="host")
            authority.settle(request, response_bytes=1)
    result = check(fresh, state, now + timedelta(minutes=15))
    assert result["phase"] == "FAILED"
    assert result["reason"] == reason
    assert result["canary_storage_baseline_bytes"] == 233_472
    assert check(fresh, result, now + timedelta(minutes=16))["phase"] == "FAILED"


def test_healthy_empty_polls_cannot_earn_useful_canary_time(fresh):
    _, _, database, _ = fresh
    now, state = start(fresh)
    observations(database, now, 16)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM continuous_shadow_evaluations")
    result = check(fresh, state, now + timedelta(minutes=16))
    assert result["phase"] == "FAILED"
    assert result["reason"] == "fresh_input_flow_stalled_or_cohort_quiet"


def test_new_campaign_cannot_inherit_other_campaign_or_weaken_useful_gap(fresh):
    _, plan, _, _ = fresh
    with pytest.raises(ValueError, match="identity mismatch"):
        check(fresh, {"campaign_id": "other", "phase": "OBSERVING"}, NOW)
    plan["maximum_useful_observation_gap_seconds"] = 901
    with pytest.raises(ValueError, match="criteria"):
        check(fresh, {}, NOW)


def test_uncertain_charges_and_regressed_counters_cannot_pass_capacity(fresh):
    from tests.unit.storage.test_acquisition_authority import ENDPOINT

    authority, _, database, usage = fresh
    now, state = start(fresh)
    observations(database, now, 15)
    authority.reserve(ENDPOINT, now=now, host="host")
    assert check(fresh, state, now + timedelta(minutes=15))["reason"] == (
        "campaign_acquisition_accounting_uncertain"
    )
    usage[0] = -1
    with pytest.raises(ValueError, match="regressed"):
        check(fresh, state, now + timedelta(minutes=15))
