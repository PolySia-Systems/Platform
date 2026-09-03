from __future__ import annotations

from yaml import safe_load

from scripts.dependency_locks import (
    approved_sdk_versions,
    assert_sdk_pins_synchronized,
    check_pip_locks,
    classify_lock_sync_intent,
    declared_sdk_version,
    generate_pip_locks,
    repository_root,
)
from scripts.dependency_policy import (
    DEV_LOCK,
    RUNTIME_LOCK,
    DependencyChange,
    classify_dependency_change,
    development_changes_are_low_risk,
    is_low_risk_version_bump,
    parse_lock_pins,
    shared_pin_conflicts,
)


def test_sdk_approval_pins_match_pyproject() -> None:
    declared = declared_sdk_version()
    approved = approved_sdk_versions()
    assert declared == "0.7.1"
    assert assert_sdk_pins_synchronized() == declared
    assert set(approved.values()) == {declared}


def test_runtime_lock_excludes_development_tools_and_local_project() -> None:
    root = repository_root()
    runtime = parse_lock_pins((root / RUNTIME_LOCK).read_text(encoding="utf-8"))
    development = parse_lock_pins((root / DEV_LOCK).read_text(encoding="utf-8"))
    for name in ("pytest", "ruff", "mypy", "pip-tools", "pip-audit", "hypothesis", "polysia"):
        assert name not in runtime
    assert "polymarket-client" in runtime
    assert development["polymarket-client"] == runtime["polymarket-client"]
    assert not shared_pin_conflicts(runtime, development)
    assert development["pip-tools"] == "7.6.1"


def test_committed_locks_are_deterministic() -> None:
    check_pip_locks()
    root = repository_root()
    first = (root / RUNTIME_LOCK).read_text(encoding="utf-8")
    second = (root / DEV_LOCK).read_text(encoding="utf-8")
    generate_pip_locks(root, upgrade=False)
    assert (root / RUNTIME_LOCK).read_text(encoding="utf-8") == first
    assert (root / DEV_LOCK).read_text(encoding="utf-8") == second


def test_pyproject_only_dependency_pr_is_rejected() -> None:
    decision = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/pip/ruff-0.16.7",
            changed_files=("pyproject.toml",),
            package_ecosystem="pip",
            dependency_names=("ruff",),
            update_type="version-update:semver-patch",
            pyproject_changed=True,
            locks_complete=False,
            locks_valid=False,
        )
    )
    assert decision.action == "reject"


def test_complete_development_patch_can_automerge() -> None:
    decision = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/pip/ruff-0.16.7",
            changed_files=("pyproject.toml", DEV_LOCK),
            package_ecosystem="pip",
            dependency_names=("ruff",),
            update_type="version-update:semver-patch",
            pyproject_changed=True,
            development_lock_changed=True,
            locks_complete=True,
            locks_valid=True,
            development_only_low_risk=True,
        )
    )
    assert decision.action == "auto_merge"
    assert "risk:auto-merge" in decision.labels


def test_runtime_and_sdk_changes_require_human_review() -> None:
    runtime = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/pip/pydantic-2.14.0",
            changed_files=("pyproject.toml", RUNTIME_LOCK, DEV_LOCK),
            package_ecosystem="pip",
            dependency_names=("pydantic",),
            update_type="version-update:semver-minor",
            pyproject_changed=True,
            production_declaration_changed=True,
            runtime_lock_changed=True,
            development_lock_changed=True,
            locks_complete=True,
            locks_valid=True,
        )
    )
    sdk = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/pip/polymarket-client-0.8.0",
            changed_files=("pyproject.toml", RUNTIME_LOCK, DEV_LOCK),
            package_ecosystem="pip",
            dependency_names=("polymarket-client",),
            runtime_lock_changed=True,
            pyproject_changed=True,
            production_declaration_changed=True,
            sdk_pin_changed=True,
            locks_complete=True,
            locks_valid=True,
        )
    )
    zero_minor = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/pip/ruff-0.17.0",
            changed_files=("pyproject.toml", DEV_LOCK),
            package_ecosystem="pip",
            dependency_names=("ruff",),
            update_type="version-update:semver-minor",
            pyproject_changed=True,
            development_lock_changed=True,
            locks_complete=True,
            locks_valid=True,
            zero_version_minor=True,
        )
    )
    assert runtime.action == sdk.action == zero_minor.action == "human_review"


