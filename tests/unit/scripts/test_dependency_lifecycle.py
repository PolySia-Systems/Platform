from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from polysia.developer.dependency_preflight import dependency_preflight, input_hashes
from scripts import dependency_lifecycle as lifecycle
from scripts import dependency_locks as locks
from scripts import dependency_publication as publication
from scripts.dependency_policy import (
    DEV_LOCK,
    EXPECTED_REPOSITORY,
    PYPROJECT,
    RUNTIME_LOCK,
    is_low_risk_version_bump,
    is_trusted_dependency_actor,
    parse_lock_pins,
)
from scripts.dependency_provenance import FILES, WORKFLOW, binding, seal, validate

BASE, HEAD = "a" * 40, "b" * 40
NOW = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def proposal(tmp_path):
    root, artifact = tmp_path / "root", tmp_path / "artifact"
    for path in (root, artifact):
        (path / "locks").mkdir(parents=True)
        (path / PYPROJECT).write_text("""[build-system]
requires = ["hatchling==1.32.4"]
build-backend = "hatchling.build"
[project]
name = "polysia"
requires-python = ">=3.14,<3.15"
dependencies = ["rich==15.0.0"]
[project.optional-dependencies]
dev = ["hypothesis==6.170.1"]
""")
        (path / RUNTIME_LOCK).write_text("rich==15.0.0\n")
        (path / DEV_LOCK).write_text("rich==15.0.0\nhypothesis==6.170.1\nhatchling==1.32.4\n")
    identity = binding(
        repository=EXPECTED_REPOSITORY,
        actor="dependabot[bot]",
        base=BASE,
        head=HEAD,
        run="1234",
        attempt="1",
    )
    seal(artifact, root, identity)
    return root, artifact, identity


@pytest.mark.parametrize(
    "old,new",
    [
        ("1.2.3", "1.2.4rc1"),
        ("1.2.3", "1.3.0.dev1"),
        ("1.2.3", "1!1.2.4"),
        ("1!1.2.3", "1!1.2.4"),
        ("1.2.3", "1.2.4+local"),
        ("1.2.3+local", "1.2.4"),
        ("1.2.3", "1.2.3.post1"),
        ("1.2.3", "1.2.2"),
        ("1.2.3", "1.2.4junk"),
        ("1.2.3rc1", "1.2.3"),
        ("0.17.1", "0.18.0"),
        ("1.2.3", "1.2.3.4"),
    ],
)
def test_nonroutine_versions_are_held(old, new):
    assert not is_low_risk_version_bump(old, new)


def test_branch_prefix_does_not_confer_actor_trust():
    assert not is_trusted_dependency_actor("spoof", "codex/scheduled-lock-refresh-20261020")
    assert is_trusted_dependency_actor("github-actions[bot]", "codex/scheduled-lock-refresh-abc")
    assert not is_trusted_dependency_actor("dependabot[bot]", "feature/attacker")


@pytest.mark.parametrize(
    "text", ["x==1.0\nx==1.1\n", "x==1.0junk\n", "x==1.0 \\\n--index-url https://example.invalid\n"]
)
def test_malformed_or_ambiguous_locks_fail_closed(text):
    with pytest.raises(ValueError):
        parse_lock_pins(text)


def test_origin_and_hashes_are_independently_required(proposal):
    root, artifact, identity = proposal
    validate(artifact, root, identity)
    for field, value in (
        ("repository", "spoof/repo"),
        ("actor", "spoof"),
        ("base", HEAD),
        ("head", BASE),
        ("run", "1235"),
        ("attempt", "2"),
        ("workflow", ".github/workflows/spoof.yml"),
    ):
        with pytest.raises(ValueError, match="origin"):
            validate(artifact, root, dict(identity, **{field: value}))
    (artifact / DEV_LOCK).write_text("rich==15.0.0\nhypothesis==6.170.2\n")
    with pytest.raises(ValueError, match="hash"):
        validate(artifact, root, identity)


