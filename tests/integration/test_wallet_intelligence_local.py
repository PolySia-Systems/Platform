from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polysia.application.ports.wallet_intelligence_research import ResearchPublicationError
from polysia.cli import app
from polysia.cli_support.wallet_intelligence_workflow import (
    WorkflowPaths,
    execute_workflow,
    human_summary,
    workflow_lock,
)

NOW = datetime(2026, 10, 3, 21, tzinfo=UTC)


def seal(data):
    analytical = {k: v for k, v in data.items() if k not in {"snapshot_digest", "diagnostics"}}
    data["snapshot_digest"] = hashlib.sha256(
        json.dumps(
            analytical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def setup(
    tmp_path,
    data,
    *,
    reused=False,
    renderer="ok",
    producer_failure=False,
    replace_source=False,
    mutate_pinned=False,
):
    producer = tmp_path / "producer"
    root = producer / "data"
    source = root / "snapshots" / data["run_id"] / "wallet-intelligence.json"
    source.parent.mkdir(parents=True)
    seal(data)
    source.write_text(json.dumps(data), encoding="utf-8")
    paths = WorkflowPaths(
        producer, producer / "producer.exe", producer / "acceptance.toml", root, tmp_path / "output"
    )
    calls = []

    def runner(command, cwd, timeout):
        calls.append(command)
        if "run" in command:
            if producer_failure:
                return subprocess.CompletedProcess(
                    command,
                    2,
                    "",
                    json.dumps({"invocation_resources": {"requests": 2, "retries": 1}}),
                )
            result = {
                "run_id": data["run_id"],
                "snapshot_digest": data["snapshot_digest"],
                "artifact": str(source),
                "refresh_action": "REUSED" if reused else "REFRESHED",
                "invocation_resources": {"requests": 0 if reused else 5, "retries": 0},
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
        assert "render" in command
        frozen = Path(command[-2])
        artifact = json.loads(frozen.read_text())
        if replace_source:
            source.write_text('{"run_id":"replacement"}')
            latest = root / "latest/wallet-intelligence.json"
            latest.parent.mkdir(exist_ok=True)
            latest.write_text('{"run_id":"different-latest"}')
        if mutate_pinned:
            artifact["run_id"] = "f" * 32
            seal(artifact)
            frozen.write_text(json.dumps(artifact))
        if renderer == "fail":
            return subprocess.CompletedProcess(command, 2, "", "renderer failure")
        if renderer == "wrong":
            artifact["run_id"] = "e" * 32
        Path(command[-1]).write_text(
            '<script id="artifact" type="application/json">' + json.dumps(artifact) + "</script>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "{}", "")

    return paths, runner, calls


@pytest.mark.parametrize("reused", [False, True])
def test_success_and_not_due_reuse_bind_one_snapshot(
    tmp_path, wallet_intelligence_artifact, reused
):
    data = wallet_intelligence_artifact
    paths, runner, calls = setup(tmp_path, data, reused=reused, replace_source=True)
    result = execute_workflow(paths, runner=runner, clock=lambda: NOW)
    assert result["status"] == "ACCEPTED_FOR_RESEARCH"
    assert result["counts"] == {"ACCEPTED": 1, "WATCHLIST": 1, "REJECTED": 1}
    assert result["snapshot_digest"] == data["snapshot_digest"]
    assert json.loads(Path(result["artifact"]).read_text()) == data
    report = json.loads(Path(result["consumer_report"]).read_text())
    assert report["source_snapshot_digest"] == data["snapshot_digest"]
    assert report["admission"]["live"] == "NOT_ADMITTED"
    assert result["provider_resources"]["requests"] == (0 if reused else 5)
    assert "--if-due" in calls[0] and "--no-render" in calls[0]
    assert "accepted 1" in human_summary(result)


@pytest.mark.parametrize("case", ["expired", "partial", "partial_opt_in", "empty"])
def test_existing_intake_policy_controls_expiry_partial_and_empty(
    tmp_path,
    wallet_intelligence_artifact,
    case,
):
    data = wallet_intelligence_artifact
    if case.startswith("partial"):
        data["status"] = "PARTIAL"
        data["coverage"]["missing_partitions"] = ["source_unavailable"]
    if case == "empty":
        data["records"] = data["candidates"] = data["source_references"] = []
        data["coverage"].update(
            discovered=0, examined=0, unexamined=0, active=0, performance_supported=0, published=0
        )
        data["coverage"]["outcomes"] = {k: 0 for k in data["coverage"]["outcomes"]}
    paths, runner, _ = setup(tmp_path, data, reused=True)
    result = execute_workflow(
        paths,
        runner=runner,
        clock=lambda: datetime(2026, 10, 4, 21, tzinfo=UTC) if case == "expired" else NOW,
        allow_partial=case == "partial_opt_in",
    )
    assert result["status"] == (
        {"expired": "REJECTED", "partial": "REJECTED", "empty": "ACCEPTED_EMPTY"}.get(
            case, "ACCEPTED_FOR_RESEARCH"
        )
    )
    assert result["provider_resources"]["requests"] == 0
    if case == "empty":
        assert not json.loads(Path(result["consumer_report"]).read_text())["rows"]
    if case == "partial_opt_in":
        assert result["producer_status"] == "PARTIAL"


@pytest.mark.parametrize("renderer", ["fail", "wrong"])
def test_renderer_failure_keeps_machine_result_without_old_view(
    tmp_path,
    wallet_intelligence_artifact,
    renderer,
):
    paths, runner, _ = setup(tmp_path, wallet_intelligence_artifact, renderer=renderer)
    result = execute_workflow(paths, runner=runner, clock=lambda: NOW)
    assert result["status"] == "ACCEPTED_FOR_RESEARCH"
    assert result["human_view"] is None and result["warnings"]
    assert Path(result["consumer_report"]).is_file()


def test_failure_cannot_present_old_report_or_hide_spent_requests(
    tmp_path, wallet_intelligence_artifact
):
    paths, runner, _ = setup(tmp_path, wallet_intelligence_artifact, producer_failure=True)
    paths.output_root.mkdir()
    previous = paths.output_root / "old-report.json"
    previous.write_text("old accepted report")
    result = execute_workflow(paths, runner=runner, clock=lambda: NOW)
    assert result["status"] == "FAILED" and result["error_code"] == "producer_failed"
    assert result["provider_resources"] == {"requests": 2, "retries": 1}
    assert "consumer_report" not in result and previous.read_text() == "old accepted report"
    assert json.loads((paths.output_root / "current.json").read_text()) == result


def test_pinned_replacement_and_overlapping_workflow_are_rejected(
    tmp_path, wallet_intelligence_artifact
):
    paths, runner, calls = setup(tmp_path, wallet_intelligence_artifact, mutate_pinned=True)
    with (
        workflow_lock(paths.output_root / "workflow.lock"),
        pytest.raises(ResearchPublicationError, match="workflow_already_running"),
    ):
        execute_workflow(paths, runner=runner, clock=lambda: NOW)
    assert not calls
    result = execute_workflow(paths, runner=runner, clock=lambda: NOW)
    assert result["status"] == "FAILED" and not result["consumer_report"]


def test_actual_cli_force_and_optional_open(tmp_path, wallet_intelligence_artifact, monkeypatch):
    paths, runner, calls = setup(tmp_path, wallet_intelligence_artifact)
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence_workflow.execute_workflow",
        lambda options, **kw: execute_workflow(options, runner=runner, clock=lambda: NOW, **kw),
    )
    opened = []
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence_workflow.webbrowser.open",
        lambda uri: opened.append(uri) or True,
    )
    result = CliRunner().invoke(
        app,
        [
            "wallet-intelligence",
            "local",
            "--producer-dir",
            str(paths.producer_dir),
            "--producer-executable",
            str(paths.executable),
            "--producer-config",
            str(paths.config),
            "--data-root",
            str(paths.data_root),
            "--output-root",
            str(paths.output_root),
            "--force",
            "--open-view",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "--if-due" not in calls[0] and len(opened) == 1
    assert "Research only" in result.output
