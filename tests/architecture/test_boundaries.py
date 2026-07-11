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
