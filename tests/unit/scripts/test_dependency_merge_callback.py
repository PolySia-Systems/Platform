from __future__ import annotations

import copy
import json
import os
import subprocess

import pytest

from scripts import dependency_locks as locks
from scripts import dependency_publication as publication
from scripts.dependency_policy import DEV_LOCK, EXPECTED_REPOSITORY, PYPROJECT, RUNTIME_LOCK

BASE, HEAD, MERGE, OTHER = (letter * 40 for letter in "abcd")
BRANCH = "codex/scheduled-lock-refresh-fixture"
REAL_RUN = subprocess.run


@pytest.fixture
def callback(tmp_path, monkeypatch):
    manifest = '''[build-system]
requires = ["hatchling==1.32.4"]
build-backend = "hatchling.build"
[project]
name = "polysia"
dependencies = ["rich==15.0.0"]
[project.optional-dependencies]
dev = ["example>=1,<2", "hatchling==1.32.4"]
'''
    files = {PYPROJECT: manifest, RUNTIME_LOCK: "rich==15.0.0\n",
             DEV_LOCK: "rich==15.0.0\nexample==1.0.0\nhatchling==1.32.4\n"}
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    run = dict(id=1234, path=".github/workflows/ci.yml", status="completed", conclusion="success",
               head_repository={"full_name": EXPECTED_REPOSITORY}, event="workflow_dispatch",
               head_branch=BRANCH, head_sha=HEAD, check_suite_id=55)
    pr = dict(number=9, state="open", merged=False, merge_commit_sha=None,
              user={"login": "github-actions[bot]"}, base={"ref": "main", "sha": BASE},
              head={"ref": BRANCH, "sha": HEAD, "repo": {"full_name": EXPECTED_REPOSITORY}},
              html_url="https://example.invalid/pr/9")
    gate = dict(name="CI Gate", conclusion="success", app={"slug": "github-actions"},
                check_suite={"id": 55})
    state = dict(run=run, pr=pr, gate=gate, main=BASE, checkout=BASE, ref=HEAD, merges=0,
                 deletes=0, merge_mode="ok", cleanup_mode="ok", pr_reads=0, main_reads=0,
                 changed_before_merge=False, base_race=False, open_reuse=False, integrated=True)
    state["verified"] = True

    def missing():
        raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 404")

    def api(path):
        if path == "actions/runs/1234":
            return copy.deepcopy(run)
        if path.startswith("pulls?state=all"):
            return [copy.deepcopy(pr)]
        if path.startswith("pulls?state=open"):
            return [dict(number=10)] if state["open_reuse"] else []
        if path == "pulls/9":
            state["pr_reads"] += 1
            if state["changed_before_merge"] and state["pr_reads"] == 2:
                pr["head"]["sha"] = OTHER
            if state["merge_mode"] == "unknown_read" and state["merges"]:
                raise subprocess.CalledProcessError(1, "gh", stderr="private timeout")
            return copy.deepcopy(pr)
        if path == "git/ref/heads/main":
            state["main_reads"] += 1
            if state["base_race"] and state["main_reads"] > 1:
                state["main"] = OTHER
            return {"object": {"sha": state["main"]}}
        if path == f"git/ref/heads/{BRANCH}":
            return {"object": {"sha": state["ref"]}} if state["ref"] else missing()
        if path.startswith("compare/"):
            return dict(behind_by=0 if state["integrated"] else 1, status="ahead")
        if path == f"commits/{HEAD}/check-runs?per_page=100":
            return {"check_runs": [copy.deepcopy(gate)]}
        if path == f"commits/{HEAD}":
            return dict(committer={"login": "github-actions[bot]"},
                        commit={"verification": {"verified": state["verified"]}})
        raise AssertionError(path)

    def command(*args, body=None):
        assert args == ("pr", "merge", "9", "--repo", EXPECTED_REPOSITORY,
                        "--merge", "--match-head-commit", HEAD)
        state["merges"] += 1
        if state["merge_mode"] != "not_merged":
            pr.update(state="closed", merged=True, merge_commit_sha=MERGE)
            state["main"] = MERGE
        if state["merge_mode"] == "wrong_merged_head":
            pr["head"]["sha"] = OTHER
        if state["merge_mode"] == "unconfirmed_integration":
            state["integrated"] = False
        if state["merge_mode"] in {"timeout_after", "not_merged"}:
            raise subprocess.TimeoutExpired("gh", 60)

    def git(args, **kwargs):
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, state["checkout"])
        assert "push" in args
        assert f"--force-with-lease=refs/heads/{BRANCH}:{HEAD}" in args
        assert args[-1] == f":refs/heads/{BRANCH}"
        assert "--force" not in args
        state["deletes"] += 1
        if state["cleanup_mode"] == "interrupted":
            raise subprocess.CalledProcessError(1, args, stderr="private token detail")
        if state["cleanup_mode"] == "reused":
            state["ref"] = OTHER
            raise subprocess.CalledProcessError(1, args, stderr="stale lease")
        state["ref"] = None
        if state["cleanup_mode"] == "lost_response":
            raise subprocess.TimeoutExpired(args, 60)
        return subprocess.CompletedProcess(args, 0, "deleted")

    monkeypatch.setattr(publication, "ROOT", tmp_path)
    monkeypatch.setattr(publication, "api", api)
    monkeypatch.setattr(publication, "command", command)
    monkeypatch.setattr(publication.subprocess, "run", git)
    monkeypatch.setattr(locks, "_pr_changed_files", lambda *_: (DEV_LOCK,))
    monkeypatch.setattr(locks, "_git_text", lambda _repo, sha, name:
                        files[name].replace("example==1.0.0", "example==1.0.1")
                        if sha == HEAD else files[name])
    return state


