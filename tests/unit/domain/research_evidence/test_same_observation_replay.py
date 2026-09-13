from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polysia.domain.copytrading.target_exposure import TargetExposureDecision
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)
from polysia.domain.research_evidence.replay import (
    ControlAdmission,
    MarkoutTimeBasis,
    lookup_event_time_mark,
    replay_same_observations,
)

OBSERVED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _trade(
    evidence_id: str,
    *,
    observed: datetime,
    source_time: datetime | None = None,
    side: str = "BUY",
    price: Decimal = Decimal("0.50"),
    classification: EvidenceClassification = EvidenceClassification.ACCEPTED,
    attribution: AttributionStatus = AttributionStatus.WALLET_ALIASED,
    market: str = "market-a",
    outcome: str = "token-a",
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="src",
        event_kind=ObservationKind.WALLET_TRADE,
        classification=classification,
        market_reference=market,
        outcome_reference=outcome,
        side=side,
        price=price,
        size=Decimal("10"),
        source_time=source_time or observed,
        observed_time=observed,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=attribution,
        leader_alias=None if attribution is AttributionStatus.MISSING else "pub-abc",
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance={},
        source_event_id=evidence_id,
        run_id="run-1",
    )


def _snapshot(
    evidence_id: str,
    *,
    source_time: datetime,
    price: Decimal,
    observed_time: datetime | None = None,
    market: str | None = "market-a",
    outcome: str = "token-a",
    side: str | None = None,
    size: Decimal | None = None,
    execution_evidence: bool = False,
    recorded_fee: Decimal = Decimal("0"),
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="market",
        event_kind=ObservationKind.MARKET_STATE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference=market,
        outcome_reference=outcome,
        side=side,
        price=price,
        size=size,
        source_time=source_time,
        observed_time=observed_time or source_time,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.NOT_APPLICABLE,
        leader_alias=None,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance={
            "execution_evidence": execution_evidence,
            "recorded_fee": format(recorded_fee, "f"),
        },
        run_id="run-1",
    )


def _quote(
    evidence_id: str,
    *,
    observed_time: datetime,
    market: str = "market-a",
    outcome: str = "token-a",
    price: Decimal = Decimal("0.50"),
) -> CanonicalResearchEvent:
    return _snapshot(
        evidence_id,
        source_time=observed_time,
        observed_time=observed_time,
        market=market,
        outcome=outcome,
        price=price,
        side="BUY",
        size=Decimal("100"),
        execution_evidence=True,
    )


def _depth_quote(
    evidence_id: str,
    *,
    observed_time: datetime,
    side: str = "BUY",
    market: str = "market-a",
    outcome: str = "token-a",
    levels: tuple[tuple[str, str], ...] = (("0.50", "20"),),
    fee_rate: str | None = "0.25",
    fee_exponent: str | None = "2",
) -> CanonicalResearchEvent:
    snapshot = _snapshot(
        evidence_id,
        source_time=observed_time,
        observed_time=observed_time,
        market=market,
        outcome=outcome,
        price=Decimal(levels[0][0]),
        side=side,
        size=sum((Decimal(size) for _, size in levels), Decimal("0")),
    )
    return replace(
        snapshot,
        provenance={
            "book_levels": [
                {"price": price, "size": size} for price, size in levels
            ],
            "execution_evidence": fee_rate is not None and fee_exponent is not None,
            "execution_evidence_version": "order-book-depth-v1",
            "fee_calculation_version": "polymarket-taker-fee-v1",
            "fee_exponent": fee_exponent,
            "fee_rate": fee_rate,
            "fee_taker_only": True,
            "fees_enabled": True,
        },
    )


def test_same_observations_control_accumulates_target_does_not() -> None:
    first = _trade("a", observed=OBSERVED)
    second = _trade("b", observed=OBSERVED + timedelta(seconds=1))
    quote = _quote("q", observed_time=OBSERVED - timedelta(seconds=1))
    replay = replay_same_observations((first, second), snapshots=(quote,))
    assert replay.control_decisions[0][1] is ControlAdmission.ADMIT
    assert replay.control_decisions[1][1] is ControlAdmission.ADMIT
    assert replay.target_decisions[0][1] is TargetExposureDecision.ADMIT
    assert replay.target_decisions[1][1] is TargetExposureDecision.SKIP_REPEAT_SIGNAL
    again = replay_same_observations((first, second), snapshots=(quote,))
    assert again.control_digest == replay.control_digest
    assert again.target_digest == replay.target_digest


