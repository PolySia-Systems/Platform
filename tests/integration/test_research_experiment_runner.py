from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.backtesting.offline_research_lab import (
    CODE_SHA,
    WALLET_A,
    WALLET_B,
    CoordinatedClock,
    lab_source_factory,
)
from polysia.cli import app
from polysia.config.settings import AppSettings, TradingMode
from polysia.deployment.research_experiment_runner import (
    ADMISSION_LOCK_ENV,
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


@pytest.fixture(autouse=True)
def isolate_research_admission_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ADMISSION_LOCK_ENV, str(tmp_path / "research-runner-admission"))


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
    assert MAIN_PROFILE.memory_bytes == 2 * 1024 * 1024 * 1024
    assert CANARY_PROFILE.memory_bytes == 2 * 1024 * 1024 * 1024
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


def _two_wallet_snapshot() -> ContinuousSelectionSnapshot:
    published = datetime(2026, 1, 1, tzinfo=UTC)
    return ContinuousSelectionSnapshot.create(
        source_id="polycop",
        selection_run_id="selection-run-lab",
        source_snapshot_id="source-snap-lab",
        feature_set_version="features-v1",
        policy_id="copyability-v1",
        policy_version="policy-v1",
        ranking_version="ranking-v1",
        published_at=published,
        candidates=(
            ProtectedShadowCandidate(
                wallet_id="wallet-b",
                address=WALLET_B,
                pools=("SHADOW_ALPHA",),
                alpha_rank=1,
            ),
            ProtectedShadowCandidate(
                wallet_id="wallet-a",
                address=WALLET_A,
                pools=("SHADOW_ALPHA",),
                alpha_rank=2,
            ),
        ),
    )


def _polycop_lab_runner(clock: CoordinatedClock) -> ResearchExperimentRunner:
    from datetime import UTC, datetime

    from polysia.deployment.research_wallet_selection import (
        public_selection_payload,
        reconstruction_payload,
        resolve_polycop_shadow_alpha_top3,
    )

    factory, _transport = lab_source_factory(clock)
    selection = resolve_polycop_shadow_alpha_top3(
        _two_wallet_snapshot(),
        now=datetime(2026, 1, 1, 1, tzinfo=UTC),
        wallet_limit=2,
    )
    factory_calls = {"count": 0}

    async def source_factory() -> tuple[tuple[object, ...], dict[str, object]]:
        factory_calls["count"] += 1
        sources, discovery = await factory()
        discovery.update(public_selection_payload(selection))
        discovery["_reconstruction"] = reconstruction_payload(selection)
        discovery["followed_aliases"] = list(selection.aliases)
        return sources, discovery

    async def rebuilder(aliases: dict[str, str]) -> tuple[tuple[object, ...], dict[str, object]]:
        sources, discovery = await factory()
        discovery["followed_aliases"] = sorted(aliases)
        return sources, discovery

    service = ResearchExperimentRunner(
        source_factory=source_factory,
        source_rebuilder=rebuilder,
        clock=clock,
        sleep=clock.sleep,
        settings_factory=AppSettings,
    )
    service._factory_calls = factory_calls  # type: ignore[attr-defined]
    service._selection = selection  # type: ignore[attr-defined]
    return service


def test_missing_polycop_selection_fails_before_t0(tmp_path: Path) -> None:
    from polysia.deployment.research_wallet_selection import ResearchWalletSelectionError

    clock = CoordinatedClock()

    async def failing_factory() -> tuple[tuple[object, ...], dict[str, object]]:
        raise ResearchWalletSelectionError("current Polycop selection is unavailable")

    service = ResearchExperimentRunner(
        source_factory=failing_factory,
        clock=clock,
        sleep=clock.sleep,
        settings_factory=AppSettings,
    )
    work = tmp_path / "missing-selection"
    with pytest.raises(ResearchRunnerError, match="unavailable"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="missing-run")
        )
    assert not (work / "run-manifest.json").is_file()
    assert not (work / "selection-reconstruction.json").is_file()