def test_resealed_non_dependency_manifest_change_is_rejected(proposal):
    root, artifact, identity = proposal
    manifest = artifact / PYPROJECT
    manifest.write_text(manifest.read_text().replace(">=3.14,<3.15", ">=3.15"))
    seal(artifact, root, identity)
    with pytest.raises(ValueError, match="outside dependency"):
        validate(artifact, root, identity)


def test_missing_runtime_pin_and_build_drift_fail_closed(proposal):
    root, artifact, identity = proposal
    (artifact / DEV_LOCK).write_text("hypothesis==6.170.1\nhatchling==1.32.4\n")
    seal(artifact, root, identity)
    with pytest.raises(ValueError, match="omits a runtime"):
        validate(artifact, root, identity)


def test_stale_source_and_extra_artifact_paths_are_rejected(proposal):
    root, artifact, identity = proposal
    (artifact / "extra.py").write_text("raise AssertionError('never execute')")
    with pytest.raises(ValueError, match="unexpected artifact path"):
        validate(artifact, root, identity)
    (artifact / "extra.py").unlink()
    (root / PYPROJECT).write_text((root / PYPROJECT).read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="source changed"):
        validate(artifact, root, identity)


def test_atomic_writer_sends_server_enforced_head_precondition(monkeypatch):
    requests = []

    def run(args, **kwargs):
        requests.append(json.loads(kwargs["input"]))
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"data": {"createCommitOnBranch": {"commit": {"oid": HEAD}}}})
        )

    monkeypatch.setattr(locks.subprocess, "run", run)
    assert (
        locks.commit_files_to_branch(
            repository=EXPECTED_REPOSITORY,
            branch="dependabot/pip/hypothesis",
            expected_head=BASE,
            files={RUNTIME_LOCK: "rich==15.0.0\n", DEV_LOCK: "rich==15.0.0\n"},
            message="sync",
        )
        == HEAD
    )
    assert requests[0]["variables"]["input"]["expectedHeadOid"] == BASE
    assert requests[0]["variables"]["input"]["branch"]["branchName"] == "dependabot/pip/hypothesis"
    with pytest.raises(ValueError, match="target"):
        locks.commit_files_to_branch(
            repository=EXPECTED_REPOSITORY,
            branch="main",
            expected_head=BASE,
            files={},
            message="no",
        )


def test_permission_denial_is_nonzero_and_sanitized(monkeypatch, capsys, tmp_path):
    def denied(*_):
        raise subprocess.CalledProcessError(1, "gh", stderr="private secret response")

    monkeypatch.setattr(publication, "publish", denied)
    monkeypatch.setattr("sys.argv", ["publish", "--artifact", str(tmp_path), "--run", "1234"])
    assert publication.main() == 1
    output = capsys.readouterr().out
    assert "permission_or_provider" in output and "private secret" not in output


def test_spoofed_or_changed_pr_identity_is_rejected_before_write(monkeypatch):
    run = dict(
        path=WORKFLOW,
        conclusion="success",
        head_repository={"full_name": EXPECTED_REPOSITORY},
        event="pull_request",
        actor={"login": "dependabot[bot]"},
        pull_requests=[{"number": 9}],
        head_sha=HEAD,
        id=1234,
        run_attempt=1,
    )
    pr = dict(
        state="open",
        user={"login": "spoof"},
        head={"repo": {"full_name": EXPECTED_REPOSITORY}, "sha": HEAD},
        base={"ref": "main", "sha": BASE},
    )
    monkeypatch.setattr(publication, "api", lambda _: pr)
    with pytest.raises(ValueError, match="identity/base/head"):
        publication.assessed_origin(run, BASE)
    pr["user"]["login"] = "dependabot[bot]"
    pr["head"]["sha"] = BASE
    with pytest.raises(ValueError, match="identity/base/head"):
        publication.assessed_origin(run, BASE)


