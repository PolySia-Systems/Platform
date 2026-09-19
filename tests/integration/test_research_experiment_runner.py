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
        workspace: ResearchRunWorkspace,
        manifest: dict[str, object],
        **_kwargs: object,
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
    assert MAIN_PROFILE.memory_bytes == 512 * 1024 * 1024
    assert CANARY_PROFILE.memory_bytes == 512 * 1024 * 1024
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


def test_fresh_start_discovers_sources_once(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    factory, _transport = lab_source_factory(clock)
    calls = 0

    async def counted_factory():
        nonlocal calls
        calls += 1
        return await factory()

    service = ResearchExperimentRunner(
        source_factory=counted_factory,
        clock=clock,
        sleep=clock.sleep,
        settings_factory=AppSettings,
    )
    payload = asyncio.run(
        service.start(
            tmp_path / "single-discovery",
            profile=LAB_PROFILE,
            code_sha=CODE_SHA,
            run_id="single-discovery-run",
        )
    )

    assert payload["phase"] == "CLOSED"
    assert calls == 1


def test_resume_rejects_changed_prepared_source_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "selection"
    service = _runner(clock, work)

    async def crash_after_prepare(
        workspace: ResearchRunWorkspace, manifest: dict[str, object], **_kwargs: object
    ) -> dict[str, object]:
        del workspace, manifest
        raise ResearchRunnerError("simulated crash after prepare")

    monkeypatch.setattr(service, "_collect", crash_after_prepare)
    with pytest.raises(ResearchRunnerError, match="simulated crash after prepare"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="selection-run")
        )
    monkeypatch.undo()

    original_factory = service._source_factory

    async def changed_factory():
        sources, discovery = await original_factory()
        changed = dict(discovery)
        changed["followed_aliases"] = ["changed-wallet"]
        return sources, changed

    service._source_factory = changed_factory
    with pytest.raises(ResearchRunnerError, match="source selection mismatch"):
        asyncio.run(
            service.resume(
                work,
                profile=LAB_PROFILE,
                code_sha=CODE_SHA,
                run_id="selection-run",
            )
        )


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
    newer = asyncio.run(
        service.resume(work, profile=LAB_PROFILE, code_sha="b" * 40, run_id="id-run")
    )
    assert newer["phase"] == "CLOSED"
    manifest_path = work / "run-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["code_sha"] == CODE_SHA
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
        workspace: ResearchRunWorkspace,
        manifest: dict[str, object],
        **_: object,
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
    analysis_sha = "b" * 40
    resumed = asyncio.run(
        service.resume(
            work, profile=LAB_PROFILE, code_sha=analysis_sha, run_id="crash-run"
        )
    )
    again = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert resumed["phase"] == "CLOSED"
    assert again["clocks"]["t0"] == t0
    assert again["code_sha"] == CODE_SHA
    assert again["finalization_code_sha"] == analysis_sha
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


def test_runner_does_not_replay_after_authoritative_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from polysia.backtesting import prospective_replay

    prospective_replay.REPLAY_CALLS.clear()
    clock = CoordinatedClock()
    work = tmp_path / "once"
    service = _runner(clock, work)
    asyncio.run(service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="once-run"))
    assert prospective_replay.REPLAY_CALLS.count("once-run") == 3
    asyncio.run(service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="once-run"))
    assert prospective_replay.REPLAY_CALLS.count("once-run") == 3
    asyncio.run(service.verify(work))
    service.result(work)
    assert prospective_replay.REPLAY_CALLS.count("once-run") == 3


def test_prepared_resume_rejects_collection_sha_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "prep-sha"
    service = _runner(clock, work)

    async def crash_after_prepare(
        workspace: ResearchRunWorkspace,
        manifest: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        del workspace, manifest
        raise ResearchRunnerError("simulated crash after prepare")

    monkeypatch.setattr(service, "_collect", crash_after_prepare)
    with pytest.raises(ResearchRunnerError, match="simulated crash after prepare"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="prep-sha")
        )
    with pytest.raises(ResearchRunnerError, match="code SHA"):
        asyncio.run(
            service.resume(work, profile=LAB_PROFILE, code_sha="b" * 40, run_id="prep-sha")
        )


def test_verifying_oom_shape_resumes_from_collected_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "oom"
    service = _runner(clock, work)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise MemoryError("simulated verifying OOM")

    monkeypatch.setattr(
        "polysia.deployment.research_experiment_runner.finalize_research_experiment",
        boom,
    )
    with pytest.raises(MemoryError, match="simulated verifying OOM"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="oom-run")
        )
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    t0 = manifest["clocks"]["t0"]
    collected = manifest["artifacts"]["collected_database_sha256"]
    assert manifest["phase"] == "VERIFYING"
    assert collected
    monkeypatch.undo()
    analysis_sha = "c" * 40
    resumed = asyncio.run(
        service.resume(work, profile=LAB_PROFILE, code_sha=analysis_sha, run_id="oom-run")
    )
    again = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert resumed["phase"] == "CLOSED"
    assert again["clocks"]["t0"] == t0
    assert again["code_sha"] == CODE_SHA
    assert again["finalization_code_sha"] == analysis_sha
    assert again["artifacts"]["collected_database_sha256"] == collected


def test_corrupted_published_bundle_fails_closed(tmp_path: Path) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "corrupt"
    service = _runner(clock, work)
    asyncio.run(service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="corrupt-run"))
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    bundle = Path(str(manifest["artifacts"]["bundle"]))
    database = bundle / "research-evidence.sqlite3"
    database.write_bytes(database.read_bytes() + b"tamper")
    with pytest.raises(ResearchRunnerError, match="hash mismatch"):
        asyncio.run(
            service.resume(
                work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="corrupt-run"
            )
        )


def test_collected_database_hash_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "hash"
    service = _runner(clock, work)

    async def crash_after_collect(
        workspace: ResearchRunWorkspace,
        manifest: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        del workspace, manifest
        raise ResearchRunnerError("simulated crash after collect")

    monkeypatch.setattr(service, "_verify_and_close", crash_after_collect)
    with pytest.raises(ResearchRunnerError, match="simulated crash after collect"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="hash-run")
        )
    database = work / "research-evidence.sqlite3"
    database.write_bytes(database.read_bytes() + b"tamper")
    monkeypatch.undo()
    with pytest.raises(ResearchRunnerError, match="hash mismatch"):
        asyncio.run(
            service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="hash-run")
        )


def test_preflight_rejects_cgroup_below_profile_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "polysia.deployment.research_experiment_runner._cgroup_memory_limit_bytes",
        lambda: 1024,
    )
    clock = CoordinatedClock()
    factory, _transport = lab_source_factory(clock)
    service = ResearchExperimentRunner(
        source_factory=factory,
        clock=clock,
        sleep=clock.sleep,
        settings_factory=AppSettings,
    )
    with pytest.raises(ResearchRunnerError, match="insufficient memory"):
        asyncio.run(
            service.start(tmp_path / "low-mem", profile=LAB_PROFILE, code_sha=CODE_SHA)
        )
