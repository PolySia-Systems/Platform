from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from polysia.adapters.wallet_intelligence import (
    MAX_ARTIFACT_BYTES,
    WalletIntelligenceArtifactSource,
)
from polysia.application.ports.wallet_intelligence_research import ResearchPublicationError


def seal(data: dict[str, Any]) -> None:
    analytical = {
        key: value for key, value in data.items() if key not in {"snapshot_digest", "diagnostics"}
    }
    data["snapshot_digest"] = hashlib.sha256(
        json.dumps(
            analytical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def read(tmp_path: Path, data: dict[str, Any]):
    path = tmp_path / "publication.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return WalletIntelligenceArtifactSource(path).read_publication()


def test_exact_record_metadata_components_and_rank_are_preserved(
    tmp_path, wallet_intelligence_artifact
):
    data = wallet_intelligence_artifact
    data["records"][0]["additional_feature"] = {"unit": "count", "value": None}
    seal(data)
    publication = read(tmp_path, data)
    assert json.loads(publication.analytical_json)["coverage"] == data["coverage"]
    assert json.loads(publication.records[0].source_record_json) == data["records"][0]
    assert publication.records[0].producer_rank == 1
    assert data["records"][0]["discovery"][0]["source_rank"] == 4
    assert publication.records[0].external_wallet_id == "0x" + "1" * 40
    assert str(publication.records[0].performance_value) == "10.25"
    assert publication.records[1].performance_value is None
    assert publication.records[2].performance_value == 0
    assert "source_score" not in json.loads(publication.records[0].source_record_json)


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "profile",
        "rank",
        "identity",
        "counts",
        "candidate_projection",
        "future",
        "money_float",
        "money_null",
        "money_nan",
        "span",
        "unit",
        "copyability",
        "evidence",
        "observation_clock",
        "expiry",
        "partial",
        "bool_count",
        "component",
    ],
)
def test_resealed_semantically_invalid_publications_are_rejected(
    tmp_path,
    wallet_intelligence_artifact,
    mutation,
):
    data = wallet_intelligence_artifact
    record = data["records"][0]
    if mutation == "version":
        data["schema_version"] = "wallet-intelligence/v9"
    elif mutation == "profile":
        data["profile"]["id"] = "copyable"
    elif mutation == "rank":
        record["candidate_rank"] = 2
    elif mutation == "identity":
        record["identity"]["account_wallet"] = "0x" + "4" * 40
    elif mutation == "counts":
        data["coverage"]["unexamined"] = 0
    elif mutation == "candidate_projection":
        data["candidates"] = []
    elif mutation == "future":
        record["performance"]["end"] = "2026-10-04T22:00:00Z"
    elif mutation == "money_float":
        record["performance"]["value"] = 10.25
    elif mutation == "money_null":
        record["performance"]["value"] = None
    elif mutation == "money_nan":
        record["performance"]["value"] = "NaN"
    elif mutation == "span":
        record["performance"]["span_seconds"] = 1
    elif mutation == "unit":
        record["performance"]["unit"] = "shares"
    elif mutation == "copyability":
        data["capabilities"]["copyability"] = "AVAILABLE"
    elif mutation == "evidence":
        record["evidence_references"] = []
    elif mutation == "observation_clock":
        record["observed_at"] = data["expires_at"]
    elif mutation == "expiry":
        data["expires_at"] = "2026-10-05T21:00:00Z"
    elif mutation == "partial":
        data["coverage"]["missing_partitions"] = ["source_unavailable"]
    elif mutation == "bool_count":
        data["coverage"]["published"] = True
    elif mutation == "component":
        record["performance"]["components"]["position_pnl"]["value"] = "99"
    seal(data)
    with pytest.raises(ResearchPublicationError):
        read(tmp_path, data)


def test_tampering_duplicate_keys_and_nonfinite_json_are_rejected(
    tmp_path, wallet_intelligence_artifact
):
    data = wallet_intelligence_artifact
    data["records"][0]["performance"]["value"] = "12.25"
    with pytest.raises(ResearchPublicationError, match="snapshot_digest_mismatch"):
        read(tmp_path, data)
    path = tmp_path / "publication.json"
    path.write_text('{"schema_version": "a", "schema_version": "b"}')
    with pytest.raises(ResearchPublicationError, match="duplicate_json_key"):
        WalletIntelligenceArtifactSource(path).read_publication()
    path.write_text('{"value":NaN}')
    with pytest.raises(ResearchPublicationError, match="nonfinite_json_number"):
        WalletIntelligenceArtifactSource(path).read_publication()
    path.write_text('{"diagnostics":{"duration":1e400}}')
    with pytest.raises(ResearchPublicationError, match="nonfinite_json_number"):
        WalletIntelligenceArtifactSource(path).read_publication()


def test_unavailable_oversized_and_invalid_bytes_are_safe(tmp_path):
    path = tmp_path / "secret-account-name.json"
    with pytest.raises(ResearchPublicationError, match="artifact_unavailable") as error:
        WalletIntelligenceArtifactSource(path).read_publication()
    assert "secret-account-name" not in str(error.value)
    path.write_bytes(b" " * (MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(ResearchPublicationError, match="artifact_size_limit"):
        WalletIntelligenceArtifactSource(path).read_publication()
    path.write_bytes(b"\xff")
    with pytest.raises(ResearchPublicationError, match="invalid_artifact_schema"):
        WalletIntelligenceArtifactSource(path).read_publication()


def test_cross_wallet_reference_and_partial_inactivity_are_rejected(
    tmp_path,
    wallet_intelligence_artifact,
):
    data = wallet_intelligence_artifact
    original = data["records"][0]["evidence_references"]
    data["records"][0]["evidence_references"] = data["records"][1]["evidence_references"]
    seal(data)
    with pytest.raises(ResearchPublicationError, match="foreign_wallet_evidence"):
        read(tmp_path, data)
    data["records"][0]["evidence_references"] = original
    data["records"][2]["activity"]["acquisition"] = "INCOMPLETE"
    seal(data)
    with pytest.raises(ResearchPublicationError, match="unsupported_inactive_claim"):
        read(tmp_path, data)
