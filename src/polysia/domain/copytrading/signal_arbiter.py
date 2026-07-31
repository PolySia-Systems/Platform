from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

_WALLET_FRAGMENT = re.compile(r"(?<![0-9a-fA-F])0x[a-fA-F0-9]{40}(?![0-9a-fA-F])")
_LN_TWO = Decimal("0.693147180559945309417232121458176568")
_ZERO = Decimal("0")
_ONE = Decimal("1")


class ArbiterMode(StrEnum):
    """Research-only selection policies supported by chronological Replay."""

    CURRENT = "current"
    COOLDOWN_ONLY = "cooldown_only"
    FULL = "full"


class AssessmentStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class ConcentrationCause(StrEnum):
    LATE_SIGNAL = "LATE_SIGNAL"
    COMPLETED_CYCLE = "COMPLETED_CYCLE"


@dataclass(frozen=True, slots=True)
class SignalContext:
    market_type: str
    timeframe_seconds: int

    def __post_init__(self) -> None:
        _safe_identifier("market_type", self.market_type)
        if self.timeframe_seconds <= 0:
            raise ValueError("timeframe_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ExecutableEvidence:
    """Decision-time book and cost evidence; missing values remain unknown."""

    leader_price: Decimal | None
    executable_price: Decimal | None
    quantity: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    expected_fees: Decimal | None
    estimated_slippage: Decimal | None
    captured_at: datetime | None

    def assess(self, *, as_of: datetime, maximum_age: timedelta) -> ExecutableEdge:
        _require_utc("as_of", as_of)
        values = {
            "leader_price": self.leader_price,
            "executable_price": self.executable_price,
            "quantity": self.quantity,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "expected_fees": self.expected_fees,
            "estimated_slippage": self.estimated_slippage,
        }
        missing = tuple(name for name, value in values.items() if value is None)
        if self.captured_at is None:
            missing += ("captured_at",)
        if missing:
            return ExecutableEdge.unknown(f"missing decision-time evidence: {', '.join(missing)}")

        captured_at = self.captured_at
        assert captured_at is not None
        _require_utc("captured_at", captured_at)
        age = as_of - captured_at
        if age < timedelta(0):
            return ExecutableEdge.unknown("order-book evidence is from the future")
        if age > maximum_age:
            return ExecutableEdge.unknown("order-book evidence is stale")

        leader_price = values["leader_price"]
        executable_price = values["executable_price"]
        quantity = values["quantity"]
        best_bid = values["best_bid"]
        best_ask = values["best_ask"]
        expected_fees = values["expected_fees"]
        estimated_slippage = values["estimated_slippage"]
        assert isinstance(leader_price, Decimal)
        assert isinstance(executable_price, Decimal)
        assert isinstance(quantity, Decimal)
        assert isinstance(best_bid, Decimal)
        assert isinstance(best_ask, Decimal)
        assert isinstance(expected_fees, Decimal)
        assert isinstance(estimated_slippage, Decimal)

        if not _ZERO < leader_price < _ONE:
            return ExecutableEdge.unknown("leader price is outside (0, 1)")
        if not _ZERO < executable_price < _ONE:
            return ExecutableEdge.unknown("executable price is outside (0, 1)")
        if quantity <= _ZERO:
            return ExecutableEdge.unknown("quantity is not positive")
        if not _ZERO <= best_bid <= best_ask <= _ONE:
            return ExecutableEdge.unknown("order-book spread is invalid")
        if expected_fees < _ZERO or estimated_slippage < _ZERO:
            return ExecutableEdge.unknown("fees and slippage must not be negative")
        if executable_price >= best_ask:
            return ExecutableEdge.unknown("executable price would cross the observed ask")

        reference_cost = leader_price * quantity
        all_in_cost = (
            executable_price * quantity + expected_fees + estimated_slippage
        )
        return ExecutableEdge(
            status=AssessmentStatus.ELIGIBLE,
            net_edge=reference_cost - all_in_cost,
            spread_cost=(best_ask - best_bid) * quantity,
            reason="decision-time execution evidence is complete",
        )


@dataclass(frozen=True, slots=True)
class ExecutableEdge:
    status: AssessmentStatus
    net_edge: Decimal | None
    spread_cost: Decimal | None
    reason: str

    @classmethod
    def unknown(cls, reason: str) -> ExecutableEdge:
        return cls(
            status=AssessmentStatus.UNKNOWN,
            net_edge=None,
            spread_cost=None,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    signal_id: str
    leader_key: str
    context: SignalContext
    executed_at: datetime
    observed_at: datetime
    safety_eligible: bool
    safety_reason: str
    evidence: ExecutableEvidence

    def __post_init__(self) -> None:
        _safe_identifier("signal_id", self.signal_id)
        _safe_identifier("leader_key", self.leader_key)
        _require_utc("executed_at", self.executed_at)
        _require_utc("observed_at", self.observed_at)
        if self.observed_at < self.executed_at:
            raise ValueError("observed_at must not precede executed_at")
        if not self.safety_reason:
            raise ValueError("safety_reason must not be empty")
        if _WALLET_FRAGMENT.search(self.safety_reason):
            raise ValueError("safety_reason must not contain a wallet address")


@dataclass(frozen=True, slots=True)
class ClosedSignalOutcome:
    outcome_id: str
    leader_key: str
    context: SignalContext
    opened_at: datetime
    closed_at: datetime
    net_return: Decimal
    maximum_drawdown: Decimal

    def __post_init__(self) -> None:
        _safe_identifier("outcome_id", self.outcome_id)
        _safe_identifier("leader_key", self.leader_key)
        _require_utc("opened_at", self.opened_at)
        _require_utc("closed_at", self.closed_at)
        if self.closed_at < self.opened_at:
            raise ValueError("closed_at must not precede opened_at")
        if self.maximum_drawdown < _ZERO:
            raise ValueError("maximum_drawdown must not be negative")


@dataclass(frozen=True, slots=True)
class FollowerExecutionOutcome:
    execution_id: str
    leader_key: str
    context: SignalContext
    closed_at: datetime
    filled: bool
    net_pnl: Decimal | None
    execution_cost: Decimal | None
    slippage: Decimal | None
    completed_cycle: bool = False

    def __post_init__(self) -> None:
        _safe_identifier("execution_id", self.execution_id)
        _safe_identifier("leader_key", self.leader_key)
        _require_utc("closed_at", self.closed_at)
        if self.filled and self.net_pnl is None:
            raise ValueError("a filled follower execution requires net_pnl")
        if self.completed_cycle and not self.filled:
            raise ValueError("a completed follower cycle requires a filled entry")
        if self.execution_cost is not None and self.execution_cost < _ZERO:
            raise ValueError("execution_cost must not be negative")
        if self.slippage is not None and self.slippage < _ZERO:
            raise ValueError("slippage must not be negative")


@dataclass(frozen=True, slots=True)
class ConcentrationEvent:
    event_id: str
    leader_key: str
    cause: ConcentrationCause
    occurred_at: datetime

    def __post_init__(self) -> None:
        _safe_identifier("event_id", self.event_id)
        _safe_identifier("leader_key", self.leader_key)
        _require_utc("occurred_at", self.occurred_at)


@dataclass(frozen=True, slots=True)
class SignalArbiterConfig:
    maximum_signal_age: timedelta = timedelta(seconds=10)
    maximum_evidence_age: timedelta = timedelta(seconds=5)
    evidence_half_life: timedelta = timedelta(days=30)
    neutral_prior_weight: Decimal = Decimal("20")
    neutral_prior_variance: Decimal = Decimal("0.01")
    uncertainty_multiplier: Decimal = Decimal("1.645")
    executable_edge_tolerance: Decimal = Decimal("0.01")
    wallet_score_tolerance: Decimal = Decimal("0.01")
    completed_cycle_durations: tuple[timedelta, ...] = (
        timedelta(minutes=30),
        timedelta(minutes=60),
        timedelta(minutes=120),
    )
    concentration_level_decay: timedelta = timedelta(hours=24)
    late_signal_window: timedelta = timedelta(minutes=30)
    late_signal_repeat_threshold: int = 2
    late_signal_penalty: timedelta = timedelta(minutes=10)

    def __post_init__(self) -> None:
        if self.maximum_signal_age != timedelta(seconds=10):
            raise ValueError("the Signal Arbiter freshness limit must remain ten seconds")
        positive_durations = (
            self.maximum_signal_age,
            self.maximum_evidence_age,
            self.evidence_half_life,
            self.concentration_level_decay,
            self.late_signal_window,
            self.late_signal_penalty,
            *self.completed_cycle_durations,
        )
        if any(value <= timedelta(0) for value in positive_durations):
            raise ValueError("Arbiter durations must be positive")
        if self.neutral_prior_weight <= _ZERO:
            raise ValueError("neutral_prior_weight must be positive")
        if self.neutral_prior_variance < _ZERO:
            raise ValueError("neutral_prior_variance must not be negative")
        if self.uncertainty_multiplier < _ZERO:
            raise ValueError("uncertainty_multiplier must not be negative")
        if self.executable_edge_tolerance < _ZERO or self.wallet_score_tolerance < _ZERO:
            raise ValueError("selection tolerances must not be negative")
        if self.late_signal_repeat_threshold < 2:
            raise ValueError("late_signal_repeat_threshold must be at least two")


@dataclass(frozen=True, slots=True)
class WalletQualityScore:
    source: str
    sample_count: int
    effective_sample_weight: Decimal
    posterior_mean: Decimal
    uncertainty: Decimal
    confidence: Decimal
    conservative_score: Decimal


@dataclass(frozen=True, slots=True)
class ConcentrationAssessment:
    level: int
    penalty: Decimal
    reason: str


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    signal_id: str
    leader_key: str
    status: AssessmentStatus
    reason: str
    net_edge: Decimal | None = None
    spread_cost: Decimal | None = None
    wallet_score: WalletQualityScore | None = None
    concentration: ConcentrationAssessment | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "leader_key": self.leader_key,
            "reason": self.reason,
            "signal_id": self.signal_id,
            "status": self.status.value,
        }
        if self.net_edge is not None:
            payload["net_edge"] = str(self.net_edge)
        if self.spread_cost is not None:
            payload["spread_cost"] = str(self.spread_cost)
        if self.wallet_score is not None:
            payload["wallet_score"] = {
                "confidence": str(self.wallet_score.confidence),
                "conservative_score": str(self.wallet_score.conservative_score),
                "effective_sample_weight": str(
                    self.wallet_score.effective_sample_weight
                ),
                "posterior_mean": str(self.wallet_score.posterior_mean),
                "sample_count": self.wallet_score.sample_count,
                "source": self.wallet_score.source,
                "uncertainty": str(self.wallet_score.uncertainty),
            }
        if self.concentration is not None:
            payload["concentration"] = {
                "level": self.concentration.level,
                "penalty": str(self.concentration.penalty),
                "reason": self.concentration.reason,
            }
        return payload


@dataclass(frozen=True, slots=True)
class ArbiterDecision:
    mode: ArbiterMode
    decided_at: datetime
    selected_signal_id: str | None
    selected_leader_key: str | None
    assessments: tuple[CandidateAssessment, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "assessments": [assessment.to_dict() for assessment in self.assessments],
            "decided_at": self.decided_at.isoformat(),
            "mode": self.mode.value,
            "selected_leader_key": self.selected_leader_key,
            "selected_signal_id": self.selected_signal_id,
        }


class SignalArbiter:
    """Pure, synchronous selector. It never waits for another signal or mutates state."""

    def __init__(self, config: SignalArbiterConfig | None = None) -> None:
        self._config = config or SignalArbiterConfig()

    def decide(
        self,
        candidates: tuple[SignalCandidate, ...],
        *,
        mode: ArbiterMode,
        as_of: datetime,
        wallet_outcomes: tuple[ClosedSignalOutcome, ...] = (),
        concentration_events: tuple[ConcentrationEvent, ...] = (),
        used_leaders: frozenset[str] = frozenset(),
    ) -> ArbiterDecision:
        _require_utc("as_of", as_of)
        assessments: list[CandidateAssessment] = []
        eligible: list[tuple[SignalCandidate, CandidateAssessment]] = []
        seen_signal_ids: set[str] = set()

        for candidate in candidates:
            if candidate.signal_id in seen_signal_ids:
                assessments.append(
                    CandidateAssessment(
                        signal_id=candidate.signal_id,
                        leader_key=candidate.leader_key,
                        status=AssessmentStatus.REJECTED,
                        reason="duplicate signal identifier in ready snapshot",
                    )
                )
                continue
            seen_signal_ids.add(candidate.signal_id)
            if not candidate.safety_eligible:
                assessments.append(
                    CandidateAssessment(
                        signal_id=candidate.signal_id,
                        leader_key=candidate.leader_key,
                        status=AssessmentStatus.REJECTED,
                        reason=f"safety rejected: {candidate.safety_reason}",
                    )
                )
                continue
            age = as_of - candidate.executed_at
            if age < timedelta(0) or age > self._config.maximum_signal_age:
                assessments.append(
                    CandidateAssessment(
                        signal_id=candidate.signal_id,
                        leader_key=candidate.leader_key,
                        status=AssessmentStatus.REJECTED,
                        reason="signal is outside the unchanged freshness window",
                    )
                )
                continue
            if mode is ArbiterMode.CURRENT and candidate.leader_key in used_leaders:
                assessments.append(
                    CandidateAssessment(
                        signal_id=candidate.signal_id,
                        leader_key=candidate.leader_key,
                        status=AssessmentStatus.REJECTED,
                        reason="current policy permits one attempt per leader per run",
                    )
                )
                continue
            edge = candidate.evidence.assess(
                as_of=as_of,
                maximum_age=self._config.maximum_evidence_age,
            )
            if edge.status is AssessmentStatus.UNKNOWN or edge.net_edge is None:
                assessments.append(
                    CandidateAssessment(
                        signal_id=candidate.signal_id,
                        leader_key=candidate.leader_key,
                        status=AssessmentStatus.UNKNOWN,
                        reason=edge.reason,
                    )
                )
                continue
            score = score_wallet_quality(
                wallet_outcomes,
                leader_key=candidate.leader_key,
                context=candidate.context,
                as_of=as_of,
                config=self._config,
            )
            concentration = assess_concentration(
                concentration_events,
                leader_key=candidate.leader_key,
                as_of=as_of,
                config=self._config,
            )
            assessment = CandidateAssessment(
                signal_id=candidate.signal_id,
                leader_key=candidate.leader_key,
                status=AssessmentStatus.ELIGIBLE,
                reason="eligible decision-time snapshot",
                net_edge=edge.net_edge,
                spread_cost=edge.spread_cost,
                wallet_score=score,
                concentration=concentration,
            )
            assessments.append(assessment)
            eligible.append((candidate, assessment))

        selected = self._select(eligible, mode=mode)
        return ArbiterDecision(
            mode=mode,
            decided_at=as_of,
            selected_signal_id=None if selected is None else selected[0].signal_id,
            selected_leader_key=None if selected is None else selected[0].leader_key,
            assessments=tuple(assessments),
        )

    def _select(
        self,
        eligible: list[tuple[SignalCandidate, CandidateAssessment]],
        *,
        mode: ArbiterMode,
    ) -> tuple[SignalCandidate, CandidateAssessment] | None:
        if not eligible:
            return None
        if mode is ArbiterMode.CURRENT:
            return min(
                eligible,
                key=lambda item: (
                    item[0].executed_at,
                    item[0].leader_key,
                    item[0].signal_id,
                ),
            )

        best_edge = max(_required_edge(item[1]) for item in eligible)
        edge_band = [
            item
            for item in eligible
            if best_edge - _required_edge(item[1]) <= self._config.executable_edge_tolerance
        ]
        if mode is ArbiterMode.COOLDOWN_ONLY:
            return min(edge_band, key=_concentration_tie_key)

        best_wallet_score = max(_required_wallet_score(item[1]) for item in edge_band)
        wallet_band = [
            item
            for item in edge_band
            if best_wallet_score - _required_wallet_score(item[1])
            <= self._config.wallet_score_tolerance
        ]
        return min(wallet_band, key=_concentration_tie_key)


def score_wallet_quality(
    outcomes: tuple[ClosedSignalOutcome, ...],
    *,
    leader_key: str,
    context: SignalContext,
    as_of: datetime,
    config: SignalArbiterConfig | None = None,
) -> WalletQualityScore:
    """Return a walk-forward empirical-Bayes score from already-closed outcomes."""

    _safe_identifier("leader_key", leader_key)
    _require_utc("as_of", as_of)
    settings = config or SignalArbiterConfig()
    closed = tuple(
        outcome
        for outcome in outcomes
        if outcome.leader_key == leader_key and outcome.closed_at <= as_of
    )
    contextual = tuple(outcome for outcome in closed if outcome.context == context)
    selected = contextual or closed
    source = "context" if contextual else "global_fallback"
    return _posterior_score(selected, as_of=as_of, source=source, config=settings)


def assess_concentration(
    events: tuple[ConcentrationEvent, ...],
    *,
    leader_key: str,
    as_of: datetime,
    config: SignalArbiterConfig | None = None,
) -> ConcentrationAssessment:
    _safe_identifier("leader_key", leader_key)
    _require_utc("as_of", as_of)
    settings = config or SignalArbiterConfig()
    relevant = tuple(
        sorted(
            (
                event
                for event in events
                if event.leader_key == leader_key and event.occurred_at <= as_of
            ),
            key=lambda event: (event.occurred_at, event.event_id),
        )
    )
    completed = tuple(
        event for event in relevant if event.cause is ConcentrationCause.COMPLETED_CYCLE
    )
    level = 0
    cycle_penalty = _ZERO
    cycle_reason = "no completed-cycle concentration"
    if completed:
        previous_cycle: datetime | None = None
        for event in completed:
            if previous_cycle is not None:
                decay_steps = int(
                    (event.occurred_at - previous_cycle)
                    / settings.concentration_level_decay
                )
                level = max(0, level - decay_steps)
            level = min(len(settings.completed_cycle_durations), level + 1)
            previous_cycle = event.occurred_at
        last_cycle = completed[-1].occurred_at
        idle = as_of - last_cycle
        decay_steps = int(idle / settings.concentration_level_decay)
        level = max(0, level - decay_steps)
        if level > 0:
            duration = settings.completed_cycle_durations[level - 1]
            remaining = duration - idle
            if remaining > timedelta(0):
                cycle_penalty = _timedelta_ratio(remaining, duration)
                cycle_reason = f"adaptive completed-cycle level {level}"

    late = tuple(
        event
        for event in relevant
        if event.cause is ConcentrationCause.LATE_SIGNAL
        and as_of - event.occurred_at <= settings.late_signal_window
    )
    late_penalty = _ZERO
    late_reason = "no repeated-late-signal concentration"
    if len(late) >= settings.late_signal_repeat_threshold:
        remaining = settings.late_signal_penalty - (as_of - late[-1].occurred_at)
        if remaining > timedelta(0):
            late_penalty = _timedelta_ratio(remaining, settings.late_signal_penalty)
            late_reason = "repeated late signals"

    if late_penalty > cycle_penalty:
        return ConcentrationAssessment(level=level, penalty=late_penalty, reason=late_reason)
    return ConcentrationAssessment(level=level, penalty=cycle_penalty, reason=cycle_reason)


def summarize_follower_execution_quality(
    outcomes: tuple[FollowerExecutionOutcome, ...],
    *,
    as_of: datetime,
) -> dict[str, object]:
    """Keep follower execution evidence separate from leader-quality scoring."""

    _require_utc("as_of", as_of)
    closed = tuple(outcome for outcome in outcomes if outcome.closed_at <= as_of)
    filled = tuple(outcome for outcome in closed if outcome.filled)
    complete_costs = tuple(
        outcome.execution_cost for outcome in filled if outcome.execution_cost is not None
    )
    complete_slippage = tuple(
        outcome.slippage for outcome in filled if outcome.slippage is not None
    )
    complete_pnl = tuple(outcome.net_pnl for outcome in filled if outcome.net_pnl is not None)
    return {
        "closed_execution_count": len(closed),
        "fill_count": len(filled),
        "fill_rate": None if not closed else str(Decimal(len(filled)) / Decimal(len(closed))),
        "known_cost_count": len(complete_costs),
        "known_pnl_count": len(complete_pnl),
        "known_slippage_count": len(complete_slippage),
        "net_pnl": None if not complete_pnl else str(sum(complete_pnl, _ZERO)),
        "total_execution_cost": (
            None if not complete_costs else str(sum(complete_costs, _ZERO))
        ),
        "total_slippage": (
            None if not complete_slippage else str(sum(complete_slippage, _ZERO))
        ),
    }


def _posterior_score(
    outcomes: tuple[ClosedSignalOutcome, ...],
    *,
    as_of: datetime,
    source: str,
    config: SignalArbiterConfig,
) -> WalletQualityScore:
    weights = tuple(
        _decay_weight(as_of - outcome.closed_at, config.evidence_half_life)
        for outcome in outcomes
    )
    sample_weight = sum(weights, _ZERO)
    total_weight = config.neutral_prior_weight + sample_weight
    weighted_sum = sum(
        (weight * outcome.net_return for weight, outcome in zip(weights, outcomes, strict=True)),
        _ZERO,
    )
    posterior_mean = weighted_sum / total_weight
    weighted_second_moment = sum(
        (
            weight * outcome.net_return * outcome.net_return
            for weight, outcome in zip(weights, outcomes, strict=True)
        ),
        config.neutral_prior_weight * config.neutral_prior_variance,
    )
    variance = max(_ZERO, weighted_second_moment / total_weight - posterior_mean**2)
    uncertainty = (variance / total_weight).sqrt()
    confidence = sample_weight / total_weight
    conservative = posterior_mean - config.uncertainty_multiplier * uncertainty * confidence
    return WalletQualityScore(
        source=source,
        sample_count=len(outcomes),
        effective_sample_weight=sample_weight,
        posterior_mean=posterior_mean,
        uncertainty=uncertainty,
        confidence=confidence,
        conservative_score=conservative,
    )


def _decay_weight(age: timedelta, half_life: timedelta) -> Decimal:
    if age < timedelta(0):
        raise ValueError("walk-forward scoring cannot use a future outcome")
    age_seconds = Decimal(str(age.total_seconds()))
    half_life_seconds = Decimal(str(half_life.total_seconds()))
    return (-_LN_TWO * age_seconds / half_life_seconds).exp()


def _concentration_tie_key(
    item: tuple[SignalCandidate, CandidateAssessment],
) -> tuple[Decimal, float, str, str]:
    candidate, assessment = item
    concentration = assessment.concentration
    assert concentration is not None
    # Lower penalty is preferred. Freshness then protected identifier is deterministic.
    return (
        concentration.penalty,
        -candidate.executed_at.timestamp(),
        candidate.leader_key,
        candidate.signal_id,
    )


def _required_edge(assessment: CandidateAssessment) -> Decimal:
    assert assessment.net_edge is not None
    return assessment.net_edge


def _required_wallet_score(assessment: CandidateAssessment) -> Decimal:
    assert assessment.wallet_score is not None
    return assessment.wallet_score.conservative_score


def _timedelta_ratio(value: timedelta, total: timedelta) -> Decimal:
    return min(
        _ONE,
        max(
            _ZERO,
            Decimal(str(value.total_seconds())) / Decimal(str(total.total_seconds())),
        ),
    )


def _safe_identifier(name: str, value: str) -> None:
    if not value or len(value) > 200:
        raise ValueError(f"{name} must be a non-empty bounded identifier")
    if _WALLET_FRAGMENT.search(value):
        raise ValueError(f"{name} must not contain a wallet address")


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = [
    "ArbiterDecision",
    "ArbiterMode",
    "AssessmentStatus",
    "CandidateAssessment",
    "ClosedSignalOutcome",
    "ConcentrationAssessment",
    "ConcentrationCause",
    "ConcentrationEvent",
    "ExecutableEdge",
    "ExecutableEvidence",
    "FollowerExecutionOutcome",
    "SignalArbiter",
    "SignalArbiterConfig",
    "SignalCandidate",
    "SignalContext",
    "WalletQualityScore",
    "assess_concentration",
    "score_wallet_quality",
    "summarize_follower_execution_quality",
]
