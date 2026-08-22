from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from polysia.cli import app

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
    assert payload["reasons"] == ["never_succeeded"]
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
