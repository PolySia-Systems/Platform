from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.application.services.continuous_shadow import ContinuousShadowError
from polysia.application.services.continuous_shadow_failures import (
    FAILURE_CATEGORY_ACCOUNTING_BLOCKED,
    FAILURE_CATEGORY_MARKET_READ_FAILED,
    FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
    FAILURE_CATEGORY_SQLITE_BUSY,
)
from polysia.cli import app
from polysia.cli_commands.wallet_intelligence import (
    _ACCOUNTING_STOP_FAILURES,
    _RETRYABLE_PERSISTENT_SHADOW_FAILURES,
    _load_continuous_shadow_runtime_spec,
)
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.copytrading.wallet_capacity import workload_digest
from polysia.domain.wallet_intelligence import CandidateWalletDataset, CandidateWalletRecord

runner = CliRunner()


def test_preparation_reuses_fresh_artifact_and_replaces_it_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.cli_commands import research_evidence_cli, wallet_intelligence

    now = datetime.now(UTC)
    wallet = ProtectedShadowCandidate(
        "wallet-1", "0x" + "1" * 40, ("SHADOW_ALPHA",), alpha_rank=1,
    )
    snapshot = ContinuousSelectionSnapshot.create(
        source_id="polycop", selection_run_id="stage3", source_snapshot_id="source",
        feature_set_version="copyability-v0.1", policy_id="copyability-selection",
        policy_version="v0.1", ranking_version="ranking-v1", published_at=now,
        candidates=(wallet,),
    )
    base = ContinuousShadowConfig(
        runtime_version="continuous-shadow-runtime-v2", code_sha="a" * 40,
        wallet_count=1, selection_policy="shadow-alpha-active-v2",
        selection_activity_counts={"wallet-1": 1}, selection_observed_at=now,
        selection_preflight_digest="b" * 64,
    )
    capacity: dict[str, object] = {
        "version": "wallet-capacity-v2", "code_sha": "a" * 40,
        "workload_digest": workload_digest("continuous-shadow", base.capacity_workload()),
        "validated_count": 1, "result": "PASS", "polls_observed": 3,
        "max_queue_delay_ms": 1, "p95_decision_latency_ms": 1,
        "peak_memory_bytes": 1024, "storage_growth_bytes": 1024,
        "other_consumer_requests": 1, "data_requests": 3,
        "clob_requests": 3, "gamma_requests": 3, "rate_limited_requests": 0,
        "probe_scope": "SHADOW_FULL_PATH", "nonempty_event_count": 3,
        "writer_poll_count": 3, "book_requests": 3, "fee_requests": 3,
        "host_peak_memory_bytes": 2048, "ledger_balanced": True,
        "shared_ip_observed": True,
    }
    capacity["digest"] = hashlib.sha256(json.dumps(
        capacity, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({
        "source_mode": "per-wallet-v2", **replace(base, capacity_evidence=capacity).to_dict(),
    }), encoding="utf-8")
    policy = tmp_path / "preparation.json"
    policy.write_text(json.dumps({
        "version": "wallet-preparation-v1", "mode": "exact",
        "minimum_wallets": 1, "maximum_wallets": 1,
        "candidate_pool_size": 1, "candidate_scan_limit": 1,
        "maximum_attempts": 1, "target_observable_events_per_period": 1,
    }), encoding="utf-8")
    output = tmp_path / "prepared.json"
    calls = [0]
    fail = [False]

    class Pipeline:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def ensure(self, **_kwargs: object) -> object:
            return SimpleNamespace(
                source_refreshed=False,
                snapshot=SimpleNamespace(
                    accepted_at=now, captured_at=now, snapshot_id="source",
                    dataset_digest="c" * 64,
                ),
            )

    class Candidates:
        def __init__(self, _path: Path) -> None:
            pass

        def current_snapshot(self, _source_id: str) -> ContinuousSelectionSnapshot:
            return snapshot

    async def measure(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, int], dict[str, object]]:
        calls[0] += 1
        if fail[0]:
            raise RuntimeError("activity coverage failed")
        return {"wallet-1": 1}, {
            "digest": "b" * 64, "lookback_seconds": 14_400,
            "rows": [{"wallet_id": "wallet-1", "event_count": 1,
                      "observable_recent_event_count": 1}],
        }

    monkeypatch.setattr(wallet_intelligence, "_require_continuous_shadow_safety", lambda: None)
    monkeypatch.setattr(wallet_intelligence, "load_runtime_identity",
                        lambda **_kwargs: SimpleNamespace(deploy_sha="a" * 40))
    monkeypatch.setattr(wallet_intelligence, "_source",
                        lambda _name: SimpleNamespace(source_id="polycop"))
    monkeypatch.setattr(wallet_intelligence, "WalletIntelligencePipelineService", Pipeline)
    monkeypatch.setattr(wallet_intelligence, "DynamicShadowRepository", Candidates)
    monkeypatch.setattr(wallet_intelligence, "_linux_process_peak_rss_bytes",
                        lambda: 1024 * 1024)
    monkeypatch.setattr(research_evidence_cli, "_measure_recent_alpha_activity", measure)
    args = [
        "wallet-intelligence", "portfolio-prepare", "--preparation-spec", str(policy),
        "--base-runtime-spec", str(runtime), "--code-sha", "a" * 40,
        "--source-database", str(tmp_path / "source.sqlite3"),
        "--database", str(tmp_path / "shadow.sqlite3"), "--output", str(output),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout)["status"] == "PREPARED"
    assert json.loads(first.stdout)["preparation_attempts"] == 1
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert calls == [1]
    malformed_time = json.loads(output.read_text(encoding="utf-8"))
    malformed_time["observed_at"] = "not-a-timestamp"
    output.write_text(json.dumps(malformed_time), encoding="utf-8")
    recovered_time = runner.invoke(app, args)
    assert recovered_time.exit_code == 0, recovered_time.output
    assert calls == [2]
    output.write_text("broken JSON", encoding="utf-8")
    recovered = runner.invoke(app, args)
    assert recovered.exit_code == 0, recovered.output
    assert calls == [3]
    fail[0] = True
    output.write_text("broken JSON", encoding="utf-8")
    blocked = runner.invoke(app, args)
    assert blocked.exit_code == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "BLOCKED"
    from datetime import timedelta

    from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository

    lease_store = CandidateIntelligenceRepository(tmp_path / "source.sqlite3")
    lease = lease_store.acquire_lease(
        "wallet-preparation", owner_id="another-preparer", acquired_at=datetime.now(UTC),
        lease_duration=timedelta(minutes=20),
    )
    try:
        output.write_text('{"status":"REQUESTED"}', encoding="utf-8")
        concurrent = runner.invoke(app, args)
        assert concurrent.exit_code == 1
        assert json.loads(output.read_text(encoding="utf-8"))["status"] == "REQUESTED"
    finally:
        lease_store.release_lease(lease)
    future = ContinuousSelectionSnapshot.create(
        source_id="polycop", selection_run_id="stage3-future",
        source_snapshot_id="source", feature_set_version="copyability-v0.1",
        policy_id="copyability-selection", policy_version="v0.1",
        ranking_version="ranking-v1", published_at=now + timedelta(days=1),
        candidates=(wallet,),
    )

    class FutureCandidates(Candidates):
        def current_snapshot(self, _source_id: str) -> ContinuousSelectionSnapshot:
            return future

    monkeypatch.setattr(wallet_intelligence, "DynamicShadowRepository", FutureCandidates)
    future_result = runner.invoke(app, args)
    assert future_result.exit_code == 1
    assert "future" in json.loads(output.read_text(encoding="utf-8"))["reason"]


