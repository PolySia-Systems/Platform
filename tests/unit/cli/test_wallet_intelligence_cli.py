from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polysia.cli import app
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord

runner = CliRunner()


def test_health_initializes_separate_database_and_reports_never_succeeded(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    report_path = tmp_path / "reports" / "latest.json"

    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "health",
            "--database",
            str(database),
            "--health-report",
            str(report_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["level"] == "critical"
    assert payload["reasons"] == ["never_succeeded", "candidate_pool_unavailable"]
    assert database.is_file()
    assert json.loads(report_path.read_text(encoding="utf-8")) == payload
    assert "0x" not in report_path.read_text(encoding="utf-8")


def test_unknown_source_is_rejected_before_any_network_read(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "health",
            "--source",
            "unknown",
            "--database",
            str(tmp_path / "wallet-intelligence.sqlite3"),
        ],
    )

    assert result.exit_code == 2
    assert "Unsupported candidate-wallet source" in result.output


def test_shadow_commands_fail_safe_before_stage3_and_results_stay_address_free(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    sync = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "shadow-sync",
            "--database",
            str(database),
            "--mode",
            "HISTORICAL",
            "--lookback-hours",
            "1",
        ],
    )
    results = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "shadow-results",
            "--database",
            str(database),
            "--mode",
            "HISTORICAL",
        ],
    )

    assert sync.exit_code == 1
    assert "no order was sent" in sync.output.lower()
    assert results.exit_code == 0
    assert json.loads(results.stdout)["rows"] == []
    assert "0x" not in results.stdout


def test_ensure_builds_pool_and_pool_command_never_exposes_address(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    address = "0x" + "1" * 40
    fetched_at = datetime.now(UTC)
    record = CandidateWalletRecord(
        external_wallet_id=address,
        source_rank=1,
        source_page=1,
        metrics={"score": "90"},
        row_digest=hashlib.sha256(address.encode()).hexdigest(),
    )
    dataset = CandidateWalletDataset(
        source_id="polycop",
        schema_version="test-v1",
        fetched_at=fetched_at,
        source_total_pages=1,
        records=(record,),
        dataset_digest=hashlib.sha256(record.row_digest.encode()).hexdigest(),
    )

    class Source:
        source_id = "polycop"

        async def fetch_snapshot(self) -> CandidateWalletDataset:
            return dataset

    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._source",
        lambda _source_id: Source(),
    )
    database = tmp_path / "wallet-intelligence.sqlite3"
    report = tmp_path / "reports" / "latest.json"
    ensured = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "ensure",
            "--database",
            str(database),
            "--health-report",
            str(report),
            "--no-backup",
        ],
    )

    assert ensured.exit_code == 0, ensured.output
    ensured_payload = json.loads(ensured.stdout)
    assert ensured_payload["candidate_pool"]["selected_count"] == 1
    assert ensured_payload["copyability_selection"]["live_review_count"] == 0
    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "pool",
            "--database",
            str(database),
            "--limit",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["count"] == 1
    assert payload["rows"][0]["candidate_rank"] == 1
    assert address not in result.stdout
    assert "0x" not in report.read_text(encoding="utf-8")
    selection = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "selection",
            "--database",
            str(database),
            "--pool",
            "LIVE_REVIEW_CANDIDATE",
        ],
    )
    assert selection.exit_code == 0, selection.output
    selection_payload = json.loads(selection.stdout)
    assert selection_payload["count"] == 0
    assert address not in selection.stdout
