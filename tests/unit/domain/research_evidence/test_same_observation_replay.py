from __future__ import annotations

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
    outcome: str = "token-a",
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="src",
        event_kind=ObservationKind.WALLET_TRADE,
        classification=classification,
        market_reference="market-a",
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
        run_id="run-1",
    )


def _snapshot(
    evidence_id: str,
    *,
    source_time: datetime,
    price: Decimal,
    outcome: str = "token-a",
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="market",
        event_kind=ObservationKind.MARKET_STATE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference=None,
        outcome_reference=outcome,
        side=None,
        price=price,
        size=None,
        source_time=source_time,
        observed_time=source_time,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.NOT_APPLICABLE,
        leader_alias=None,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance={},
        run_id="run-1",
    )


def test_same_observations_control_accumulates_target_does_not() -> None:
    first = _trade("a", observed=OBSERVED)
    second = _trade("b", observed=OBSERVED + timedelta(seconds=1))
    replay = replay_same_observations((first, second))
    assert replay.control_decisions[0][1] is ControlAdmission.ADMIT
    assert replay.control_decisions[1][1] is ControlAdmission.ADMIT
    assert replay.target_decisions[0][1] is TargetExposureDecision.ADMIT
    assert replay.target_decisions[1][1] is TargetExposureDecision.SKIP_REPEAT_SIGNAL
    again = replay_same_observations((first, second))
    assert again.control_digest == replay.control_digest
    assert again.target_digest == replay.target_digest


def test_future_information_does_not_change_earlier_decision_order() -> None:
    early = _trade("early", observed=OBSERVED)
    late = _trade("late", observed=OBSERVED + timedelta(seconds=5), price=Decimal("0.20"))
    chronological = replay_same_observations((late, early))
    assert chronological.control_decisions[0][0] == "early"
    assert chronological.target_decisions[0][1] is TargetExposureDecision.ADMIT


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
        outcome_reference="token-a",
        event_time=event_time,
        horizon=timedelta(seconds=5),
        tolerance=timedelta(seconds=0),
    )
    measured = lookup_event_time_mark(
        (exact,),
        outcome_reference="token-a",
        event_time=event_time,
        horizon=timedelta(seconds=5),
        tolerance=timedelta(seconds=0),
    )
    assert missing.status == "UNKNOWN"
    assert missing.price is None
    assert measured.status == "MEASURED"
    assert measured.price == Decimal("0.55")