def test_real_callback_merges_exact_head_confirms_integration_and_guarded_cleanup(callback):
    result = publication.merge_after_ci("1234")
    assert result["outcome"] == "merged" and result["merged"] is True
    assert result["head"] == HEAD and result["cleanup"] == "deleted"
    assert callback["merges"] == callback["deletes"] == 1


@pytest.mark.parametrize(("field", "value"), [
    ("path", ".github/workflows/other.yml"), ("conclusion", "failure"),
    ("status", "in_progress"), ("id", 999), ("event", "push"),
    ("head_repository", {"full_name": "untrusted/fork"}), ("head_sha", OTHER),
])
def test_wrong_source_or_ci_never_merges_or_deletes(callback, field, value):
    callback["run"][field] = value
    with pytest.raises(ValueError):
        publication.merge_after_ci("1234")
    assert callback["merges"] == callback["deletes"] == 0


@pytest.mark.parametrize("change", ["suite", "gate", "checkout", "base", "head_race", "base_race"])
def test_stale_or_changed_evidence_stops_before_merge(callback, change):
    if change == "suite":
        callback["gate"]["check_suite"]["id"] = 999
    elif change == "gate":
        callback["gate"]["conclusion"] = "failure"
    elif change == "checkout":
        callback["checkout"] = OTHER
    elif change == "base":
        callback["pr"]["base"]["sha"] = OTHER
    else:
        callback["changed_before_merge" if change == "head_race" else "base_race"] = True
    with pytest.raises(ValueError):
        publication.merge_after_ci("1234")
    assert callback["merges"] == callback["deletes"] == 0


def test_duplicate_callback_does_not_merge_or_delete_again(callback):
    assert publication.merge_after_ci("1234")["cleanup"] == "deleted"
    callback["checkout"] = MERGE
    result = publication.merge_after_ci("1234")
    assert result["outcome"] == "already_merged" and result["cleanup"] == "already_absent"
    assert callback["merges"] == callback["deletes"] == 1


def test_unverified_bot_head_requires_review(callback):
    callback["verified"] = False
    assert publication.merge_after_ci("1234")["outcome"] == "human_review"
    assert callback["merges"] == callback["deletes"] == 0


@pytest.mark.parametrize("mode", ["wrong_merged_head", "unconfirmed_integration"])
def test_merged_flag_alone_cannot_confirm_expected_source(callback, mode):
    callback["merge_mode"] = mode
    result = publication.merge_after_ci("1234")
    assert result["outcome"] == "merge_unknown"
    assert result["cleanup"] == "not_attempted" and callback["deletes"] == 0


def test_interrupted_cleanup_is_nonzero_and_retry_does_not_repeat_merge(
    callback, monkeypatch, capsys, tmp_path,
):
    callback["cleanup_mode"] = "interrupted"
    output = tmp_path / "step-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr("sys.argv", ["publication", "--run", "1234", "--merge-after-ci"])
    assert publication.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["merged"] is True and result["cleanup"] == "pending"
    assert "private" not in json.dumps(result)
    assert output.read_text() == "integration_complete=false\n"
    callback.update(checkout=MERGE, cleanup_mode="ok")
    assert publication.main() == 0
    assert json.loads(capsys.readouterr().out)["cleanup"] == "deleted"
    assert output.read_text().splitlines()[-1] == "integration_complete=true"
    assert callback["merges"] == 1 and callback["deletes"] == 2