def test_actions_patch_automerge_and_minor_requires_review() -> None:
    patch = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/github_actions/actions/checkout-7.0.1",
            changed_files=(".github/workflows/ci.yml",),
            package_ecosystem="github_actions",
            dependency_names=("actions/checkout",),
            update_type="version-update:semver-patch",
            locks_complete=True,
            locks_valid=True,
        )
    )
    minor = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/github_actions/actions/checkout-8.0.0",
            changed_files=(".github/workflows/ci.yml",),
            package_ecosystem="github_actions",
            dependency_names=("actions/checkout",),
            update_type="version-update:semver-minor",
            locks_complete=True,
            locks_valid=True,
        )
    )
    assert patch.action == "auto_merge"
    assert minor.action == "human_review"


def test_unexpected_actor_or_workflow_change_is_rejected() -> None:
    actor = classify_dependency_change(
        DependencyChange(
            actor="not-dependabot",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="feature/deps",
            changed_files=(DEV_LOCK,),
            locks_complete=True,
            locks_valid=True,
        )
    )
    workflow = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/pip/ruff-0.16.7",
            changed_files=("pyproject.toml", ".github/workflows/ci.yml"),
            workflow_or_permission_changed=True,
            locks_complete=True,
            locks_valid=True,
        )
    )
    assert actor.action == workflow.action == "reject"


def test_ambiguous_development_update_without_version_evidence_stays_open() -> None:
    decision = classify_dependency_change(
        DependencyChange(
            actor="dependabot[bot]",
            repository="PolySia-Systems/Platform",
            base_branch="main",
            head_branch="dependabot/pip/ruff-0.16.7",
            changed_files=("pyproject.toml", DEV_LOCK),
            package_ecosystem="pip",
            dependency_names=("ruff",),
            pyproject_changed=True,
            development_lock_changed=True,
            locks_complete=True,
            locks_valid=True,
        )
    )
    assert decision.action == "human_review"


def test_lock_sync_intent_is_adaptive_and_fail_closed() -> None:
    assert (
        classify_lock_sync_intent(("pyproject.toml", DEV_LOCK, RUNTIME_LOCK)) == "noop"
    )
    assert classify_lock_sync_intent(("pyproject.toml",)) == "generate"
    assert classify_lock_sync_intent((".github/workflows/ci.yml",)) == "actions"
    assert (
        classify_lock_sync_intent(("pyproject.toml", ".github/workflows/ci.yml"))
        == "reject"
    )
    assert classify_lock_sync_intent(("Dockerfile",)) == "reject"
    assert classify_lock_sync_intent(("src/polysia/cli.py",)) == "reject"


def test_dependency_automation_workflow_registers_push_and_dispatch() -> None:
    path = repository_root() / ".github/workflows/dependency-automation.yml"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("name: Dependency automation\n")
    assert "\n  push:\n" in text
    assert "\n  pull_request:\n" in text
    assert "\n  workflow_dispatch: {}\n" in text
    assert "noop:" in text
    assert "github.event_name == 'push'" in text
    assert not any(line.startswith("- ") for line in text.splitlines()), (
        "unindented YAML sequence items break GitHub workflow parsing"
    )
    loaded = safe_load(text)
    assert loaded["name"] == "Dependency automation"


def test_version_policy_helpers() -> None:
    assert is_low_risk_version_bump("0.16.6", "0.16.7")
    assert not is_low_risk_version_bump("0.16.6", "0.17.0")
    assert is_low_risk_version_bump("2.3.1", "2.4.0")
    assert not is_low_risk_version_bump("2.3.1", "3.0.0")
    assert development_changes_are_low_risk({"ruff": ("0.16.6", "0.16.7")})
    assert not development_changes_are_low_risk({"ruff": ("0.16.6", "0.17.0")})
    assert parse_lock_pins("colorama==0.4.6 ; sys_platform == 'win32'\n") == {
        "colorama": "0.4.6"
    }
