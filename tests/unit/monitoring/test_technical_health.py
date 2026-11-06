"""Deterministic controller state transitions, explicitly not prospective soak evidence."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from polysia.domain.copytrading.native_health import PURPOSE, RUNTIME
from polysia.domain.copytrading.native_run_limits import NativeRunLimits
from polysia.monitoring import technical_health as health
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from tests.unit.storage.test_acquisition_authority import ENDPOINT, NOW, policy


@pytest.fixture
def run(tmp_path, monkeypatch):
    base = replace(policy(), minimum_free_disk_bytes=9_663_676_416)
    authority = AcquisitionAuthority(tmp_path / "authority.sqlite3", base)
    authority.initialize()
    authority.stop()
    new = replace(base, purpose=PURPOSE, policy_id="health-test", maximum_requests=220000,
                  maximum_bytes=4_294_967_296, window_maximum_requests=4320,
                  window_maximum_bytes=67_108_864, expires_at=NOW + timedelta(hours=72))
    authority = authority.grant_finite_campaign(
        new, now=NOW, authorization_reference="owner-health-test",
        additional_requests=220000, additional_bytes=4_294_967_296,
    )
    authority.resume(now=NOW, host="host")
    request = authority.reserve(ENDPOINT, now=NOW, host="host")
    authority.settle(request, response_bytes=85)
    limits = NativeRunLimits()
    config = SimpleNamespace(runtime_version=RUNTIME, code_sha="a" * 40,
                             selection_preflight_digest="b" * 64,
                             capacity_evidence={"contract": "native-health-admission/v1",
                                "purpose": PURPOSE, "mode": "CONTINUOUS", "code_sha": "a" * 40,
                                "cohort_digest": "b" * 64, "policy_digest": new.digest,
                                "financial_authority": False, "resource_admitted": True,
                                "expires_at": new.expires_at.isoformat()},
                             **{k: v for k, v in limits.to_dict().items() if k != "contract"})

    class Store:
        def __init__(self, _path): pass
        def active_experiment(self, _source):
            return SimpleNamespace(config=config, experiment_id="health-test")
        def period_usage(self, _experiment): return 0, 1000000

    monkeypatch.setattr(health, "ContinuousShadowRepository", Store)
    database = tmp_path / "financial.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE continuous_shadow_poll_runs "
                           "(experiment_id,started_at,completed_at,status,new_event_count)")
    plan = {"contract": health.CONTRACT, "purpose": PURPOSE, "acceptance": health.ACCEPTANCE,
            "campaign_id": "health-test", "policy_digest": new.digest,
            "scheduled_poll_slot_seconds": 60,
            "starts_at": NOW.isoformat(), "expires_at": new.expires_at.isoformat(),
            "release_commit": "a" * 40, "cohort_digest": "b" * 64,
            "period_capacity": limits.to_dict()}
    controls = dict.fromkeys(("stop_zero_io", "resume", "restart", "recovery",
                              "protected_controls"), True)
    return authority, database, plan, controls


def samples(run, start, count, *, skip_every=0):
    authority, database, _, _ = run
    with sqlite3.connect(database) as connection:
        for minute in range(count):
            stamp = start + timedelta(minutes=minute)
            status = "failed" if skip_every and minute % skip_every == 0 else "succeeded"
            connection.execute("INSERT INTO continuous_shadow_poll_runs VALUES(?,?,?,?,?)",
                               ("health-test", stamp.isoformat(), stamp.isoformat(), status, 0))
            health.record_tick(authority.path, {
                "status": "OBSERVING" if status == "succeeded" else "FAILED",
                "release_commit": "a" * 40, "policy_digest": authority.policy.digest,
            }, now=stamp)
    latest = start + timedelta(minutes=count - 1)
    database.with_name("native-latency.health.json").write_text(json.dumps({
        "last_successful_flush": latest.isoformat(),
        "process_capacity_summary": {"release_commit": "a" * 40},
        "process_capacity": {"sample_seconds": 2, "peak_process_rss_bytes": 50_000_000,
                             "process_cpu_percent_one_core": 25,
                             "disk_free_bytes": 20_000_000_000},
    }))


def check(run, previous, now, *, controls=None):
    authority, database, plan, bound = run
    return health.health_check(plan, previous, database=database, authority=authority,
                               now=now, controls=bound if controls is None else controls)


def test_quiet_and_bounded_transients_pass_two_windows_inside_48_hours(run):
    samples(run, NOW, 1)
    initial = check(run, {}, NOW)
    assert initial["phase"] == "HEALTH_OBSERVATION_RUNNING"
    assert initial["observation_ends_at"] == (NOW + timedelta(hours=48)).isoformat()
    samples(run, NOW + timedelta(minutes=1), 120, skip_every=50)
    canary = check(run, initial, NOW + timedelta(hours=2))
    assert canary["phase"] == "HEALTH_OBSERVATION_RUNNING"
    assert canary["canary_passed_at"] == (NOW + timedelta(hours=2)).isoformat()
    assert canary["failed_polls"] == 3
    assert canary["period_events"] == 0
    samples(run, NOW + timedelta(minutes=121), 2760, skip_every=50)
    final = check(run, canary, NOW + timedelta(hours=48))
    assert final["phase"] == "OBSERVATION_COMPLETE_REVIEW_REQUIRED"
    assert final["observed_seconds"] == 172800
    assert final["poll_coverage_percent"] >= 95
    assert final["complete_zero_new_event_polls"] > 2800
    assert final["financial_authority"] is False


def test_elapsed_time_stale_status_and_missing_controls_never_pass(run):
    samples(run, NOW, 1)
    assert check(run, {}, NOW, controls={})["phase"] == "PREPARING"
    running = check(run, {}, NOW)
    failed = check(run, running, NOW + timedelta(hours=48))
    assert failed["phase"] == "FAILED"
    assert "gap" in failed["reason"]


def test_uncertainty_stop_expiry_and_legacy_contract_are_not_bypassed(run):
    authority, _, plan, _ = run
    samples(run, NOW, 1)
    running = check(run, {}, NOW)
    authority.reserve(ENDPOINT, now=NOW, host="host")
    assert check(run, running, NOW)["reason"] == "health_shared_accounting_uncertain"
    with pytest.raises(AcquisitionBlockedError, match="accounting_uncertain"):
        authority.reserve(ENDPOINT, now=NOW, host="host")
    assert check(run, running, NOW + timedelta(hours=72))["phase"] == "EXPIRED"
    plan["purpose"] = "PUBLIC_RESEARCH"
    with pytest.raises(ValueError, match="purpose"):
        check(run, {}, NOW)


def test_sqlite_checkpoint_shrinkage_is_not_consumption_regression(run, monkeypatch):
    samples(run, NOW, 1)
    running = check(run, {}, NOW)
    samples(run, NOW + timedelta(minutes=1), 16)
    monkeypatch.setattr(health.ContinuousShadowRepository, "period_usage",
                        lambda self, experiment: (0, 500000))
    current = check(run, running, NOW + timedelta(minutes=16))
    assert current["phase"] == "HEALTH_OBSERVATION_RUNNING"
    assert current["period_storage_bytes"] == 500000
    assert current["period_storage_peak_bytes"] == 1000000
    assert current["capacity_forecast"]["period_storage_bytes"] == 1000000


def test_preparing_initialized_store_without_period_waits_for_bounded_retry(run, monkeypatch):
    monkeypatch.setattr(health.ContinuousShadowRepository, "active_experiment",
                        lambda self, source: None)
    current = check(run, {}, NOW)
    assert current["phase"] == "PREPARING"
    assert current["reason"] == "await_installed_continuous_poll"
    assert run[0].status()["requests_charged"] == 1
    assert run[0].status()["stopped"] is False
    retained = {"campaign_id": run[2]["campaign_id"], "phase": "HEALTH_OBSERVATION_RUNNING",
                "observation_started_at": NOW.isoformat()}
    assert check(run, retained, NOW)["reason"] == "health_installed_period_identity_mismatch"
