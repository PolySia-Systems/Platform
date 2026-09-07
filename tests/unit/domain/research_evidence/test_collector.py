from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.domain.research_evidence.collector import (
    CollectorPolicy,
    classify_observation,
    gap_detected,
    percentile_nearest_rank,
)
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
    stable_evidence_id,
)

OBSERVED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _event(
    *,
    evidence_id: str = "e1",
    source_id: str = "src",
    classification: EvidenceClassification = EvidenceClassification.ACCEPTED,
    kind: ObservationKind = ObservationKind.WALLET_TRADE,
    source_time: datetime | None = OBSERVED - timedelta(seconds=2),
    attribution: AttributionStatus = AttributionStatus.WALLET_ALIASED,
    confirmation: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
    leader_alias: str | None = "pub-abc",
    price: Decimal | None = Decimal("0.5"),
    size: Decimal | None = Decimal("10"),
    side: str | None = "BUY",
    market: str | None = "market-a",
    outcome: str | None = "token-a",
) -> CanonicalResearchEvent:
    identity = {"id": evidence_id}
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id=source_id,
        event_kind=kind,
        classification=classification,
        market_reference=market,
        outcome_reference=outcome,
        side=side,
        price=price,
        size=size,
        source_time=source_time,
        observed_time=OBSERVED,
        receive_monotonic_ns=10,
        normalize_monotonic_ns=15,
        attribution_status=attribution,
        leader_alias=leader_alias,
        confirmation=confirmation,
        payload_digest=payload_digest(identity),
        provenance={"test": True},
        source_event_id=evidence_id,
        run_id="run-1",
    )


def test_stable_evidence_id_is_deterministic() -> None:
    first = stable_evidence_id(source_id="src", identity_fields={"tx": "abc"})
    second = stable_evidence_id(source_id="src", identity_fields={"tx": "abc"})
    assert first == second
    assert first != stable_evidence_id(source_id="other", identity_fields={"tx": "abc"})


def test_duplicate_and_conflict_classification() -> None:
    candidate = _event()
    duplicate = classify_observation(
        candidate,
        existing_digest=candidate.payload_digest,
        last_source_time=None,
        queue_depth=0,
        policy=CollectorPolicy(),
        reconnect_pending=False,
    )
    conflict = classify_observation(
        candidate,
        existing_digest="other-digest",
        last_source_time=None,
        queue_depth=0,
        policy=CollectorPolicy(),
        reconnect_pending=False,
    )
    assert duplicate.classification is EvidenceClassification.DUPLICATE
    assert conflict.classification is EvidenceClassification.CONFLICTING
    assert conflict.evidence_id != candidate.evidence_id
    assert conflict.related_evidence_id == candidate.evidence_id


def test_late_unattributable_reverted_and_overload() -> None:
    late = classify_observation(
        _event(source_time=OBSERVED - timedelta(seconds=30)),
        existing_digest=None,
        last_source_time=OBSERVED - timedelta(seconds=1),
        queue_depth=0,
        policy=CollectorPolicy(),
        reconnect_pending=False,
    )
    reconnect_backfill = classify_observation(
        _event(source_time=OBSERVED - timedelta(seconds=30)),
        existing_digest=None,
        last_source_time=OBSERVED - timedelta(seconds=1),
        queue_depth=0,
        policy=CollectorPolicy(),
        reconnect_pending=True,
    )
    missing = classify_observation(
        _event(leader_alias=None, attribution=AttributionStatus.MISSING),
        existing_digest=None,
        last_source_time=None,
        queue_depth=0,
        policy=CollectorPolicy(),
        reconnect_pending=False,
    )
    reverted = classify_observation(
        _event(confirmation=ConfirmationStatus.REVERTED),
        existing_digest=None,
        last_source_time=None,
        queue_depth=0,
        policy=CollectorPolicy(),
        reconnect_pending=False,
    )
    overload = classify_observation(
        _event(),
        existing_digest=None,
        last_source_time=None,
        queue_depth=256,
        policy=CollectorPolicy(max_queue_depth=256),
        reconnect_pending=False,
    )
    assert late.classification is EvidenceClassification.LATE
    assert reconnect_backfill.classification is EvidenceClassification.ACCEPTED
    assert missing.classification is EvidenceClassification.UNATTRIBUTABLE
    assert reverted.classification is EvidenceClassification.REVERTED
    assert overload.classification is EvidenceClassification.OVERLOAD


def test_gap_detection_and_percentiles() -> None:
    policy = CollectorPolicy(gap_threshold=timedelta(seconds=30))
    assert gap_detected(
        last_source_time=OBSERVED,
        source_time=OBSERVED + timedelta(seconds=31),
        reconnect_pending=False,
        policy=policy,
    )
    assert not gap_detected(
        last_source_time=OBSERVED,
        source_time=OBSERVED + timedelta(seconds=31),
        reconnect_pending=True,
        policy=policy,
    )
    samples = (1, 2, 3, 4, 5)
    assert percentile_nearest_rank(samples, 50) == 3
    assert percentile_nearest_rank((), 50) is None
    with pytest.raises(ValueError):
        percentile_nearest_rank(samples, 101)


def test_leader_alias_rejects_wallet_address() -> None:
    with pytest.raises(ValueError, match="wallet address"):
        _event(leader_alias="0x1111111111111111111111111111111111111111")