def test_health_ignores_noop_and_preserves_previous_success_on_failure():
    def run(number, event, created, conclusion="success"):
        return dict(
            id=number, event=event, created_at=created, conclusion=conclusion, head_branch="main"
        )

    runs = [
        run(3, "push", "2026-10-20T00:00:00Z"),
        run(2, "schedule", "2026-10-19T00:00:00Z", "failure"),
        run(1, "schedule", "2026-10-18T00:00:00Z"),
    ]
    jobs = {1: [dict(name=name, conclusion="success") for name in ("scan", "generate")]}
    result = lifecycle.maintenance_health(runs, jobs, NOW)
    assert result["outcome"] == "action_required"
    assert result["last_complete_scan"] == "2026-10-18T00:00:00Z"
    assert result["last_attempt"] == "2026-10-19T00:00:00Z"
    assert lifecycle.maintenance_health(runs[:1], {}, NOW)["stale"]


def test_registry_failure_is_partial_not_success(monkeypatch):
    monkeypatch.setattr(lifecycle, "metadata", lambda *_: (_ for _ in ()).throw(RuntimeError()))
    item = lifecycle.inspect_package("hypothesis", "6.170.1", False)
    assert item["coverage"] == "UNKNOWN" and item["state"] == "metadata_failed"


def test_registry_reports_prerelease_yanked_and_python_support(monkeypatch):
    def files(**kw):
        return [dict(yanked=False, requires_python=">=3.14", **kw)]

    data = dict(
        releases={
            "1.0": files(),
            "1.1rc1": files(),
            "2.0": [dict(yanked=True)],
            "1.2": [dict(yanked=False, requires_python=">=3.15")],
        },
        urls=[dict(yanked=True)],
        vulnerabilities=[{"id": "PYSEC-fixture"}],
        info={"requires_dist": ["child<2"]},
    )
    monkeypatch.setattr(lifecycle, "metadata", lambda *_: data)
    item = lifecycle.inspect_package("example", "1.0", True)
    assert item["latest_published_stable"] == "1.2"
    assert item["current_yanked"] is True and item["supports_python314"] is False
    assert item["advisory_ids"] == ["PYSEC-fixture"]


def test_constraints_include_only_active_markers_and_requested_extras():
    items = [
        dict(
            package="parent",
            parent_requirements=[
                'hypothesis<6; extra == "dev"',
                'child<2; python_version >= "3.14"',
                'oldchild<1; python_version < "3.10"',
                'linuxchild<2; os_name == "posix" and sys_platform == "linux"',
                'winchild<2; os_name == "nt" and platform_machine == "AMD64"',
                "crypto[backend]>=1",
            ],
        ),
        dict(package="crypto", parent_requirements=['backend<2; extra == "backend"']),
    ]
    edges = lifecycle.parent_edges(items, ["parent==1.0"])
    assert "hypothesis" not in edges and "oldchild" not in edges
    assert "child" in edges and "backend" in edges
    assert "linuxchild" in edges and "winchild" in edges


def test_independent_health_queries_meaningful_events_before_limiting_results(monkeypatch):
    reads = []
    run = dict(
        id=1,
        event="schedule",
        created_at=NOW.isoformat(),
        conclusion="success",
        head_branch="main",
        run_attempt=1,
    )

    def api(path):
        reads.append(path)
        if "dependency-automation.yml/runs" in path:
            assert "event=" in path and "branch=main" in path
            return {"workflow_runs": [run] if "event=schedule&" in path else []}
        if "attempts/1/jobs" in path:
            return {"jobs": [dict(name=n, conclusion="success") for n in ("generate", "scan")]}
        if "dependency-publish.yml/runs" in path:
            return {"workflow_runs": []}
        raise AssertionError(path)

    monkeypatch.setattr(publication, "api", api)
    monkeypatch.setattr(
        lifecycle,
        "maintenance_health",
        lambda runs, jobs, now: dict(outcome="healthy") if runs == [run] and 1 in jobs else {},
    )
    assert lifecycle.health()["outcome"] == "healthy"
    assert sum("dependency-automation.yml/runs" in path for path in reads) == 2


