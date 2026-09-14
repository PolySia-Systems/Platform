from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polysia.backtesting.offline_research_lab import (
    CODE_SHA,
    CoordinatedClock,
    lab_source_factory,
)
from polysia.cli import app
from polysia.config.settings import AppSettings, TradingMode
from polysia.deployment.research_experiment_runner import (
    ResearchExperimentRunner,
    ResearchRunnerConflictError,
    ResearchRunnerError,
    ResearchRunWorkspace,
)
from polysia.deployment.research_run_profiles import (
    CANARY_PROFILE,
    MAIN_PROFILE,
    RunnerProfile,
)
from polysia.storage.research_evidence import ResearchEvidenceStore

runner = CliRunner()
LAB_PROFILE = RunnerProfile(
    name="lab",
    version="lab-v1",
    window=timedelta(seconds=2),
    window_count=1,
    warmup=timedelta(0),
    max_events=10_000,
    max_bytes=10_000_000,
    memory_bytes=8_388_608,
)


def _runner(clock: CoordinatedClock, work: Path) -> ResearchExperimentRunner:
    factory, _transport = lab_source_factory(clock)
    del work
    return ResearchExperimentRunner(
        source_factory=factory,
        clock=clock,
        sleep=clock.sleep,
        settings_factory=AppSettings,
    )


def test_resume_from_prepared_manifest_preserves_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "prepared"
    service = _runner(clock, work)

    async def crash_after_prepare(
        workspace: ResearchRunWorkspace, manifest: dict[str, object]
    ) -> dict[str, object]:
        del workspace, manifest
        raise ResearchRunnerError("simulated crash after prepare")

    monkeypatch.setattr(service, "_collect", crash_after_prepare)
    with pytest.raises(ResearchRunnerError, match="simulated crash after prepare"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="prep-run")
        )
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "PREPARED"
    assert manifest["clocks"]["t0"] is None
    monkeypatch.undo()
    resumed = asyncio.run(
        service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="prep-run")
    )
    again = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert resumed["phase"] == "CLOSED"
    assert again["run_id"] == "prep-run"
    assert again["clocks"]["t0"] is not None


def test_canary_and_main_profile_bounds() -> None:
    assert CANARY_PROFILE.window_count == 2
    assert int(CANARY_PROFILE.duration.total_seconds()) == 1_200
    assert MAIN_PROFILE.window_count == 24
    assert int(MAIN_PROFILE.duration.total_seconds()) == 14_400
    assert MAIN_PROFILE.max_events == 750_000
    assert MAIN_PROFILE.max_bytes == 805_306_368
    assert MAIN_PROFILE.duration <= timedelta(hours=4)


def test_runner_start_is_idempotent_and_preserves_t0(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "run"
    service = _runner(clock, work)
    first = asyncio.run(
        service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="lab-run")
    )
    t0 = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))["clocks"]["t0"]
    second = asyncio.run(
        service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="lab-run")
    )
    third = service.result(work)
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert first["phase"] == "CLOSED"
    assert second["phase"] == "CLOSED"
    assert third["run_id"] == "lab-run"
    assert manifest["clocks"]["t0"] == t0
    assert first["trading_mode"] == TradingMode.DATA_ONLY.value
    assert first["live_trading_enabled"] is False
    assert (work / "receipts" / "receipts.json").is_file()
    assert manifest["outcome"]["economic"] is not None
    assert manifest["outcome"]["evidence"] is not None
    assert manifest["phase"] == "CLOSED"
    encoded = json.dumps(first, sort_keys=True)
    assert len(encoded.encode()) < 5120


def test_duplicate_start_rejects_second_runner(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "dup"
    service = _runner(clock, work)
    asyncio.run(service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="dup-run"))
    lock = ResearchRunWorkspace(work).lock()
    lock.acquire()
    try:
        with pytest.raises(ResearchRunnerConflictError):
            asyncio.run(
                service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="dup-run")
            )
    finally:
        lock.release()


def test_resume_rejects_identity_and_hash_mismatch(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "bad"
    service = _runner(clock, work)
    asyncio.run(service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="id-run"))
    with pytest.raises(ResearchRunnerError, match="code SHA"):
        asyncio.run(
            service.resume(work, profile=LAB_PROFILE, code_sha="b" * 40, run_id="id-run")
        )
    manifest_path = work / "run-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"]["database_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ResearchRunnerError, match="hash mismatch"):
        asyncio.run(
            service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="id-run")
        )