@pytest.mark.parametrize("mode", ["timeout_after", "unknown_read", "not_merged"])
def test_uncertain_merge_never_infers_cleanup_from_cli_exit(callback, mode):
    callback["merge_mode"] = mode
    result = publication.merge_after_ci("1234")
    if mode == "timeout_after":
        assert result["merged"] is True and result["cleanup"] == "deleted"
    else:
        assert result["outcome"] in {"merge_unknown", "merge_not_confirmed"}
        assert result["cleanup"] == "not_attempted" and callback["deletes"] == 0
        if mode == "unknown_read":
            callback.update(merge_mode="ok", checkout=MERGE)
            assert publication.merge_after_ci("1234")["cleanup"] == "deleted"
            assert callback["merges"] == 1


def test_lost_cleanup_response_is_checked_against_actual_ref(callback):
    callback["cleanup_mode"] = "lost_response"
    assert publication.merge_after_ci("1234")["cleanup"] == "deleted"


def test_reused_ref_is_preserved_by_expected_head_guard(callback):
    callback["cleanup_mode"] = "reused"
    result = publication.merge_after_ci("1234")
    assert result["merged"] is True and result["cleanup"] == "preserved_changed_ref"
    assert callback["ref"] == OTHER


def test_open_reused_proposal_and_unrelated_branch_are_never_deleted(callback):
    callback["open_reuse"] = True
    result = publication.merge_after_ci("1234")
    assert result["cleanup"] == "preserved_open_proposal" and callback["deletes"] == 0
    callback["pr"]["head"]["ref"] = "feature/unrelated"
    with pytest.raises(ValueError):
        publication.cleanup_merged_branch(callback["pr"], HEAD)
    assert callback["deletes"] == 0


def test_closed_unmerged_proposal_is_preserved(callback):
    callback["pr"]["state"] = "closed"
    assert publication.merge_after_ci("1234")["outcome"] == "closed_unmerged"
    assert callback["merges"] == callback["deletes"] == 0


@pytest.mark.parametrize("raced", [False, True])
def test_guarded_delete_against_real_local_git_server(tmp_path, monkeypatch, raced):
    """Local Git transport only: no GitHub write or network credential use."""
    server, client = tmp_path / "server.git", tmp_path / "client"
    client.mkdir()

    def git(*args, **kwargs):
        return REAL_RUN(("git", *args), check=True, capture_output=True, text=True, **kwargs)

    git("-c", "init.templateDir=", "init", "--bare", str(server))
    git("-c", "init.templateDir=", "init", str(client))
    tree = git("--git-dir", str(server), "mktree", input="").stdout.strip()
    env = dict(os.environ, GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
               GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
    first = git("--git-dir", str(server), "commit-tree", tree,
                "-m", "first", env=env).stdout.strip()
    second = git("--git-dir", str(server), "commit-tree", tree, "-p", first,
                 "-m", "second", env=env).stdout.strip()
    ref = f"refs/heads/{BRANCH}"
    git("--git-dir", str(server), "update-ref", ref, second if raced else first)
    reads = 0

    def api(path):
        nonlocal reads
        if path == "git/ref/heads/main":
            return {"object": {"sha": second}}
        if path.startswith("compare/"):
            return dict(status="ahead", behind_by=0)
        if path.startswith("pulls?"):
            return []
        assert path == f"git/ref/heads/{BRANCH}"
        reads += 1
        if reads == 1:
            return {"object": {"sha": first}}  # Ref may race after this observation.
        observed = REAL_RUN(("git", "--git-dir", str(server), "rev-parse", "--verify", ref),
                            capture_output=True, text=True)
        if observed.returncode:
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 404")
        return {"object": {"sha": observed.stdout.strip()}}

    def push(args, **kwargs):
        assert f"--force-with-lease={ref}:{first}" in args
        local = [str(server) if arg == f"https://github.com/{EXPECTED_REPOSITORY}.git"
                 else arg for arg in args]
        return REAL_RUN(local, **kwargs)

    monkeypatch.setattr(publication, "api", api)
    monkeypatch.setattr(publication, "ROOT", client)
    monkeypatch.setattr(publication.subprocess, "run", push)
    pr = dict(state="closed", merged=True, merge_commit_sha=second,
              user={"login": "github-actions[bot]"}, base={"ref": "main"},
              head={"ref": BRANCH, "sha": first, "repo": {"full_name": EXPECTED_REPOSITORY}})
    result = publication.cleanup_merged_branch(pr, first)
    assert result["cleanup"] == ("preserved_changed_ref" if raced else "deleted")
    if raced:
        assert git("--git-dir", str(server), "rev-parse", ref).stdout.strip() == second