def test_polycop_resume_keeps_frozen_selection_and_t0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import re

    clock = CoordinatedClock()
    work = tmp_path / "polycop-freeze"
    service = _polycop_lab_runner(clock)

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
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="polycop-run")
        )
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    frozen = manifest["followed_wallet_selection"]
    assert frozen["selection_policy"] == "polycop-shadow-alpha-top3-v1"
    assert frozen["selection_run_id"] == "selection-run-lab"
    assert (work / "selection-reconstruction.json").is_file()
    monkeypatch.undo()

    async def changed_factory() -> tuple[tuple[object, ...], dict[str, object]]:
        raise AssertionError("resume must not resolve a new Polycop snapshot")

    service._source_factory = changed_factory
    payload = asyncio.run(
        service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="polycop-run")
    )
    resumed = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert resumed["followed_wallet_selection"] == frozen
    assert resumed["clocks"]["t0"] is not None
    assert payload["phase"] == "CLOSED"
    assert payload["trading_mode"] == TradingMode.DATA_ONLY.value
    assert payload["live_trading_enabled"] is False
    encoded = json.dumps(payload, sort_keys=True)
    assert re.search(r"0x[a-fA-F0-9]{40}", encoded) is None
    assert WALLET_A not in encoded
    assert WALLET_B not in encoded
    store = ResearchEvidenceStore(work / "research-evidence.sqlite3", read_only=True)
    events = list(store.iter_events(run_id=str(resumed["run_id"])))
    aliases = set(frozen["aliases"])
    attributed = [event for event in events if event.leader_alias in aliases]
    assert attributed
    assert all(event.leader_alias in aliases for event in attributed)


def test_polycop_reconstruction_tampering_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "polycop-tamper"
    service = _polycop_lab_runner(clock)

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
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="tamper-run")
        )
    path = work / "selection-reconstruction.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["digest"] = "0" * 64
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.undo()
    with pytest.raises(ResearchRunnerError, match="reconstruction digest"):
        asyncio.run(
            service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="tamper-run")
        )


def test_admission_rejects_a_second_resource_consuming_workspace_across_parents(
    tmp_path: Path,
) -> None:
    from polysia.storage.research_evidence import ExclusiveWriterLock

    lock_path = tmp_path / "research-runner-admission"
    held = ExclusiveWriterLock(
        lock_path,
        rejected_message="second resource-consuming research run rejected",
    )
    held.acquire()
    try:
        clock = CoordinatedClock()
        factory, _transport = lab_source_factory(clock)
        service = ResearchExperimentRunner(
            source_factory=factory,
            clock=clock,
            sleep=clock.sleep,
            settings_factory=AppSettings,
        )
        with pytest.raises(ResearchRunnerConflictError, match="second resource-consuming"):
            asyncio.run(
                service.start(
                    tmp_path / "alpha-host" / "workspace",
                    profile=LAB_PROFILE,
                    code_sha=CODE_SHA,
                    run_id="admit-run-a",
                )
            )
        with pytest.raises(ResearchRunnerConflictError, match="second resource-consuming"):
            asyncio.run(
                service.start(
                    tmp_path / "beta-host" / "workspace",
                    profile=LAB_PROFILE,
                    code_sha=CODE_SHA,
                    run_id="admit-run-b",
                )
            )
    finally:
        held.release()


def test_resume_without_plan_file_fails_closed_when_digest_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "missing-plan"
    service = _runner(clock, work)

    async def crash_after_prepare(
        workspace: ResearchRunWorkspace, manifest: dict[str, object], **_kwargs: object
    ) -> dict[str, object]:
        del workspace, manifest
        raise ResearchRunnerError("simulated crash after prepare")

    monkeypatch.setattr(service, "_collect", crash_after_prepare)
    with pytest.raises(ResearchRunnerError, match="simulated crash after prepare"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="missing-plan-run")
        )
    manifest = json.loads((work / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("run_plan_digest")
    (work / "run-plan.json").unlink()
    monkeypatch.undo()
    with pytest.raises(ResearchRunnerError, match="Plan is missing"):
        asyncio.run(
            service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="missing-plan-run")
        )
    assert not (work / "run-plan.json").is_file()


def test_resume_writes_plan_additively_for_legacy_manifest_without_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = CoordinatedClock()
    work = tmp_path / "legacy-plan"
    service = _runner(clock, work)

    async def crash_after_prepare(
        workspace: ResearchRunWorkspace, manifest: dict[str, object], **_kwargs: object
    ) -> dict[str, object]:
        del workspace, manifest
        raise ResearchRunnerError("simulated crash after prepare")

    monkeypatch.setattr(service, "_collect", crash_after_prepare)
    with pytest.raises(ResearchRunnerError, match="simulated crash after prepare"):
        asyncio.run(
            service.start(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="legacy-plan-run")
        )
    (work / "run-plan.json").unlink()
    manifest_path = work / "run-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    del payload["run_plan_digest"]
    manifest_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.undo()
    resumed = asyncio.run(
        service.resume(work, profile=LAB_PROFILE, code_sha=CODE_SHA, run_id="legacy-plan-run")
    )
    assert resumed["phase"] == "CLOSED"
    assert (work / "run-plan.json").is_file()
    closed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert closed.get("run_plan_digest")
