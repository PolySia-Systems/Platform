from __future__ import annotations

from dataclasses import replace

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
    assert classify_event("schedule") == replace(ChangeMap.full(), windows=False)
    manual = classify_event("workflow_dispatch")
    assert manual.dependencies and not manual.windows
    assert not manual.quality and not manual.container


def test_manual_full_and_unknown_events_fail_closed() -> None:
    assert classify_event("workflow_dispatch", validation_scope="full") == replace(
        ChangeMap.full(), windows=False,
    )
    assert classify_event("unexpected") == replace(ChangeMap.full(), windows=False)


def test_empty_pull_request_diff_fails_closed() -> None:
    assert classify_event("pull_request") == replace(ChangeMap.full(), windows=False)


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


@pytest.mark.parametrize("path", [
    "src/polysia/monitoring/nonlive_campaign.py",
    "src/polysia/monitoring/technical_health.py",
])
def test_worker_safety_controllers_select_installed_and_windows_checks(path: str) -> None:
    result = classify_paths((path,))
    assert result.python and result.package and result.browser
    assert result.container and result.windows


def test_console_presentation_keeps_its_bounded_ci_scope() -> None:
    result = classify_paths(("src/polysia/monitoring/dashboard.py",))
    assert result.python and result.package and result.browser
    assert not result.container and not result.windows


def test_browser_document_asset_is_executable_not_editorial() -> None:
    result = classify_paths(("docs/console/index.html",))
    assert result.python and result.browser


@pytest.mark.parametrize(
    "path",
    [
        "frontend/src/App.tsx",
        "frontend/package-lock.json",
        "frontend/.node-version",
        "frontend/vite.config.mjs",
        "frontend/src/contract.generated.ts",
        "hatch_build.py",
        "frontend/tests/producer.json",
    ],
)
def test_frontend_cannot_skip_native_package_browser_container_and_supply_chain(path):
    assert classify_paths((path,)) == ChangeMap.full()


@pytest.mark.parametrize("path", [
    "src/polysia/control/local_identity.py",
    "src/polysia/monitoring/process_capacity.py",
    "src/polysia/application/services/dynamic_live_handoff.py",
    "src/polysia/application/services/persistent_prospective_collector.py",
    "src/polysia/cli_commands/wallet_intelligence_workflow.py",
    "src/polysia/monitoring/wallet_intelligence_health.py",
    "tests/unit/application/test_dynamic_live_handoff.py",
    "tests/unit/application/test_persistent_prospective_collector.py",
    "src/polysia/adapters/polymarket/bounded_transport.py",
    "src/polysia/adapters/polymarket/native_discovery.py",
    "src/polysia/adapters/polymarket/research_rpc.py",
    "src/polysia/cli_commands/platform_worker.py",
    "src/polysia/cli_support/wallet_intelligence_workflow.py",
    "tests/integration/test_operational_session.py",
    "tests/integration/test_native_drain_transport.py",
    "tests/unit/adapters/test_native_discovery.py",
    "tests/unit/monitoring/test_technical_health.py",
    "scripts/op1_backup_transport.py",
])
def test_native_behavior_and_its_regression_cases_select_windows(path: str) -> None:
    assert classify_paths((path,)).windows


def test_complete_presentation_diff_keeps_package_browser_without_install_recovery() -> None:
    paths = (
        "frontend/src/design/tokens.css",
        "src/polysia/monitoring/human_console_assets/main-old.js",
        "src/polysia/monitoring/human_console_assets/main-new.js",
        "src/polysia/monitoring/human_console_assets/manifest.json",
        "docs/04-architecture/product-design-system.md",
    )
    result = classify_paths(paths)
    assert result.python and result.package and result.browser
    assert not result.windows and not result.container and not result.dependencies
    # A mixed logic/recipe/native diff cannot borrow this exception.
    for extra in (
        "frontend/src/App.tsx", "frontend/build.mjs", "AGENTS.md",
        "frontend/src/assets/helper.tsx", "frontend/src/assets/AGENTS.md",
    ):
        assert classify_paths((*paths, extra)) == ChangeMap.full()
    assert classify_paths(paths[1:4]).windows  # output-only is not presentation proof


def test_presentation_rename_into_unknown_file_fails_closed() -> None:
    assert classify_paths(("frontend/src/theme.css", "new-system/theme.css")).comprehensive


def test_real_rename_and_deleted_control_keep_both_sides_of_complete_diff(tmp_path) -> None:
    import subprocess

    from scripts.classify_ci_changes import actual_diff

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "frontend/src/theme.css").write_text("body { color: black }")
    (tmp_path / "frontend/build.mjs").write_text("// trusted recipe")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "fixture")
    base = git("rev-parse", "HEAD")
    git("mv", "frontend/src/theme.css", "frontend/src/theme.ts")
    policy = actual_diff(tmp_path, base=base, local=True)
    assert set(policy["paths"]) == {"frontend/src/theme.css", "frontend/src/theme.ts"}
    assert policy["flags"]["comprehensive"]
    git("reset", "--hard", "HEAD")
    (tmp_path / "frontend/src/theme.css").write_text("body { color: white }")
    (tmp_path / "frontend/build.mjs").unlink()
    policy = actual_diff(tmp_path, base=base, local=True)
    assert policy["flags"]["comprehensive"]
