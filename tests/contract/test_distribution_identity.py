from __future__ import annotations

import ast
import importlib.util
import json
import re
import tomllib
from pathlib import Path

import polysia

ROOT = Path(__file__).resolve().parents[2]


def test_console_release_literals_match_the_package_owner():
    from polysia.monitoring.console_bundle import RELEASE as bundle_release
    from polysia.monitoring.console_contract import RELEASE as wire_release

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = metadata["project"]["version"]
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert expected == bundle_release == wire_release == package["version"] == lock["version"]
    assert lock["packages"][""]["version"] == expected
    manifest = ROOT / "src/polysia/monitoring/human_console_assets/manifest.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["release"] == expected
    tree = ast.parse((ROOT / "src/polysia/monitoring/console_contract.py").read_text())
    release = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                   and isinstance(n.target, ast.Name) and n.target.id == "RELEASE")
    assert ast.literal_eval(release.annotation.slice) == expected


def test_image_python_patch_matches_workflows_and_release_evidence():
    image = re.search(
        r"(?:FROM |PYTHON_IMAGE=)python:([\d.]+)-", (ROOT / "Dockerfile").read_text()
    )[1]
    source = (ROOT / "scripts/release_manifest.py").read_text()
    pins = re.findall(r'"(?:python|python_patch)": "([\d.]+)"', source)
    assert pins and set(pins) == {image}
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert set(re.findall(r'python-version: "([\d.]+)"', workflow)) == {image}


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
    ]

    findings = {
        path.relative_to(ROOT).as_posix(): token
        for path in files
        for token in legacy_tokens
        if token in path.read_text(encoding="utf-8")
    }

    assert findings == {}
