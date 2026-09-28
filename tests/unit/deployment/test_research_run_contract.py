from __future__ import annotations

import asyncio
import hashlib
import json
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
    selection_source_kwargs,
    source_factory_accepts_selection,
)
from polysia.deployment.research_run_commands import DISPOSITION_ACCEPTED
from polysia.deployment.research_run_contract import (
    ACTIVE_SELECTION_POLICY,
    ACTIVE_SELECTION_POLICY_V2,
    CAPACITY_PLAN_VERSION,
    CAPACITY_SPEC_VERSION,
    CONFIGURED_SELECTION_POLICY,
    DEFAULT_SELECTION_POLICY,
    DEFAULT_WALLET_COUNT,
    RANKED_SELECTION_POLICY_V2,
    ResearchRunContractError,
    ResearchRunPlan,
    ResearchRunSpec,
    load_run_plan,
    parse_research_run_spec,
    plans_semantically_equal,
    resolve_run_plan,
)
from polysia.deployment.research_run_profiles import CANARY_PROFILE
from polysia.deployment.research_scratch import operation_scratch, planned_scratch_bytes
from polysia.domain.copytrading.wallet_capacity import workload_digest

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
CODE_SHA = "a" * 40


@pytest.mark.parametrize("wallet_count", [5, 10, 20, 40])
def test_v3_plan_distinguishes_software_from_operational_capacity(wallet_count: int) -> None:
    spec = parse_research_run_spec({
        "spec_version": CAPACITY_SPEC_VERSION,
        "profile": "canary", "code_sha": CODE_SHA,
        "wallet_count": wallet_count,
        "selection_policy": ACTIVE_SELECTION_POLICY_V2,
        "runtime": {},
    })
    plan = resolve_run_plan(spec, observed=NOW)
    assert plan.plan_version == CAPACITY_PLAN_VERSION
    assert plan.selection["wallet_count"] == wallet_count
    assert plan.selection["capacity"]["software_limit"] == 40
    assert plan.selection["capacity"]["operational_status"] == "unverified"
    assert load_run_plan(plan.to_dict()).semantic_digest() == plan.semantic_digest()
    assert plan.selection["workload_digest"] == workload_digest(
        "canary", {**(plan.runtime or {}), "selection_policy": ACTIVE_SELECTION_POLICY_V2}
    )


def test_v3_rejects_count_outside_software_envelope() -> None:
    with pytest.raises(ResearchRunContractError, match="software envelope"):
        parse_research_run_spec({
            "spec_version": CAPACITY_SPEC_VERSION,
            "profile": "canary", "code_sha": CODE_SHA,
            "wallet_count": 41, "runtime": {},
        })


def test_runner_preserves_measured_capacity_spec_before_source_admission() -> None:
    from polysia.domain.copytrading.wallet_capacity import CAPACITY_CONTRACT_VERSION

    runtime = resolve_run_plan(ResearchRunSpec(
        profile="canary", code_sha=CODE_SHA,
        spec_version=CAPACITY_SPEC_VERSION, runtime={}, wallet_count=10,
    ), observed=NOW).runtime
    assert runtime is not None
    evidence: dict[str, object] = {
        "version": CAPACITY_CONTRACT_VERSION,
        "code_sha": CODE_SHA,
        "workload_digest": workload_digest(
            "canary", {**runtime, "selection_policy": RANKED_SELECTION_POLICY_V2}
        ),
        "validated_count": 10,
        "result": "PASS",
        "polls_observed": 3,
        "max_queue_delay_ms": 1,
        "p95_decision_latency_ms": 1,
        "peak_memory_bytes": 1024,
        "storage_growth_bytes": 1024,
        "other_consumer_requests": 1,
        "data_requests": 40,
        "clob_requests": 2,
        "gamma_requests": 2,
        "rate_limited_requests": 0,
        "probe_scope": "RESEARCH_FULL_PATH", "nonempty_event_count": 3,
        "writer_poll_count": 3, "book_requests": 2, "fee_requests": 2,
        "host_peak_memory_bytes": 2048, "ledger_balanced": True,
        "shared_ip_observed": True,
    }
    evidence["digest"] = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    runner = ResearchExperimentRunner(source_factory=lambda: None)  # type: ignore[arg-type]
    plan = runner._resolve_plan(
        profile="canary", resolved_profile=CANARY_PROFILE,
        code_sha=CODE_SHA, run_id=None, image_sha=None,
        spec={
            "spec_version": CAPACITY_SPEC_VERSION, "profile": "canary",
            "code_sha": CODE_SHA, "wallet_count": 10, "runtime": {},
            "capacity_evidence": evidence,
        },
    )
    assert plan.selection["capacity"]["operational_status"] == "measured"
    assert plan.selection["capacity"]["validated_count"] == 10