def test_preflight_invalidates_on_dirty_inputs_and_age(proposal):
    root, _, _ = proposal
    report = root / "artifacts/dependency-scan.json"
    report.parent.mkdir()
    report.write_text(
        json.dumps(
            dict(
                outcome="complete",
                last_complete_scan=NOW.isoformat(),
                input_hashes=input_hashes(root),
                packages=[],
            )
        )
    )
    assert dependency_preflight(root, (PYPROJECT,), NOW)["scan"] == "CURRENT"
    (root / RUNTIME_LOCK).write_text("rich==15.0.1\n")
    assert dependency_preflight(root, (PYPROJECT,), NOW)["scan"] == "STALE_OR_PARTIAL"
    assert dependency_preflight(root, ("README.md",), NOW)["status"] == "GO"


def test_scheduled_publication_recovers_and_reruns_without_duplicate_proposals(
    proposal, monkeypatch
):
    root, artifact, _ = proposal
    for path in (root, artifact):
        with (path / DEV_LOCK).open("a") as stream:
            stream.write("iniconfig==2.3.0\n")
    (artifact / DEV_LOCK).write_text(
        (artifact / DEV_LOCK).read_text().replace("iniconfig==2.3.0", "iniconfig==2.3.1")
    )
    identity = binding(
        repository=EXPECTED_REPOSITORY,
        actor="maintainer",
        base=BASE,
        head=BASE,
        run="1234",
        attempt="1",
    )
    seal(artifact, root, identity)
    state = dict(branches=[], prs=[], writes=0, dispatches=0, branch=None)
    run = dict(
        path=WORKFLOW,
        conclusion="success",
        head_repository={"full_name": EXPECTED_REPOSITORY},
        event="workflow_dispatch",
        head_branch="main",
        head_sha=BASE,
        actor={"login": "maintainer"},
        id=1234,
        run_attempt=1,
        html_url="https://example/run",
    )

    def api(path):
        if path == "actions/runs/1234":
            return run
        if path == "git/ref/heads/main":
            return {"object": {"sha": BASE}}
        if path.startswith("branches?"):
            return state["branches"]
        if path.startswith("pulls?"):
            return state["prs"]
        if path == "pulls/9":
            return state["prs"][0]
        if path.startswith("actions/workflows/ci.yml/runs"):
            return {
                "workflow_runs": []
                if not state["dispatches"]
                else [dict(head_sha=HEAD, head_branch=state["branch"], status="queued")]
            }
        if path.startswith("compare/"):
            return dict(behind_by=0, files=[{"filename": DEV_LOCK}])
        if path == f"commits/{HEAD}":
            return dict(
                committer={"login": "github-actions[bot]"},
                commit={"verification": {"verified": True}},
            )
        raise AssertionError(path)

    def command(*args, body=None):
        if args[:2] == ("workflow", "run"):
            state["dispatches"] += 1
        elif args[3].endswith("/git/refs"):
            state["branch"] = body["ref"].removeprefix("refs/heads/")
            state["branches"].append(dict(name=state["branch"], commit={"sha": BASE}))
        elif args[3].endswith("/pulls"):
            state["prs"].append(
                dict(
                    number=9,
                    state="open",
                    user={"login": "github-actions[bot]"},
                    base={"ref": "main"},
                    head={"sha": HEAD, "repo": {"full_name": EXPECTED_REPOSITORY}},
                    html_url="https://example/pr/9",
                )
            )
            return state["prs"][0]
        else:
            raise AssertionError(args)

    def write(**kwargs):
        assert kwargs["expected_head"] == BASE
        state["writes"] += 1
        state["branches"][0]["commit"]["sha"] = HEAD
        return HEAD

    monkeypatch.setattr(publication, "ROOT", root)
    monkeypatch.setattr(publication, "api", api)
    monkeypatch.setattr(publication, "command", command)
    monkeypatch.setattr(
        publication.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, BASE)
    )
    monkeypatch.setattr(locks, "commit_files_to_branch", write)
    monkeypatch.setattr(
        locks,
        "_git_text",
        lambda repo, ref, path: (artifact if ref == HEAD else root).joinpath(path).read_text(),
    )
    first = publication.publish(artifact, "1234")
    assert first["policy"] == "auto_merge" and first["head"] == HEAD
    assert publication.publish(artifact, "1234")["pull_request"] == first["pull_request"]
    assert state["writes"] == state["dispatches"] == len(state["prs"]) == 1
    assert len(state["branches"]) == 1


