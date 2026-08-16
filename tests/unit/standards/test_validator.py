from __future__ import annotations

from pathlib import Path

from scripts.validate_standards import (
    EXPECTED_COMMIT,
    EXPECTED_OUTCOME_COUNTS,
    EXPECTED_RELEASE,
    Finding,
    _baseline_fingerprints,
    _load_toml,
    classify_findings,
    scan_repository,
)

REPOSITORY = Path(__file__).resolve().parents[3]


def test_adoption_manifest_is_remediated_and_baseline_is_resolved() -> None:
    manifest = _load_toml(REPOSITORY / "standards/adoption.toml")
    findings = scan_repository(REPOSITORY, manifest)
    baseline = _baseline_fingerprints(REPOSITORY / "standards/baseline.toml")

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
    assert findings == []
    assert len(baseline) == 10


def test_changed_baseline_path_must_be_remediated() -> None:
    finding = Finding("ENG-PY-006", "scripts/legacy-name.py", "legacy finding")
    baseline = {finding.fingerprint}

    blocking, acknowledged = classify_findings(
        [finding], baseline, {finding.path}, mode="changed", allow_baseline=False
    )

    assert blocking == [finding]
    assert acknowledged == []


def test_unchanged_baseline_path_is_temporarily_acknowledged() -> None:
    finding = Finding("ENG-PY-006", "scripts/legacy-name.py", "legacy finding")

    blocking, acknowledged = classify_findings(
        [finding], {finding.fingerprint}, set(), mode="changed", allow_baseline=False
    )

    assert blocking == []
    assert acknowledged == [finding]


def test_unrecorded_finding_always_blocks_changed_mode() -> None:
    finding = Finding("CORE-NAM-033", "src/Example.py", "new finding")

    blocking, acknowledged = classify_findings(
        [finding], set(), set(), mode="changed", allow_baseline=False
    )

    assert blocking == [finding]
    assert acknowledged == []