def test_replay_indexes_snapshot_stream_once() -> None:
    class CountingSnapshots(tuple[CanonicalResearchEvent, ...]):
        iterations: int

        def __new__(
            cls,
            values: tuple[CanonicalResearchEvent, ...],
        ) -> CountingSnapshots:
            instance = super().__new__(cls, values)
            instance.iterations = 0
            return instance

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.iterations += 1
            return super().__iter__()

    snapshots = CountingSnapshots(
        (
            _quote("quote", observed_time=OBSERVED - timedelta(seconds=1)),
            _snapshot(
                "markout",
                source_time=OBSERVED + timedelta(seconds=5),
                price=Decimal("0.51"),
            ),
        )
    )
    replay = replay_same_observations(
        (
            _trade("first", observed=OBSERVED),
            _trade("second", observed=OBSERVED + timedelta(seconds=1)),
        ),
        snapshots=snapshots,
    )

    assert replay.control_decisions[0][1] is ControlAdmission.ADMIT
    assert snapshots.iterations == 1


def test_future_information_does_not_change_earlier_decision_order() -> None:
    early = _trade("early", observed=OBSERVED)
    late = _trade("late", observed=OBSERVED + timedelta(seconds=5), price=Decimal("0.20"))
    quote = _quote("q", observed_time=OBSERVED - timedelta(seconds=1))
    chronological = replay_same_observations((late, early), snapshots=(quote,))
    assert chronological.control_decisions[0][0] == "early"
    assert chronological.target_decisions[0][1] is TargetExposureDecision.ADMIT


def test_target_episode_state_is_isolated_by_market_and_outcome() -> None:
    market_a = _trade("a", observed=OBSERVED, market="market-a", outcome="token-a")
    market_b = _trade(
        "b",
        observed=OBSERVED + timedelta(seconds=1),
        market="market-b",
        outcome="token-b",
    )
    quotes = (
        _quote("qa", observed_time=OBSERVED - timedelta(seconds=1)),
        _quote(
            "qb",
            observed_time=OBSERVED - timedelta(seconds=1),
            market="market-b",
            outcome="token-b",
        ),
    )
    replay = replay_same_observations((market_a, market_b), snapshots=quotes)
    assert replay.target_decisions == (
        ("a", TargetExposureDecision.ADMIT),
        ("b", TargetExposureDecision.ADMIT),
    )


def test_missing_execution_evidence_stays_unknown() -> None:
    trade = _trade("a", observed=OBSERVED)
    raw_market_price = _snapshot(
        "raw",
        source_time=OBSERVED - timedelta(seconds=1),
        price=Decimal("0.49"),
    )
    for snapshots in ((), (raw_market_price,)):
        replay = replay_same_observations((trade,), snapshots=snapshots)
        assert replay.control_decisions == (("a", ControlAdmission.UNKNOWN),)
        assert replay.target_decisions == (("a", "UNKNOWN"),)
        assert replay.unknown_count == 1


def test_bounded_causal_quote_acquisition_is_not_lookahead() -> None:
    trade = _trade("a", observed=OBSERVED)
    future_quote = _quote("future", observed_time=OBSERVED + timedelta(milliseconds=1))

    replay = replay_same_observations((trade,), snapshots=(future_quote,))

    assert replay.control_decisions == (("a", ControlAdmission.ADMIT),)
    assert replay.target_decisions == (("a", TargetExposureDecision.ADMIT),)
    assert replay.evaluations[0].decision_time == future_quote.observed_time


def test_depth_execution_uses_asks_vwap_fee_and_partial_fill() -> None:
    trade = _trade(
        "buy",
        observed=OBSERVED,
        price=Decimal("0.50"),
    )
    quote = _depth_quote(
        "depth",
        observed_time=OBSERVED - timedelta(seconds=1),
        levels=(("0.51", "4"), ("0.52", "10")),
    )

    replay = replay_same_observations((trade,), snapshots=(quote,))

    evaluation = replay.evaluations[0]
    assert evaluation.execution is not None
    assert evaluation.execution.economically_complete is True
    assert evaluation.execution.executable_price > Decimal("0.51")
    assert evaluation.execution.notional == Decimal("5.000000000000000000000000000")
    assert evaluation.execution.recorded_fee > Decimal("0")
    assert evaluation.execution.partial_fill is False
    assert replay.execution_evidence_count == 1