def test_sensitive_advisory_delta_remains_review_required():
    _, decision = locks.build_change_from_lock_diff(
        actor="dependabot[bot]",
        repository=EXPECTED_REPOSITORY,
        base_branch="main",
        head_branch="dependabot/pip/security",
        changed_files=(RUNTIME_LOCK, DEV_LOCK),
        base_runtime="httpx==0.28.0\n",
        head_runtime="httpx==0.28.1\n",
        base_dev="httpx==0.28.0\n",
        head_dev="httpx==0.28.1\n",
        production_declaration_changed=False,
        sdk_pin_changed=False,
        security_update=True,
    )
    assert decision.action == "human_review"


def test_generation_resolver_failure_never_writes_partial_artifact(proposal, monkeypatch, tmp_path):
    root, _, _ = proposal
    before = {name: (root / name).read_bytes() for name in FILES}
    monkeypatch.setattr(lifecycle, "ROOT", root)
    for key, value in dict(
        GITHUB_REPOSITORY=EXPECTED_REPOSITORY,
        DEPENDENCY_ACTOR="maintainer",
        GITHUB_RUN_ID="1234",
        GITHUB_RUN_ATTEMPT="1",
    ).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        lifecycle.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, BASE)
    )

    def failed(work, **_):
        (work / RUNTIME_LOCK).write_text("rich==15.1.0\n")
        raise RuntimeError("resolver conflict")

    monkeypatch.setattr(locks, "generate_pip_locks", failed)
    destination = tmp_path / "failed-proposal"
    with pytest.raises(RuntimeError, match="resolver conflict"):
        lifecycle.generate(destination, None)
    assert not list(destination.iterdir())
    assert before == {name: (root / name).read_bytes() for name in FILES}


def test_ci_completion_rechecks_run_identity_and_holds_runtime(proposal, monkeypatch):
    root, artifact, _ = proposal
    for path in (root, artifact):
        manifest = path / PYPROJECT
        manifest.write_text(manifest.read_text().replace('"rich==15.0.0"', '"rich>=15.0.0"'))
    for name in (RUNTIME_LOCK, DEV_LOCK):
        target = artifact / name
        target.write_text(target.read_text().replace("rich==15.0.0", "rich==15.0.1"))
    run = dict(
        path=".github/workflows/ci.yml",
        conclusion="success",
        head_repository={"full_name": EXPECTED_REPOSITORY},
        event="workflow_dispatch",
        head_branch="dependabot/pip/rich",
        head_sha=HEAD,
        check_suite_id=55,
    )
    pr = dict(
        number=9,
        user={"login": "dependabot[bot]"},
        base={"ref": "main", "sha": BASE},
        head={"sha": HEAD, "repo": {"full_name": EXPECTED_REPOSITORY}},
    )
    checks = [
        dict(
            name="CI Gate",
            conclusion="success",
            app={"slug": "github-actions"},
            check_suite={"id": 55},
        )
    ]

    def api(path):
        if path.startswith("actions/runs/"):
            return run
        if path.startswith("pulls?"):
            return [pr]
        if path == "pulls/9":
            return pr
        if path == "git/ref/heads/main":
            return {"object": {"sha": BASE}}
        if path.startswith("compare/"):
            return {"behind_by": 0}
        if path.startswith("commits/"):
            return {"check_runs": checks}
        raise AssertionError(path)

    monkeypatch.setattr(publication, "ROOT", root)
    monkeypatch.setattr(publication, "api", api)
    monkeypatch.setattr(
        publication.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, BASE)
    )
    monkeypatch.setattr(locks, "_pr_changed_files", lambda *_: (RUNTIME_LOCK, DEV_LOCK))
    monkeypatch.setattr(locks, "_git_text", lambda repo, ref, name: (artifact / name).read_text())
    monkeypatch.setattr(publication, "command", lambda *a, **kw: pytest.fail("unexpected merge"))
    assert publication.merge_after_ci("1234")["outcome"] == "human_review"
    checks[0]["check_suite"]["id"] = 54
    with pytest.raises(ValueError, match="exact run and head"):
        publication.merge_after_ci("1234")
    pr["head"]["sha"] = BASE
    with pytest.raises(ValueError, match="base/head changed"):
        publication.merge_after_ci("1234")


