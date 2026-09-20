from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.backtesting import prospective_reanalysis as reanalysis_module
from polysia.backtesting.prospective_analysis import capture_protected_artifacts
from polysia.backtesting.prospective_reanalysis import (
    CLAIM_CONFIRMATORY,
    CLAIM_EXPLORATORY,
    ProspectiveReanalysisError,
    write_reanalysis,
)
from polysia.storage.immutable_sqlite import sha256_file
from polysia.storage.research_evidence import ResearchEvidenceStore


def _recorded_database(path: Path, run_id: str = "capture-run") -> Path:
    store = ResearchEvidenceStore(path)
    store.start_or_resume_experiment(
        requested_run_id=run_id,
        duration=timedelta(hours=1),
        max_events=100,
        max_bytes=10_000_000,
        code_sha="a" * 40,
        configuration_digest="configuration",
    )
    ProspectiveCollector(store, run_id=run_id).close_window(complete=True)
    return path


def test_reanalysis_is_additive_and_leaves_source_hash_unchanged(tmp_path: Path) -> None:
    database = _recorded_database(tmp_path / "research.sqlite3")
    before = sha256_file(database)
    protected = capture_protected_artifacts(database=database)
    first = write_reanalysis(
        database=database,
        run_id="capture-run",
        analysis_code_sha="b" * 40,
        analysis_dir=tmp_path / "analyses",
        analysis_id="pass-1",
    )
    second_dir = tmp_path / "analyses" / "pass-1"
    assert first["claim_class"] == CLAIM_EXPLORATORY
    assert (second_dir / "result.json").is_file()
    assert (second_dir / "provenance.json").is_file()
    assert sha256_file(database) == before
    assert capture_protected_artifacts(database=database).digests == protected.digests
    with pytest.raises(ProspectiveReanalysisError, match="already exists"):
        write_reanalysis(
            database=database,
            run_id="capture-run",
            analysis_code_sha="c" * 40,
            analysis_dir=tmp_path / "analyses",
            analysis_id="pass-1",
        )
    assert sha256_file(database) == before


def test_reanalysis_publication_is_atomic_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _recorded_database(tmp_path / "research.sqlite3")
    original = reanalysis_module._atomic_json
    calls = 0

    def fail_second(path: Path, payload: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publication failure")
        original(path, payload)

    monkeypatch.setattr(reanalysis_module, "_atomic_json", fail_second)
    with pytest.raises(OSError, match="injected publication failure"):
        write_reanalysis(
            database=database,
            run_id="capture-run",
            analysis_code_sha="b" * 40,
            analysis_dir=tmp_path / "analyses",
            analysis_id="retryable",
        )
    destination = tmp_path / "analyses" / "retryable"
    assert not destination.exists()
    assert not list((tmp_path / "analyses").glob(".retryable.*.tmp"))

    monkeypatch.setattr(reanalysis_module, "_atomic_json", original)
    write_reanalysis(
        database=database,
        run_id="capture-run",
        analysis_code_sha="b" * 40,
        analysis_dir=tmp_path / "analyses",
        analysis_id="retryable",
    )
    assert (destination / "result.json").is_file()
    assert (destination / "provenance.json").is_file()


def test_reanalysis_requires_immutable_analysis_sha(tmp_path: Path) -> None:
    database = _recorded_database(tmp_path / "research.sqlite3")
    with pytest.raises(ProspectiveReanalysisError, match="40-character Git SHA"):
        write_reanalysis(
            database=database,
            run_id="capture-run",
            analysis_code_sha="unknown",
            analysis_dir=tmp_path / "analyses",
        )


def test_reanalysis_reads_sanitized_wallet_identity_from_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    database = _recorded_database(bundle / "research-evidence.sqlite3")
    checksum = sha256_file(database)
    database.with_suffix(".sqlite3.sha256").write_text(
        f"{checksum}  {database.name}\n",
        encoding="ascii",
    )
    manifest = {
        "database": database.name,
        "database_sha256": checksum,
        "wallet_selection": {
            "identity_status": "RECORDED",
            "selection_digest": "d" * 64,
            "selection_policy": "polycop-shadow-alpha-configured-v1",
            "wallet_count": 2,
        },
    }
    (bundle / "experiment-manifest.json").write_text(
        f"{json.dumps(manifest, sort_keys=True)}\n",
        encoding="utf-8",
    )
    summary = write_reanalysis(
        database=database,
        run_id="capture-run",
        analysis_code_sha="b" * 40,
        analysis_dir=tmp_path / "analyses",
        analysis_id="selection",
        bundle_root=bundle,
    )
    result = json.loads(
        (Path(str(summary["path"])) / "result.json").read_text(encoding="utf-8")
    )

    assert result["wallet_selection"] == {
        "configuration_digest": "configuration",
        "identity_status": "RECORDED",
        "selection_digest": "d" * 64,
        "selection_policy": "polycop-shadow-alpha-configured-v1",
        "wallet_count": 2,
    }
    assert "wallet_ids" not in result["wallet_selection"]


def test_reanalysis_reports_unknown_wallet_identity_for_legacy_evidence(tmp_path: Path) -> None:
    database = _recorded_database(tmp_path / "research.sqlite3")
    summary = write_reanalysis(
        database=database,
        run_id="capture-run",
        analysis_code_sha="b" * 40,
        analysis_dir=tmp_path / "analyses",
        analysis_id="legacy",
    )
    result = json.loads(
        (Path(str(summary["path"])) / "result.json").read_text(encoding="utf-8")
    )
    assert result["wallet_selection"] == {
        "configuration_digest": "configuration",
        "identity_status": "UNKNOWN",
    }


def test_confirmatory_claim_requires_frozen_hypothesis_and_independent_evidence(
    tmp_path: Path,
) -> None:
    database = _recorded_database(tmp_path / "research.sqlite3")
    with pytest.raises(ProspectiveReanalysisError, match="independent evidence"):
        write_reanalysis(
            database=database,
            run_id="capture-run",
            analysis_code_sha="b" * 40,
            analysis_dir=tmp_path / "analyses",
            analysis_id="bad-hypothesis",
            hypothesis={"hypothesis_id": "h1"},
        )
    payload = write_reanalysis(
        database=database,
        run_id="capture-run",
        analysis_code_sha="b" * 40,
        analysis_dir=tmp_path / "analyses",
        analysis_id="confirm",
        hypothesis={
            "hypothesis_id": "h1",
            "digest": "d" * 64,
            "independent_evidence_hash": "e" * 64,
        },
    )
    assert payload["claim_class"] == CLAIM_CONFIRMATORY
