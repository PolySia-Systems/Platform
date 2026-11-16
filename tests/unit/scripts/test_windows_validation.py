from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from scripts.classify_ci_changes import project_policy
from scripts.windows_validation import selected_tests


@pytest.mark.parametrize("paths", [[], ["README.md"],
    ["src/polysia/adapters/polymarket/bounded_transport.py"], ["unknown/file.xyz"]])
def test_explicit_opt_in_always_selects_full_native_suite(paths) -> None:
    policy = project_policy(paths, event="workflow_dispatch", run_windows="true")
    assert selected_tests(policy) == ()
    broken = copy.deepcopy(policy)
    broken["source"]["run_windows"] = "false"
    with pytest.raises(ValueError):
        selected_tests(broken)


def test_unrequested_windows_cannot_run() -> None:
    for event in ("push", "pull_request", "schedule", "workflow_dispatch"):
        with pytest.raises(ValueError, match="not selected"):
            selected_tests(project_policy([], event=event, validation_scope="full"))


def test_workflow_boundary_and_all_dispatch_consumers() -> None:
    root = Path(__file__).resolve().parents[3]
    # BaseLoader preserves Actions' on key instead of YAML 1.1's boolean alias.
    workflow = yaml.load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
                         Loader=yaml.BaseLoader)
    consent = workflow["on"]["workflow_dispatch"]["inputs"]["run_windows"]
    assert consent["type"] == "boolean" and consent["default"] == "false"
    jobs = workflow["jobs"]
    guard = jobs["windows-compatibility"]["if"]
    assert "github.event_name == 'workflow_dispatch'" in guard
    assert "inputs.run_windows == true" in guard
    assert "needs.changes.outputs.windows == 'true'" in guard
    for job in ("changes", "ci-gate"):
        steps = [step for step in jobs[job]["steps"]
                 if "classify_ci_changes.py" in step.get("run", "")]
        assert len(steps) == 1
        assert steps[0]["env"]["RUN_WINDOWS"] == "${{ inputs.run_windows && 'true' || 'false' }}"
        assert '--run-windows "$RUN_WINDOWS"' in steps[0]["run"]
    native_jobs = []
    for path in (root / ".github/workflows").glob("*.yml"):
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for name, job in document["jobs"].items():
            if "windows" in str(job.get("runs-on", "")).lower():
                native_jobs.append((path.name, name))
    assert native_jobs == [("ci.yml", "windows-compatibility")]
    assert not (root / ".github/workflows/windows-health.yml").exists()
