from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.domain.copytrading.signal_arbiter import (
    ArbiterMode,
    AssessmentStatus,
    ClosedSignalOutcome,
    ConcentrationCause,
    ConcentrationEvent,
    ExecutableEvidence,
    FollowerExecutionOutcome,
    SignalArbiter,
    SignalArbiterConfig,
    SignalCandidate,
    SignalContext,
    assess_concentration,
    score_wallet_quality,
    summarize_follower_execution_quality,
)

NOW = datetime(2026, 8, 1, 10, tzinfo=UTC)
CONTEXT = SignalContext(market_type="btc-updown", timeframe_seconds=900)
OTHER_CONTEXT = SignalContext(market_type="eth-updown", timeframe_seconds=900)


def _evidence(
    *,
    leader_price: str = "0.50",
    executable_price: str = "0.47",
    captured_at: datetime = NOW,
) -> ExecutableEvidence:
    return ExecutableEvidence(
        leader_price=Decimal(leader_price),
        executable_price=Decimal(executable_price),
        quantity=Decimal("5"),
        best_bid=Decimal("0.46"),
        best_ask=Decimal("0.50"),
        expected_fees=Decimal("0"),
        estimated_slippage=Decimal("0"),
        captured_at=captured_at,
    )


def _candidate(
    leader_key: str,
    *,
    signal_id: str | None = None,
    executed_at: datetime = NOW - timedelta(seconds=5),
    observed_at: datetime = NOW - timedelta(seconds=1),
    evidence: ExecutableEvidence | None = None,
    safety_eligible: bool = True,
    safety_reason: str | None = None,
) -> SignalCandidate:
    return SignalCandidate(
        signal_id=signal_id or f"signal-{leader_key}",
        leader_key=leader_key,
        context=CONTEXT,
        executed_at=executed_at,
        observed_at=observed_at,
        safety_eligible=safety_eligible,
        safety_reason=safety_reason
        or ("independent gates passed" if safety_eligible else "risk blocked"),
        evidence=evidence or _evidence(),
    )


def _outcome(
    index: int,
    leader_key: str,
    net_return: str,
    *,
    context: SignalContext = CONTEXT,
    closed_at: datetime | None = None,
) -> ClosedSignalOutcome:
    closed = closed_at or NOW - timedelta(hours=index + 1)
    return ClosedSignalOutcome(
        outcome_id=f"outcome-{leader_key}-{index}",
        leader_key=leader_key,
        context=context,
        opened_at=closed - timedelta(minutes=10),
        closed_at=closed,
        net_return=Decimal(net_return),
        maximum_drawdown=Decimal("0.02"),
    )


def test_missing_execution_evidence_is_unknown_and_fails_closed() -> None:
    evidence = ExecutableEvidence(
        leader_price=Decimal("0.50"),
        executable_price=None,
        quantity=Decimal("5"),
        best_bid=Decimal("0.46"),
        best_ask=Decimal("0.50"),
        expected_fees=Decimal("0"),
        estimated_slippage=None,
        captured_at=NOW,
    )

    decision = SignalArbiter().decide(
        (_candidate("leader-001", evidence=evidence),),
        mode=ArbiterMode.FULL,
        as_of=NOW,
    )

    assert decision.selected_signal_id is None
    assert decision.assessments[0].status is AssessmentStatus.UNKNOWN
    assert "executable_price" in decision.assessments[0].reason
    assert "estimated_slippage" in decision.assessments[0].reason


def test_complete_execution_evidence_reports_edge_and_spread_cost() -> None:
    decision = SignalArbiter().decide(
        (_candidate("leader-001"),),
        mode=ArbiterMode.FULL,
        as_of=NOW,
    )

    assessment = decision.assessments[0]
    assert assessment.net_edge == Decimal("0.15")
    assert assessment.spread_cost == Decimal("0.20")


def test_future_and_stale_book_evidence_are_unknown() -> None:
    arbiter = SignalArbiter()
    future = arbiter.decide(
        (_candidate("leader-001", evidence=_evidence(captured_at=NOW + timedelta(seconds=1))),),
        mode=ArbiterMode.FULL,
        as_of=NOW,
    )
    stale = arbiter.decide(
        (_candidate("leader-002", evidence=_evidence(captured_at=NOW - timedelta(seconds=6))),),
        mode=ArbiterMode.FULL,
        as_of=NOW,
    )

    assert future.assessments[0].status is AssessmentStatus.UNKNOWN
    assert "future" in future.assessments[0].reason
    assert stale.assessments[0].status is AssessmentStatus.UNKNOWN
    assert "stale" in stale.assessments[0].reason


