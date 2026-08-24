from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import StrEnum

from polysia.domain.wallet_intelligence.candidate_intelligence import (
    CandidateStatus,
    DataReadinessStatus,
)

FEATURE_SET_VERSION = "copyability-v0.1"
POLICY_ID = "copyability-selection"
POLICY_VERSION = "v0.1"
RANKING_VERSION = "percentile-alpha-stress-v0.1"
DEFAULT_ALPHA_SIZE = 50
DEFAULT_STRESS_SIZE = 100
HEDGE_PCT_ALPHA_MAX = Decimal("50")
HEDGE_RISK_ALPHA_MAX = Decimal("80")
HEDGE_FLAG_WITHOUT_PCT_RISK = Decimal("60")
ALPHA_WEIGHTS = {
    "copyability_score": Decimal("0.35"),
    "performance_score": Decimal("0.25"),
    "recent_edge_score": Decimal("0.15"),
    "activity_score": Decimal("0.10"),
    "confidence_score": Decimal("0.10"),
    "stability_score": Decimal("0.05"),
}
_PERFORMANCE_FIELDS = (
    "actual_pnl",
    "roi",
    "win_rate",
    "avg_pnl_m",
    "avg_profit_loss_ratio",
)
_COPYABILITY_POSITIVE_FIELDS = ("copy_backtest_pnl", "r20_pnl", "r20_wr")
_COPYABILITY_INVERTED_FIELDS = ("copy_loss_rate", "r20_slip")
_DECIMAL_METRIC_FIELDS = (
    *_PERFORMANCE_FIELDS,
    *_COPYABILITY_POSITIVE_FIELDS,
    *_COPYABILITY_INVERTED_FIELDS,
    "trading_volume",
    "avg_invest",
    "buy_price",
    "hold_time",
    "last_2d",
    "hedged_pct",
    "score",
)
_INT_METRIC_FIELDS = ("markets_traded", "trading_days", "hedged")
_NON_NEGATIVE_FIELDS = frozenset(
    {"markets_traded", "trading_days", "trading_volume", "win_rate"}
)


class SelectionPoolId(StrEnum):
    SHADOW_ALPHA = "SHADOW_ALPHA"
    SHADOW_STRESS = "SHADOW_STRESS"
    LIVE_REVIEW_CANDIDATE = "LIVE_REVIEW_CANDIDATE"
    REJECTED = "REJECTED"


class SelectionStatus(StrEnum):
    REJECTED = "REJECTED"
    WATCHLIST = "WATCHLIST"
    SELECTED = "SELECTED"


class MetricsParseError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CopyabilityProcessingKey:
    stage2_run_id: str
    feature_set_version: str
    policy_id: str
    policy_version: str
    ranking_version: str


@dataclass(frozen=True, slots=True)
class CopyabilityEvidence:
    wallet_id: str
    stage2_run_id: str
    source_id: str
    source_snapshot_id: str
    source_rank: int
    source_score: Decimal | None
    source_metrics_json: str
    effective_at: datetime
    observed_at: datetime
    ingested_at: datetime
    stage2_calculated_at: datetime
    observation_count: int
    observed_days: int
    presence_ratio: Decimal
    rank_delta_7d: int | None
    rank_delta_30d: int | None
    score_delta_7d: Decimal | None
    score_delta_30d: Decimal | None
    rank_stability: Decimal | None
    score_stability: Decimal | None
    data_readiness_status: DataReadinessStatus
    candidate_status: CandidateStatus


@dataclass(frozen=True, slots=True)
class CopyabilityScore:
    wallet_id: str
    performance_score: Decimal | None
    recent_edge_score: Decimal | None
    activity_score: Decimal | None
    copyability_score: Decimal | None
    hedging_risk_score: Decimal | None
    confidence_score: Decimal | None
    stability_score: Decimal | None
    alpha_score: Decimal | None
    status: SelectionStatus
    reasons: tuple[str, ...]
    effective_at: datetime
    observed_at: datetime
    ingested_at: datetime
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class CopyabilityMembership:
    wallet_id: str
    pool_id: SelectionPoolId
    pool_rank: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CopyabilitySelectionRun:
    run_id: str
    key: CopyabilityProcessingKey
    source_id: str
    source_snapshot_id: str
    calculated_at: datetime
    published_at: datetime
    evaluated_count: int
    alpha_count: int
    stress_count: int
    live_review_count: int
    rejected_count: int
    watchlist_count: int
    overlap_count: int


