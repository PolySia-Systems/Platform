from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from scripts import windows_health as health

NOW = datetime(2026, 10, 25, 0, tzinfo=UTC)
SHA = "a" * 40


def fixture(run_id=1, *, conclusion="success", event="schedule", age=1):
    run = dict(
        id=run_id,
        run_attempt=1,
        event=event,
        head_branch="main",
        head_sha=SHA,
        head_repository={"full_name": health.REPOSITORY},
        path=".github/workflows/ci.yml",
        status="completed",
        conclusion=conclusion,
        created_at=(NOW - timedelta(days=age)).isoformat(),
        html_url=f"https://example/{run_id}",
    )
    job = dict(
        name="Windows Compatibility",
        head_sha=SHA,
        conclusion=conclusion,
        labels=["windows-latest"],
        steps=[dict(name=name, conclusion="success") for name in health.STEPS],
    )
    return run, job


def test_failure_partial_and_unrelated_green_cannot_heal():
    good, good_job = fixture(1, age=3)
    failed, failed_job = fixture(2, conclusion="failure", age=2)
    unrelated, unrelated_job = fixture(3, event="push", age=1)
    unrelated_job["conclusion"] = "skipped"
    result = health.assess(
        [good, failed, unrelated],
        {1: [good_job], 2: [failed_job], 3: [unrelated_job]},
        {1: {"source": SHA}, 2: {"source": SHA}},
        NOW,
    )
    assert result["outcome"] == "action_required"
    assert result["unresolved_failure"]["id"] == 2
    partial, partial_job = fixture(4, age=0)
    partial_job["steps"].pop()
    result = health.assess(
        [good, partial],
        {1: [good_job], 4: [partial_job]},
        {1: {"source": SHA}, 4: {"source": SHA}},
        NOW,
    )
    assert result["unresolved_failure"]["id"] == 4


@pytest.mark.parametrize("defect", ["foreign", "pr", "sha", "step", "job_sha", "source", "labels"])
def test_trust_and_input_identity_fail_closed(defect):
    run, job = fixture()
    sources = {1: {"source": SHA}}
    if defect == "foreign":
        run["head_repository"]["full_name"] = "other/Platform"
    elif defect == "pr":
        run["event"] = "pull_request"
    elif defect == "sha":
        run["head_sha"] = "not-a-sha"
    elif defect == "step":
        job["steps"][0]["conclusion"] = "skipped"
    elif defect == "job_sha":
        job["head_sha"] = "b" * 40
    elif defect == "labels":
        job["labels"] = ["ubuntu-latest"]
    else:
        sources = {}
    assert health.assess([run], {1: [job]}, sources, NOW)["outcome"] == "action_required"


def test_qualifying_recovery_overdue_and_pending():
    failed, failed_job = fixture(1, conclusion="failure", age=2)
    good, job = fixture(2, age=1)
    assert (
        health.assess(
            [failed, good],
            {1: [failed_job], 2: [job]},
            {1: {"source": SHA}, 2: {"source": SHA}},
            NOW,
        )["outcome"]
        == "healthy"
    )
    old, job = fixture(age=10)
    assert (
        health.assess([old], {1: [job]}, {1: {"source": SHA}}, NOW)["outcome"] == "action_required"
    )
    pending, pending_job = fixture(3, age=0)
    pending["status"] = "in_progress"
    result = health.assess(
        [failed, pending], {1: [failed_job], 3: [pending_job]}, {1: {"source": SHA}}, NOW
    )
    assert result["in_progress"]
    assert result["unresolved_failure"]["id"] == 1


def test_notification_meaningful_transitions_and_denial():
    result = health.assess([], {}, {}, NOW)
    issues, mutations = [], []

    def request(path, *, method="GET", body=None):
        if method == "GET":
            return copy.deepcopy(issues)
        mutations.append((path, method, body))
        issues[:] = [dict(number=99, **body)]

    health.notify(result, request)
    health.notify(result | {"in_progress": True}, request)
    assert len(mutations) == 1
    health.notify(result | {"outcome": "healthy", "problems": []}, request)
    assert len(mutations) == 2
    assert issues[0]["state"] == "closed"
    health.notify(result, request)
    assert len(mutations) == 3

    def denied(*args, **kwargs):
        raise PermissionError("API denied")

    with pytest.raises(PermissionError, match="denied"):
        health.notify(result, denied)


def test_missing_or_skipped_timing_cannot_complete_current_source_contract():
    run, job = fixture()
    source = {1: {"required_steps": [*health.STEPS, "Retain Windows timing"]}}
    result = health.assess([run], {1: [job]}, source, NOW)
    assert result["outcome"] == "action_required"
    job["steps"].append(dict(name="Retain Windows timing", conclusion="success"))
    assert health.assess([run], {1: [job]}, source, NOW)["outcome"] == "healthy"


def test_failed_classification_is_partial_even_when_windows_skipped():
    run, job = fixture(event="push")
    job["conclusion"] = "skipped"
    jobs = {1: [job, dict(name="changes", conclusion="failure")]}
    result = health.assess([run], jobs, {}, NOW)
    assert result["unresolved_failure"]["id"] == 1


def test_unknown_source_contract_and_api_denial_are_visible(monkeypatch):
    import base64

    def unsupported(path, **kwargs):
        return {"content": base64.b64encode(b"jobs: {}\n").decode()}

    monkeypatch.setattr(health, "api", unsupported)
    with pytest.raises(ValueError):
        health.source_identity(SHA)

    def denied(*args, **kwargs):
        raise PermissionError("API denied")

    monkeypatch.setattr(health, "api", denied)
    with pytest.raises(PermissionError, match="denied"):
        health.observe()
