from __future__ import annotations

import copy
import hashlib
import json

import pytest

from scripts.classify_ci_changes import project_policy
from scripts.release_evidence import (
    ARTIFACTS,
    JOBS,
    REPOSITORY,
    select_artifacts,
    validate_receipt,
    validate_run,
)


def evidence():
    run = dict(id=10, run_attempt=2, workflow_id=7, path=".github/workflows/ci.yml",
               event="workflow_dispatch", head_branch="main", status="completed",
               conclusion="success", head_sha="a" * 40,
               repository=dict(full_name=REPOSITORY), head_repository=dict(full_name=REPOSITORY))
    jobs = [dict(name=name, run_id=10, run_attempt=2, head_sha="a" * 40,
                 status="completed", conclusion="success") for name in JOBS]
    receipt = dict(repository=REPOSITORY, run_id=10, run_attempt=2, policy=project_policy(
        ["README.md"], event="workflow_dispatch", head="a" * 40,
        validation_scope="full", run_windows="true"))
    artifacts = [dict(name=f"{name}-attempt-2", expired=False,
                      workflow_run=dict(id=10, head_sha="a" * 40)) for name in ARTIFACTS]
    return run, jobs, receipt, artifacts


def test_full_manual_release_accepts_one_exact_attempt() -> None:
    run, jobs, receipt, artifacts = evidence()
    validate_run(run, jobs, 7)
    validate_receipt(receipt, run)
    assert select_artifacts(artifacts, run) == [f"{name}-attempt-2" for name in ARTIFACTS]


@pytest.mark.parametrize(("key", "bad"), [
    ("event", "push"), ("head_branch", "other"), ("head_sha", "main"),
    ("path", ".github/workflows/other.yml"), ("workflow_id", 8),
    ("repository", dict(full_name="other/repo")), ("head_repository", {}),
    ("conclusion", "failure"), ("status", "in_progress"),
])
def test_wrong_release_source_is_rejected(key, bad) -> None:
    run, jobs, _, _ = evidence()
    run[key] = bad
    with pytest.raises(ValueError):
        validate_run(run, jobs, 7)


@pytest.mark.parametrize("result", [None, "skipped", "failure", "cancelled"])
def test_incomplete_windows_evidence_is_rejected(result) -> None:
    run, jobs, _, _ = evidence()
    jobs[3]["conclusion"] = result
    with pytest.raises(ValueError):
        validate_run(run, jobs, 7)


def test_partial_mixed_stale_or_forged_evidence_is_rejected() -> None:
    run, jobs, receipt, artifacts = evidence()
    for key, value in (("run_attempt", 1), ("head_sha", "b" * 40), ("run_id", 11)):
        broken = copy.deepcopy(jobs)
        broken[0][key] = value
        with pytest.raises(ValueError):
            validate_run(run, broken, 7)
    for key, value in (("run_attempt", 1), ("run_id", 11), ("repository", "other/repo")):
        with pytest.raises(ValueError):
            validate_receipt(dict(receipt, **{key: value}), run)
    for scope, consent in (("auto", "true"), ("full", "false")):
        broken = dict(receipt, policy=project_policy(["README.md"], event="workflow_dispatch",
                      head="a" * 40, validation_scope=scope, run_windows=consent))
        with pytest.raises(ValueError):
            validate_receipt(broken, run)
    for key, value in (("expired", True), ("name", "polysia-sbom-attempt-1"),
                       ("workflow_run", dict(id=11, head_sha="a" * 40))):
        broken = copy.deepcopy(artifacts)
        broken[-1][key] = value
        with pytest.raises(ValueError):
            select_artifacts(broken, run)
    for broken in (artifacts[:-1], artifacts + [artifacts[0]]):
        with pytest.raises(ValueError):
            select_artifacts(broken, run)


def test_archive_source_and_hash_checks(tmp_path) -> None:
    from scripts.release_evidence import validate_archive

    manifest = dict(commit="a" * 40, archive_name="polysia-image.tar.gz")
    for name, key in (
        ("platform_backup.py", "backup_job_sha256"),
        ("platform_bootstrap.py", "bootstrap_sha256"),
        ("platform_admin.py", "admin_sha256"), ("os-packages.txt", "os_packages_sha256"),
        ("polysia-image.tar.gz", "archive_sha256"),
    ):
        (tmp_path / name).write_bytes(name.encode())
        manifest[key] = hashlib.sha256(name.encode()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    validate_archive(tmp_path, "a" * 40)
    with pytest.raises(ValueError, match="source differs"):
        validate_archive(tmp_path, "b" * 40)
    (tmp_path / "polysia-image.tar.gz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="archive hash"):
        validate_archive(tmp_path, "a" * 40)


def test_release_preparation_uses_attempt_endpoints_and_checks_receipt_first(
    tmp_path, monkeypatch,
) -> None:
    from scripts import release_evidence as release

    run, jobs, receipt, artifacts = evidence()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_RUN_ID", "10")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(release.sys, "argv", ["release_evidence.py"])
    responses = {
        "actions/runs/10": run, "actions/workflows/ci.yml": dict(id=7),
        "actions/runs/10/attempts/2/jobs?per_page=100": dict(total_count=len(jobs), jobs=jobs),
        "actions/runs/10/artifacts?per_page=100": dict(total_count=4, artifacts=artifacts),
    }
    monkeypatch.setattr(release, "api", lambda path: responses[path])
    commands = []

    def command(args, **kwargs):
        commands.append(args)
        if args[0] == "gh":
            if args[-1] == "evidence":
                (tmp_path / "evidence").mkdir(exist_ok=True)
                (tmp_path / "evidence/ci-policy.json").write_text(json.dumps(receipt))
            else:
                assert (tmp_path / "evidence/ci-policy.json").exists()

    monkeypatch.setattr(release.subprocess, "run", command)
    release.main()
    assert len(commands) == 5
    assert json.loads((tmp_path / "run.json").read_text())["run_attempt"] == 2
    run["run_attempt"] = 3
    with pytest.raises(ValueError, match="attempt changed"):
        release.assert_current_attempt(dict(run, run_attempt=2))
