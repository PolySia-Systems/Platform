"""Source-neutral discovery and qualification; never financial authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from polysia.domain.wallet_intelligence.models import CandidateWalletDataset


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("source-selection clocks must be UTC")
    return value


def require_decimal(value: Decimal, *, nonnegative: bool = True) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or nonnegative and value < 0:
        raise ValueError("source-selection values must be finite Decimal")
    return value


@dataclass(frozen=True, slots=True)
class RetainedCandidateSnapshot:
    dataset: CandidateWalletDataset
    chain: str
    effective_at: datetime | None
    observed_at: datetime
    complete: bool
    coverage: str
    confidence: Decimal | None

    def __post_init__(self) -> None:
        require_utc(self.observed_at)
        if self.effective_at is not None and require_utc(self.effective_at) > self.observed_at:
            raise ValueError("upstream effective time cannot follow observation")
        if self.dataset.fetched_at > self.observed_at or not self.chain or not self.coverage:
            raise ValueError("retained snapshot identity or timestamps are invalid")
        if type(self.complete) is not bool:
            raise ValueError("source completeness must be explicit")
        if self.confidence is not None and not 0 <= require_decimal(self.confidence) <= 1:
            raise ValueError("source confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class CohortSelectionPolicy:
    version: str
    cohort_size: int
    minimum_samples: int
    freshness: timedelta
    maximum_spread: Decimal
    maximum_drawdown: Decimal
    maximum_delay_seconds: Decimal
    maximum_concentration: Decimal
    maximum_correlation: Decimal
    minimum_confidence: Decimal
    follower_size: Decimal

    def __post_init__(self) -> None:
        if (
            not self.version
            or type(self.cohort_size) is not int
            or self.cohort_size < 1
            or type(self.minimum_samples) is not int
            or self.minimum_samples < 1
            or self.freshness <= timedelta(0)
        ):
            raise ValueError("selection policy requires explicit bounded limits")
        for value in (
            self.maximum_spread,
            self.maximum_drawdown,
            self.maximum_delay_seconds,
            self.maximum_concentration,
            self.maximum_correlation,
            self.minimum_confidence,
            self.follower_size,
        ):
            require_decimal(value)
        if self.follower_size <= 0 or self.minimum_confidence > 1:
            raise ValueError("selection size or confidence is invalid")


@dataclass(frozen=True, slots=True)
class FollowerQualificationEvidence:
    """Comparable, point-in-time follower evidence, separate from provider rank.

    The evaluation window begins strictly after selection. A provider backtest
    score or a seed activity count is not an observed follower outcome.
    """

    wallet_id: str
    evidence_id: str
    selection_start: datetime
    selection_end: datetime
    evaluation_start: datetime
    available_at: datetime
    last_activity_at: datetime
    sample_count: int
    follower_net_per_unit: Decimal | None
    drawdown: Decimal | None
    spread: Decimal | None
    entry_depth: Decimal | None
    exit_depth: Decimal | None
    delay_seconds: Decimal | None
    concentration: Decimal | None
    correlation: Decimal | None
    confidence: Decimal | None
    cost_per_unit: Decimal | None
    route_compatible: bool | None
    complete: bool
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        for timestamp in (
            self.selection_start,
            self.selection_end,
            self.evaluation_start,
            self.available_at,
            self.last_activity_at,
        ):
            require_utc(timestamp)
        if not self.wallet_id or not self.evidence_id or type(self.sample_count) is not int:
            raise ValueError("qualification identity and sample count are required")
        if self.sample_count < 0 or type(self.complete) is not bool:
            raise ValueError("qualification completeness and counts are invalid")
        for value in (
            self.drawdown,
            self.spread,
            self.entry_depth,
            self.exit_depth,
            self.delay_seconds,
            self.concentration,
            self.correlation,
            self.confidence,
            self.cost_per_unit,
        ):
            if value is not None:
                require_decimal(value)
        if self.follower_net_per_unit is not None:
            require_decimal(self.follower_net_per_unit, nonnegative=False)
        if self.confidence is not None and self.confidence > 1:
            raise ValueError("qualification confidence is invalid")


@dataclass(frozen=True, slots=True)
class CohortCandidate:
    wallet_id: str
    sources: tuple[str, ...]
    current_sources: tuple[str, ...]
    state: str
    reasons: tuple[str, ...]
    rank: int | None
    evidence_id: str | None
    evaluation_start: datetime | None
    ranking_explanation: str


def qualification_reasons(
    evidence: FollowerQualificationEvidence | None,
    policy: CohortSelectionPolicy,
    *,
    now: datetime,
) -> tuple[str, ...]:
    require_utc(now)
    if evidence is None:
        return ("independent_follower_evidence_missing",)
    reasons: list[str] = []
    if not evidence.complete:
        reasons.append("qualification_evidence_incomplete")
    if not evidence.selection_start < evidence.selection_end < evidence.evaluation_start:
        reasons.append("selection_and_evaluation_windows_overlap")
    if now >= evidence.evaluation_start or evidence.available_at >= evidence.evaluation_start:
        reasons.append("evaluation_already_started_before_selection")
    if not evidence.selection_end <= evidence.available_at <= now:
        reasons.append("qualification_unavailable_at_decision")
    if not evidence.selection_start <= evidence.last_activity_at <= evidence.selection_end:
        reasons.append("activity_outside_selection_window")
    if not timedelta(0) <= now - evidence.available_at <= policy.freshness:
        reasons.append("qualification_stale_or_future")
    if not timedelta(0) <= now - evidence.last_activity_at <= policy.freshness:
        reasons.append("activity_stale_or_future")
    if evidence.sample_count < policy.minimum_samples:
        reasons.append("insufficient_samples")
    required = (
        evidence.follower_net_per_unit,
        evidence.drawdown,
        evidence.spread,
        evidence.entry_depth,
        evidence.exit_depth,
        evidence.delay_seconds,
        evidence.concentration,
        evidence.correlation,
        evidence.confidence,
        evidence.cost_per_unit,
    )
    if any(value is None for value in required):
        reasons.append("economics_depth_cost_or_confidence_unknown")
    if evidence.route_compatible is not True:
        reasons.append("collateral_or_settlement_route_unverified")
    checks = (
        (evidence.spread, policy.maximum_spread, "spread_limit"),
        (evidence.drawdown, policy.maximum_drawdown, "drawdown_limit"),
        (evidence.delay_seconds, policy.maximum_delay_seconds, "delay_sensitivity_limit"),
        (evidence.concentration, policy.maximum_concentration, "concentration_limit"),
        (evidence.correlation, policy.maximum_correlation, "correlation_limit"),
    )
    reasons.extend(reason for value, limit, reason in checks if value is not None and value > limit)
    if evidence.confidence is not None and evidence.confidence < policy.minimum_confidence:
        reasons.append("confidence_below_minimum")
    if any(
        value is not None and value < policy.follower_size
        for value in (evidence.entry_depth, evidence.exit_depth)
    ):
        reasons.append("follower_size_exceeds_entry_or_exit_depth")
    if evidence.labels:
        reasons.append("strategy_compatibility_uncertain:" + ",".join(sorted(set(evidence.labels))))
    return tuple(reasons)
