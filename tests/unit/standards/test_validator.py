from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_standards import (
    EXPECTED_COMMIT,
    EXPECTED_OUTCOME_COUNTS,
    EXPECTED_RELEASE,
    _conformance_findings,
    _load_toml,
    _manifest_findings,
    scan_repository,
)

REPOSITORY = Path(__file__).resolve().parents[3]


def test_adoption_manifest_is_fully_enforced_without_a_baseline() -> None:
    manifest = _load_toml(REPOSITORY / "standards/adoption.toml")
    findings = scan_repository(REPOSITORY, manifest)

    assert manifest["standards_release"] == EXPECTED_RELEASE
    assert manifest["standards_commit"] == EXPECTED_COMMIT
    assert {
        outcome: sum(
            len(group["ids"])
            for group in manifest["requirement_groups"]
            if group["outcome"] == outcome
        )
        for outcome in EXPECTED_OUTCOME_COUNTS
    } == EXPECTED_OUTCOME_COUNTS
    assert manifest["status"] == "active_conformant"
    assert manifest["enforcement"]["mode"] == "full"
    assert "baseline" not in manifest["enforcement"]
    assert not (REPOSITORY / "standards/baseline.toml").exists()
    assert findings == []


@pytest.mark.parametrize("value", [None, False, "UNKNOWN"])
def test_maintained_dependency_fact_cannot_hide_existing_closure(value: object) -> None:
    manifest = _load_toml(REPOSITORY / "standards/adoption.toml")
    manifest["consumer_facts"]["maintained_third_party_dependencies"] = value

    assert any(f.requirement_id == "ENG-PY-022" for f in _manifest_findings(manifest))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("standards_release", "v0.5.2"),
        ("standards_commit", "2ccbe4dbbcb3574db52e5a8eb73e968a9165a83c"),
        ("standards_release_id", 414090521),
        ("standards_release_immutable", False),
    ],
)
def test_adoption_rejects_mismatched_release_identity(field: str, value: object) -> None:
    manifest = _load_toml(REPOSITORY / "standards/adoption.toml")
    manifest[field] = value

    assert any(
        f.requirement_id in {"CORE-LCY-001", "CORE-VER-012"}
        for f in _manifest_findings(manifest)
    )


def test_maintenance_requirements_cannot_be_omitted_from_adoption() -> None:
    manifest = _load_toml(REPOSITORY / "standards/adoption.toml")
    manifest["requirement_groups"] = [
        group for group in manifest["requirement_groups"]
        if not group["name"].startswith("python-maintenance-")
    ]

    assert any(f.requirement_id == "PRF-PYS-005" for f in _manifest_findings(manifest))


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('standards_release = "v1.0.0"', 'standards_release = "v0.5.2"'),
        ('ids = ["ENG-PY-025"]', 'ids = []'),
        ('applicable = 93', 'applicable = 89'),
    ],
)
def test_conformance_rejects_stale_or_incomplete_record(
    tmp_path: Path, before: str, after: str,
) -> None:
    source = (REPOSITORY / "standards/conformance.toml").read_text(encoding="utf-8")
    assert before in source
    (tmp_path / "standards").mkdir()
    (tmp_path / "standards/conformance.toml").write_text(
        source.replace(before, after), encoding="utf-8",
    )

    assert _conformance_findings(tmp_path)
