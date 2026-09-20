from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from polysia.application.services.prospective_collector import ProspectiveCollector
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