@pytest.mark.parametrize("wallet_count", [1, 3])
def test_shadow_runtime_spec_freezes_supported_count_and_budgets(
    tmp_path: Path, wallet_count: int
) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({
        "runtime_version": "continuous-shadow-runtime-v1",
        "source_mode": "per-wallet-v2",
        "code_sha": "a" * 40,
        "wallet_count": wallet_count,
        "poll_interval_seconds": 90,
        "maximum_pages_per_wallet": 12,
        "source_max_pages": 8,
        "source_max_requests": 9,
        "period_duration_seconds": 7200,
        "period_max_events": 500,
    }), encoding="utf-8")
    config = _load_continuous_shadow_runtime_spec(path, ContinuousShadowConfig())
    assert config.wallet_count == wallet_count
    assert config.poll_interval_seconds == 90
    assert config.maximum_pages_per_wallet == 12
    assert config.source_max_pages == 8
    assert config.to_dict()["code_sha"] == "a" * 40


@pytest.mark.parametrize("field,value", [
    ("wallet_count", 4),
    ("period_duration_seconds", 0),
    ("source_mode", "global-v2"),
    ("unknown", 1),
])
def test_shadow_runtime_spec_rejects_unsupported_changes(
    tmp_path: Path, field: str, value: object
) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({
        "runtime_version": "continuous-shadow-runtime-v1",
        "source_mode": "per-wallet-v2",
        "code_sha": "a" * 40,
        field: value,
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        _load_continuous_shadow_runtime_spec(path, ContinuousShadowConfig())


def test_shadow_runtime_spec_requires_code_identity(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({
        "runtime_version": "continuous-shadow-runtime-v1",
        "source_mode": "per-wallet-v2",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="requires the running code SHA"):
        _load_continuous_shadow_runtime_spec(path, ContinuousShadowConfig())


@pytest.mark.parametrize("wallet_count", [5, 10, 20, 40])
def test_v2_shadow_runtime_loader_accepts_supported_count(
    tmp_path: Path, wallet_count: int,
) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({
        "runtime_version": "continuous-shadow-runtime-v2",
        "source_mode": "per-wallet-v2",
        "code_sha": "a" * 40,
        "wallet_count": wallet_count,
        "selection_policy": "shadow-alpha-ranked-v2",
        "follower_bankroll": "800",
        "maximum_event_notional": "4",
    }), encoding="utf-8")
    config = _load_continuous_shadow_runtime_spec(path, ContinuousShadowConfig())
    assert config.wallet_count == wallet_count
    assert config.runtime_version == "continuous-shadow-runtime-v2"
    assert str(config.follower_bankroll) == "800"
    assert str(config.maximum_event_notional) == "4"


def test_shadow_config_cli_preview_apply_and_receipt_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.cli_commands import wallet_intelligence

    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({
        "runtime_version": "continuous-shadow-runtime-v2",
        "source_mode": "per-wallet-v2",
        "code_sha": "a" * 40, "wallet_count": 5,
        "selection_policy": "shadow-alpha-ranked-v2",
    }), encoding="utf-8")
    captured: list[tuple[str, str]] = []

    class FakeService:
        def preview_configuration(self, source_id: str) -> dict[str, object]:
            captured.append(("preview", source_id))
            return {"version": "shadow-config-preview-v1", "status": "BLOCKED_CAPACITY"}

        def apply_configuration(
            self, source_id: str, *, command_id: str,
            expected_latest_experiment_id: str,
        ) -> dict[str, object]:
            captured.append((command_id, expected_latest_experiment_id))
            return {
                "version": "shadow-config-command-v1", "disposition": "PENDING_DRAIN",
                "source_id": source_id,
            }

    monkeypatch.setattr(wallet_intelligence, "_require_continuous_shadow_safety", lambda: None)
    monkeypatch.setattr(wallet_intelligence, "_verify_continuous_shadow_code", lambda _: None)
    monkeypatch.setattr(
        wallet_intelligence, "_continuous_shadow_service",
        lambda *_args, **_kwargs: FakeService(),
    )
    preview = runner.invoke(app, [
        "wallet-intelligence", "portfolio-preview", "--runtime-spec", str(path),
    ])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.stdout)["status"] == "BLOCKED_CAPACITY"
    apply = runner.invoke(app, [
        "wallet-intelligence", "portfolio-apply", "--runtime-spec", str(path),
        "--command-id", "change-5", "--expected-latest-experiment-id", "old",
    ])
    assert apply.exit_code == 0, apply.output
    assert json.loads(apply.stdout)["disposition"] == "PENDING_DRAIN"
    assert captured == [("preview", "polycop"), ("change-5", "old")]
    caps = runner.invoke(app, ["wallet-intelligence", "portfolio-capabilities"])
    assert caps.exit_code == 0
    assert json.loads(caps.stdout)["software_wallet_limit"] == 40


def test_portfolio_preflight_cli_freezes_bounded_active_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.cli_commands import research_evidence_cli, wallet_intelligence
    from polysia.deployment import research_wallet_selection

    candidates = tuple(
        ProtectedShadowCandidate(
            f"alpha-{index}", f"0x{index:040x}", ("SHADOW_ALPHA",),
            alpha_rank=index,
        ) for index in range(1, 7)
    )
    seen: list[int] = []

    async def measure(
        _candidates: object, **kwargs: object,
    ) -> tuple[dict[str, int], dict[str, object]]:
        seen.append(int(kwargs["minimum_candidates"]))
        return ({f"alpha-{index}": 7 - index for index in range(1, 7)},
                {"candidate_count": 6, "lookback_seconds": 14_400,
                 "digest": "b" * 64})

    monkeypatch.setattr(wallet_intelligence, "_require_continuous_shadow_safety", lambda: None)
    monkeypatch.setattr(wallet_intelligence, "load_runtime_identity",
                        lambda **_kwargs: SimpleNamespace(deploy_sha="a" * 40))
    monkeypatch.setattr(research_wallet_selection, "load_current_polycop_snapshot",
                        lambda _path: SimpleNamespace(candidates=candidates))
    monkeypatch.setattr(research_evidence_cli, "_measure_recent_alpha_activity", measure)
    result = runner.invoke(app, [
        "wallet-intelligence", "portfolio-preflight", "--wallet-count", "5",
        "--code-sha", "a" * 40, "--source-database", str(tmp_path / "source.sqlite3"),
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "PENDING_CAPACITY"
    assert payload["selected_count"] == 5
    assert payload["proposed_runtime_spec"]["wallet_count"] == 5
    assert payload["proposed_runtime_spec"]["selection_policy"] == "shadow-alpha-active-v2"
    assert payload["proposed_runtime_spec"]["selection_preflight_digest"] == "b" * 64
    assert seen == [5]


def test_capacity_workload_changes_with_financial_or_selection_limits() -> None:
    base = ContinuousShadowConfig(
        runtime_version="continuous-shadow-runtime-v2", code_sha="a" * 40,
        wallet_count=5, selection_policy="shadow-alpha-ranked-v2",
    )
    assert base.capacity_workload() == replace(base, wallet_count=10).capacity_workload()
    assert base.capacity_workload() != replace(
        base, follower_bankroll=base.follower_bankroll * 2
    ).capacity_workload()
    assert base.capacity_workload() != replace(
        base, selection_policy="shadow-alpha-active-v2",
        selection_activity_counts={"alpha-1": 3}, selection_observed_at=datetime.now(UTC),
        selection_preflight_digest="b" * 64,
    ).capacity_workload()
    with pytest.raises(ValueError, match="preflight digest"):
        replace(
            base, selection_policy="shadow-alpha-active-v2",
            selection_activity_counts={"alpha-1": 3},
            selection_observed_at=datetime.now(UTC),
        )


def test_capacity_counts_nested_bundles_and_legacy_files_but_not_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRADING_MODE", "DATA_ONLY")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    root = tmp_path / "backups"
    for relative in (
        "legacy.sqlite3", "bundle-new/shadow.sqlite3", "pinned/cutover/state.sqlite3",
        ".bundle-staging-in-progress/partial.sqlite3",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"capacity-only-fixture")
    result = runner.invoke(app, [
        "wallet-intelligence", "capacity", "--backup-dir", str(root),
        "--database", str(tmp_path / "absent-shadow.sqlite3"),
        "--intelligence-database", str(tmp_path / "absent-intelligence.sqlite3"),
    ])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["backup_count"] == 3
    assert payload["backup_bytes"] == 3 * len(b"capacity-only-fixture")


def test_persistent_shadow_retries_only_expected_transient_failures() -> None:
    assert {
        FAILURE_CATEGORY_MARKET_READ_FAILED,
        FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
        FAILURE_CATEGORY_SQLITE_BUSY,
    } == _RETRYABLE_PERSISTENT_SHADOW_FAILURES
    assert FAILURE_CATEGORY_ACCOUNTING_BLOCKED in _ACCOUNTING_STOP_FAILURES
    assert FAILURE_CATEGORY_ACCOUNTING_BLOCKED not in _RETRYABLE_PERSISTENT_SHADOW_FAILURES


@pytest.mark.parametrize(
    "error_code",
    [FAILURE_CATEGORY_SOURCE_UNAVAILABLE, FAILURE_CATEGORY_MARKET_READ_FAILED],
)
def test_persistent_shadow_keeps_running_after_transient_source_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_code: str,
) -> None:
    handlers: dict[int, object] = {}
    polls = 0

    def emit_poll(*_args: object, **_kwargs: object) -> None:
        nonlocal polls
        polls += 1
        raise ContinuousShadowError(
            "sanitized transient failure",
            error_code=error_code,
            processing_stage="collect_events",
        )

    def install_handler(sig: int, handler: object) -> None:
        handlers[sig] = handler

    def stop_after_retry_delay(_seconds: float) -> None:
        handler = handlers[2]
        assert callable(handler)
        handler()

    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._require_continuous_shadow_safety",
        lambda: None,
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._continuous_shadow_service",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._source",
        lambda _source: SimpleNamespace(source_id="polycop"),
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._emit_portfolio_poll", emit_poll
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence.signal.signal", install_handler
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence.time.sleep", stop_after_retry_delay
    )

    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "portfolio-sync",
            "--database",
            str(tmp_path / "wallet-intelligence.sqlite3"),
            "--loop",
        ],
    )

    assert result.exit_code == 0, result.output
    assert polls == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == error_code
    assert payload["status"] == "skipped"


