from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polysia.cli import app
from polysia.storage.continuous_shadow import ContinuousShadowRepository

runner = CliRunner()


def test_operational_health_completes_while_writer_holds_the_live_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    artifact = tmp_path / "continuous-shadow.json"
    artifact.write_text(
        json.dumps({"level": "healthy", "reasons": []}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ContinuousShadowRepository(database).initialize()
    holder = sqlite3.connect(database, timeout=30)
    holder.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    result = runner.invoke(
        app,
        ["wallet-intelligence", "portfolio-health", "--health-report", str(artifact)],
    )
    elapsed = time.monotonic() - started
    holder.commit()
    holder.close()

    assert result.exit_code == 0, result.output
    assert elapsed < 1
    assert json.loads(result.stdout)["level"] == "healthy"


def test_results_sqlite_busy_fails_fast_with_sanitized_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    ContinuousShadowRepository(database).initialize()

    def boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ContinuousShadowRepository, "results", boom)
    holder = sqlite3.connect(database, timeout=30)
    holder.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "portfolio-results",
            "--database",
            str(database),
            "--experiment-id",
            "exp-busy",
            "--limit",
            "10",
        ],
    )
    elapsed = time.monotonic() - started
    holder.execute(
        "UPDATE continuous_shadow_metadata SET initialized_at = initialized_at"
    )
    holder.commit()
    holder.close()

    assert elapsed < 1
    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "sqlite_busy"
    assert payload["status"] == "failed"
    assert "0x" not in result.output