def test_raw_wallet_fragments_are_rejected() -> None:
    with pytest.raises(ValueError, match="wallet address"):
        _candidate("leader-0x1111111111111111111111111111111111111111")
    with pytest.raises(ValueError, match="safety_reason"):
        _candidate(
            "leader-001",
            safety_reason="wallet 0x1111111111111111111111111111111111111111 passed",
        )


def test_ten_second_freshness_limit_cannot_be_reconfigured() -> None:
    with pytest.raises(ValueError, match="ten seconds"):
        SignalArbiterConfig(maximum_signal_age=timedelta(seconds=20))


def test_wallet_score_is_walk_forward_contextual_and_time_decayed() -> None:
    outcomes = (
        _outcome(1, "leader-001", "0.20"),
        _outcome(2, "leader-001", "0.10", context=OTHER_CONTEXT),
        _outcome(
            3,
            "leader-001",
            "9.00",
            closed_at=NOW + timedelta(minutes=1),
        ),
    )

    contextual = score_wallet_quality(
        outcomes,
        leader_key="leader-001",
        context=CONTEXT,
        as_of=NOW,
    )
    fallback = score_wallet_quality(
        outcomes,
        leader_key="leader-001",
        context=SignalContext(market_type="sol-updown", timeframe_seconds=900),
        as_of=NOW,
    )
    old = score_wallet_quality(
        (
            _outcome(
                4,
                "leader-002",
                "0.20",
                closed_at=NOW - timedelta(days=60),
            ),
        ),
        leader_key="leader-002",
        context=CONTEXT,
        as_of=NOW,
    )

    assert contextual.source == "context"
    assert contextual.sample_count == 1
    assert contextual.posterior_mean < Decimal("0.02")
    assert fallback.source == "global_fallback"
    assert fallback.sample_count == 2
    assert old.effective_sample_weight < contextual.effective_sample_weight


def test_current_mode_preserves_one_attempt_per_leader_and_oldest_first() -> None:
    older = _candidate(
        "leader-001",
        signal_id="older",
        executed_at=NOW - timedelta(seconds=8),
    )
    newer = _candidate(
        "leader-002",
        signal_id="newer",
        executed_at=NOW - timedelta(seconds=4),
    )
    arbiter = SignalArbiter()

    decision = arbiter.decide(
        (newer, older),
        mode=ArbiterMode.CURRENT,
        as_of=NOW,
    )
    after_use = arbiter.decide(
        (older,),
        mode=ArbiterMode.CURRENT,
        as_of=NOW,
        used_leaders=frozenset({"leader-001"}),
    )

    assert decision.selected_signal_id == "older"
    assert after_use.selected_signal_id is None
    assert "one attempt" in after_use.assessments[0].reason


def test_ready_snapshot_deduplication_preserves_first_signal() -> None:
    first = _candidate("leader-001")
    second = _candidate("leader-002")
    duplicate = SignalCandidate(
        signal_id=first.signal_id,
        leader_key=second.leader_key,
        context=second.context,
        executed_at=second.executed_at,
        observed_at=second.observed_at,
        safety_eligible=second.safety_eligible,
        safety_reason=second.safety_reason,
        evidence=second.evidence,
    )

    decision = SignalArbiter().decide(
        (first, duplicate),
        mode=ArbiterMode.FULL,
        as_of=NOW,
    )

    assert decision.selected_leader_key == "leader-001"
    assert decision.assessments[1].reason == "duplicate signal identifier in ready snapshot"


def test_edge_dominates_diversity_but_wallet_quality_breaks_near_ties() -> None:
    config = SignalArbiterConfig(
        executable_edge_tolerance=Decimal("0.01"),
        wallet_score_tolerance=Decimal("0.0001"),
    )
    arbiter = SignalArbiter(config)
    materially_better = _candidate(
        "leader-001",
        evidence=_evidence(executable_price="0.45"),
    )
    weaker = _candidate(
        "leader-002",
        evidence=_evidence(executable_price="0.47"),
    )
    outcomes = tuple(
        _outcome(index, "leader-002", "0.20") for index in range(1, 41)
    )

    edge_wins = arbiter.decide(
        (weaker, materially_better),
        mode=ArbiterMode.FULL,
        as_of=NOW,
        wallet_outcomes=outcomes,
    )
    near_tie = arbiter.decide(
        (
            _candidate("leader-001", evidence=_evidence(executable_price="0.469")),
            weaker,
        ),
        mode=ArbiterMode.FULL,
        as_of=NOW,
        wallet_outcomes=outcomes,
    )

    assert edge_wins.selected_leader_key == "leader-001"
    assert near_tie.selected_leader_key == "leader-002"


