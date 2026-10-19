from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
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


def test_scheduled_workflow_retains_proposals_without_attempting_denied_publication():
    value = workflow()
    events = value.get("on", value.get(True))  # YAML 1.1's spelling of on.
    assert events["workflow_dispatch"]["inputs"]["publish"]["default"] is False
    publication = value["jobs"]["scheduled-publish"]
    assert "workflow_dispatch" in publication["if"] and "inputs.publish" in publication["if"]
    mutate = next(step for step in publication["steps"]
                  if "delete_on_failed_open" in step.get("run", ""))
    assert mutate["if"] == "steps.capability.outputs.allowed == 'true'"


@pytest.mark.parametrize("delete_requested,changed_head,pr_count,should_delete", [
    (True, False, 0, True), (False, False, 0, False),
    (True, True, 0, False), (True, False, 1, False),
])
def test_workflow_failure_shell_calls_real_cleanup_helper(
    tmp_path: Path, delete_requested, changed_head, pr_count, should_delete,
):
    """Run the actual YAML boolean handoff and failure path with local tool fakes."""
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).resolve().parents[1] / "bin/bash.exe" if git else None
        if candidate and candidate.is_file():
            bash = str(candidate)
    assert bash, "workflow contract requires the same Bash shell available on CI runners"
    step = next(item for item in workflow()["jobs"]["scheduled-publish"]["steps"]
                if "delete_on_failed_open" in item.get("run", ""))
    script = step["run"]
    boolean_line = next(line for line in script.splitlines() if line.startswith("DELETE_ON_FAIL="))
    start = script.index("if ! PR_URL=$(gh pr create")
    end = script.index("\n  gh workflow run", start)
    failure = script[start:end]
    (tmp_path / "plan.json").write_text(json.dumps({"delete_on_failed_open": delete_requested}))
    deletes = tmp_path / "deletions.txt"
    shell = '''set -euo pipefail
python() { "$ACTUAL_PYTHON" "$@"; }
gh() { if [ "$1 $2" = "pr create" ]; then return 1; fi; echo "$TEST_PR_COUNT"; }
git() {
  if [ "$1" = "ls-remote" ]; then printf '%s\\trefs/heads/example\\n' "$TEST_REMOTE_SHA";
  elif [ "$1" = "push" ]; then printf '%s\\n' "$*" >> "$TEST_DELETIONS";
  else return 90; fi
}
'''
    environment = dict(os.environ, ACTUAL_PYTHON=Path(sys.executable).as_posix(),
                       RUNNER_TEMP=tmp_path.as_posix(),
                       PLAN_BRANCH="codex/scheduled-lock-refresh-20261018",
                       CREATED_SHA="a" * 40, TEST_REMOTE_SHA=("b" if changed_head else "a") * 40,
                       TEST_PR_COUNT=str(pr_count), TEST_DELETIONS=deletes.as_posix(),
                       PR_BODY="local test body")
    result = subprocess.run([bash, "-c", shell + boolean_line + "\n" + failure],
                            cwd=ROOT, env=environment, text=True, capture_output=True, timeout=30)
    assert result.returncode == 1, result.stderr
    assert deletes.exists() is should_delete
    if should_delete:
        assert "--delete codex/scheduled-lock-refresh-20261018" in deletes.read_text()


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
