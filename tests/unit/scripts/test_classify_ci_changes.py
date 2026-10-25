from __future__ import annotations

import pytest

from scripts.classify_ci_changes import ChangeMap, classify_event, classify_paths


def test_documentation_only_changes_are_lightweight() -> None:
    result = classify_paths(("README.md", "docs/README.md"))

    assert result == ChangeMap(
        quality=True,
        python=False,
        package=False,
        container=False,
        dependencies=False,
        windows=False,
        comprehensive=False,
    )


def test_source_tests_and_tooling_receive_distinct_risk_maps() -> None:
    source = classify_paths(("src/polysia/domain/orders/models.py",))
    tests = classify_paths(("tests/unit/domain/test_orders.py",))
    tooling = classify_paths(("scripts/report_fixture.py",))

    assert source.python and source.package
    assert not source.container and not source.windows
    assert tests.python and not tests.package
    assert tooling.python and not tooling.package


@pytest.mark.parametrize("directory", [
    "docs/03-requirements", "docs/04-architecture/adrs", "docs/10-operations",
    "docs/00-governance", "docs/05-security",
])
def test_document_role_does_not_depend_on_parent_directory(directory: str) -> None:
    prose = f"{directory}/guide.md"
    assert classify_paths((prose,)) == ChangeMap(
        quality=True, python=False, package=False, container=False,
        dependencies=False, windows=False, comprehensive=False,
    )
    for asset in ("contract.json", "contract.yaml", "upgrade.sql", "fixture.html", "run.py"):
        assert classify_paths((f"{directory}/{asset}",)) == ChangeMap.full()
    for control in ("AGENTS.md", "AGENTS.override.md"):
        assert classify_paths((f"{directory}/{control}",)) == ChangeMap.full()
        assert classify_paths((f"{directory}/{control.lower()}",)) == ChangeMap.full()


@pytest.mark.parametrize("risky", [
    "locks/requirements-dev-py314.txt", "src/polysia/storage/console_commands.py",
    "deploy/platform_bootstrap.py", ".github/workflows/ci.yml",
])
def test_prose_never_cancels_risky_requirements(risky: str) -> None:
    assert classify_paths(("docs/00-governance/PROJECT_STATUS.md", risky)) == classify_paths(
        (risky,),
    )


def test_packaging_dependency_container_and_windows_changes_are_explicit() -> None:
    package = classify_paths(("pyproject.toml",))
    runtime_lock = classify_paths(("locks/requirements-runtime-py314.txt",))
    development_lock = classify_paths(("locks/requirements-dev-py314.txt",))
    deployment = classify_paths(("compose.yaml",))
    powershell = classify_paths(("scripts/operator-check.ps1",))

    assert package.python and package.package and package.dependencies and package.windows
    assert package.container
    assert runtime_lock == ChangeMap(
        quality=True,
        python=True,
        package=True,
        container=True,
        dependencies=True,
        windows=True,
        comprehensive=False,
        browser=True,
    )
    assert development_lock.dependencies and development_lock.windows
    assert development_lock.python and development_lock.package
    assert development_lock.container  # Docker builder installs the development lock.
    assert deployment.container and deployment.python and deployment.browser
    assert powershell.windows and not powershell.python


def test_job_specific_ci_configuration_is_bounded() -> None:
    windows = classify_paths((".github/actions/windows/action.yml",))
    supply_chain = classify_paths((".github/actions/supply-chain/action.yml",))

    assert windows == ChangeMap.full()
    assert supply_chain == ChangeMap.full()


def test_shared_or_unknown_configuration_fails_closed() -> None:
    workflow = classify_paths((".github/workflows/ci.yml",))
    classifier = classify_paths(("scripts/classify_ci_changes.py",))
    unknown = classify_paths(("new-system/config.custom",))

    assert workflow == ChangeMap.full()
    assert classifier == ChangeMap.full()
    assert unknown == ChangeMap.full()


def test_scheduled_and_manual_auto_events_run_periodic_gates() -> None:
    assert classify_event("schedule") == ChangeMap.full()
    manual = classify_event("workflow_dispatch")
    assert manual.dependencies and manual.windows
    assert not manual.quality and not manual.container


def test_manual_full_and_unknown_events_fail_closed() -> None:
    assert classify_event("workflow_dispatch", validation_scope="full") == ChangeMap.full()
    assert classify_event("unexpected") == ChangeMap.full()


def test_empty_pull_request_diff_fails_closed() -> None:
    assert classify_event("pull_request") == ChangeMap.full()


@pytest.mark.parametrize("path", [
    "docs/03-requirements/shadow-contract.json",
    "docs/examples/acquisition.yaml",
    "docs/migrations/upgrade.sql",
    "plans/runtime.py",
    "prompts/runner.sh",
])
def test_executable_or_unclassified_document_assets_fail_closed(path: str) -> None:
    assert classify_paths((path,)) == ChangeMap.full()


def test_deployment_selects_behavioral_contract_checks() -> None:
    result = classify_paths(("deploy/migrations/upgrade.sql",))
    assert result.python and result.container


@pytest.mark.parametrize("path", [
    "src/polysia/cli_commands/platform_worker.py",
    "src/polysia/cli_support/native_lifecycle.py",
    "pyproject.toml",
])
def test_installed_runtime_entry_points_select_container_contract(path: str) -> None:
    assert classify_paths((path,)).container


def test_browser_document_asset_is_executable_not_editorial() -> None:
    result = classify_paths(("docs/console/index.html",))
    assert result.python and result.browser