@dataclass(frozen=True, slots=True)
class CopyabilitySelectionState:
    source_id: str
    current_run: CopyabilitySelectionRun | None
    last_run_id: str | None
    last_run_status: str | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class CopyabilityPoolRow:
    wallet_id: str
    source_id: str
    source_snapshot_id: str
    stage2_run_id: str
    pool_id: str
    pool_rank: int | None
    status: SelectionStatus
    alpha_score: Decimal | None
    copyability_score: Decimal | None
    performance_score: Decimal | None
    recent_edge_score: Decimal | None
    activity_score: Decimal | None
    hedging_risk_score: Decimal | None
    confidence_score: Decimal | None
    stability_score: Decimal | None
    reasons: tuple[str, ...]
    effective_at: datetime
    observed_at: datetime
    ingested_at: datetime
    calculated_at: datetime
    feature_set_version: str
    policy_id: str
    policy_version: str
    ranking_version: str
    run_id: str


MetricRow = dict[str, Decimal | int | None]


def select_copyability_pools(
    evidence: tuple[CopyabilityEvidence, ...],
    *,
    calculated_at: datetime,
    alpha_size: int = DEFAULT_ALPHA_SIZE,
    stress_size: int = DEFAULT_STRESS_SIZE,
) -> tuple[tuple[CopyabilityScore, ...], tuple[CopyabilityMembership, ...]]:
    if alpha_size < 1 or stress_size < 1:
        raise ValueError("selection sizes must be positive")
    if not evidence:
        raise ValueError("copyability evidence must not be empty")
    parsed = tuple(_try_parse_metrics(item.source_metrics_json) for item in evidence)
    scores = _score_wallets(evidence, parsed, calculated_at=calculated_at)
    memberships = _assign_pools(
        evidence,
        scores,
        parsed,
        alpha_size=alpha_size,
        stress_size=stress_size,
    )
    return finalize_scores_with_memberships(scores, memberships), memberships


def _try_parse_metrics(source_metrics_json: str) -> MetricRow | MetricsParseError:
    try:
        return _parse_metrics(source_metrics_json)
    except MetricsParseError as error:
        return error


def _parse_metrics(source_metrics_json: str) -> MetricRow:
    try:
        raw = json.loads(source_metrics_json)
    except (TypeError, ValueError) as error:
        raise MetricsParseError("metrics_json_invalid") from error
    if not isinstance(raw, dict):
        raise MetricsParseError("metrics_json_invalid")
    parsed: MetricRow = {}
    for field_name in _DECIMAL_METRIC_FIELDS:
        parsed[field_name] = _decimal_metric(raw.get(field_name), field_name=field_name)
    for field_name in _INT_METRIC_FIELDS:
        parsed[field_name] = _int_metric(raw.get(field_name), field_name=field_name)
    return parsed


