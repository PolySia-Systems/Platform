"""Deterministic recent-activity selection shared by Research and Shadow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate


def select_active_shadow_alpha(
    candidates: Sequence[ProtectedShadowCandidate],
    activity_counts: Mapping[str, int],
    *,
    count: int,
) -> tuple[ProtectedShadowCandidate, ...]:
    if count < 1:
        raise ValueError("active selection count must be positive")
    eligible = sorted(
        (
            item for item in candidates
            if "SHADOW_ALPHA" in item.pools
            and item.alpha_rank is not None
            and activity_counts.get(item.wallet_id, 0) > 0
        ),
        key=lambda item: (
            -activity_counts[item.wallet_id], int(item.alpha_rank or 0), item.wallet_id,
        ),
    )
    selected: list[ProtectedShadowCandidate] = []
    seen: set[str] = set()
    for item in eligible:
        if item.wallet_id in seen:
            continue
        if not item.address:
            raise ValueError("selected SHADOW_ALPHA wallet is missing an address")
        seen.add(item.wallet_id)
        selected.append(item)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError("recent-active SHADOW_ALPHA candidates are insufficient")
    return tuple(selected)


def active_selection_options(
    candidates: Sequence[ProtectedShadowCandidate],
    activity_counts: Mapping[str, int],
    latest_token_counts: Mapping[str, int],
    *,
    lookback_seconds: int,
    requested_count: int,
) -> list[dict[str, object]]:
    """Compare cohorts from one frozen preflight without predicting future trades."""

    if lookback_seconds <= 0:
        raise ValueError("activity lookback must be positive")
    options: list[dict[str, object]] = []
    for count in sorted({5, 10, 20, 40, requested_count}):
        if count < 1 or count > 40:
            continue
        try:
            selected = select_active_shadow_alpha(candidates, activity_counts, count=count)
        except ValueError:
            options.append({
                "wallet_count": count, "status": "INSUFFICIENT_ACTIVE_CANDIDATES",
                "observed_latest_token_events": None, "hours_for_20_if_rate_holds": None,
            })
            continue
        observed = sum(latest_token_counts.get(item.wallet_id, 0) for item in selected)
        estimate = (
            None if observed < 5 else
            format(
                Decimal(20) * Decimal(lookback_seconds) /
                (Decimal(3600) * Decimal(observed)),
                ".2f",
            )
        )
        options.append({
            "wallet_count": count,
            "status": "ROUGH_RATE_NOT_FORECAST" if estimate is not None
            else "INSUFFICIENT_OBSERVED_RATE",
            "observed_latest_token_events": observed,
            "hours_for_20_if_rate_holds": estimate,
            "uncertainty": "high; correlated trades and future market evidence may differ",
        })
    return options
