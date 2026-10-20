from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import dependency_locks

ROOT = Path(__file__).resolve().parents[3]


def test_git_contents_request_is_explicit_get_and_attributes_read_failures(monkeypatch):
    seen = []

    def run(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps({
            "content": base64.b64encode(b"pure configuration").decode(),
        }))

    monkeypatch.setattr(dependency_locks.subprocess, "run", run)
    assert dependency_locks._git_text("owner/repo", "a" * 40, "pyproject.toml") == (
        "pure configuration"
    )
    assert seen[0][:4] == ("gh", "api", "--method", "GET")
    assert "ref=" + "a" * 40 in seen[0]

    def denied(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="private provider detail")

    monkeypatch.setattr(dependency_locks.subprocess, "run", denied)
    with pytest.raises(RuntimeError, match="GitHub contents GET failed") as error:
        dependency_locks._git_text("owner/repo", "a" * 40, "pyproject.toml")
    assert "private provider detail" not in str(error.value)


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/dependency-automation.yml").read_text())


def test_generation_has_no_write_authority_and_publisher_uses_main():
    value = workflow()
    assert value["permissions"] == {"contents": "read"}
    for job in value["jobs"].values():
        assert all(permission == "read" for permission in job.get("permissions", {}).values())
    publisher = yaml.safe_load((ROOT / ".github/workflows/dependency-publish.yml").read_text())
    job = publisher["jobs"]["publish"]
    checkout = next(s for s in job["steps"] if "checkout@" in s.get("uses", ""))
    assert checkout["with"]["ref"] == "main"
    assert checkout["with"]["persist-credentials"] is False
    assert not any("pip install" in s.get("run", "") for s in job["steps"])
    text = (ROOT / ".github/workflows/dependency-publish.yml").read_text()
    assert "workflow_run:" in text
    assert "run-id: ${{ github.event.workflow_run.id }}" in text
    assert "can_approve_pull_request_reviews" not in text


def test_ci_health_check_is_independent_and_cannot_mutate_from_pr():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    health = ci["jobs"]["dependency-health"]
    assert "github.event_name == 'schedule'" in health["if"]
    assert "github.ref == 'refs/heads/main'" in health["if"]
    assert "pull_request" not in health["if"]
    assert health["permissions"]["contents"] == "read"
    assert health["permissions"]["issues"] == "write"


def test_sdk_declaration_cannot_trigger_unreviewed_lock_generation(monkeypatch):
    monkeypatch.setattr(dependency_locks, "_pr_changed_files", lambda *_: ("pyproject.toml",))
    original = (ROOT / "pyproject.toml").read_text()
    monkeypatch.setattr(dependency_locks, "_git_text", lambda _repo, ref, _path:
                        original if ref == "a" * 40 else original.replace(
                            "polymarket-client==0.13.0", "polymarket-client==0.14.0"))
    decision = dependency_locks.evaluate_lock_sync(
        repository="PolySia-Systems/Platform", number=169, actor="dependabot[bot]",
        base_branch="main", head_branch="dependabot/pip/test", base_sha="a" * 40,
        head_sha="b" * 40,
    )
    assert decision["status"] == "noop"
    assert decision["decision"] == "human_review"