def test_health_notification_is_quiet_on_unchanged_state_and_recovers(monkeypatch):
    issue = dict(number=9, state="open", body="", html_url="https://example/issue/9")
    writes = []
    monkeypatch.setattr(publication, "api", lambda _: [issue] if issue["body"] else [])

    def command(*args, body=None):
        writes.append(body)
        issue.update(body)
        return issue

    monkeypatch.setattr(publication, "command", command)
    failure = dict(outcome="action_required", last_complete_scan=None, stale=True)
    lifecycle.notify_health(failure)
    assert len(writes) == 1
    lifecycle.notify_health(failure)
    assert len(writes) == 1
    lifecycle.notify_health(dict(outcome="healthy"))
    assert len(writes) == 2 and issue["state"] == "closed"


def test_conditional_lock_cannot_be_resealed_as_portable(proposal):
    root, artifact, identity = proposal
    (artifact / RUNTIME_LOCK).write_text('rich==15.0.0 ; python_version < "3"\n')
    seal(artifact, root, identity)
    with pytest.raises(ValueError, match="portable closure"):
        validate(artifact, root, identity)


def test_targeted_refresh_uses_canonical_resolver_and_plain_names():
    command = locks._pip_compile_command(
        extra="dev",
        output=Path(DEV_LOCK),
        upgrade=False,
        constraint=Path(RUNTIME_LOCK),
        upgrade_packages=("iniconfig", "identify"),
    )
    assert command[command.index("--constraint") + 1] == RUNTIME_LOCK
    assert "--upgrade" not in command
    assert command.count("--upgrade-package") == 2
    with pytest.raises(ValueError, match="plain package"):
        locks._pip_compile_command(
            extra=None,
            output=Path(RUNTIME_LOCK),
            upgrade=False,
            constraint=None,
            upgrade_packages=("--index-url=spoof",),
        )


def test_build_tooling_cannot_enter_low_risk_dev_slice():
    _, decision = locks.build_change_from_lock_diff(
        actor="dependabot[bot]",
        repository=EXPECTED_REPOSITORY,
        base_branch="main",
        head_branch="dependabot/pip/build",
        changed_files=(DEV_LOCK,),
        base_runtime="rich==15.0.0\n",
        head_runtime="rich==15.0.0\n",
        base_dev="rich==15.0.0\nsetuptools==84.0.0\n",
        head_dev="rich==15.0.0\nsetuptools==84.2.0\n",
        production_declaration_changed=False,
        sdk_pin_changed=False,
    )
    assert decision.action == "human_review"