def test_spec_rejects_unknown_fields_and_executable_expressions() -> None:
    with pytest.raises(ResearchRunContractError, match="unsupported"):
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "extra_field": 10,
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


@pytest.mark.parametrize("wallet_count", [1, 3])
def test_v2_runtime_is_frozen_with_supported_wallet_counts(wallet_count: int) -> None:
    spec = parse_research_run_spec({
        "spec_version": "research-run-spec-v2",
        "profile": "canary",
        "code_sha": CODE_SHA,
        "wallet_count": wallet_count,
        "runtime": {
            "source_mode": "per-wallet-v2",
            "poll_interval_seconds": 3,
            "max_pages": 12,
            "max_requests": 12,
            "overlap_seconds": 60,
        },
    })
    plan = resolve_run_plan(spec, observed=NOW)
    assert plan.plan_version == "research-run-plan-v2"
    assert plan.runtime is not None
    assert plan.runtime["overlap_seconds"] == 60
    assert selection_source_kwargs(plan)["runtime"] == plan.runtime
    assert load_run_plan(plan.to_dict()).semantic_digest() == plan.semantic_digest()
    changed = resolve_run_plan(
        ResearchRunSpec(
            profile="canary", code_sha=CODE_SHA, wallet_count=wallet_count,
            spec_version="research-run-spec-v2",
            runtime={"overlap_seconds": 90},
        ),
        observed=NOW,
    )
    assert not plans_semantically_equal(plan, changed)


@pytest.mark.parametrize("runtime", [
    {"source_mode": "global-v2"},
    {"max_pages": 21, "max_requests": 20},
    {"economic_policy_version": "unknown"},
    {"unused": 1},
])
def test_v2_runtime_rejects_unsupported_values(runtime: dict[str, object]) -> None:
    with pytest.raises(ResearchRunContractError):
        parse_research_run_spec({
            "spec_version": "research-run-spec-v2",
            "profile": "canary",
            "code_sha": CODE_SHA,
            "runtime": runtime,
        })


def test_spec_and_plan_require_immutable_git_shas() -> None:
    with pytest.raises(ResearchRunContractError, match="40-character Git SHA"):
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": "unknown",
            }
        )
    with pytest.raises(ResearchRunContractError, match="40-character Git SHA"):
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "image_sha": "local",
            }
        )
    with pytest.raises(ResearchRunContractError, match="40-character Git SHA"):
        resolve_run_plan(ResearchRunSpec(profile="canary", code_sha="unknown"), observed=NOW)
    payload = _sample_plan().to_dict()
    payload["code_sha"] = "unknown"
    with pytest.raises(ResearchRunContractError, match="40-character Git SHA"):
        load_run_plan(payload)
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


def test_explicit_wallet_count_uses_configured_policy_without_changing_top3_default() -> None:
    omitted = resolve_run_plan(
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
            }
        ),
        observed=NOW,
    )
    explicit_three = resolve_run_plan(
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "wallet_count": 3,
            }
        ),
        observed=NOW,
    )
    configured = resolve_run_plan(
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "wallet_count": 2,
            }
        ),
        observed=NOW,
    )
    assert omitted.selection["policy"] == DEFAULT_SELECTION_POLICY
    assert plans_semantically_equal(omitted, explicit_three)
    assert configured.selection["policy"] == CONFIGURED_SELECTION_POLICY
    assert configured.selection["wallet_count"] == 2
    assert configured.selection["capacity"]["operational_status"] == "unverified"
    assert omitted.selection["capacity"]["operational_status"] == "validated"
    with pytest.raises(ResearchRunContractError, match="operationally supported capacity"):
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "wallet_count": 10,
            }
        )


