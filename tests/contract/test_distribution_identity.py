from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import polysia

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_package_metadata() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "polysia"
    assert metadata["project"]["scripts"] == {"polysia": "polysia.cli:app"}
    assert metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/polysia"
    ]
    assert polysia.__version__ == metadata["project"]["version"]


def test_legacy_import_namespace_is_absent() -> None:
    legacy_namespace = "pm" + "_trader"

    assert importlib.util.find_spec(legacy_namespace) is None


def test_active_implementation_has_no_legacy_identity() -> None:
    legacy_tokens = ("pm" + "_trader", "pm" + "-trader", "polymarket-" + "trading-system")
    files = [
        *sorted((ROOT / "src").rglob("*.py")),
        *sorted((ROOT / "tests" / "unit").rglob("*.py")),
        ROOT / "README.md",
        ROOT / "Makefile",
        ROOT / "pyproject.toml",
        ROOT / "docs" / "FINAL_HANDOFF.md",
        ROOT / "docs" / "LIVE_CONNECTIVITY_SMOKE_TEST.md",
        ROOT / "docs" / "OPERATOR_RUNBOOK.md",
        ROOT / "docs" / "RELEASE_HANDOFF.md",
    ]

    findings = {
        path.relative_to(ROOT).as_posix(): token
        for path in files
        for token in legacy_tokens
        if token in path.read_text(encoding="utf-8")
    }

    assert findings == {}
