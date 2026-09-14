from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.backtesting.offline_research_lab import (
    independent_control_economics,
    independent_fill,
    run_offline_proof,
    run_scenario_a,
    run_scenario_b,
    run_scenario_c,
)
from polysia.deployment.research_experiment_bundle import (
    OUTCOME_FAILURE_ARCHIVED,
    OUTCOME_FINALIZED,
    finalize_research_experiment,
)
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)
from polysia.storage.research_evidence import ResearchEvidenceStore


def test_scenario_a_matches_independent_decimal_economics(tmp_path: Path) -> None:
    result = asyncio.run(run_scenario_a(tmp_path / "a"))
    expected_target = independent_fill()
    expected_control = independent_control_economics()
    economic = result.report["economic"]
    assert result.bundle_verified is True
    assert result.bundle_outcome == OUTCOME_FINALIZED
    assert result.source_hash_before == result.source_hash_after
    assert result.replay_hashes[0] == result.replay_hashes[1]
    assert economic["data_canary_status"] == "PASS"
    assert economic["economic_classification"] == "POSITIVE"
    assert Decimal(economic["target"]["net_pnl"]) == expected_target["net_pnl"]
    assert Decimal(economic["target"]["fees"]) == expected_target["fees"]
    assert Decimal(economic["target"]["slippage"]) == expected_target["slippage"]
    assert Decimal(economic["target"]["cash"]) == expected_target["cash"]
    assert Decimal(economic["control"]["net_pnl"]) == expected_control["net_pnl"]
    assert Decimal(economic["control"]["fees"]) == expected_control["fees"]
    target_decisions = [row["decision"] for row in result.report["target_decisions"]]
    control_decisions = [row["decision"] for row in result.report["control_decisions"]]
    assert target_decisions.count("ADMIT") == 1
    assert "SKIP_REPEAT_SIGNAL" in target_decisions
    assert control_decisions.count("ADMIT") == 20
    remaining = economic["target"]["remaining_positions"]
    assert remaining[0]["quantity"] == format(expected_target["available_quantity"], "f")
    assert remaining[0]["valuation_status"] == "MEASURED"


def test_scenario_b_recovers_and_does_not_double_apply(tmp_path: Path) -> None:
    result = asyncio.run(run_scenario_b(tmp_path / "b"))
    extras = result.extras
    first_wallet_ids = set(extras["first_process_wallet_ids"])
    assert first_wallet_ids
    assert first_wallet_ids <= set(extras["restart_wallet_ids"])
    assert extras["aliased_wallet_count"] >= 2
    assert extras["aliased_wallet_count"] == extras["unique_aliased_source_event_ids"]
    assert extras["restart_event_count"] >= len(extras["first_process_evidence_ids"])
    wallet_ids = [
        row["wallet_evidence_id"]
        for row in result.report["decision_evidence"]
        if isinstance(row, dict)
    ]
    assert len(wallet_ids) == len(set(wallet_ids))
    assert extras["reconnect_count"] >= 1 or extras["book_recovery_count"] >= 1
    assert extras["transport_purposes"]
    first = set(extras["first_process_evidence_ids"])
    assert first
    assert result.replay_hashes[0] == result.replay_hashes[1]
    assert result.source_hash_before == result.source_hash_after


def test_scenario_c_does_not_invent_positive_economics(tmp_path: Path) -> None:
    result = asyncio.run(run_scenario_c(tmp_path / "c"))
    economic = result.report["economic"]
    assert economic["economic_classification"] == "INSUFFICIENT_DATA"
    assert economic["economic_classification"] != "POSITIVE"
    pnl = economic["target"]["net_pnl"]
    assert pnl is None or Decimal(str(pnl)) <= Decimal("0")
    assert Decimal(economic["target"]["fees"]) == Decimal("0")
    unknown = result.report["unknown_by_cause"]
    assert int(unknown.get("stale_quote") or unknown.get("missing_quote") or 0) >= 1
    assert economic["data_canary_status"] in {"FAIL", "INSUFFICIENT_ACTIVITY"}
    assert result.source_hash_before == result.source_hash_after
    assert result.replay_hashes[0] == result.replay_hashes[1]


def test_offline_proof_runs_all_scenarios(tmp_path: Path) -> None:
    results = asyncio.run(run_offline_proof(tmp_path / "all"))
    assert set(results) == {"A", "B", "C"}
    assert results["A"].bundle_verified is True
    assert results["C"].report["economic"]["economic_classification"] == "INSUFFICIENT_DATA"


def test_finalization_is_idempotent_and_resumes_existing_bundle(tmp_path: Path) -> None:
    result = asyncio.run(run_scenario_a(tmp_path / "resume"))
    database = tmp_path / "resume" / "research-evidence.sqlite3"
    bundle_root = tmp_path / "resume" / "bundles"
    first = finalize_research_experiment(database, bundle_root, run_id=result.run_id)
    second = finalize_research_experiment(database, bundle_root, run_id=result.run_id)
    live = ResearchEvidenceStore(database)
    connection = live._connect()
    try:
        connection.execute(
            "UPDATE research_experiments SET status='ACTIVE' WHERE run_id=?",
            (result.run_id,),
        )
        connection.commit()
    finally:
        connection.close()
    resumed = finalize_research_experiment(database, bundle_root, run_id=result.run_id)
    assert first.verified is True
    assert second.path == first.path
    assert resumed.path == first.path
    assert resumed.sha256 == first.sha256
    assert live.load_experiment(result.run_id).status == "FINALIZED"  # type: ignore[union-attr]


