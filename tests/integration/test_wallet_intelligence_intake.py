from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from polysia.cli import app
from polysia.domain.clock import SystemClock

runner = CliRunner()


@pytest.fixture(autouse=True)
def fixed_consumer_clock(monkeypatch):
    monkeypatch.setattr(SystemClock, "now", lambda self: datetime(2026, 10, 3, 21, tzinfo=UTC))


def write(path: Path, data: dict[str, Any]) -> None:
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
    path.write_text(json.dumps(data), encoding="utf-8")


def test_real_cli_adapter_service_wiring_and_protected_identity_projection(
    tmp_path,
    wallet_intelligence_artifact,
):
    path, output = tmp_path / "producer.json", tmp_path / "research.json"
    write(path, wallet_intelligence_artifact)
    before = path.read_bytes()
    result = runner.invoke(
        app, ["wallet-intelligence", "intake", "--artifact", str(path), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["counts"] == {"ACCEPTED": 1, "WATCHLIST": 1, "REJECTED": 1}
    assert report["source_snapshot_digest"] == wallet_intelligence_artifact["snapshot_digest"]
    assert report["source_metadata"]["coverage"] == wallet_intelligence_artifact["coverage"]
    assert report["source_metadata"]["profile"] == wallet_intelligence_artifact["profile"]
    assert report["admission"]["shadow_alpha"] == "NOT_ADMITTED"
    assert "0x" + "1" * 40 not in result.output
    assert (
        report["rows"][0]["source_record_projection"]["identity"]["account_wallet"] == "[protected]"
    )
    assert json.loads(output.read_text()) == report and path.read_bytes() == before
    full = runner.invoke(
        app, ["wallet-intelligence", "intake", "--artifact", str(path), "--include-identities"]
    )
    assert full.exit_code == 0
    full_report = json.loads(full.stdout)
    assert (
        full_report["rows"][0]["source_record_projection"]
        == wallet_intelligence_artifact["records"][0]
    )
    assert full_report["rows"][0]["producer_rank"] == 1
    assert not list(tmp_path.glob("*.sqlite*"))


@pytest.mark.parametrize("case", ["partial", "stale", "capability", "tampered", "unsupported"])
def test_invalid_or_disallowed_intake_preserves_previous_report(
    tmp_path,
    wallet_intelligence_artifact,
    case,
):
    data = wallet_intelligence_artifact
    path, output = tmp_path / "producer.json", tmp_path / "research.json"
    extra = []
    if case == "partial":
        data["status"] = "PARTIAL"
        data["coverage"]["missing_partitions"] = ["source_unavailable"]
    elif case == "stale":
        data["generated_at"] = data["evaluation_at"] = "2026-10-02T21:00:00Z"
        data["data_cutoff"] = "2026-10-02T21:00:00Z"
        # A valid old empty artifact exercises consumer expiry rather than schema rejection.
        data["records"] = data["candidates"] = data["source_references"] = []
        data["coverage"].update(
            discovered=0,
            examined=0,
            unexamined=0,
            active=0,
            performance_supported=0,
            published=0,
            discovery_at="2026-10-02T21:00:00Z",
        )
        data["coverage"]["outcomes"] = {key: 0 for key in data["coverage"]["outcomes"]}
        data["expires_at"] = "2026-10-03T21:00:00Z"
    elif case == "capability":
        extra = ["--require-copyability"]
    elif case == "unsupported":
        data["schema_version"] = "wallet-intelligence/v9"
    write(path, data)
    if case == "tampered":
        data["records"][0]["performance"]["value"] = "99"
        path.write_text(json.dumps(data))
    output.write_text("previous-valid-research-report")
    result = runner.invoke(
        app,
        ["wallet-intelligence", "intake", "--artifact", str(path), "--output", str(output), *extra],
    )
    assert result.exit_code == 2
    assert output.read_text() == "previous-valid-research-report"
    assert not list(tmp_path.glob("*.sqlite*"))
    if case == "partial":
        accepted = runner.invoke(
            app, ["wallet-intelligence", "intake", "--artifact", str(path), "--allow-partial"]
        )
        assert accepted.exit_code == 0
        assert json.loads(accepted.stdout)["source_metadata"]["status"] == "PARTIAL"
    if case == "capability":
        assert "capability_unavailable:copyability:NOT_EVALUATED" in result.stdout


def test_valid_empty_supersedes_previous_candidates(tmp_path, wallet_intelligence_artifact):
    data = wallet_intelligence_artifact
    data["records"] = data["candidates"] = data["source_references"] = []
    data["coverage"].update(
        discovered=0, examined=0, unexamined=0, active=0, performance_supported=0, published=0
    )
    data["coverage"]["outcomes"] = {key: 0 for key in data["coverage"]["outcomes"]}
    path, output = tmp_path / "producer.json", tmp_path / "research.json"
    write(path, data)
    output.write_text("previous-candidates")
    result = runner.invoke(
        app, ["wallet-intelligence", "intake", "--artifact", str(path), "--output", str(output)]
    )
    assert result.exit_code == 0
    assert json.loads(output.read_text())["status"] == "ACCEPTED_EMPTY"
    assert json.loads(output.read_text())["rows"] == []


def test_refuses_source_overwrite_and_atomic_write_failure_is_safe(
    tmp_path,
    wallet_intelligence_artifact,
    monkeypatch,
):
    path, output = tmp_path / "producer.json", tmp_path / "research.json"
    write(path, wallet_intelligence_artifact)
    before = path.read_bytes()
    same = runner.invoke(
        app, ["wallet-intelligence", "intake", "--artifact", str(path), "--output", str(path)]
    )
    assert same.exit_code == 2 and path.read_bytes() == before
    output.write_text("previous")

    def interrupted(*args):
        raise OSError("interrupted rename")

    monkeypatch.setattr("polysia.cli_support.wallet_intelligence_research.os.replace", interrupted)
    failed = runner.invoke(
        app, ["wallet-intelligence", "intake", "--artifact", str(path), "--output", str(output)]
    )
    assert failed.exit_code == 2 and output.read_text() == "previous"
    assert not list(tmp_path.glob(".research-intake-*"))
