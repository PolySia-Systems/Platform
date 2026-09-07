"""Pure collector classification, bounds, and latency summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum

from polysia.domain.research_evidence.models import (
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)

COLLECTOR_POLICY_VERSION = "prospective-collector-v1"


class CollectorVerdict(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class CollectorPolicy:
    """Bounded in-memory and recovery policy. Diagnostic telemetry may fail open."""

    policy_version: str = COLLECTOR_POLICY_VERSION
    max_queue_depth: int = 256
    gap_threshold: timedelta = timedelta(seconds=30)
    max_persisted_events: int = 100_000
    market_state_retention: timedelta = timedelta(days=7)
    late_grace: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.policy_version != COLLECTOR_POLICY_VERSION:
            raise ValueError("collector policy_version is frozen")
        if self.max_queue_depth < 1:
            raise ValueError("max_queue_depth must be positive")
        if self.max_persisted_events < 1:
            raise ValueError("max_persisted_events must be positive")
        if self.gap_threshold.total_seconds() <= 0:
            raise ValueError("gap_threshold must be positive")
        if self.market_state_retention.total_seconds() <= 0:
            raise ValueError("market_state_retention must be positive")
        if self.late_grace.total_seconds() < 0:
            raise ValueError("late_grace must not be negative")


def percentile_nearest_rank(samples: tuple[int, ...], percentile: int) -> int | None:
    """Nearest-rank percentile using Decimal rank. Empty input is unknown."""

    if not samples:
        return None
    if percentile < 0 or percentile > 100:
        raise ValueError("percentile must be within [0, 100]")
    ordered = tuple(sorted(samples))
    if percentile == 0:
        return ordered[0]
    rank = (
        Decimal(percentile) / Decimal(100) * Decimal(len(ordered))
    ).to_integral_value(rounding=ROUND_CEILING)
    index = int(rank) - 1
    if index < 0:
        return ordered[0]
    if index >= len(ordered):
        return ordered[-1]
    return ordered[index]


def classify_observation(
    candidate: CanonicalResearchEvent,
    *,
    existing_digest: str | None,
    last_source_time: datetime | None,
    queue_depth: int,
    policy: CollectorPolicy,
    reconnect_pending: bool,
) -> CanonicalResearchEvent:
    """Classify one candidate without I/O. Never upgrades missing fields."""

    if queue_depth >= policy.max_queue_depth:
        return apply_classification(candidate, EvidenceClassification.OVERLOAD)

    if candidate.event_kind is ObservationKind.CONTROL:
        return candidate

    if candidate.confirmation is ConfirmationStatus.REVERTED:
        return apply_classification(candidate, EvidenceClassification.REVERTED)

    if candidate.event_kind is ObservationKind.WALLET_TRADE and not _wallet_complete(
        candidate
    ):
        classification = (
            EvidenceClassification.UNATTRIBUTABLE
            if candidate.leader_alias is None
            else EvidenceClassification.INCOMPLETE
        )
        return apply_classification(candidate, classification)

    if existing_digest is not None:
        if existing_digest == candidate.payload_digest:
            return apply_classification(candidate, EvidenceClassification.DUPLICATE)
        return apply_classification(candidate, EvidenceClassification.CONFLICTING)

    if (
        candidate.event_kind is ObservationKind.WALLET_TRADE
        and not reconnect_pending
        and last_source_time is not None
        and candidate.source_time is not None
        and candidate.source_time + policy.late_grace < last_source_time
    ):
        return apply_classification(candidate, EvidenceClassification.LATE)

    return apply_classification(candidate, EvidenceClassification.ACCEPTED)


def gap_detected(
    *,
    last_source_time: datetime | None,
    source_time: datetime | None,
    reconnect_pending: bool,
    policy: CollectorPolicy,
) -> bool:
    """True when wallet source time jumped past the recovery threshold."""

    if reconnect_pending or last_source_time is None or source_time is None:
        return False
    return source_time - last_source_time > policy.gap_threshold


def _wallet_complete(candidate: CanonicalResearchEvent) -> bool:
    return (
        candidate.leader_alias is not None
        and candidate.market_reference is not None
        and candidate.outcome_reference is not None
        and candidate.side is not None
        and candidate.price is not None
        and candidate.size is not None
        and candidate.source_time is not None
    )


def apply_classification(
    candidate: CanonicalResearchEvent,
    classification: EvidenceClassification,
) -> CanonicalResearchEvent:
    related = candidate.related_evidence_id
    evidence_id = candidate.evidence_id
    if classification is EvidenceClassification.CONFLICTING:
        related = candidate.evidence_id
        evidence_id = payload_digest(
            {
                "conflict_of": candidate.evidence_id,
                "payload_digest": candidate.payload_digest,
            }
        )
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=candidate.schema_version,
        source_id=candidate.source_id,
        event_kind=candidate.event_kind,
        classification=classification,
        market_reference=candidate.market_reference,
        outcome_reference=candidate.outcome_reference,
        side=candidate.side,
        price=candidate.price,
        size=candidate.size,
        source_time=candidate.source_time,
        observed_time=candidate.observed_time,
        receive_monotonic_ns=candidate.receive_monotonic_ns,
        normalize_monotonic_ns=candidate.normalize_monotonic_ns,
        attribution_status=candidate.attribution_status,
        leader_alias=candidate.leader_alias,
        confirmation=candidate.confirmation,
        payload_digest=candidate.payload_digest,
        provenance=candidate.provenance,
        source_event_id=candidate.source_event_id,
        related_evidence_id=related,
        run_id=candidate.run_id,
    )
