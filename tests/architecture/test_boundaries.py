from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "polysia"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_domain_and_application_do_not_import_adapters_or_sdk() -> None:
    forbidden_prefixes = ("polymarket", "polysia.adapters")
    findings: dict[str, list[str]] = {}

    for boundary in (PACKAGE / "domain", PACKAGE / "application"):
        for path in boundary.rglob("*.py"):
            forbidden = sorted(
                name for name in _imports(path) if name.startswith(forbidden_prefixes)
            )
            if forbidden:
                findings[path.relative_to(ROOT).as_posix()] = forbidden

    assert findings == {}


def test_strategy_and_storage_layers_do_not_import_venue_adapters() -> None:
    findings: dict[str, list[str]] = {}

    for layer in (PACKAGE / "strategies", PACKAGE / "storage"):
        for path in layer.rglob("*.py"):
            forbidden = sorted(
                name for name in _imports(path) if name.startswith("polysia.adapters")
            )
            if forbidden:
                findings[path.relative_to(ROOT).as_posix()] = forbidden

    assert findings == {}


def test_official_sdk_imports_are_confined_to_polymarket_adapter() -> None:
    adapter_root = PACKAGE / "adapters" / "polymarket"
    findings: dict[str, list[str]] = {}

    for path in PACKAGE.rglob("*.py"):
        if path.is_relative_to(adapter_root):
            continue
        forbidden = sorted(name for name in _imports(path) if name.startswith("polymarket"))
        if forbidden:
            findings[path.relative_to(ROOT).as_posix()] = forbidden

    assert findings == {}


def test_developer_tooling_has_no_trading_authority_dependency() -> None:
    forbidden_prefixes = (
        "polysia.execution",
        "polysia.risk",
        "polysia.strategies",
        "polysia.wallet",
        "polysia.adapters",
        "polymarket",
    )
    findings: dict[str, list[str]] = {}
    for path in (PACKAGE / "developer").rglob("*.py"):
        forbidden = sorted(
            name for name in _imports(path) if name.startswith(forbidden_prefixes)
        )
        if forbidden:
            findings[path.relative_to(ROOT).as_posix()] = forbidden
    assert findings == {}


def test_control_kernel_is_venue_neutral() -> None:
    control_root = PACKAGE / "control"
    forbidden_prefixes = ("polymarket", "polysia.adapters")
    findings: dict[str, list[str]] = {}

    for path in control_root.rglob("*.py"):
        forbidden = sorted(
            name for name in _imports(path) if name.startswith(forbidden_prefixes)
        )
        if forbidden:
            findings[path.relative_to(ROOT).as_posix()] = forbidden

    assert findings == {}


def test_control_core_does_not_depend_on_sqlite_adapter() -> None:
    core_files = (
        PACKAGE / "control" / "models.py",
        PACKAGE / "control" / "service.py",
        PACKAGE / "control" / "shadow_runtime.py",
    )
    findings = {
        path.relative_to(ROOT).as_posix(): sorted(
            name for name in _imports(path) if name.startswith("polysia.storage")
        )
        for path in core_files
    }

    assert {path: imports for path, imports in findings.items() if imports} == {}


def test_dynamic_shadow_core_has_no_trading_authority_dependency() -> None:
    core_files = (
        PACKAGE / "domain" / "copytrading" / "dynamic_shadow.py",
        PACKAGE / "application" / "ports" / "dynamic_shadow.py",
        PACKAGE / "application" / "services" / "dynamic_shadow.py",
        PACKAGE / "application" / "services" / "dynamic_live_handoff.py",
        PACKAGE / "domain" / "copytrading" / "continuous_shadow.py",
        PACKAGE / "domain" / "copytrading" / "continuous_shadow_experiments.py",
        PACKAGE / "application" / "ports" / "continuous_shadow.py",
        PACKAGE / "application" / "services" / "continuous_shadow.py",
        PACKAGE / "application" / "services" / "continuous_shadow_failures.py",
        PACKAGE / "domain" / "copytrading" / "target_exposure.py",
        PACKAGE / "domain" / "research_evidence" / "models.py",
        PACKAGE / "domain" / "research_evidence" / "collector.py",
        PACKAGE / "domain" / "research_evidence" / "replay.py",
        PACKAGE / "application" / "ports" / "research_evidence.py",
        PACKAGE / "application" / "services" / "prospective_collector.py",
        PACKAGE / "application" / "services" / "persistent_prospective_collector.py",
        PACKAGE / "application" / "services" / "source_benchmark.py",
        PACKAGE / "backtesting" / "shadow_stateful_replay.py",
        PACKAGE / "backtesting" / "shadow_historical_baseline.py",
        PACKAGE / "backtesting" / "prospective_replay.py",
        PACKAGE / "storage" / "immutable_sqlite.py",
    )
    forbidden_prefixes = (
        "polysia.execution",
        "polysia.risk",
        "polysia.strategies",
        "polysia.wallet",
    )
    findings = {
        path.relative_to(ROOT).as_posix(): sorted(
            name for name in _imports(path) if name.startswith(forbidden_prefixes)
        )
        for path in core_files
    }

    assert {path: imports for path, imports in findings.items() if imports} == {}


def test_continuous_shadow_service_does_not_import_monitoring() -> None:
    imports = _imports(PACKAGE / "application" / "services" / "continuous_shadow.py")
    forbidden = sorted(name for name in imports if name.startswith("polysia.monitoring"))
    assert forbidden == []


def test_target_exposure_replay_has_no_live_or_sqlite_authority() -> None:
    files = (
        PACKAGE / "domain" / "copytrading" / "target_exposure.py",
        PACKAGE / "domain" / "research_evidence" / "replay.py",
        PACKAGE / "backtesting" / "shadow_stateful_replay.py",
    )
    forbidden_prefixes = (
        "sqlite3",
        "polysia.storage",
        "polysia.execution",
        "polysia.risk",
        "polysia.adapters",
    )
    findings = {
        path.relative_to(ROOT).as_posix(): sorted(
            name for name in _imports(path) if name.startswith(forbidden_prefixes)
        )
        for path in files
    }
    assert {path: imports for path, imports in findings.items() if imports} == {}
