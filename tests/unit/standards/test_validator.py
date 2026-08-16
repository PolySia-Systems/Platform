from __future__ import annotations

from pathlib import Path

from scripts.validate_standards import (
    EXPECTED_COMMIT,
    EXPECTED_OUTCOME_COUNTS,
    EXPECTED_RELEASE,
    _load_toml,
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
