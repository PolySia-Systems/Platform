"""Produce point-in-time metrics from retained causal follower observations.

Empirical forward-price estimates are experimental predictors, not provider-rank
probabilities. Missing/censored cost, quotes or paired returns stay UNKNOWN.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from polysia.domain.financial_session import SessionBlocked, decimal_value, digest, utc
from polysia.domain.wallet_intelligence.source_cohort import FollowerQualificationEvidence

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class FollowerSample:
    wallet: str
    token: str
    occurrence_id: str
    source_at: datetime
    admission_at: datetime
    entry_quote_at: datetime
    forward_quote_at: datetime
    available_at: datetime
    entry_price: Decimal
    forward_bid: Decimal | None
    spread: Decimal | None
    entry_depth: Decimal | None
    exit_depth: Decimal | None
    cost_per_share: Decimal | None
    route_verified: bool
    complete: bool
    source_digest: str

    def __post_init__(self) -> None:
        times = (
            self.source_at,
            self.admission_at,
            self.entry_quote_at,
            self.forward_quote_at,
            self.available_at,
        )
        for timestamp in times:
            utc(timestamp)
        if (
            not self.source_at
            <= self.admission_at
            <= self.entry_quote_at
            < self.forward_quote_at
            <= self.available_at
        ):
            raise SessionBlocked("follower_sample_is_not_causal")
        for value in (
            self.entry_price,
            self.forward_bid,
            self.spread,
            self.entry_depth,
            self.exit_depth,
            self.cost_per_share,
        ):
            if value is not None:
                decimal_value(value)
        if (
            not self.wallet
            or not self.token
            or not self.occurrence_id
            or not self.source_digest
            or not 0 < self.entry_price < 1
            or self.forward_bid is not None
            and self.forward_bid > 1
        ):
            raise SessionBlocked("invalid_follower_sample")


@dataclass(frozen=True, slots=True)
class EmpiricalForwardEstimate:
    wallet: str
    token: str
    fair_price: Decimal | None
    uncertainty: Decimal | None
    sample_count: int
    confidence: Decimal
    available_at: datetime
    selection_end: datetime
    evidence_digest: str
    method: str = "bounded-forward-price-hoeffding/v1"
    assumptions: str = (
        "Experimental bounded independent samples; "
        "stationarity and calibration require qualification"
    )


def estimate_forward_price(
    samples: tuple[FollowerSample, ...],
    *,
    wallet: str,
    token: str,
    selection_end: datetime,
    available_at: datetime,
    confidence: Decimal,
    minimum_samples: int,
) -> EmpiricalForwardEstimate:
    if not 0 < confidence < 1 or minimum_samples <= 0:
        raise SessionBlocked("explicit_estimator_sample_confidence_required")
    retained = _retained(samples, selection_end=selection_end, available_at=available_at)
    usable = tuple(
        sample
        for sample in retained
        if sample.wallet == wallet and sample.token == token and _usable(sample)
    )
    count = len(usable)
    values = [sample.forward_bid for sample in usable if sample.forward_bid is not None]
    fair = sum(values, ZERO) / count if count >= minimum_samples else None
    # Range [0,1], a fixed confidence and one predeclared estimate. No parameter
    # search, rank conversion or automatically positive conservative edge.
    uncertainty = (
        ((Decimal(2) / (1 - confidence)).ln() / (2 * count)).sqrt()
        if (count >= minimum_samples)
        else None
    )
    return EmpiricalForwardEstimate(
        wallet,
        token,
        fair,
        uncertainty,
        count,
        confidence,
        available_at,
        selection_end,
        digest([asdict(sample) for sample in usable]),
    )


def produce_qualification(
    samples: tuple[FollowerSample, ...],
    *,
    wallet: str,
    selection_start: datetime,
    selection_end: datetime,
    available_at: datetime,
    evaluation_start: datetime,
    confidence: Decimal,
) -> FollowerQualificationEvidence:
    if not 0 < confidence < 1:
        raise SessionBlocked("qualification_confidence_required")
    if not utc(selection_start) < utc(selection_end) <= utc(available_at) < utc(evaluation_start):
        raise SessionBlocked("qualification_selection_evaluation_leakage")
    retained = _retained(samples, selection_end=selection_end, available_at=available_at)
    rows = tuple(
        sample
        for sample in retained
        if sample.wallet == wallet and sample.source_at >= selection_start
    )
    usable = tuple(sample for sample in rows if _usable(sample))
    returns = [_net(sample) for sample in usable]
    count = len(usable)
    peak = cumulative = drawdown = ZERO
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    tokens = Counter(sample.token for sample in usable)
    correlation = _correlation(wallet, retained)
    return FollowerQualificationEvidence(
        wallet,
        digest([asdict(sample) for sample in rows]),
        selection_start,
        selection_end,
        evaluation_start,
        available_at,
        max((sample.source_at for sample in rows), default=selection_start),
        count,
        # Returns are bounded [-2, 1] under the explicit usable cost bound.
        # A positive sample mean alone is not evidence of positive net edge.
        sum(returns, ZERO) / count - 3 * ((Decimal(2) / (1 - confidence)).ln() / (2 * count)).sqrt()
        if count
        else None,
        drawdown if count else None,
        max((sample.spread for sample in usable if sample.spread is not None), default=None),
        min(
            (sample.entry_depth for sample in usable if sample.entry_depth is not None),
            default=None,
        ),
        min(
            (sample.exit_depth for sample in usable if sample.exit_depth is not None), default=None
        ),
        max(
            (
                Decimal(str((sample.entry_quote_at - sample.source_at).total_seconds()))
                for sample in usable
            ),
            default=None,
        ),
        Decimal(max(tokens.values())) / count if count else None,
        correlation,
        confidence if count else None,
        max(
            (sample.cost_per_share for sample in usable if sample.cost_per_share is not None),
            default=None,
        ),
        all(sample.route_verified for sample in rows) if rows else None,
        bool(rows) and count == len(rows),
        (),
    )


def _retained(
    samples: Iterable[FollowerSample],
    *,
    selection_end: datetime,
    available_at: datetime,
) -> tuple[FollowerSample, ...]:
    unique: dict[tuple[str, str], FollowerSample] = {}
    for sample in samples:
        if sample.forward_quote_at > selection_end or sample.available_at > available_at:
            raise SessionBlocked("follower_evidence_not_available_at_selection")
        key = (sample.wallet, sample.occurrence_id)
        if key in unique and unique[key] != sample:
            raise SessionBlocked("conflicting_follower_occurrence")
        unique[key] = sample
    return tuple(sorted(unique.values(), key=lambda row: (row.source_at, row.occurrence_id)))


def _usable(sample: FollowerSample) -> bool:
    return (
        sample.complete
        and sample.route_verified
        and sample.cost_per_share is not None
        and sample.cost_per_share <= 1
        and all(
            value is not None
            for value in (
                sample.forward_bid,
                sample.spread,
                sample.entry_depth,
                sample.exit_depth,
                sample.cost_per_share,
            )
        )
    )


def _net(sample: FollowerSample) -> Decimal:
    assert sample.forward_bid is not None and sample.cost_per_share is not None
    return sample.forward_bid - sample.entry_price - sample.cost_per_share


def _correlation(wallet: str, samples: tuple[FollowerSample, ...]) -> Decimal | None:
    groups: dict[str, dict[datetime, Decimal]] = defaultdict(dict)
    for row in samples:
        if _usable(row):
            groups[row.wallet][row.forward_quote_at] = _net(row)
    correlations = []
    for other, values in groups.items():
        if other == wallet:
            continue
        common = sorted(set(values) & set(groups[wallet]))
        if len(common) < 3:
            continue
        x, y = [groups[wallet][key] for key in common], [values[key] for key in common]
        mx, my = sum(x, ZERO) / len(x), sum(y, ZERO) / len(y)
        sx = sum(((value - mx) ** 2 for value in x), ZERO)
        sy = sum(((value - my) ** 2 for value in y), ZERO)
        if sx and sy:
            correlations.append(
                abs(
                    sum(((a - mx) * (b - my) for a, b in zip(x, y, strict=True)), ZERO)
                    / (sx * sy).sqrt()
                )
            )
    return min(Decimal(1), max(correlations)) if correlations else None