def test_activity_aware_policy_is_explicit_and_bounded_to_three_wallets() -> None:
    active = resolve_run_plan(
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "selection_policy": ACTIVE_SELECTION_POLICY,
            }
        ),
        observed=NOW,
    )

    assert active.selection["policy"] == ACTIVE_SELECTION_POLICY
    assert active.selection["reasons_policy"] == (
        "highest-recent-activity-within-shadow-alpha"
    )
    assert active.selection["activity_preflight"] == {
        "candidate_limit": 50,
        "lookback_seconds": 14_400,
        "minimum_event_count": 1,
        "source": "polymarket:data-api-v2:trades",
    }
    with pytest.raises(ResearchRunContractError, match="requires exactly three"):
        resolve_run_plan(
            parse_research_run_spec(
                {
                    "spec_version": "research-run-spec-v1",
                    "profile": "canary",
                    "code_sha": CODE_SHA,
                    "selection_policy": ACTIVE_SELECTION_POLICY,
                    "wallet_count": 2,
                }
            ),
            observed=NOW,
        )
    with pytest.raises(ResearchRunContractError, match="not supported"):
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "selection_policy": "pick-the-winner",
            }
        )


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


def _configured_plan() -> ResearchRunPlan:
    return resolve_run_plan(
        parse_research_run_spec(
            {
                "spec_version": "research-run-spec-v1",
                "profile": "canary",
                "code_sha": CODE_SHA,
                "run_id": "configured-run",
                "wallet_count": 2,
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


def test_open_sources_propagates_internal_typeerror_without_fallback() -> None:
    calls: list[tuple[object, object]] = []

    async def factory(
        *,
        wallet_count: int | None = None,
        selection_policy: str | None = None,
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        calls.append((wallet_count, selection_policy))
        raise TypeError("internal mapping failed")

    runner = ResearchExperimentRunner(source_factory=factory)
    with pytest.raises(TypeError, match="internal mapping failed"):
        asyncio.run(runner._open_sources(_configured_plan()))
    assert calls == [(2, CONFIGURED_SELECTION_POLICY)]


def test_open_sources_passes_frozen_v2_runtime_to_composition() -> None:
    seen: dict[str, object] = {}

    async def factory(
        *, wallet_count: int | None = None,
        selection_policy: str | None = None,
        runtime: dict[str, object] | None = None,
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        seen.update({"wallet_count": wallet_count, "selection_policy": selection_policy,
                     "runtime": runtime})
        return ((), {})

    plan = resolve_run_plan(ResearchRunSpec(
        profile="canary", code_sha=CODE_SHA, wallet_count=2,
        spec_version="research-run-spec-v2", runtime={"overlap_seconds": 90},
    ), observed=NOW)
    asyncio.run(ResearchExperimentRunner(source_factory=factory)._open_sources(plan))
    assert seen["wallet_count"] == 2
    assert seen["runtime"] == plan.runtime


def test_v2_runtime_rejects_factory_that_cannot_apply_it() -> None:
    async def factory(
        *, wallet_count: int | None = None, selection_policy: str | None = None,
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        del wallet_count, selection_policy
        return ((), {})

    plan = resolve_run_plan(ResearchRunSpec(
        profile="canary", code_sha=CODE_SHA,
        spec_version="research-run-spec-v2", runtime={},
    ), observed=NOW)
    with pytest.raises(ResearchRunnerError, match="cannot honor frozen runtime"):
        asyncio.run(ResearchExperimentRunner(source_factory=factory)._open_sources(plan))


def test_open_sources_fails_closed_when_factory_lacks_selection_parameters() -> None:
    calls: list[str] = []

    async def factory() -> tuple[tuple[object, ...], dict[str, object]]:
        calls.append("zero-arg")
        return ((), {})

    runner = ResearchExperimentRunner(source_factory=factory)
    with pytest.raises(
        ResearchRunnerError,
        match="cannot honor the frozen Polycop selection",
    ):
        asyncio.run(runner._open_sources(_configured_plan()))
    assert calls == []


def test_open_sources_fails_closed_for_kwargs_only_factory() -> None:
    calls: list[dict[str, object]] = []

    async def factory(**_kwargs: object) -> tuple[tuple[object, ...], dict[str, object]]:
        calls.append(dict(_kwargs))
        return ((), {})

    runner = ResearchExperimentRunner(source_factory=factory)
    with pytest.raises(
        ResearchRunnerError,
        match="cannot honor the frozen Polycop selection",
    ):
        asyncio.run(runner._open_sources(_configured_plan()))
    assert calls == []
    assert source_factory_accepts_selection(factory) is False
