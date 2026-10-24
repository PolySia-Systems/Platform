from __future__ import annotations

import json
import subprocess

import pytest

from scripts import dependency_publication as publication
from scripts.dependency_policy import EXPECTED_REPOSITORY, is_trusted_dependency_actor


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fixture-job-token")
    monkeypatch.setenv("DEPENDENCY_PR_TOKEN", "fixture-app-token")
    monkeypatch.setenv("DEPENDENCY_APP_SLUG", "polysia-platform-dependencies")
    monkeypatch.setenv("DEPENDENCY_APP_INSTALLATION", "173681867")


@pytest.mark.parametrize("create", [False, True])
def test_app_token_is_environment_only_and_route_is_pr_or_scope_read(app_env, monkeypatch, create):
    proposal = dict(head="codex/scheduled-lock-refresh-fixture", base="main") if create else None

    def run(args, **kwargs):
        assert "fixture-app-token" not in str(args) + str(kwargs.get("input"))
        assert kwargs["env"]["GH_TOKEN"] == "fixture-app-token"
        assert kwargs["capture_output"] is True and kwargs["check"] is True
        if create:
            assert args[2:5] == ("--method", "POST", f"repos/{EXPECTED_REPOSITORY}/pulls")
            assert json.loads(kwargs["input"]) == proposal
        else:
            assert args[2:] == ("--method", "GET", "/installation/repositories?per_page=100")
        return subprocess.CompletedProcess(args, 0, '{"fixture": true}')

    monkeypatch.setattr(publication.subprocess, "run", run)
    assert publication.app_request(proposal=proposal) == {"fixture": True}


@pytest.mark.parametrize("name", ["DEPENDENCY_PR_TOKEN", "DEPENDENCY_APP_SLUG",
                                  "DEPENDENCY_APP_INSTALLATION"])
def test_missing_or_different_app_fails_before_request(app_env, monkeypatch, name):
    monkeypatch.setenv(name, "" if name == "DEPENDENCY_PR_TOKEN" else "different")
    monkeypatch.setattr(publication.subprocess, "run", lambda *_a, **_kw: pytest.fail("request"))
    with pytest.raises(ValueError, match="publication App installation"):
        publication.app_request()


@pytest.mark.parametrize("repos", [[EXPECTED_REPOSITORY], [], ["other/repo"],
                                   [EXPECTED_REPOSITORY, "other/repo"]])
def test_token_scope_is_exactly_platform(monkeypatch, repos):
    monkeypatch.setattr(publication, "app_request", lambda: dict(
        total_count=len(repos), repositories=[dict(full_name=r) for r in repos]))
    if repos == [EXPECTED_REPOSITORY]:
        publication.verify_app_scope()
    else:
        with pytest.raises(ValueError, match="Platform only"):
            publication.verify_app_scope()


def test_app_cannot_publish_other_branch_or_inherit_commit_trust(app_env, monkeypatch):
    with pytest.raises(ValueError, match="scheduled dependency PRs"):
        publication.app_request(proposal=dict(head="main", base="main"))
    actor = publication.PUBLICATION_APP_LOGIN
    assert not is_trusted_dependency_actor(actor, "dependabot/pip/example")
    monkeypatch.setattr(publication, "api", lambda _: dict(
        committer={"login": actor}, author={"login": actor},
        commit={"verification": {"verified": True}}))
    assert not publication.trusted_bot_commit("a" * 40)
