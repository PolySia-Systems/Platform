from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from polysia.monitoring.nonlive_campaign import campaign_check, supervise_campaign
from polysia.storage.acquisition_authority import AcquisitionAuthority
from tests.unit.storage.test_acquisition_authority import ENDPOINT, NOW, policy


@pytest.fixture
def campaign(tmp_path):
    original = replace(policy(), minimum_free_disk_bytes=9_663_676_416)
    authority = AcquisitionAuthority(tmp_path / "authority.sqlite3", original)
    authority.initialize()
    authority.stop()
    replacement = replace(
        original,
        policy_id="new",
        maximum_requests=1000,
        maximum_bytes=1_000_000,
        expires_at=NOW + timedelta(hours=72),
    )
    authority = authority.grant_finite_campaign(
        replacement,
        now=NOW,
        additional_requests=1000,
        additional_bytes=1_000_000,
        authorization_reference="owner-finite-test",
    )
    authority.resume(now=NOW, host="host")
    authority.reserve(ENDPOINT, now=NOW, host="host")
    plan = {
        "contract": "nonlive-campaign/v1",
        "campaign_id": "test",
        "starts_at": NOW.isoformat(),
        "expires_at": replacement.expires_at.isoformat(),
        "canary_not_before": (NOW + timedelta(hours=2)).isoformat(),
        "policy_digest": replacement.digest,
        "observation_seconds": 172800,
        "maximum_poll_gap_seconds": 180,
        "maximum_input_age_seconds": 300,
        "minimum_fresh_evaluations": 2,
    }
    database = tmp_path / "financial.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE continuous_shadow_poll_runs(poll_run_id TEXT,started_at TEXT,"
            "completed_at TEXT,status TEXT,new_event_count INTEGER);"
            "CREATE TABLE continuous_shadow_evaluations(poll_run_id TEXT,"
            "source_api_lag_ms INTEGER,signal_delay_ms INTEGER);"
        )
    return tmp_path, authority, plan, database


def observations(database, start, minutes):
    with sqlite3.connect(database) as connection:
        for minute in range(minutes + 1):
            stamp = start + timedelta(minutes=minute)
            identity = stamp.isoformat()
            connection.execute(
                "INSERT INTO continuous_shadow_poll_runs VALUES(?,?,?,?,?)",
                (
                    identity,
                    identity,
                    identity,
                    "succeeded",
                    1,
                ),
            )
            connection.execute(
                "INSERT INTO continuous_shadow_evaluations VALUES(?,?,?)",
                (
                    identity,
                    60000,
                    1000,
                ),
            )


def test_server_does_not_promote_early_or_with_missing_control_evidence(campaign):
    _, authority, plan, database = campaign
    observations(database, NOW, 120)
    early = campaign_check(
        plan,
        {},
        database=database,
        authority=authority,
        now=NOW + timedelta(minutes=119),
        controls={},
    )
    assert early["phase"] == "CANARY"
    denied = campaign_check(
        plan, {}, database=database, authority=authority, now=NOW + timedelta(hours=2), controls={}
    )
    assert denied["phase"] == "FAILED"
    assert denied["reason"] == "canary_control_evidence_incomplete"


def test_server_requires_real_duration_and_stops_at_completion_without_liquidation(campaign):
    _, authority, plan, database = campaign
    observations(database, NOW, 120)
    controls = dict.fromkeys(
        ("stop_zero_io", "resume", "restart", "recovery", "protected_controls"), True
    )
    state = campaign_check(
        plan,
        {},
        database=database,
        authority=authority,
        now=NOW + timedelta(hours=2),
        controls=controls,
    )
    assert state["phase"] == "OBSERVING"
    observations(database, NOW + timedelta(hours=2), 48 * 60)
    state = campaign_check(
        plan,
        state,
        database=database,
        authority=authority,
        now=NOW + timedelta(hours=50),
        controls=controls,
    )
    assert state["phase"] == "OBSERVATION_COMPLETE_REVIEW_REQUIRED"
    assert state["final_review"] == "REQUIRED"
    assert state["financial_authority"] is False


def test_elapsed_time_does_not_hide_stalled_data_and_failure_remains_sticky(campaign):
    _, authority, plan, database = campaign
    observations(database, NOW, 1)
    result = campaign_check(
        plan,
        {"phase": "OBSERVING", "observation_started_at": NOW.isoformat()},
        database=database,
        authority=authority,
        now=NOW + timedelta(hours=48),
        controls={},
    )
    assert result["phase"] == "FAILED"
    assert result["reason"] == "useful_poll_flow_stalled"
    observations(database, NOW, 48 * 60)
    assert (
        campaign_check(
            plan,
            result,
            database=database,
            authority=authority,
            now=NOW + timedelta(hours=48),
            controls={},
        )["phase"]
        == "FAILED"
    )


def test_unavailable_plan_independently_stops_before_acquisition(campaign):
    root, authority, _, database = campaign
    result = supervise_campaign(
        {"campaign": str(root / "missing.json")}, database=database, authority=authority, now=NOW
    )
    assert result["phase"] == "FAILED"
    assert authority.status()["stopped"] is True
