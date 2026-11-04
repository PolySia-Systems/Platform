from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import timedelta
from types import SimpleNamespace

import pytest

from polysia.deployment.nonlive_campaign_repair import begin_repair
from polysia.monitoring.nonlive_campaign import (
    REPAIR_RECEIPT,
    campaign_check,
    configuration_digest,
    effective_plan,
    supervise_campaign,
)
from polysia.storage.console_commands import ConsoleCommandStore
from tests.unit.monitoring.test_nonlive_campaign import campaign, observations
from tests.unit.storage.test_acquisition_authority import NOW

__all__ = ["campaign"]
CONTROLS = dict.fromkeys(
    ("stop_zero_io", "resume", "restart", "recovery", "protected_controls"), True,
)


@pytest.fixture
def repaired(campaign, monkeypatch):
    root, authority, plan, database = campaign
    with sqlite3.connect(root / "authority.sqlite3") as reader:
        request_id = reader.execute("SELECT request_id FROM reservations").fetchone()[0]
    authority.settle(request_id, response_bytes=85)
    authority.stop()
    plan.update(release_commit="a" * 40, cohort_digest="c" * 64)
    value = {"release_commit": "b" * 40, "admission": {"cohort_digest": "c" * 64},
             "database": str(database), "authority": str(root / "authority.sqlite3"),
             "manifest": str(root / "policy.json"), "commands": str(root / "commands.sqlite3"),
             "campaign": str(root / "plan.json")}
    plan["configuration_digest"] = "d" * 64
    raw = json.dumps(plan).encode()
    (root / "plan.json").write_bytes(raw)
    (root / "policy.json").write_text(json.dumps(authority.policy.to_dict()))
    ConsoleCommandStore(root / "commands.sqlite3").initialize()
    prior = b'{"phase":"FAILED","reason":"useful_poll_flow_stalled"}'
    database.with_name("nonlive-campaign-status.json").write_bytes(prior)
    value["campaign_repair"] = {
        "contract": "nonlive-campaign-repair/v1", "release_commit": "b" * 40,
        "image": "sha256:" + "e" * 64, "policy_digest": plan["policy_digest"],
        "cohort_digest": plan["cohort_digest"],
        "original_plan_sha256": hashlib.sha256(raw).hexdigest(),
        "previous_status_sha256": hashlib.sha256(prior).hexdigest(),
        "authorization_reference": "owner-readiness-repair",
        "reason": "Separate bounded readiness from useful acceptance after valid empty input.",
    }
    value["campaign_repair"]["configuration_digest"] = configuration_digest(value)
    config = root / "worker.json"
    config.write_text(json.dumps(value))
    active = SimpleNamespace(config=SimpleNamespace(
        code_sha=value["release_commit"], selection_preflight_digest=plan["cohort_digest"],
        capacity_evidence=value["admission"],
    ))
    monkeypatch.setattr("polysia.storage.continuous_shadow.ContinuousShadowRepository.active_experiment",
                        lambda *args: active)
    return config, value, authority, database, raw


def state(database):
    return json.loads(database.with_name("nonlive-campaign-status.json").read_bytes())


def check(value, raw, database, authority, previous, now, controls=CONTROLS):
    return campaign_check(effective_plan(value, raw), previous, database=database,
                          authority=authority, now=now, controls=controls)


def health(database, now):
    database.with_name("native-latency.health.json").write_text(json.dumps({
        "last_successful_flush": now.isoformat(), "telemetry_errors": 0,
        "dropped_measurements": 0,
        "process_capacity_summary": {"release_commit": "b" * 40, "samples": 1},
        "process_capacity": {"sample_seconds": 1, "peak_process_rss_bytes": 1000,
                             "process_cpu_percent_one_core": 2},
    }))


def test_repair_preserves_original_grant_and_failure_and_cannot_reset_it(repaired):
    config, value, authority, database, raw = repaired
    before = authority.status()
    receipt = begin_repair(config, now=NOW)
    assert receipt["prior_status"]["reason"] == "useful_poll_flow_stalled"
    assert authority.status() == before
    assert (config.parent / "plan.json").read_bytes() == raw
    assert state(database)["phase"] == "PREPARING"
    stopped = {**state(database), "phase": "FAILED", "reason": "later_failure"}
    database.with_name("nonlive-campaign-status.json").write_text(json.dumps(stopped))
    assert begin_repair(config, now=NOW + timedelta(minutes=1)) == receipt
    assert state(database) == stopped


def test_preparation_gets_no_time_credit_and_requires_fresh_data_controls_and_telemetry(repaired):
    config, value, authority, database, raw = repaired
    begin_repair(config, now=NOW)
    now = NOW + timedelta(hours=3)
    previous = state(database)
    assert check(value, raw, database, authority, previous, now)["phase"] == "PREPARING"
    observations(database, now - timedelta(minutes=1), 1)
    assert check(value, raw, database, authority, previous, now)["phase"] == "PREPARING"
    health(database, now)
    assert check(value, raw, database, authority, previous, now, {})["phase"] == "PREPARING"
    started = check(value, raw, database, authority, previous, now)
    assert started["phase"] == "CANARY"
    assert started["canary_started_at"] == now.isoformat()
    observations(database, now, 120)
    early = check(value, raw, database, authority, started, now + timedelta(minutes=119))
    assert early["phase"] == "CANARY"
    promoted = check(value, raw, database, authority, started, now + timedelta(hours=2))
    assert promoted["phase"] == "OBSERVING"
    assert promoted["observation_started_at"] == (now + timedelta(hours=2)).isoformat()


def test_readiness_has_hard_latest_start_and_missing_audit_fails_closed(repaired):
    config, value, authority, database, raw = repaired
    begin_repair(config, now=NOW)
    end = authority.policy.expires_at
    failed = check(value, raw, database, authority, state(database), end - timedelta(hours=50))
    assert failed["phase"] == "FAILED"
    assert failed["reason"] == "insufficient_remaining_real_observation_authority"
    database.with_name(REPAIR_RECEIPT).unlink()
    result = supervise_campaign(value, database=database, authority=authority, now=NOW)
    assert result["phase"] == "FAILED"
    assert authority.status()["stopped"] is True


@pytest.mark.parametrize("fault", ["plan", "receipt", "source", "pending", "late"])
def test_unbound_or_unsafe_repair_cannot_initialize(repaired, fault):
    config, value, authority, database, raw = repaired
    now = NOW
    if fault == "plan":
        (config.parent / "plan.json").write_bytes(raw + b" ")
    elif fault == "source":
        value["release_commit"] = "f" * 40
        config.write_text(json.dumps(value))
    elif fault == "pending":
        ConsoleCommandStore(config.parent / "commands.sqlite3").submit(
            subject="owner", action="resume", expected_revision=0,
            idempotency_key="pending-resume-is-not-repair-approval",
        )
    elif fault == "late":
        now = authority.policy.expires_at - timedelta(hours=50)
    else:
        begin_repair(config, now=NOW)
        path = database.with_name(REPAIR_RECEIPT)
        receipt = json.loads(path.read_bytes())
        receipt["prior_status_raw"] = "{}"
        path.write_text(json.dumps(receipt))
    before = authority.status()
    with pytest.raises(ValueError):
        begin_repair(config, now=now)
    assert authority.status() == before