def test_stop_during_open_interval_and_crash_resume(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "stop"
    long_profile = RunnerProfile(
        name="lab",
        version="lab-v1",
        window=timedelta(seconds=8),
        window_count=2,
        warmup=timedelta(0),
        max_events=10_000,
        max_bytes=10_000_000,
        memory_bytes=8_388_608,
    )
    service = _runner(clock, work)

    async def run_and_stop() -> dict[str, object]:
        task = asyncio.create_task(
            service.start(work, profile=long_profile, code_sha=CODE_SHA, run_id="stop-run")
        )
        for _ in range(200):
            if (work / "run-manifest.json").is_file():
                phase = json.loads(
                    (work / "run-manifest.json").read_text(encoding="utf-8")
                ).get("phase")
                if phase == "COLLECTING":
                    service.request_stop(work, reason="operator_stop")
                    break
            await asyncio.sleep(0)
        return await task

    payload = asyncio.run(run_and_stop())
    store = ResearchEvidenceStore(work / "research-evidence.sqlite3", read_only=True)
    intervals = store.load_intervals_for_run("stop-run")
    assert payload["phase"] == "CLOSED"
    assert any(interval.validity.value != "VALID" for interval in intervals) or intervals == ()
    outcome = payload["outcome"]
    assert isinstance(outcome, dict)
    assert outcome.get("stop_reason") == "operator_stop"
    second = asyncio.run(
        service.start(work, profile=long_profile, code_sha=CODE_SHA, run_id="stop-run")
    )
    assert second["phase"] == "CLOSED"


def test_prepare_then_resume_from_collected_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "crash"
    service = _runner(clock, work)

    async def crash_after_collect(
        workspace: ResearchRunWorkspace, manifest: dict[str, object]
    ) -> dict[str, object]:
        del workspace, manifest
        raise ResearchRunnerError("simulated crash after collect")

    monkeypatch.setattr(service, "_verify_and_close", crash_after_collect)
    with pytest.raises(ResearchRunnerError, match="simulated crash after collect"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="crash-run")
        )
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    t0 = manifest["clocks"]["t0"]
    assert manifest["phase"] == "COLLECTED"
    monkeypatch.undo()
    resumed = asyncio.run(
        service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="crash-run")
    )
    again = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert resumed["phase"] == "CLOSED"
    assert again["clocks"]["t0"] == t0
    verified = asyncio.run(service.verify(work))
    result = service.result(work)
    assert verified["run_id"] == result["run_id"] == "crash-run"


def test_resume_reuses_published_bundle_after_interrupted_close(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "published"
    service = _runner(clock, work)
    closed = asyncio.run(
        service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="pub-run")
    )
    assert closed["phase"] == "CLOSED"
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    t0 = manifest["clocks"]["t0"]
    bundle_sha = manifest["artifacts"]["bundle_sha256"]
    collected = manifest["artifacts"]["collected_database_sha256"]
    manifest["phase"] = "VERIFYING"
    manifest["artifacts"]["bundle"] = None
    manifest["artifacts"]["bundle_sha256"] = None
    manifest["artifacts"]["database_sha256"] = collected
    (work / "run-manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    resumed = asyncio.run(
        service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="pub-run")
    )
    again = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert resumed["phase"] == "CLOSED"
    assert again["clocks"]["t0"] == t0
    assert again["artifacts"]["bundle_sha256"] == bundle_sha
    assert again["phase"] == "CLOSED"


def test_second_writer_rejected_for_database(tmp_path: Path) -> None:
    database = tmp_path / "research-evidence.sqlite3"
    store = ResearchEvidenceStore(database)
    store.initialize()
    store.acquire_writer()
    try:
        other = ResearchEvidenceStore(database)
        with pytest.raises(Exception, match="second writer"):
            other.acquire_writer()
    finally:
        store.release_writer()


def test_cli_status_is_read_only(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "cli"
    service = _runner(clock, work)
    asyncio.run(service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="cli-run"))
    before = (work / "run-manifest.json").read_bytes()
    result = runner.invoke(
        app,
        ["research", "prospective-run", "status", "--state-root", str(work)],
    )
    assert result.exit_code == 0
    assert (work / "run-manifest.json").read_bytes() == before
    payload = json.loads(result.stdout)
    assert payload["phase"] == "CLOSED"
    assert payload["trading_mode"] == "DATA_ONLY"
    assert len(result.stdout.encode()) < 5120


def test_live_settings_fail_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    clock = CoordinatedClock()
    factory, _transport = lab_source_factory(clock)
    service = ResearchExperimentRunner(
        source_factory=factory,
        clock=clock,
        sleep=clock.sleep,
        settings_factory=AppSettings,
    )
    with pytest.raises(ResearchRunnerError, match="LIVE_TRADING_ENABLED"):
        asyncio.run(service.start(tmp_path / "live", profile=LAB_PROFILE, code_sha=CODE_SHA))