def test_persistent_shadow_exits_zero_on_accounting_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    polls = 0

    def emit_poll(*_args: object, **_kwargs: object) -> None:
        nonlocal polls
        polls += 1
        raise ContinuousShadowError(
            "accounting blocked",
            error_code=FAILURE_CATEGORY_ACCOUNTING_BLOCKED,
            processing_stage="pre_poll",
        )

    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._require_continuous_shadow_safety",
        lambda: None,
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._continuous_shadow_service",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._source",
        lambda _source: SimpleNamespace(source_id="polycop"),
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence._emit_portfolio_poll", emit_poll
    )

    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "portfolio-sync",
            "--database",
            str(tmp_path / "wallet-intelligence.sqlite3"),
            "--health-report",
            str(tmp_path / "continuous-shadow.json"),
            "--loop",
        ],
    )

    assert result.exit_code == 0, result.output
    assert polls == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == FAILURE_CATEGORY_ACCOUNTING_BLOCKED
    assert payload["status"] == "blocked"
    assert payload["processing_stage"] == "pre_poll"


def test_restore_check_reports_intelligence_evidence_only_without_shadow_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation = SimpleNamespace(
        candidate_intelligence_schema_version=1,
        candidate_pool_count=2,
        candidate_run_count=1,
        copyability_membership_count=2,
        copyability_run_count=1,
        copyability_selection_schema_version=1,
        dynamic_shadow_evaluation_count=5,
        dynamic_shadow_run_count=1,
        dynamic_shadow_schema_version=1,
        row_count=2,
        schema_version=1,
        snapshot_count=1,
    )
    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence.rehearse_wallet_intelligence_restore",
        lambda *_args, **_kwargs: SimpleNamespace(
            sha256="a" * 64,
            validation=validation,
        ),
    )

    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "restore-check",
            "--backup",
            str(tmp_path / "backup.sqlite3"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "continuous_shadow_schema_version" not in payload
    assert "restored_continuous_shadow_experiment_count" not in payload


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


def test_runtime_bank_refuses_non_data_only_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("POLYMARKET_LIVE_TOKEN_ALLOWLIST", "token-1")

    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "runtime-bank",
            "--database",
            str(tmp_path / "wallet-intelligence.sqlite3"),
            "--candidate-file",
            str(tmp_path / "candidates.txt"),
            "--manifest-dir",
            str(tmp_path / "candidate-banks"),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "handoff_requires_data_only"
    assert payload["values_redacted"] is True
    assert not (tmp_path / "candidates.txt").exists()


def test_portfolio_health_reads_artifact_without_initializing_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("initialize must not run for operational health")

    monkeypatch.setattr(
        "polysia.cli_commands.wallet_intelligence.ContinuousShadowRepository.initialize",
        boom,
    )
    artifact = tmp_path / "continuous-shadow.json"
    artifact.write_text(
        json.dumps(
            {
                "level": "healthy",
                "ledger_balanced": True,
                "operator_summary": {"MIXED_BASELINE": {"nav": "1000"}},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "portfolio-health",
            "--health-report",
            str(artifact),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["level"] == "healthy"
    assert payload["operator_summary"]["MIXED_BASELINE"]["nav"] == "1000"


def test_portfolio_results_does_not_initialize_or_write_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.storage.continuous_shadow import ContinuousShadowRepository

    database = tmp_path / "snapshot.sqlite3"
    ContinuousShadowRepository(database).initialize()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("initialize must not run for portfolio-results")

    monkeypatch.setattr(ContinuousShadowRepository, "initialize", boom)
    result = runner.invoke(
        app,
        [
            "wallet-intelligence",
            "portfolio-results",
            "--database",
            str(database),
            "--limit",
            "10",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "failed"
    assert "0x" not in result.output
