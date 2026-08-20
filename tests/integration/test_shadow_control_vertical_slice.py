from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from polysia.cli import app

runner = CliRunner()


def test_cli_shadow_control_pause_resume_vertical_slice(tmp_path: Path) -> None:
    database_path = tmp_path / "control.sqlite3"

    pause_plan = _plan(database_path, "PAUSED")
    pause_apply = _apply(
        database_path,
        plan_id=pause_plan["plan_id"],
        command_id="pause-command",
        expected_revision=0,
    )
    assert pause_apply["revision"]["desired_state"] == "PAUSED"
    assert pause_apply["observation"]["observed_state"] == "PAUSED"

    paused = _shadow_run(database_path, tmp_path / "paused")
    assert paused["classification"] == "SHADOW_PAUSED"
    paused_report = json.loads(
        (tmp_path / "paused" / "shadow_run.json").read_text(encoding="utf-8")
    )
    assert paused_report["operational_state"] == "PAUSED"
    assert paused_report["control_revision"] == 1
    assert paused_report["metrics"]["event_count"] == 4
    assert paused_report["metrics"]["orderbook_updates"] == 4
    assert paused_report["metrics"]["stream_health"] == "mocked_public_stream"
    assert paused_report["metrics"]["strategy_intent_count"] == 0
    assert paused_report["metrics"]["risk_approval_count"] == 0
    assert paused_report["metrics"]["paper_order_count"] == 0
    assert paused_report["metrics"]["paper_fill_count"] == 0
    assert paused_report["metrics"]["live_broker_used"] is False

    resume_plan = _plan(database_path, "RUNNING")
    resume_apply = _apply(
        database_path,
        plan_id=resume_plan["plan_id"],
        command_id="resume-command",
        expected_revision=1,
    )
    assert resume_apply["revision"]["desired_state"] == "RUNNING"
    assert resume_apply["observation"]["observed_state"] == "RUNNING"

    running = _shadow_run(database_path, tmp_path / "running")
    assert running["classification"] == "SHADOW_HEALTHY"
    running_report = json.loads(
        (tmp_path / "running" / "shadow_run.json").read_text(encoding="utf-8")
    )
    assert running_report["operational_state"] == "RUNNING"
    assert running_report["control_revision"] == 2
    assert running_report["metrics"]["strategy_intent_count"] > 0
    assert running_report["metrics"]["risk_approval_count"] > 0
    assert running_report["metrics"]["paper_fill_count"] > 0
    assert running_report["metrics"]["live_broker_used"] is False

    status = runner.invoke(
        app,
        ["control", "status", "--database-path", str(database_path)],
    )
    assert status.exit_code == 0, status.stdout
    status_payload = json.loads(status.stdout)
    assert status_payload["desired_state"] == "RUNNING"
    assert status_payload["observed_state"] == "RUNNING"
    assert status_payload["last_reconciled_revision"] == 2

    history = runner.invoke(
        app,
        ["control", "history", "--database-path", str(database_path)],
    )
    assert history.exit_code == 0, history.stdout
    history_payload = json.loads(history.stdout)
    assert [item["created_revision"] for item in history_payload] == [1, 2]
    assert [item["command_id"] for item in history_payload] == [
        "pause-command",
        "resume-command",
    ]


def _plan(database_path: Path, state: str) -> dict[str, object]:
    result = runner.invoke(
        app,
        [
            "control",
            "plan",
            state,
            "--database-path",
            str(database_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _apply(
    database_path: Path,
    *,
    plan_id: object,
    command_id: str,
    expected_revision: int,
) -> dict[str, object]:
    result = runner.invoke(
        app,
        [
            "control",
            "apply",
            "--plan-id",
            str(plan_id),
            "--command-id",
            command_id,
            "--expected-revision",
            str(expected_revision),
            "--actor",
            "integration-owner",
            "--database-path",
            str(database_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _shadow_run(database_path: Path, output_dir: Path) -> dict[str, object]:
    result = runner.invoke(
        app,
        [
            "research",
            "shadow",
            "--max-events",
            "4",
            "--control-database-path",
            str(database_path),
            "--output-dir",
            str(output_dir),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)
