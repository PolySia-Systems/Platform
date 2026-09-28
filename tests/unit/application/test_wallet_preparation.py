from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.application.services.wallet_preparation import (
    WalletPreparationConfig,
    choose_prepared_cohort,
)
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.copytrading.wallet_capacity import workload_digest

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def _snapshot() -> ContinuousSelectionSnapshot:
    return ContinuousSelectionSnapshot.create(
        source_id="polycop", selection_run_id="stage3", source_snapshot_id="source",
        feature_set_version="copyability-v0.1", policy_id="copyability-selection",
        policy_version="v0.1", ranking_version="percentile-alpha-stress-v0.1",
        published_at=NOW,
        candidates=tuple(ProtectedShadowCandidate(
            f"wallet-{index}", f"0x{index:040x}", ("SHADOW_ALPHA",),
            alpha_rank=index,
        ) for index in range(1, 6)),
    )


def _activity() -> tuple[dict[str, int], dict[str, object]]:
    counts = {f"wallet-{index}": int(index < 5) for index in range(1, 6)}
    return counts, {
        "digest": "b" * 64,
        "rows": [{
            "wallet_id": f"wallet-{index}",
            "event_count": int(index < 5),
            "observable_recent_event_count": int(index < 5),
        } for index in range(1, 6)],
    }


def _capacity(base: ContinuousShadowConfig, count: int) -> dict[str, object]:
    active = replace(
        base, selection_policy="shadow-alpha-active-v2",
        selection_activity_counts=_activity()[0], selection_observed_at=NOW,
        selection_preflight_digest="b" * 64,
    )
    evidence: dict[str, object] = {
        "version": "wallet-capacity-v2", "code_sha": "a" * 40,
        "workload_digest": workload_digest("continuous-shadow", active.capacity_workload()),
        "validated_count": count, "result": "PASS", "polls_observed": 3,
        "max_queue_delay_ms": 1, "p95_decision_latency_ms": 1,
        "peak_memory_bytes": 1024, "storage_growth_bytes": 1024,
        "other_consumer_requests": 1, "data_requests": 5,
        "clob_requests": 5, "gamma_requests": 5, "rate_limited_requests": 0,
        "probe_scope": "SHADOW_FULL_PATH", "nonempty_event_count": 3,
        "writer_poll_count": 3, "book_requests": 5, "fee_requests": 5,
        "host_peak_memory_bytes": 2048, "ledger_balanced": True,
        "shared_ip_observed": True,
    }
    evidence["digest"] = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return evidence


def test_adaptive_four_is_prepared_but_exact_five_remains_insufficient() -> None:
    snapshot = _snapshot()
    counts, activity = _activity()
    base = ContinuousShadowConfig(
        runtime_version="continuous-shadow-runtime-v2", code_sha="a" * 40,
        wallet_count=5, selection_policy="shadow-alpha-ranked-v2",
    )
    base = replace(base, capacity_evidence=_capacity(base, 4))
    adaptive = WalletPreparationConfig(
        mode="adaptive", minimum_wallets=3, maximum_wallets=5,
        target_observable_events_per_period=4,
    )
    proposal = choose_prepared_cohort(
        adaptive, snapshot, counts, activity, base, observed_at=NOW,
    )
    assert proposal["status"] == "PREPARED"
    assert proposal["effective_count"] == 4
    assert proposal["selected_wallet_ids"] == [f"wallet-{index}" for index in range(1, 5)]
    assert proposal["rate_status"] == "TARGET_OBSERVED"
    assert proposal["screening"]["unread_alpha_count"] == 0
    assert proposal["capacity"]["operational_status"] == "measured"
    assert proposal["proposed_runtime_spec"]["follower_bankroll"] == "1000"

    exact = replace(adaptive, mode="exact", minimum_wallets=5)
    rejected = choose_prepared_cohort(
        exact, snapshot, counts, activity, base, observed_at=NOW,
    )
    assert rejected["status"] == "INSUFFICIENT_ACTIVE_CANDIDATES"
    assert rejected["alternative_count"] == 4
    assert rejected["effective_count"] is None


def test_missing_capacity_and_incomplete_screening_do_not_claim_ready() -> None:
    snapshot = _snapshot()
    counts, activity = _activity()
    base = ContinuousShadowConfig(
        runtime_version="continuous-shadow-runtime-v2", code_sha="a" * 40,
        wallet_count=5, selection_policy="shadow-alpha-ranked-v2",
    )
    policy = WalletPreparationConfig(mode="adaptive", minimum_wallets=3, maximum_wallets=5)
    proposal = choose_prepared_cohort(
        policy, snapshot, counts, activity, base, observed_at=NOW,
    )
    assert proposal["status"] == "LOW_OBSERVABLE_RATE"
    assert proposal["capacity"]["operational_status"] == "unverified"
    assert proposal["observable_recent_events"] == 4
    assert proposal["next_action"] == "widen_pool_or_review_target"
    pending_capacity = choose_prepared_cohort(
        replace(policy, target_observable_events_per_period=4), snapshot,
        counts, activity, base, observed_at=NOW,
    )
    assert pending_capacity["status"] == "PENDING_CAPACITY"
    activity["rows"] = list(activity["rows"])[:-1]
    try:
        choose_prepared_cohort(policy, snapshot, counts, activity, base, observed_at=NOW)
    except ValueError as error:
        assert "incomplete" in str(error)
    else:
        raise AssertionError("partial screening cannot be presented as complete")


def test_bounded_partial_screening_reports_unread_alpha_and_next_action() -> None:
    snapshot = _snapshot()
    counts, evidence = _activity()
    evidence["rows"] = list(evidence["rows"])[:3]
    counts = {key: counts[key] for key in ("wallet-1", "wallet-2", "wallet-3")}
    base = ContinuousShadowConfig(
        runtime_version="continuous-shadow-runtime-v2", code_sha="a" * 40,
        wallet_count=5, selection_policy="shadow-alpha-ranked-v2",
    )
    policy = WalletPreparationConfig(
        mode="exact", minimum_wallets=5, maximum_wallets=5,
        candidate_scan_limit=3,
    )
    result = choose_prepared_cohort(
        policy, snapshot, counts, evidence, base, observed_at=NOW,
    )
    assert result["status"] == "INSUFFICIENT_ACTIVE_CANDIDATES"
    assert result["screening_complete"] is False
    assert result["screening"]["unread_alpha_wallet_ids"] == ["wallet-4", "wallet-5"]
    assert result["next_action"] == "increase_candidate_scan_limit_within_pool"