def test_soft_concentration_only_breaks_near_quality_ties() -> None:
    arbiter = SignalArbiter(
        SignalArbiterConfig(
            executable_edge_tolerance=Decimal("0.01"),
            wallet_score_tolerance=Decimal("0.01"),
        )
    )
    penalized = _candidate("leader-001")
    unpenalized = _candidate(
        "leader-002",
        evidence=_evidence(executable_price="0.471"),
    )
    events = (
        ConcentrationEvent(
            event_id="cycle-1",
            leader_key="leader-001",
            cause=ConcentrationCause.COMPLETED_CYCLE,
            occurred_at=NOW - timedelta(minutes=5),
        ),
    )

    decision = arbiter.decide(
        (penalized, unpenalized),
        mode=ArbiterMode.FULL,
        as_of=NOW,
        concentration_events=events,
    )

    assert decision.selected_leader_key == "leader-002"


def test_concentration_is_cause_aware_and_decays() -> None:
    events = (
        ConcentrationEvent(
            event_id="late-1",
            leader_key="leader-001",
            cause=ConcentrationCause.LATE_SIGNAL,
            occurred_at=NOW - timedelta(minutes=4),
        ),
        ConcentrationEvent(
            event_id="late-2",
            leader_key="leader-001",
            cause=ConcentrationCause.LATE_SIGNAL,
            occurred_at=NOW - timedelta(minutes=2),
        ),
        ConcentrationEvent(
            event_id="cycle-1",
            leader_key="leader-002",
            cause=ConcentrationCause.COMPLETED_CYCLE,
            occurred_at=NOW - timedelta(minutes=5),
        ),
    )

    late = assess_concentration(events, leader_key="leader-001", as_of=NOW)
    cycle = assess_concentration(events, leader_key="leader-002", as_of=NOW)
    expired = assess_concentration(
        events,
        leader_key="leader-002",
        as_of=NOW + timedelta(minutes=31),
    )

    assert late.penalty > Decimal("0")
    assert late.reason == "repeated late signals"
    assert cycle.level == 1
    assert cycle.penalty > Decimal("0")
    assert expired.penalty == Decimal("0")


def test_completed_cycle_level_resets_after_sufficient_idle_time() -> None:
    events = tuple(
        ConcentrationEvent(
            event_id=f"old-cycle-{index}",
            leader_key="leader-001",
            cause=ConcentrationCause.COMPLETED_CYCLE,
            occurred_at=NOW - timedelta(days=4) + timedelta(minutes=index),
        )
        for index in range(3)
    ) + (
        ConcentrationEvent(
            event_id="recent-cycle",
            leader_key="leader-001",
            cause=ConcentrationCause.COMPLETED_CYCLE,
            occurred_at=NOW - timedelta(minutes=5),
        ),
    )

    assessment = assess_concentration(events, leader_key="leader-001", as_of=NOW)

    assert assessment.level == 1
    assert assessment.penalty > Decimal("0")


def test_follower_execution_quality_is_separate_and_missing_values_stay_unknown() -> None:
    outcomes = (
        FollowerExecutionOutcome(
            execution_id="execution-1",
            leader_key="leader-001",
            context=CONTEXT,
            closed_at=NOW - timedelta(minutes=2),
            filled=True,
            net_pnl=Decimal("0.20"),
            execution_cost=Decimal("0.03"),
            slippage=Decimal("0.01"),
        ),
        FollowerExecutionOutcome(
            execution_id="execution-2",
            leader_key="leader-002",
            context=CONTEXT,
            closed_at=NOW - timedelta(minutes=1),
            filled=False,
            net_pnl=None,
            execution_cost=None,
            slippage=None,
        ),
    )

    summary = summarize_follower_execution_quality(outcomes, as_of=NOW)

    assert summary["fill_rate"] == "0.5"
    assert summary["net_pnl"] == "0.20"
    assert summary["known_cost_count"] == 1
    assert summary["known_slippage_count"] == 1
