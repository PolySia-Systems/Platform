from __future__ import annotations

from scripts.classify_ci_changes import ChangeMap, classify_event, classify_paths


def test_documentation_only_changes_are_lightweight() -> None:
    result = classify_paths(("README.md", "docs/05-security/supply-chain.md"))

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
    tooling = classify_paths(("scripts/check_changed_docs.py",))

    assert source.python and source.package
    assert not source.container and not source.windows
    assert tests.python and not tests.package
    assert tooling.python and not tooling.package


def test_packaging_dependency_container_and_windows_changes_are_explicit() -> None:
    package = classify_paths(("pyproject.toml",))
    runtime_lock = classify_paths(("locks/pip-runtime-py314.lock",))
    deployment = classify_paths(("compose.yaml",))
    powershell = classify_paths(("scripts/operator-check.ps1",))

    assert package.python and package.package and package.dependencies and package.windows
    assert runtime_lock == ChangeMap(
        quality=True,
        python=True,
        package=True,
        container=True,
        dependencies=True,
        windows=True,
        comprehensive=False,
    )
    assert deployment.container and not deployment.python
    assert powershell.windows and not powershell.python


def test_job_specific_ci_configuration_is_bounded() -> None:
    windows = classify_paths((".github/actions/windows/action.yml",))
    supply_chain = classify_paths((".github/actions/supply-chain/action.yml",))

    assert windows.quality and windows.windows and not windows.comprehensive
    assert not windows.python and not windows.dependencies and not windows.container
    assert supply_chain.quality and supply_chain.dependencies
    assert not supply_chain.comprehensive and not supply_chain.windows


def test_shared_or_unknown_configuration_fails_closed() -> None:
    workflow = classify_paths((".github/workflows/ci.yml",))
    classifier = classify_paths(("scripts/classify_ci_changes.py",))
    unknown = classify_paths(("new-system/config.custom",))

    assert workflow == ChangeMap.full()
    assert classifier == ChangeMap.full()
    assert unknown == ChangeMap.full()


def test_scheduled_and_manual_auto_events_run_periodic_gates() -> None:
    for event in ("schedule", "workflow_dispatch"):
        result = classify_event(event)
        assert result.dependencies and result.windows
        assert not result.quality and not result.container
        assert not result.comprehensive


def test_manual_full_and_unknown_events_fail_closed() -> None:
    assert classify_event("workflow_dispatch", validation_scope="full") == ChangeMap.full()
    assert classify_event("unexpected") == ChangeMap.full()


def test_empty_pull_request_diff_fails_closed() -> None:
    assert classify_event("pull_request") == ChangeMap.full()