def test_targeted_dev_refresh_cannot_introduce_dev_package_into_runtime(proposal, monkeypatch):
    root, _, _ = proposal
    with (root / DEV_LOCK).open("a") as stream:
        stream.write("pip-tools==7.6.2\n")
    calls = []

    def resolve(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr(locks, "_run", resolve)
    locks.generate_pip_locks(root, upgrade=False, upgrade_packages=("hypothesis",))
    assert "--upgrade-package" not in calls[0]
    assert calls[1][calls[1].index("--upgrade-package") + 1] == "hypothesis"
    assert "hypothesis" not in parse_lock_pins((root / RUNTIME_LOCK).read_text())


@pytest.mark.parametrize(
    "behind,filename,actor,verified",
    [
        (1, DEV_LOCK, "github-actions[bot]", True),
        (0, ".github/workflows/ci.yml", "github-actions[bot]", True),
        (0, DEV_LOCK, "spoof", True),
        (0, DEV_LOCK, "github-actions[bot]", False),
    ],
)
def test_existing_scheduled_branch_is_assessed_before_any_dispatch(
    monkeypatch,
    behind,
    filename,
    actor,
    verified,
):
    def api(path):
        if path.startswith("branches?"):
            return [dict(name="codex/scheduled-lock-refresh-spoof", commit={"sha": HEAD})]
        if path.startswith("pulls?"):
            return []
        if path.startswith("compare/"):
            return dict(behind_by=behind, files=[{"filename": filename}])
        if path.startswith("commits/"):
            return dict(committer={"login": actor}, commit={"verification": {"verified": verified}})
        raise AssertionError(path)

    monkeypatch.setattr(publication, "api", api)
    monkeypatch.setattr(publication, "command", lambda *a, **kw: pytest.fail("unexpected write"))
    with pytest.raises(ValueError, match="stale, untrusted or changes executable"):
        publication.scheduled_target(BASE, {DEV_LOCK: "example==1.0\n"})


def test_completed_scheduled_proposal_does_not_block_new_content_or_resurrect_itself(monkeypatch):
    branches = []
    old = dict(state="closed", html_url="https://example/disposed")

    def api(path):
        if path.startswith("branches?"):
            return branches
        if path.startswith("pulls?"):
            return [old]
        raise AssertionError(path)

    monkeypatch.setattr(publication, "api", api)
    first = publication.scheduled_target(BASE, {DEV_LOCK: "example==1.0\n"})
    branches.append(dict(name=first["branch"], commit={"sha": HEAD}))
    same = publication.scheduled_target(BASE, {DEV_LOCK: "example==1.0\n"})
    assert same["disposed"] == old
    newer = publication.scheduled_target(BASE, {DEV_LOCK: "example==1.1\n"})
    assert newer["disposed"] is None and newer["branch"] != first["branch"]


def test_human_pr_cannot_inherit_scheduled_actor_trust(monkeypatch):
    def api(path):
        if path.startswith("branches?"):
            return [dict(name="codex/scheduled-lock-refresh-spoof", commit={"sha": BASE})]
        if path.startswith("pulls?"):
            return [dict(state="open", user={"login": "spoof"})]
        raise AssertionError(path)

    monkeypatch.setattr(publication, "api", api)
    with pytest.raises(ValueError, match="identity changed"):
        publication.scheduled_target(BASE, {DEV_LOCK: "example==1.0\n"})


def test_human_event_actor_cannot_inherit_dependabot_pr_authority():
    run = dict(
        path=WORKFLOW,
        conclusion="success",
        head_repository={"full_name": EXPECTED_REPOSITORY},
        event="pull_request",
        actor={"login": "spoof"},
    )
    with pytest.raises(ValueError, match="event actor"):
        publication.assessed_origin(run, BASE)


@pytest.mark.parametrize(
    "author,verified,expected",
    [
        ("github-actions[bot]", True, True),
        ("spoof", True, False),
        ("github-actions[bot]", False, False),
    ],
)
def test_github_graphql_bot_signature_is_bound_to_author(monkeypatch, author, verified, expected):
    monkeypatch.setattr(
        publication,
        "api",
        lambda _: dict(
            committer={"login": "web-flow"},
            author={"login": author},
            commit={"verification": {"verified": verified}},
        ),
    )
    assert publication.trusted_bot_commit(HEAD) is expected


def test_publication_failure_cannot_be_crowded_out_by_ci_callbacks(monkeypatch):
    publications = [dict(id=n, run_attempt=1, conclusion="success") for n in range(15)] + [
        dict(id=99, run_attempt=1, conclusion="failure", html_url="https://example/failed")
    ]

    def api(path):
        if "dependency-automation.yml/runs" in path:
            return {"workflow_runs": []}
        if "dependency-publish.yml/runs" in path:
            return {"workflow_runs": publications}
        if "actions/runs/99/" in path:
            return {"jobs": [dict(name="publish", conclusion="failure")]}
        if "/jobs" in path:
            return {
                "jobs": [
                    dict(name="publish", conclusion="skipped"),
                    dict(name="merge", conclusion="success"),
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(publication, "api", api)
    monkeypatch.setattr(lifecycle, "maintenance_health", lambda *a: {"outcome": "healthy"})
    result = lifecycle.health()
    assert result["publication"] == "failed"
    assert result["outcome"] == "action_required"