def _decimal_metric(value: object, *, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise MetricsParseError(f"{field_name}_invalid")
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise MetricsParseError(f"{field_name}_invalid") from error
    if not parsed.is_finite():
        raise MetricsParseError(f"{field_name}_non_finite")
    if field_name == "hedged_pct" and (parsed < Decimal(0) or parsed > Decimal(100)):
        raise MetricsParseError("hedged_pct_out_of_range")
    if field_name in _NON_NEGATIVE_FIELDS and parsed < Decimal(0):
        raise MetricsParseError(f"{field_name}_negative")
    return parsed


def _int_metric(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MetricsParseError(f"{field_name}_invalid")
    if value < 0:
        raise MetricsParseError(f"{field_name}_negative")
    return value


def _score_wallets(
    evidence: tuple[CopyabilityEvidence, ...],
    parsed: tuple[MetricRow | MetricsParseError, ...],
    *,
    calculated_at: datetime,
) -> tuple[CopyabilityScore, ...]:
    rows: list[MetricRow | None] = []
    hard_reasons: list[tuple[str, ...]] = []
    for item, metrics in zip(evidence, parsed, strict=True):
        reasons: list[str] = []
        if item.data_readiness_status is DataReadinessStatus.INVALID:
            reasons.append("invalid_current_evidence")
        if isinstance(metrics, MetricsParseError):
            reasons.append(metrics.reason)
            rows.append(None)
        else:
            rows.append(metrics)
        hard_reasons.append(tuple(reasons))

    def decimals(field_name: str) -> list[Decimal | None]:
        values: list[Decimal | None] = []
        for row in rows:
            if row is None:
                values.append(None)
                continue
            value = row.get(field_name)
            values.append(value if isinstance(value, Decimal) else None)
        return values

    def ints(field_name: str) -> list[Decimal | None]:
        values: list[Decimal | None] = []
        for row in rows:
            if row is None:
                values.append(None)
                continue
            value = row.get(field_name)
            values.append(None if value is None else Decimal(int(value)))
        return values

    performance = _mean_percentiles(
        [_percentiles(decimals(name)) for name in _PERFORMANCE_FIELDS]
    )
    copyability = _mean_percentiles(
        [_percentiles(decimals(name)) for name in _COPYABILITY_POSITIVE_FIELDS]
        + [_invert(_percentiles(decimals(name))) for name in _COPYABILITY_INVERTED_FIELDS]
        + [_percentiles([item.presence_ratio for item in evidence])]
    )
    activity = _mean_percentiles(
        [
            _percentiles(decimals("trading_volume")),
            _percentiles(ints("markets_traded")),
            _percentiles(ints("trading_days")),
            _percentiles(
                [
                    None if hard_reasons[index] else Decimal(item.observation_count)
                    for index, item in enumerate(evidence)
                ]
            ),
        ]
    )
    recent_edge = _mean_percentiles(
        [
            _percentiles(decimals("last_2d")),
            _percentiles(decimals("r20_pnl")),
            _percentiles(decimals("r20_wr")),
            _invert(_percentiles(decimals("r20_slip"))),
            _percentiles(
                [
                    None if item.rank_delta_7d is None else Decimal(item.rank_delta_7d)
                    for item in evidence
                ]
            ),
            _percentiles([item.score_delta_7d for item in evidence]),
        ]
    )
    hedge_pct_percentiles = _percentiles(decimals("hedged_pct"))
    hedging_risk: list[Decimal | None] = []
    for index, row in enumerate(rows):
        if row is None:
            hedging_risk.append(None)
            continue
        hedged = row.get("hedged")
        hedge_pct = row.get("hedged_pct")
        if hedge_pct_percentiles[index] is not None:
            hedging_risk.append(hedge_pct_percentiles[index])
        elif isinstance(hedged, int) and hedged > 0:
            hedging_risk.append(HEDGE_FLAG_WITHOUT_PCT_RISK)
        elif hedged == 0 or hedge_pct == Decimal(0):
            hedging_risk.append(Decimal(0))
        else:
            hedging_risk.append(None)

    expected = len(_DECIMAL_METRIC_FIELDS) + len(_INT_METRIC_FIELDS)
    completeness: list[Decimal | None] = []
    for row in rows:
        if row is None:
            completeness.append(None)
            continue
        present = sum(1 for value in row.values() if value is not None)
        completeness.append(Decimal(present) / Decimal(expected) * Decimal(100))
    confidence = _mean_percentiles(
        [
            _percentiles(
                [
                    None if hard_reasons[index] else Decimal(item.observation_count)
                    for index, item in enumerate(evidence)
                ]
            ),
            _percentiles(
                [
                    None if hard_reasons[index] else item.presence_ratio
                    for index, item in enumerate(evidence)
                ]
            ),
            completeness,
        ]
    )
    stability = _mean_percentiles(
        [
            _percentiles([item.rank_stability for item in evidence]),
            _percentiles([item.score_stability for item in evidence]),
        ]
    )

    scores: list[CopyabilityScore] = []
    for index, item in enumerate(evidence):
        components = {
            "copyability_score": copyability[index],
            "performance_score": performance[index],
            "recent_edge_score": recent_edge[index],
            "activity_score": activity[index],
            "confidence_score": confidence[index],
            "stability_score": stability[index],
        }
        rejected = bool(hard_reasons[index])
        alpha = None if rejected else _weighted_alpha(components)
        if rejected:
            status = SelectionStatus.REJECTED
            reasons = list(hard_reasons[index])
        else:
            status = SelectionStatus.WATCHLIST
            reasons = ["valid_non_member"]
            if item.data_readiness_status is not DataReadinessStatus.READY:
                reasons.append(f"readiness_{item.data_readiness_status.value.lower()}")
            if components["copyability_score"] is None:
                reasons.append("copyability_evidence_missing")
            if item.rank_delta_7d is None or item.rank_delta_30d is None:
                reasons.append("historical_windows_incomplete")
            row = rows[index]
            hedge_pct = None if row is None else row.get("hedged_pct")
            hedged = None if row is None else row.get("hedged")
            if isinstance(hedge_pct, Decimal) and hedge_pct >= HEDGE_PCT_ALPHA_MAX:
                reasons.append("polycop_hedge_proxy_high")
            elif isinstance(hedged, int) and hedged > 0 and hedge_pct is None:
                reasons.append("polycop_hedge_flag_without_pct")
        scores.append(
            CopyabilityScore(
                wallet_id=item.wallet_id,
                performance_score=components["performance_score"],
                recent_edge_score=components["recent_edge_score"],
                activity_score=components["activity_score"],
                copyability_score=components["copyability_score"],
                hedging_risk_score=hedging_risk[index],
                confidence_score=components["confidence_score"],
                stability_score=components["stability_score"],
                alpha_score=alpha,
                status=status,
                reasons=tuple(dict.fromkeys(reasons)),
                effective_at=item.effective_at,
                observed_at=item.observed_at,
                ingested_at=item.ingested_at,
                calculated_at=calculated_at,
            )
        )
    return tuple(scores)


def _assign_pools(
    evidence: tuple[CopyabilityEvidence, ...],
    scores: tuple[CopyabilityScore, ...],
    parsed: tuple[MetricRow | MetricsParseError, ...],
    *,
    alpha_size: int,
    stress_size: int,
) -> tuple[CopyabilityMembership, ...]:
    by_id = {item.wallet_id: item for item in evidence}
    alpha_eligible: list[CopyabilityScore] = []
    stress_eligible: list[CopyabilityScore] = []
    rejected: list[CopyabilityScore] = []
    for index, score in enumerate(scores):
        if score.status is SelectionStatus.REJECTED:
            rejected.append(score)
            continue
        row = parsed[index]
        metrics = row if isinstance(row, dict) else None
        hedge_pct = None if metrics is None else metrics.get("hedged_pct")
        hedged = None if metrics is None else metrics.get("hedged")
        hedge_blocked = (
            (isinstance(hedge_pct, Decimal) and hedge_pct >= HEDGE_PCT_ALPHA_MAX)
            or (
                score.hedging_risk_score is not None
                and score.hedging_risk_score >= HEDGE_RISK_ALPHA_MAX
            )
            or (isinstance(hedged, int) and hedged > 0 and hedge_pct is None)
        )
        readiness = by_id[score.wallet_id].data_readiness_status
        if (
            readiness is DataReadinessStatus.READY
            and score.copyability_score is not None
            and score.alpha_score is not None
            and not hedge_blocked
        ):
            alpha_eligible.append(score)
        if score.activity_score is not None and readiness not in {
            DataReadinessStatus.STALE,
            DataReadinessStatus.UNKNOWN,
            DataReadinessStatus.INVALID,
        }:
            stress_eligible.append(score)

    alpha_eligible.sort(
        key=lambda item: (
            item.alpha_score is None,
            Decimal(0) if item.alpha_score is None else -item.alpha_score,
            item.copyability_score is None,
            Decimal(0) if item.copyability_score is None else -item.copyability_score,
            item.wallet_id,
        )
    )
    stress_eligible.sort(
        key=lambda item: (
            item.activity_score is None,
            Decimal(0) if item.activity_score is None else -item.activity_score,
            item.wallet_id,
        )
    )
    memberships: list[CopyabilityMembership] = []
    for rank, score in enumerate(alpha_eligible[:alpha_size], 1):
        memberships.append(
            CopyabilityMembership(
                wallet_id=score.wallet_id,
                pool_id=SelectionPoolId.SHADOW_ALPHA,
                pool_rank=rank,
                reasons=("copyability_oriented_shadow_alpha",),
            )
        )
    for rank, score in enumerate(stress_eligible[:stress_size], 1):
        memberships.append(
            CopyabilityMembership(
                wallet_id=score.wallet_id,
                pool_id=SelectionPoolId.SHADOW_STRESS,
                pool_rank=rank,
                reasons=("high_activity_shadow_stress",),
            )
        )
    rejected.sort(key=lambda item: item.wallet_id)
    for rank, score in enumerate(rejected, 1):
        memberships.append(
            CopyabilityMembership(
                wallet_id=score.wallet_id,
                pool_id=SelectionPoolId.REJECTED,
                pool_rank=rank,
                reasons=score.reasons,
            )
        )
    return tuple(memberships)


def finalize_scores_with_memberships(
    scores: tuple[CopyabilityScore, ...],
    memberships: tuple[CopyabilityMembership, ...],
) -> tuple[CopyabilityScore, ...]:
    selected = {
        item.wallet_id
        for item in memberships
        if item.pool_id in {SelectionPoolId.SHADOW_ALPHA, SelectionPoolId.SHADOW_STRESS}
    }
    alpha_ids = {
        item.wallet_id for item in memberships if item.pool_id is SelectionPoolId.SHADOW_ALPHA
    }
    stress_ids = {
        item.wallet_id for item in memberships if item.pool_id is SelectionPoolId.SHADOW_STRESS
    }
    finalized: list[CopyabilityScore] = []
    for score in scores:
        if score.status is SelectionStatus.REJECTED or score.wallet_id not in selected:
            finalized.append(score)
            continue
        reasons = [reason for reason in score.reasons if reason != "valid_non_member"]
        if score.wallet_id in alpha_ids:
            reasons.append("shadow_alpha_member")
        if score.wallet_id in stress_ids:
            reasons.append("shadow_stress_member")
        finalized.append(
            CopyabilityScore(
                wallet_id=score.wallet_id,
                performance_score=score.performance_score,
                recent_edge_score=score.recent_edge_score,
                activity_score=score.activity_score,
                copyability_score=score.copyability_score,
                hedging_risk_score=score.hedging_risk_score,
                confidence_score=score.confidence_score,
                stability_score=score.stability_score,
                alpha_score=score.alpha_score,
                status=SelectionStatus.SELECTED,
                reasons=tuple(dict.fromkeys(reasons)),
                effective_at=score.effective_at,
                observed_at=score.observed_at,
                ingested_at=score.ingested_at,
                calculated_at=score.calculated_at,
            )
        )
    return tuple(finalized)


def _percentiles(values: list[Decimal | None]) -> list[Decimal | None]:
    indexed = [(index, value) for index, value in enumerate(values) if value is not None]
    result: list[Decimal | None] = [None] * len(values)
    if not indexed:
        return result
    indexed.sort(key=lambda item: (item[1], item[0]))
    count = len(indexed)
    if count == 1:
        result[indexed[0][0]] = Decimal("50")
        return result
    with localcontext() as context:
        context.prec = 28
        start = 0
        while start < count:
            end = start
            while end + 1 < count and indexed[end + 1][1] == indexed[start][1]:
                end += 1
            average_rank = (Decimal(start + 1) + Decimal(end + 1)) / Decimal(2)
            percentile = (average_rank - Decimal(1)) / Decimal(count - 1) * Decimal(100)
            for offset in range(start, end + 1):
                result[indexed[offset][0]] = percentile
            start = end + 1
    return result


def _invert(values: list[Decimal | None]) -> list[Decimal | None]:
    return [None if value is None else Decimal(100) - value for value in values]


def _mean_percentiles(columns: list[list[Decimal | None]]) -> list[Decimal | None]:
    if not columns:
        return []
    length = len(columns[0])
    result: list[Decimal | None] = []
    with localcontext() as context:
        context.prec = 28
        for index in range(length):
            present: list[Decimal] = []
            for column in columns:
                value = column[index]
                if value is not None:
                    present.append(value)
            if not present:
                result.append(None)
            else:
                result.append(sum(present, Decimal(0)) / Decimal(len(present)))
    return result


def _weighted_alpha(component: dict[str, Decimal | None]) -> Decimal | None:
    with localcontext() as context:
        context.prec = 28
        usable = {
            name: value
            for name, value in component.items()
            if value is not None and name in ALPHA_WEIGHTS
        }
        if not usable:
            return None
        weight_total = sum((ALPHA_WEIGHTS[name] for name in usable), Decimal(0))
        weighted = sum((value * ALPHA_WEIGHTS[name] for name, value in usable.items()), Decimal(0))
        return weighted / weight_total