def test_honest_failure_archive_is_not_verified(tmp_path: Path) -> None:

    database = tmp_path / "fail.sqlite3"
    store = ResearchEvidenceStore(database)
    store.start_or_resume_experiment(
        requested_run_id="fail-run",
        duration=timedelta(hours=1),
        max_events=10,
        max_bytes=10_000_000,
        code_sha="b" * 40,
        configuration_digest="config",
    )
    collector = ProspectiveCollector(store, run_id="fail-run")
    observed = datetime(2026, 9, 13, tzinfo=UTC)
    collector.ingest(
        CanonicalResearchEvent(
            evidence_id="only-wallet",
            schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
            source_id="wallet",
            event_kind=ObservationKind.WALLET_TRADE,
            classification=EvidenceClassification.ACCEPTED,
            market_reference="m",
            outcome_reference="t",
            side="BUY",
            price=Decimal("0.5"),
            size=Decimal("1"),
            source_time=observed,
            observed_time=observed,
            receive_monotonic_ns=1,
            normalize_monotonic_ns=2,
            attribution_status=AttributionStatus.WALLET_ALIASED,
            leader_alias="pub-a",
            confirmation=ConfirmationStatus.CONFIRMED,
            payload_digest=payload_digest({"id": "only-wallet"}),
            provenance={},
            source_event_id="source-only-wallet",
            run_id="fail-run",
        )
    )
    collector.close_window(complete=False)
    bundle = finalize_research_experiment(database, tmp_path / "bundles", run_id="fail-run")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert bundle.verified is False
    assert bundle.outcome == OUTCOME_FAILURE_ARCHIVED
    assert manifest["verified"] is False
    assert manifest["outcome"] == OUTCOME_FAILURE_ARCHIVED
    assert store.load_experiment("fail-run").status == OUTCOME_FAILURE_ARCHIVED  # type: ignore[union-attr]


FROZEN_BUNDLE_ENV = "POLYSIA_FROZEN_RESEARCH_BUNDLE"
FROZEN_RUN_ID = "2a596ba825e4471385c2dd18aa7b8370"
FROZEN_DB_SHA256 = "2e0fc780e8c9d6fe9013d0be2ef2ccd7714520aecf741a4a39c368298e4a9140"


def test_frozen_bundle_read_only_replay_is_deterministic() -> None:
    import os

    import pytest

    from polysia.backtesting.prospective_analysis import (
        capture_protected_artifacts,
        load_bundle_manifest,
        open_recorded_experiment_store,
        protected_bundle_paths,
        verify_declared_bundle_artifacts,
    )
    from polysia.backtesting.prospective_replay import replay_recorded_experiment
    from polysia.backtesting.replay_report import detailed_replay_payload, result_hash
    from polysia.storage.immutable_sqlite import sha256_file

    configured = os.environ.get(FROZEN_BUNDLE_ENV, "").strip()
    if not configured:
        pytest.skip(
            f"{FROZEN_BUNDLE_ENV} is unset; synthetic offline proof remains authoritative"
        )
    bundle_root = Path(configured)
    if not bundle_root.is_dir():
        pytest.fail(f"frozen bundle directory is missing: {bundle_root}")
    manifest_path = bundle_root / "experiment-manifest.json"
    database = bundle_root / "research-evidence.sqlite3"
    checksum = database.with_suffix(f"{database.suffix}.sha256")
    if not manifest_path.is_file() or not database.is_file() or not checksum.is_file():
        pytest.fail("frozen bundle is incomplete; not substituting another bundle")
    actual = sha256_file(database)
    if actual != FROZEN_DB_SHA256:
        pytest.fail(
            f"frozen bundle SHA-256 mismatch: expected {FROZEN_DB_SHA256}, got {actual}; "
            "not substituting another bundle"
        )
    manifest = load_bundle_manifest(manifest_path)
    if str(manifest.get("run_id")) != FROZEN_RUN_ID:
        pytest.fail(
            f"frozen bundle run_id mismatch: expected {FROZEN_RUN_ID}; "
            "not substituting another bundle"
        )
    verify_declared_bundle_artifacts(
        database=database,
        bundle_root=bundle_root,
        manifest=manifest,
    )
    protected = protected_bundle_paths(bundle_root, manifest=manifest)
    assert all(path.is_file() for path in protected)
    before = capture_protected_artifacts(
        database=database,
        bundle_root=bundle_root,
        manifest=manifest,
    )
    with open_recorded_experiment_store(
        database,
        bundle_root=bundle_root,
        expected_database_sha256=FROZEN_DB_SHA256,
    ) as store:
        first = replay_recorded_experiment(store, run_id=FROZEN_RUN_ID)
        second = replay_recorded_experiment(store, run_id=FROZEN_RUN_ID)
        experiment = store.load_experiment(FROZEN_RUN_ID)
    after = capture_protected_artifacts(
        database=database,
        bundle_root=bundle_root,
        manifest=manifest,
    )
    assert after.digests == before.digests
    assert first == second
    assert experiment is not None
    report = detailed_replay_payload(
        first,
        experiment=experiment,
        run_id=FROZEN_RUN_ID,
        source_database_sha256=actual,
    )
    assert result_hash(report) == result_hash(
        detailed_replay_payload(
            second,
            experiment=experiment,
            run_id=FROZEN_RUN_ID,
            source_database_sha256=actual,
        )
    )
    economic = first.economics
    assert economic.data_canary_status == "FAIL"
    assert economic.economic_classification == "INSUFFICIENT_DATA"
    assert format(economic.execution_evidence_ratio, "f") == "0.7701266093274213366098616379"
    assert first.result.unknown_count == 4303
    unknown = dict(first.result.unknown_by_cause)
    assert unknown.get("stale_quote") == 4273
    assert first.replayed_event_count == 174_920
    assert len(first.valid_intervals) == 24
