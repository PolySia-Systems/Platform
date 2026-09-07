"""Same-observation Current Control vs Target Exposure replay.

Reuses frozen Target Exposure v1. Does not create a second accounting engine
or a Live/Risk/Execution path. Missing books, prices, marks, and gaps stay
UNKNOWN. Event-time markouts never interpolate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from polysia.domain.copytrading.continuous_shadow import ZERO
from polysia.domain.copytrading.target_exposure import (
    TargetExposureDecision,
    TargetExposurePolicy,
    decide_entry,
)
from polysia.domain.research_evidence.models import (
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)

MARKOUT_HORIZONS: tuple[timedelta, ...] = (
    timedelta(seconds=5),
    timedelta(seconds=30),
    timedelta(minutes=5),
)


class ControlAdmission(StrEnum):
    ADMIT = "ADMIT"
    SKIP = "SKIP"
    UNKNOWN = "UNKNOWN"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class ProspectiveObservation:
    evidence_id: str
    observed_time: datetime
    source_time: datetime | None
    market_reference: str
    outcome_reference: str
    side: str
    price: Decimal
    size: Decimal


@dataclass(frozen=True, slots=True)
class MarkoutLookup:
    horizon: timedelta
    status: str
    price: Decimal | None
    snapshot_evidence_id: str | None


@dataclass(frozen=True, slots=True)
class SameObservationReplay:
    control_decisions: tuple[tuple[str, ControlAdmission], ...]
    target_decisions: tuple[tuple[str, TargetExposureDecision | str], ...]
    markouts: tuple[tuple[str, tuple[MarkoutLookup, ...]], ...]
    control_digest: str
    target_digest: str
    unknown_count: int
    invalidated: bool


def observation_from_event(event: CanonicalResearchEvent) -> ProspectiveObservation | None:
    if event.event_kind is not ObservationKind.WALLET_TRADE:
        return None
    if event.classification is not EvidenceClassification.ACCEPTED:
        return None
    if event.attribution_status is not AttributionStatus.WALLET_ALIASED:
        return None
    if event.confirmation is not ConfirmationStatus.CONFIRMED:
        return None
    if (
        event.market_reference is None
        or event.outcome_reference is None
        or event.side is None
        or event.price is None
        or event.size is None
    ):
        return None
    return ProspectiveObservation(
        evidence_id=event.evidence_id,
        observed_time=event.observed_time,
        source_time=event.source_time,
        market_reference=event.market_reference,
        outcome_reference=event.outcome_reference,
        side=event.side,
        price=event.price,
        size=event.size,
    )


def lookup_event_time_mark(
    snapshots: tuple[CanonicalResearchEvent, ...],
    *,
    outcome_reference: str,
    event_time: datetime,
    horizon: timedelta,
    tolerance: timedelta,
) -> MarkoutLookup:
    """Return a stored snapshot in [event_time+horizon, +tolerance], else UNKNOWN.

    Never interpolates between snapshots or fabricates a price.
    """

    if horizon not in MARKOUT_HORIZONS:
        raise ValueError("markout horizon is not in the frozen set")
    if tolerance.total_seconds() < 0:
        raise ValueError("tolerance must not be negative")
    start = event_time + horizon
    end = start + tolerance
    matches = [
        snapshot
        for snapshot in snapshots
        if snapshot.event_kind is ObservationKind.MARKET_STATE
        and snapshot.classification is EvidenceClassification.ACCEPTED
        and snapshot.outcome_reference == outcome_reference
        and snapshot.source_time is not None
        and start <= snapshot.source_time <= end
        and snapshot.price is not None
    ]
    if len(matches) != 1:
        if not matches:
            return MarkoutLookup(
                horizon=horizon,
                status="UNKNOWN",
                price=None,
                snapshot_evidence_id=None,
            )
        return MarkoutLookup(
            horizon=horizon,
            status="UNKNOWN",
            price=None,
            snapshot_evidence_id=None,
        )
    match = matches[0]
    return MarkoutLookup(
        horizon=horizon,
        status="MEASURED",
        price=match.price,
        snapshot_evidence_id=match.evidence_id,
    )


def replay_same_observations(
    events: tuple[CanonicalResearchEvent, ...],
    *,
    policy: TargetExposurePolicy | None = None,
    interval_valid: bool = True,
    snapshots: tuple[CanonicalResearchEvent, ...] = (),
    markout_tolerance: timedelta = timedelta(seconds=1),
) -> SameObservationReplay:
    """Consume one observation stream for Current Control and Target Exposure."""

    policy = policy or TargetExposurePolicy()
    ordered = tuple(
        sorted(
            events,
            key=lambda item: (item.observed_time, item.evidence_id),
        )
    )
    control: list[tuple[str, ControlAdmission]] = []
    target: list[tuple[str, TargetExposureDecision | str]] = []
    markouts: list[tuple[str, tuple[MarkoutLookup, ...]]] = []
    unknown_count = 0
    episode_open = False
    first_price: Decimal | None = None
    control_exposure = ZERO
    target_exposure = ZERO
    control_cash = Decimal("1000")
    target_cash = Decimal("1000")

    for event in ordered:
        observation = observation_from_event(event)
        if observation is None:
            if event.event_kind is ObservationKind.WALLET_TRADE and event.classification in {
                EvidenceClassification.UNATTRIBUTABLE,
                EvidenceClassification.INCOMPLETE,
                EvidenceClassification.GAP,
                EvidenceClassification.OVERLOAD,
            }:
                unknown_count += 1
                control.append((event.evidence_id, ControlAdmission.UNKNOWN))
                target.append((event.evidence_id, "UNKNOWN"))
            continue
        if not interval_valid:
            control.append((observation.evidence_id, ControlAdmission.INVALIDATED))
            target.append((observation.evidence_id, "INVALIDATED"))
            continue
        if observation.side == "BUY":
            requested = observation.size
            control_notional = min(policy.entry_budget, observation.price * requested)
            if (
                control_cash >= control_notional
                and control_exposure + control_notional <= policy.market_exposure_cap
            ):
                control.append((observation.evidence_id, ControlAdmission.ADMIT))
                control_cash -= control_notional
                control_exposure += control_notional
            else:
                control.append((observation.evidence_id, ControlAdmission.SKIP))
            admission = decide_entry(
                policy,
                episode_open=episode_open,
                episode_closed=False,
                first_entry_price=first_price,
                executable_price=observation.price,
                requested_quantity=requested,
                recorded_fee=ZERO,
                opposing_quantity=ZERO,
                market_exposure=target_exposure,
                cash=target_cash,
            )
            target.append((observation.evidence_id, admission.decision))
            if admission.accepted:
                episode_open = True
                first_price = observation.price
                target_cash -= admission.notional
                target_exposure += admission.notional
        else:
            control.append((observation.evidence_id, ControlAdmission.SKIP))
            target.append((observation.evidence_id, TargetExposureDecision.SKIP_REPEAT_SIGNAL))

        event_time = observation.source_time or observation.observed_time
        markouts.append(
            (
                observation.evidence_id,
                tuple(
                    lookup_event_time_mark(
                        snapshots,
                        outcome_reference=observation.outcome_reference,
                        event_time=event_time,
                        horizon=horizon,
                        tolerance=markout_tolerance,
                    )
                    for horizon in MARKOUT_HORIZONS
                ),
            )
        )

    control_digest = _decision_digest(control)
    target_digest = _decision_digest(target)
    return SameObservationReplay(
        control_decisions=tuple(control),
        target_decisions=tuple(target),
        markouts=tuple(markouts),
        control_digest=control_digest,
        target_digest=target_digest,
        unknown_count=unknown_count,
        invalidated=not interval_valid,
    )


def _decision_digest(rows: Sequence[tuple[str, object]]) -> str:
    return payload_digest(
        {
            "rows": tuple((evidence_id, str(decision)) for evidence_id, decision in rows),
        }
    )
