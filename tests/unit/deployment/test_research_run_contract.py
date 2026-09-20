from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from polysia.deployment.research_experiment_runner import (
    ADMISSION_LOCK_ENV,
    HOST_ADMISSION_LOCK,
    ResearchExperimentRunner,
    ResearchRunnerError,
    ResearchRunWorkspace,
    _read_manifest,
    _write_manifest,
    resolve_admission_lock_path,
)
from polysia.deployment.research_run_commands import DISPOSITION_ACCEPTED
from polysia.deployment.research_run_contract import (
    DEFAULT_SELECTION_POLICY,
    DEFAULT_WALLET_COUNT,
    ResearchRunContractError,
    ResearchRunPlan,
    parse_research_run_spec,
    plans_semantically_equal,
    resolve_run_plan,
)
from polysia.deployment.research_scratch import operation_scratch, planned_scratch_bytes

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
CODE_SHA = "a" * 40


def test_spec_rejects_unknown_fields_and_executable_expressions() -> None:
    with pytest.raises(ResearchRunContractError, match="unsupported"):
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "wallet_count": 10,
            }
        )
    with pytest.raises(ResearchRunContractError, match="executable"):
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": "${__import__('os').system('x')}",
            }
        )


def test_identical_inputs_resolve_to_equivalent_semantic_plans() -> None:
    spec = parse_research_run_spec(
        {
            "spec_version": "research-run-spec-v1",
            "profile": "canary",
            "code_sha": CODE_SHA,
            "run_id": "first",
        }
    )
    left = resolve_run_plan(spec, observed=NOW)
    right = resolve_run_plan(
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "run_id": "second",
            }
        ),
        observed=NOW.replace(minute=1),
    )
    assert plans_semantically_equal(left, right)
    assert left.run_id != right.run_id
    assert left.selection["policy"] == DEFAULT_SELECTION_POLICY
    assert left.selection["wallet_count"] == DEFAULT_WALLET_COUNT
    assert left.safety["trading_mode"] == "DATA_ONLY"
    assert left.safety["overridable"] is False
    assert left.economic_contract["entry_budget"] == "5"


def test_canary_and_main_budgets_stay_on_declared_profiles() -> None:
    canary = resolve_run_plan(
        parse_research_run_spec(
            {"spec_version": "research-run-spec-v1", "profile": "canary", "code_sha": CODE_SHA}
        ),
        observed=NOW,
    )
    main = resolve_run_plan(
        parse_research_run_spec(
            {"spec_version": "research-run-spec-v1", "profile": "main", "code_sha": CODE_SHA}
        ),
        observed=NOW,
    )
    assert canary.budgets["window_count"] == 2
    assert main.budgets["window_count"] == 24
    assert main.budgets["max_bytes"] > canary.budgets["max_bytes"]


def test_stop_does_not_overwrite_manifest(tmp_path: Path) -> None:
    work = tmp_path / "run"
    work.mkdir()
    manifest = {
        "phase": "COLLECTING",
        "revision": 3,
        "run_id": "lock-run",
        "receipts": [],
        "outcome": {"lifecycle": "COLLECTING"},
        "clocks": {},
        "artifacts": {},
        "code_sha": CODE_SHA,
        "profile": "lab",
        "trading_mode": "DATA_ONLY",
        "live_trading_enabled": False,
    }
    _write_manifest(work / "run-manifest.json", manifest)
    before = _read_manifest(work / "run-manifest.json")

    class _Clock:
        def __call__(self) -> datetime:
            return NOW

    runner = ResearchExperimentRunner(
        source_factory=lambda: None,  # type: ignore[arg-type]
        clock=_Clock(),
    )
    payload = runner.request_stop(work, reason="operator_stop", command_id="stop-1")
    after = _read_manifest(work / "run-manifest.json")
    assert after["phase"] == "COLLECTING"
    assert after["revision"] == before["revision"]
    assert after.get("receipts") == before.get("receipts")
    assert payload["stop_requested"] is True
    assert payload["stop_command"]["disposition"] == DISPOSITION_ACCEPTED
    again = runner.request_stop(work, reason="operator_stop", command_id="stop-1")
    assert again["stop_command"]["disposition"] == DISPOSITION_ACCEPTED
    with pytest.raises(ResearchRunnerError, match="different research-run content"):
        runner.request_stop(work, reason="other", command_id="stop-1")
    with pytest.raises(ResearchRunnerError, match="stale"):
        runner.request_stop(
            work, reason="operator_stop", command_id="stop-2", expected_revision=0
        )


