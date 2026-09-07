"""Typed, versioned canonical research evidence.

Venue adapters translate source payloads before this module sees them.
Leader aliases must never be raw wallet addresses.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

_WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
RESEARCH_EVIDENCE_SCHEMA_VERSION = "research-evidence-v2"
LEGACY_RESEARCH_EVIDENCE_SCHEMA_VERSION = "research-evidence-v1"
SUPPORTED_RESEARCH_EVIDENCE_SCHEMA_VERSIONS = frozenset(
    {LEGACY_RESEARCH_EVIDENCE_SCHEMA_VERSION, RESEARCH_EVIDENCE_SCHEMA_VERSION}
)


class ObservationKind(StrEnum):
    WALLET_TRADE = "WALLET_TRADE"
    MARKET_STATE = "MARKET_STATE"
    CONTROL = "CONTROL"


class EvidenceClassification(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    LATE = "LATE"
    CONFLICTING = "CONFLICTING"
    REVERTED = "REVERTED"
    UNATTRIBUTABLE = "UNATTRIBUTABLE"
    GAP = "GAP"
    OVERLOAD = "OVERLOAD"
    INCOMPLETE = "INCOMPLETE"


class AttributionStatus(StrEnum):
    WALLET_ALIASED = "WALLET_ALIASED"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ConfirmationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"
    REVERTED = "REVERTED"


class IntervalValidity(StrEnum):
    VALID = "VALID"
    INVALID_OVERLOAD = "INVALID_OVERLOAD"
    INVALID_GAP = "INVALID_GAP"
    INVALID_MISSING_EVIDENCE = "INVALID_MISSING_EVIDENCE"


class SourceCandidateStatus(StrEnum):
    MEASURED = "MEASURED"
    UNAVAILABLE = "UNAVAILABLE"
    INSUFFICIENT = "INSUFFICIENT"


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


def payload_digest(fields: Mapping[str, object]) -> str:
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def stable_evidence_id(*, source_id: str, identity_fields: Mapping[str, object]) -> str:
    if not source_id.strip():
        raise ValueError("source_id must not be empty")
    return payload_digest({"source_id": source_id, **identity_fields})


@dataclass(frozen=True, slots=True)
class CanonicalResearchEvent:
    """One canonical observation or control signal for prospective research."""

    evidence_id: str
    schema_version: str
    source_id: str
    event_kind: ObservationKind
    classification: EvidenceClassification
    market_reference: str | None
    outcome_reference: str | None
    side: str | None
    price: Decimal | None
    size: Decimal | None
    source_time: datetime | None
    observed_time: datetime
    receive_monotonic_ns: int
    normalize_monotonic_ns: int
    attribution_status: AttributionStatus
    leader_alias: str | None
    confirmation: ConfirmationStatus
    payload_digest: str
    provenance: dict[str, object]
    source_event_id: str | None = None
    related_evidence_id: str | None = None
    run_id: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_id", "schema_version", "source_id", "payload_digest"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.schema_version not in SUPPORTED_RESEARCH_EVIDENCE_SCHEMA_VERSIONS:
            raise ValueError("schema_version is not a supported research-evidence version")
        _require_utc("observed_time", self.observed_time)
        if self.source_time is not None:
            _require_utc("source_time", self.source_time)
        if self.receive_monotonic_ns < 0 or self.normalize_monotonic_ns < 0:
            raise ValueError("monotonic timestamps must not be negative")
        if self.normalize_monotonic_ns < self.receive_monotonic_ns:
            raise ValueError("normalize_monotonic_ns must not precede receive_monotonic_ns")
        if self.leader_alias is not None:
            if not self.leader_alias.strip():
                raise ValueError("leader_alias must not be empty when provided")
            if _WALLET_PATTERN.fullmatch(self.leader_alias):
                raise ValueError("leader_alias must not be a wallet address")
        if self.source_event_id is not None and not self.source_event_id.strip():
            raise ValueError("source_event_id must not be empty when provided")
        if (
            self.schema_version == RESEARCH_EVIDENCE_SCHEMA_VERSION
            and self.event_kind is ObservationKind.WALLET_TRADE
            and self.classification is EvidenceClassification.ACCEPTED
            and self.attribution_status is AttributionStatus.WALLET_ALIASED
            and self.source_event_id is None
        ):
            raise ValueError("accepted v2 wallet evidence requires source_event_id")
        if self.price is not None and (
            not self.price.is_finite() or self.price <= Decimal("0")
        ):
            raise ValueError("price must be finite and positive when present")
        if self.size is not None and (
            not self.size.is_finite() or self.size <= Decimal("0")
        ):
            raise ValueError("size must be finite and positive when present")
        if self.side is not None and self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY, SELL, or omitted")

    @property
    def receive_normalize_latency_ns(self) -> int:
        return self.normalize_monotonic_ns - self.receive_monotonic_ns

    def decision_ready(self) -> bool:
        return (
            self.classification is EvidenceClassification.ACCEPTED
            and self.event_kind is ObservationKind.WALLET_TRADE
            and self.attribution_status is AttributionStatus.WALLET_ALIASED
            and self.confirmation is ConfirmationStatus.CONFIRMED
            and self.market_reference is not None
            and self.outcome_reference is not None
            and self.side is not None
            and self.price is not None
            and self.size is not None
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "confirmation": self.confirmation.value,
            "market_reference": self.market_reference,
            "outcome_reference": self.outcome_reference,
            "price": None if self.price is None else format(self.price, "f"),
            "side": self.side,
            "size": None if self.size is None else format(self.size, "f"),
            "source_event_id": self.source_event_id,
            "source_id": self.source_id,
            "source_time": None
            if self.source_time is None
            else self.source_time.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ResearchInterval:
    interval_id: str
    started_at: datetime
    ended_at: datetime | None
    validity: IntervalValidity
    reason: str
    code_sha: str | None
    configuration_digest: str | None
    policy_version: str

    def __post_init__(self) -> None:
        if (
            not self.interval_id.strip()
            or not self.policy_version.strip()
            or not self.reason.strip()
        ):
            raise ValueError("interval identity, policy_version, and reason are required")
        _require_utc("started_at", self.started_at)
        if self.ended_at is not None:
            _require_utc("ended_at", self.ended_at)
            if self.ended_at < self.started_at:
                raise ValueError("ended_at must not precede started_at")


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    interval_id: str
    observed_time: datetime
    policy_id: str
    policy_version: str
    decision: str
    evidence_ids: tuple[str, ...]
    code_sha: str | None
    configuration_digest: str | None

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "interval_id",
            "policy_id",
            "policy_version",
            "decision",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        _require_utc("observed_time", self.observed_time)
        if not self.evidence_ids:
            raise ValueError("decision evidence_ids must not be empty")
        if any(not item.strip() for item in self.evidence_ids):
            raise ValueError("decision evidence_ids must not contain empty values")