def test_sell_uses_bids_and_reports_insufficient_depth_as_partial() -> None:
    trade = _trade(
        "sell",
        observed=OBSERVED,
        side="SELL",
        price=Decimal("0.50"),
    )
    quote = _depth_quote(
        "bids",
        observed_time=OBSERVED - timedelta(seconds=1),
        side="SELL",
        levels=(("0.49", "2"), ("0.48", "1")),
    )

    replay = replay_same_observations((trade,), snapshots=(quote,))

    execution = replay.evaluations[0].execution
    assert execution is not None
    assert execution.available_quantity == Decimal("3")
    assert execution.executable_price == Decimal("0.4866666666666666666666666667")
    assert execution.partial_fill is True
    assert replay.partial_fill_count == 1


def test_fee_and_causality_failures_are_exact() -> None:
    trade = _trade("trade", observed=OBSERVED)
    missing_fee = _depth_quote(
        "missing-fee",
        observed_time=OBSERVED - timedelta(seconds=1),
        fee_rate=None,
    )
    too_late = _depth_quote("future", observed_time=OBSERVED + timedelta(seconds=31))
    stale = _depth_quote("stale", observed_time=OBSERVED - timedelta(seconds=31))

    assert replay_same_observations((trade,), snapshots=(missing_fee,)).unknown_by_cause == (
        ("missing_fee", 1),
    )
    assert replay_same_observations((trade,), snapshots=(too_late,)).unknown_by_cause == (
        ("missing_quote", 1),
    )
    assert replay_same_observations((trade,), snapshots=(stale,)).unknown_by_cause == (
        ("stale_quote", 1),
    )


def test_missing_attribution_and_overload_stay_unknown() -> None:
    missing = _trade(
        "miss",
        observed=OBSERVED,
        classification=EvidenceClassification.UNATTRIBUTABLE,
        attribution=AttributionStatus.MISSING,
    )
    unknown = replay_same_observations((missing,))
    assert unknown.control_decisions[0][1] is ControlAdmission.UNKNOWN
    assert unknown.unknown_count == 1
    invalidated = replay_same_observations((_trade("ok", observed=OBSERVED),), interval_valid=False)
    assert invalidated.control_decisions[0][1] is ControlAdmission.INVALIDATED
    assert invalidated.invalidated


def test_markout_is_unknown_without_interpolation() -> None:
    event_time = OBSERVED
    before = _snapshot("s0", source_time=event_time + timedelta(seconds=4), price=Decimal("0.4"))
    after = _snapshot("s1", source_time=event_time + timedelta(seconds=7), price=Decimal("0.6"))
    exact = _snapshot("s2", source_time=event_time + timedelta(seconds=5), price=Decimal("0.55"))
    missing = lookup_event_time_mark(
        (before, after),
        market_reference="market-a",
        outcome_reference="token-a",
        event_time=event_time,
        horizon=timedelta(seconds=5),
        tolerance=timedelta(seconds=0),
        time_basis=MarkoutTimeBasis.LEADER_SOURCE,
    )
    measured = lookup_event_time_mark(
        (exact,),
        market_reference="market-a",
        outcome_reference="token-a",
        event_time=event_time,
        horizon=timedelta(seconds=5),
        tolerance=timedelta(seconds=0),
        time_basis=MarkoutTimeBasis.LEADER_SOURCE,
    )
    assert missing.status == "UNKNOWN"
    assert missing.price is None
    assert measured.status == "MEASURED"
    assert measured.price == Decimal("0.55")


def test_markout_clocks_are_separate_and_multiple_matches_are_deterministic() -> None:
    trade = _trade(
        "a",
        observed=OBSERVED + timedelta(seconds=10),
        source_time=OBSERVED,
    )
    leader = _snapshot(
        "leader",
        source_time=OBSERVED + timedelta(seconds=5),
        observed_time=OBSERVED + timedelta(seconds=11),
        price=Decimal("0.41"),
    )
    follower_first = _snapshot(
        "follower-first",
        source_time=OBSERVED + timedelta(seconds=2),
        observed_time=OBSERVED + timedelta(seconds=15),
        price=Decimal("0.51"),
    )
    follower_second = _snapshot(
        "follower-second",
        source_time=OBSERVED + timedelta(seconds=3),
        observed_time=OBSERVED + timedelta(seconds=15, milliseconds=500),
        price=Decimal("0.52"),
    )
    replay = replay_same_observations(
        (trade,),
        snapshots=(follower_second, leader, follower_first),
        markout_tolerance=timedelta(seconds=1),
    )
    assert replay.leader_markouts[0][1][0].snapshot_evidence_id == "leader"
    assert replay.follower_markouts[0][1][0].snapshot_evidence_id == "follower-first"
    assert replay.follower_markouts[0][1][0].price == Decimal("0.51")
