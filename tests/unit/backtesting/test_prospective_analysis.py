from __future__ import annotations

from pathlib import Path

import pytest

from polysia.backtesting.prospective_analysis import verify_declared_bundle_artifacts
from polysia.storage.research_evidence import ResearchEvidenceStoreError


def test_bundle_analysis_requires_manifest_protected_artifacts(tmp_path: Path) -> None:
    database = tmp_path / "research-evidence.sqlite3"
    database.write_bytes(b"sqlite")
    manifest = {
        "database": "research-evidence.sqlite3",
        "database_sha256": "0" * 64,
        "protected_files": ["experiment-manifest.json", "notes.txt"],
    }
    with pytest.raises(ResearchEvidenceStoreError, match="artifact is missing"):
        verify_declared_bundle_artifacts(
            database=database,
            bundle_root=tmp_path,
            manifest=manifest,
        )
