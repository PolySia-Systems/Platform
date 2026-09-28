"""Bounded, pre-period cohort choice shared by command and future UI adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.services.active_wallet_selection import select_active_shadow_alpha
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.copytrading.wallet_capacity import (
    WalletCapacityError,
    capacity_status,
    workload_digest,
)


@dataclass(frozen=True, slots=True)
class WalletPreparationConfig:
    version: Literal["wallet-preparation-v1"] = "wallet-preparation-v1"
    mode: Literal["exact", "adaptive"] = "exact"
    minimum_wallets: int = 3
    maximum_wallets: int = 3
    candidate_pool_size: int = 50
    candidate_scan_limit: int = 50
    markets_per_wallet: int = 4
    pages_per_wallet: int = 20
    requests_per_wallet: int = 20
    total_data_requests: int = 1000
    total_market_tokens: int = 500
    time_budget_seconds: int = 180
    maximum_process_rss_mb: int = 768
    maximum_source_storage_growth_mb: int = 256
    refresh_hours: int = 20
    evidence_expiry_minutes: int = 180
    maximum_attempts: int = 3
    target_observable_events_per_period: int = 20

    def __post_init__(self) -> None:
        if self.version != "wallet-preparation-v1" or self.mode not in {"exact", "adaptive"}:
            raise ValueError("wallet preparation version or mode is unsupported")
        if not 1 <= self.minimum_wallets <= self.maximum_wallets <= 40:
            raise ValueError("wallet preparation count bounds are invalid")
        if self.mode == "exact" and self.minimum_wallets != self.maximum_wallets:
            raise ValueError("exact preparation requires one count")
        if not 1 <= self.candidate_pool_size <= 500:
            raise ValueError("candidate pool size must be within [1, 500]")
        if not 1 <= self.candidate_scan_limit <= self.candidate_pool_size:
            raise ValueError("candidate scan must fit the configured pool")
        if not 1 <= self.markets_per_wallet <= 20:
            raise ValueError("market scan limit must be within [1, 20]")
        if not 1 <= self.pages_per_wallet <= self.requests_per_wallet <= 100:
            raise ValueError("wallet source budgets are invalid")
        if not 1 <= self.total_data_requests <= 5000:
            raise ValueError("total data request budget is invalid")
        if not 1 <= self.total_market_tokens <= 1000:
            raise ValueError("total market token budget is invalid")
        if not 1 <= self.time_budget_seconds <= 600:
            raise ValueError("preparation time budget is invalid")
        if not 64 <= self.maximum_process_rss_mb <= 768:
            raise ValueError("preparation RSS budget must be within [64, 768] MiB")
        if not 1 <= self.maximum_source_storage_growth_mb <= 1024:
            raise ValueError("source storage growth budget must be within [1, 1024] MiB")
        if not 1 <= self.refresh_hours <= 24 or not 1 <= self.evidence_expiry_minutes <= 240:
            raise ValueError("preparation freshness limits are invalid")
        if not 1 <= self.maximum_attempts <= 10:
            raise ValueError("preparation attempts must be within [1, 10]")
        if not 1 <= self.target_observable_events_per_period <= 10_000:
            raise ValueError("observable event target is invalid")


def choose_prepared_cohort(
    config: WalletPreparationConfig,
    snapshot: ContinuousSelectionSnapshot,
    activity_counts: dict[str, int],
    activity_evidence: dict[str, object],
    base_runtime: ContinuousShadowConfig,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Choose only from completed, observable Alpha reads; never infer missing activity."""

    if observed_at.tzinfo is None or observed_at.utcoffset() != UTC.utcoffset(observed_at):
        raise ValueError("preparation time must be UTC")
    if len(snapshot.candidates) < 1 or activity_evidence.get("digest") is None:
        raise ValueError("complete activity evidence is required")
    rows = activity_evidence.get("rows")
    if not isinstance(rows, list) or len(rows) > config.candidate_scan_limit:
        raise ValueError("activity screening coverage is invalid")
    ranked_alpha = sorted(
            (
                candidate for candidate in snapshot.candidates
                if "SHADOW_ALPHA" in candidate.pools and candidate.alpha_rank is not None
            ),
            key=lambda item: (int(item.alpha_rank or 0), item.wallet_id),
        )
    expected = tuple(item.wallet_id for item in ranked_alpha[:config.candidate_scan_limit])
    if len(rows) != len(expected):
        raise ValueError("activity screening is incomplete")
    if tuple(row.get("wallet_id") if isinstance(row, dict) else None for row in rows) != expected:
        raise ValueError("activity screening identities do not match the ranked pool")
    if set(activity_counts) != set(expected):
        raise ValueError("activity counts do not match screened candidates")
    alpha_count = sum("SHADOW_ALPHA" in item.pools for item in snapshot.candidates)
    screening = {
        "candidate_pool_count": len(snapshot.candidates),
        "alpha_candidate_count": alpha_count,
        "screened_count": len(rows),
        "unread_alpha_count": max(0, alpha_count - len(rows)),
        "unread_alpha_wallet_ids": [
            item.wallet_id for item in ranked_alpha[config.candidate_scan_limit:]
        ],
        "screening_complete": len(rows) == alpha_count,
        "coverage_rows": rows,
    }
    if not ranked_alpha:
        return {
            "version": config.version, "status": "INSUFFICIENT_ACTIVE_CANDIDATES",
            "requested_count": config.maximum_wallets, "effective_count": None,
            "eligible_count": 0, "candidate_count": len(snapshot.candidates),
            "screening": screening, "next_action": "refresh_or_widen_qualified_alpha",
        }
    feasible = sum(1 for count in activity_counts.values() if count > 0)
    selected_count = min(feasible, config.maximum_wallets)
    measured_limit = (
        base_runtime.capacity_evidence.get("validated_count")
        if base_runtime.capacity_evidence is not None else None
    )
    if (
        config.mode == "adaptive" and isinstance(measured_limit, int)
        and not isinstance(measured_limit, bool) and 1 <= measured_limit <= 40
    ):
        selected_count = min(selected_count, measured_limit)
    if selected_count < config.minimum_wallets:
        if feasible >= config.minimum_wallets:
            return {
                "version": config.version,
                "status": "BLOCKED_CAPACITY_ENVELOPE",
                "requested_count": config.maximum_wallets,
                "effective_count": None,
                "eligible_count": feasible,
                "validated_count": measured_limit,
                "screening": screening,
                "next_action": "reduce_minimum_or_measure_expansion",
            }
        reasons = {
            row.get("reason") for row in rows if isinstance(row, dict)
        }
        status = (
            "ZERO_ACTIVITY" if feasible == 0 and all(
                isinstance(row, dict) and row.get("event_count") == 0 for row in rows
            ) else "UNAVAILABLE_FEE" if feasible == 0 and "missing_fee" in reasons
            else "UNAVAILABLE_DEPTH" if feasible == 0 and "missing_book_or_depth" in reasons
            else "INSUFFICIENT_ACTIVE_CANDIDATES"
        )
        next_action = (
            "retry_market_evidence" if status in {"UNAVAILABLE_FEE", "UNAVAILABLE_DEPTH"}
            else "widen_pool_or_wait_for_activity"
        )
        return {
            "version": config.version,
            "status": status,
            "requested_count": config.maximum_wallets,
            "effective_count": None,
            "eligible_count": feasible,
            "candidate_count": len(snapshot.candidates),
            "screened_count": len(rows),
            "screening_complete": screening["screening_complete"],
            "screening": screening,
            "alternative_count": feasible if feasible > 0 else None,
            "next_action": next_action,
        }
    selected = select_active_shadow_alpha(
        snapshot.candidates, activity_counts, count=selected_count
    )
    selected_aliases = {item.wallet_id for item in selected}
    observable = sum(
        int(row.get("observable_recent_event_count", 0)) for row in rows
        if isinstance(row, dict) and row.get("wallet_id") in selected_aliases
    )
    lookback_seconds = activity_evidence.get("lookback_seconds", 14_400)
    if isinstance(lookback_seconds, bool) or not isinstance(lookback_seconds, int) or (
        lookback_seconds <= 0
    ):
        raise ValueError("activity lookback duration is invalid")
    estimated_period_events = (
        Decimal(observable) * Decimal(base_runtime.period_duration_seconds)
        / Decimal(lookback_seconds)
    )
    runtime = replace(
        base_runtime,
        runtime_version="continuous-shadow-runtime-v2",
        wallet_count=selected_count,
        selection_policy="shadow-alpha-active-v2",
        selection_activity_counts=dict(activity_counts),
        selection_observed_at=observed_at,
        selection_preflight_digest=str(activity_evidence["digest"]),
    )
    try:
        capacity = capacity_status(
            selected_count,
            code_sha=runtime.code_sha or "",
            workload_digest=workload_digest("continuous-shadow", runtime.capacity_workload()),
            evidence=runtime.capacity_evidence,
        )
    except WalletCapacityError as error:
        capacity = {"operational_status": "blocked", "reason": str(error)}
    status = (
        "LOW_OBSERVABLE_RATE" if estimated_period_events <
        config.target_observable_events_per_period
        else "PREPARED" if capacity.get("operational_status") == "measured"
        else "BLOCKED_CAPACITY_ENVELOPE" if "exceeds measured" in str(
            capacity.get("reason", "")
        ) else "PENDING_CAPACITY"
    )
    return {
        "version": config.version,
        "status": status,
        "requested_count": config.maximum_wallets,
        "effective_count": selected_count,
        "eligible_count": feasible,
        "candidate_count": len(snapshot.candidates),
        "screened_count": len(rows),
        "screening_complete": screening["screening_complete"],
        "screening": screening,
        "selected_wallet_ids": [item.wallet_id for item in selected],
        "observable_recent_events": observable,
        "estimated_observable_events_per_period": str(estimated_period_events),
        "rate_uncertainty": "high; pre-T0 current-market observability is not future execution",
        "rate_status": (
            "TARGET_OBSERVED" if estimated_period_events >=
            config.target_observable_events_per_period
            else "INSUFFICIENT_OBSERVED_RATE"
        ),
        "capacity": capacity,
        "observed_at": observed_at.isoformat(),
        "snapshot_published_at": snapshot.published_at.isoformat(),
        "activity_digest": activity_evidence["digest"],
        "proposed_runtime_spec": {"source_mode": "per-wallet-v2", **runtime.to_dict()},
        "next_action": (
            "queue_for_safe_boundary" if status == "PREPARED"
            else "widen_pool_or_review_target" if status == "LOW_OBSERVABLE_RATE"
            else "reduce_count_or_measure_expansion" if status == "BLOCKED_CAPACITY_ENVELOPE"
            else "measure_full_workload_capacity"
        ),
    }