def test_concurrent_stop_cannot_regress_collected_phase(tmp_path: Path) -> None:
    work = tmp_path / "race"
    work.mkdir()
    manifest = {
        "phase": "COLLECTING",
        "revision": 1,
        "run_id": "race-run",
        "receipts": [],
        "outcome": {"lifecycle": "COLLECTING"},
        "clocks": {},
        "artifacts": {},
        "code_sha": CODE_SHA,
        "profile": "lab",
        "trading_mode": "DATA_ONLY",
        "live_trading_enabled": False,
    }
    _write_manifest(work / "run-manifest.json", manifest)
    runner = ResearchExperimentRunner(source_factory=lambda: None)  # type: ignore[arg-type]
    barrier = threading.Barrier(2)

    def worker() -> None:
        payload = _read_manifest(work / "run-manifest.json")
        payload["phase"] = "COLLECTED"
        payload["outcome"] = {"lifecycle": "COLLECTED"}
        barrier.wait()
        time.sleep(0.05)
        _write_manifest(work / "run-manifest.json", payload)

    def stopper() -> None:
        barrier.wait()
        runner.request_stop(work, reason="operator_stop")

    first = threading.Thread(target=worker)
    second = threading.Thread(target=stopper)
    first.start()
    second.start()
    first.join()
    second.join()
    final = _read_manifest(work / "run-manifest.json")
    assert final["phase"] == "COLLECTED"
    assert (work / "stop-request.json").is_file()


def test_operation_scratch_stays_off_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path / "forbidden-tmp"))
    monkeypatch.setenv("TEMP", str(tmp_path / "forbidden-tmp"))
    monkeypatch.setenv("TMP", str(tmp_path / "forbidden-tmp"))
    parent = tmp_path / "owned"
    parent.mkdir()
    sample = parent / "db"
    sample.write_bytes(b"x" * 32)
    with operation_scratch(
        parent,
        prefix="polysia-research-op-",
        needed_bytes=planned_scratch_bytes(sample, copies=4),
    ) as scratch:
        assert scratch.is_relative_to(parent)
        assert "forbidden-tmp" not in str(scratch)


def _sample_plan() -> ResearchRunPlan:
    return resolve_run_plan(
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "run_id": "plan-run",
            }
        ),
        observed=NOW,
    )


def test_admission_lock_default_ignores_workspace_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ADMISSION_LOCK_ENV, raising=False)
    runner = ResearchExperimentRunner(source_factory=lambda: None)  # type: ignore[arg-type]
    left = runner._admission_lock(tmp_path / "alpha" / "run")
    right = runner._admission_lock(tmp_path / "beta" / "run")
    expected = HOST_ADMISSION_LOCK.with_name(f"{HOST_ADMISSION_LOCK.name}.lock")
    assert left.path == right.path == expected
    assert resolve_admission_lock_path() == HOST_ADMISSION_LOCK
    assert resolve_admission_lock_path(
        environment={},
    ) == HOST_ADMISSION_LOCK


def test_admission_lock_env_override_is_shared_across_parents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom-admission"
    monkeypatch.setenv(ADMISSION_LOCK_ENV, str(override))
    runner = ResearchExperimentRunner(source_factory=lambda: None)  # type: ignore[arg-type]
    left = runner._admission_lock(tmp_path / "alpha" / "run")
    right = runner._admission_lock(tmp_path / "beta" / "run")
    expected = override.with_name(f"{override.name}.lock")
    assert left.path == right.path == expected


def test_admission_lock_constructor_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ADMISSION_LOCK_ENV, str(tmp_path / "from-env"))
    configured = tmp_path / "from-constructor"
    runner = ResearchExperimentRunner(
        source_factory=lambda: None,  # type: ignore[arg-type]
        admission_lock_path=configured,
    )
    lock = runner._admission_lock(tmp_path / "workspace")
    assert lock.path == configured.with_name(f"{configured.name}.lock")


def test_freeze_plan_fails_closed_when_digest_exists_and_file_is_missing(
    tmp_path: Path,
) -> None:
    plan = _sample_plan()
    workspace = ResearchRunWorkspace(tmp_path / "run")
    workspace.root.mkdir()
    runner = ResearchExperimentRunner(source_factory=lambda: None)  # type: ignore[arg-type]
    existing: dict[str, object] = {
        "run_plan_digest": plan.semantic_digest(),
        "clocks": {"t0": "already-started"},
        "budgets": {},
        "followed_wallet_selection": {},
    }
    with pytest.raises(ResearchRunnerError, match="Plan is missing"):
        runner._freeze_plan(workspace, plan, existing=existing)
    assert not workspace.plan_path.is_file()


def test_freeze_plan_writes_additively_for_legacy_manifest_without_digest(
    tmp_path: Path,
) -> None:
    plan = _sample_plan()
    workspace = ResearchRunWorkspace(tmp_path / "run")
    workspace.root.mkdir()
    runner = ResearchExperimentRunner(source_factory=lambda: None)  # type: ignore[arg-type]
    existing: dict[str, object] = {
        "clocks": {"t0": "already-started"},
        "budgets": {},
        "followed_wallet_selection": {},
    }
    runner._freeze_plan(workspace, plan, existing=existing)
    assert workspace.plan_path.is_file()
    assert existing["run_plan_digest"] == plan.semantic_digest()
