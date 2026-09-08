"""Same-observation Current Control vs Target Exposure replay.

Reuses frozen Target Exposure v1. Does not create a second accounting engine
or a Live/Risk/Execution path. Missing books, prices, marks, and gaps stay
UNKNOWN. Event-time markouts never interpolate.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
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
EXECUTION_EVIDENCE_MAX_AGE = timedelta(seconds=30)


class ControlAdmission(StrEnum):
    ADMIT = "ADMIT"
    SKIP = "SKIP"
    UNKNOWN = "UNKNOWN"
    INVALIDATED = "INVALIDATED"


class MarkoutTimeBasis(StrEnum):
    LEADER_SOURCE = "LEADER_SOURCE"
    FOLLOWER_OBSERVED = "FOLLOWER_OBSERVED"


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
    time_basis: MarkoutTimeBasis
    status: str
    price: Decimal | None
    snapshot_evidence_id: str | None


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    snapshot_evidence_id: str
    executable_price: Decimal
    available_quantity: Decimal
    recorded_fee: Decimal


@dataclass(slots=True)
class _EpisodeState:
    open: bool = False
    first_price: Decimal | None = None
    exposure: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class SameObservationReplay:
    control_decisions: tuple[tuple[str, ControlAdmission], ...]
    target_decisions: tuple[tuple[str, TargetExposureDecision | str], ...]
    leader_markouts: tuple[tuple[str, tuple[MarkoutLookup, ...]], ...]
    follower_markouts: tuple[tuple[str, tuple[MarkoutLookup, ...]], ...]
    control_digest: str
    target_digest: str
    unknown_count: int
    invalidated: bool


@dataclass(frozen=True, slots=True)
class _SnapshotTimeline:
    times: tuple[datetime, ...]
    events: tuple[CanonicalResearchEvent, ...]


class _ReplaySnapshotIndex:
    """Bound each lookup to one outcome and a narrow time window."""

    def __init__(self, snapshots: tuple[CanonicalResearchEvent, ...]) -> None:
        markouts: dict[
            tuple[str, MarkoutTimeBasis],
            list[tuple[datetime, CanonicalResearchEvent]],
        ] = defaultdict(list)
        executions: dict[
            tuple[str, str],
            list[tuple[datetime, CanonicalResearchEvent]],
        ] = defaultdict(list)
        for snapshot in snapshots:
            if not _is_base_snapshot(snapshot) or snapshot.outcome_reference is None:
                continue
            if snapshot.price is not None:
                markouts[
                    (snapshot.outcome_reference, MarkoutTimeBasis.FOLLOWER_OBSERVED)
                ].append((snapshot.observed_time, snapshot))
                if snapshot.source_time is not None:
                    markouts[
                        (snapshot.outcome_reference, MarkoutTimeBasis.LEADER_SOURCE)
                    ].append((snapshot.source_time, snapshot))
            if (
                snapshot.side is not None
                and snapshot.price is not None
                and snapshot.size is not None
                and snapshot.provenance.get("execution_evidence") is True
                and _nonnegative_decimal(snapshot.provenance.get("recorded_fee"))
                is not None
            ):
                executions[(snapshot.outcome_reference, snapshot.side)].append(
                    (snapshot.observed_time, snapshot)
                )
        self._markouts = {
            key: _build_timeline(rows, use_observed_tiebreak=True)
            for key, rows in markouts.items()
        }
        self._executions = {
            key: _build_timeline(rows, use_observed_tiebreak=False)
            for key, rows in executions.items()
        }

    def markout(
        self,
        *,
        market_reference: str,
        outcome_reference: str,
        event_time: datetime,
        horizon: timedelta,
        tolerance: timedelta,
        time_basis: MarkoutTimeBasis,
    ) -> MarkoutLookup:
        _validate_markout_request(horizon=horizon, tolerance=tolerance)
        timeline = self._markouts.get((outcome_reference, time_basis))
        if timeline is None:
            return _unknown_markout(horizon=horizon, time_basis=time_basis)
        start = event_time + horizon
        end = start + tolerance
        left = bisect_left(timeline.times, start)
        right = bisect_right(timeline.times, end)
        for snapshot in timeline.events[left:right]:
            if snapshot.market_reference in {None, market_reference}:
                return MarkoutLookup(
                    horizon=horizon,
                    time_basis=time_basis,
                    status="MEASURED",
                    price=snapshot.price,
                    snapshot_evidence_id=snapshot.evidence_id,
                )
        return _unknown_markout(horizon=horizon, time_basis=time_basis)

    def execution(
        self,
        *,
        observation: ProspectiveObservation,
        max_age: timedelta,
    ) -> ExecutionEvidence | None:
        if max_age.total_seconds() < 0:
            raise ValueError("execution evidence max_age must not be negative")
        timeline = self._executions.get(
            (observation.outcome_reference, observation.side)
        )
        if timeline is None:
            return None
        cutoff = observation.observed_time - max_age
        left = bisect_left(timeline.times, cutoff)
        right = bisect_right(timeline.times, observation.observed_time)
        for snapshot in reversed(timeline.events[left:right]):
            if snapshot.market_reference not in {None, observation.market_reference}:
                continue
            fee = _nonnegative_decimal(snapshot.provenance.get("recorded_fee"))
            if fee is None or snapshot.price is None or snapshot.size is None:
                continue
            return ExecutionEvidence(
                snapshot_evidence_id=snapshot.evidence_id,
                executable_price=snapshot.price,
                available_quantity=snapshot.size,
                recorded_fee=fee,
            )
        return None


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
    market_reference: str,
    outcome_reference: str,
    event_time: datetime,
    horizon: timedelta,
    tolerance: timedelta,
    time_basis: MarkoutTimeBasis,
) -> MarkoutLookup:
    """Return a stored snapshot in [event_time+horizon, +tolerance], else UNKNOWN.

    Never interpolates between snapshots or fabricates a price.
    """

    _validate_markout_request(horizon=horizon, tolerance=tolerance)
    start = event_time + horizon
    end = start + tolerance
    matches: list[tuple[datetime, CanonicalResearchEvent]] = []
    for snapshot in snapshots:
        snapshot_time = _snapshot_time(snapshot, time_basis=time_basis)
        if (
            snapshot.event_kind is ObservationKind.MARKET_STATE
            and snapshot.classification is EvidenceClassification.ACCEPTED
            and snapshot.confirmation is ConfirmationStatus.CONFIRMED
            and snapshot.outcome_reference == outcome_reference
            and snapshot.market_reference in {None, market_reference}
            and snapshot_time is not None
            and start <= snapshot_time <= end
            and snapshot.price is not None
        ):
            matches.append((snapshot_time, snapshot))
    if not matches:
        return _unknown_markout(horizon=horizon, time_basis=time_basis)
    _, match = min(
        matches,
        key=lambda item: (item[0], item[1].observed_time, item[1].evidence_id),
    )
    return MarkoutLookup(
        horizon=horizon,
        time_basis=time_basis,
        status="MEASURED",
        price=match.price,
        snapshot_evidence_id=match.evidence_id,
    )


def lookup_execution_evidence(
    snapshots: tuple[CanonicalResearchEvent, ...],
    *,
    observation: ProspectiveObservation,
    max_age: timedelta = EXECUTION_EVIDENCE_MAX_AGE,
) -> ExecutionEvidence | None:
    """Return the latest explicit, side-aware quote known before observation."""

    if max_age.total_seconds() < 0:
        raise ValueError("execution evidence max_age must not be negative")
    cutoff = observation.observed_time - max_age
    candidates: list[CanonicalResearchEvent] = []
    for snapshot in snapshots:
        fee = _nonnegative_decimal(snapshot.provenance.get("recorded_fee"))
        if (
            snapshot.event_kind is ObservationKind.MARKET_STATE
            and snapshot.classification is EvidenceClassification.ACCEPTED
            and snapshot.confirmation is ConfirmationStatus.CONFIRMED
            and snapshot.outcome_reference == observation.outcome_reference
            and snapshot.market_reference in {None, observation.market_reference}
            and snapshot.side == observation.side
            and snapshot.price is not None
            and snapshot.size is not None
            and snapshot.provenance.get("execution_evidence") is True
            and fee is not None
            and cutoff <= snapshot.observed_time <= observation.observed_time
        ):
            candidates.append(snapshot)
    if not candidates:
        return None
    match = max(candidates, key=lambda item: (item.observed_time, item.evidence_id))
    fee = _nonnegative_decimal(match.provenance.get("recorded_fee"))
    if fee is None or match.price is None or match.size is None:
        return None
    return ExecutionEvidence(
        snapshot_evidence_id=match.evidence_id,
        executable_price=match.price,
        available_quantity=match.size,
        recorded_fee=fee,
    )


def replay_same_observations(
    events: tuple[CanonicalResearchEvent, ...],
    *,
    policy: TargetExposurePolicy | None = None,
    interval_valid: bool = True,
    snapshots: tuple[CanonicalResearchEvent, ...] = (),
    markout_tolerance: timedelta = timedelta(seconds=1),
    execution_evidence_max_age: timedelta = EXECUTION_EVIDENCE_MAX_AGE,
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
    leader_markouts: list[tuple[str, tuple[MarkoutLookup, ...]]] = []
    follower_markouts: list[tuple[str, tuple[MarkoutLookup, ...]]] = []
    unknown_count = 0
    target_episodes: dict[tuple[str, str], _EpisodeState] = {}
    control_exposures: dict[tuple[str, str], Decimal] = {}
    control_cash = Decimal("1000")
    target_cash = Decimal("1000")
    snapshot_index = _ReplaySnapshotIndex(snapshots)

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
        key = (observation.market_reference, observation.outcome_reference)
        episode = target_episodes.setdefault(key, _EpisodeState())
        execution = snapshot_index.execution(
            observation=observation,
            max_age=execution_evidence_max_age,
        )
        if observation.side == "BUY":
            if execution is None:
                unknown_count += 1
                control.append((observation.evidence_id, ControlAdmission.UNKNOWN))
                target.append((observation.evidence_id, "UNKNOWN"))
                _append_markouts(
                    observation,
                    snapshot_index=snapshot_index,
                    tolerance=markout_tolerance,
                    leader=leader_markouts,
                    follower=follower_markouts,
                )
                continue
            requested = min(observation.size, execution.available_quantity)
            requested_fee = (
                execution.recorded_fee * requested / execution.available_quantity
            )
            control_notional = min(
                policy.entry_budget,
                execution.executable_price * requested,
            )
            control_quantity = control_notional / execution.executable_price
            control_fee = requested_fee * control_quantity / requested
            control_exposure = control_exposures.get(key, ZERO)
            if (
                control_cash >= control_notional + control_fee
                and control_exposure + control_notional <= policy.market_exposure_cap
            ):
                control.append((observation.evidence_id, ControlAdmission.ADMIT))
                control_cash -= control_notional + control_fee
                control_exposures[key] = control_exposure + control_notional
            else:
                control.append((observation.evidence_id, ControlAdmission.SKIP))
            admission = decide_entry(
                policy,
                episode_open=episode.open,
                episode_closed=False,
                first_entry_price=episode.first_price,
                executable_price=execution.executable_price,
                requested_quantity=requested,
                recorded_fee=requested_fee,
                opposing_quantity=ZERO,
                market_exposure=episode.exposure,
                cash=target_cash,
            )
            target.append((observation.evidence_id, admission.decision))
            if admission.accepted:
                episode.open = True
                episode.first_price = execution.executable_price
                target_cash -= admission.notional + admission.fee
                episode.exposure += admission.notional
        else:
            control.append((observation.evidence_id, ControlAdmission.SKIP))
            target.append((observation.evidence_id, TargetExposureDecision.SKIP_REPEAT_SIGNAL))

        _append_markouts(
            observation,
            snapshot_index=snapshot_index,
            tolerance=markout_tolerance,
            leader=leader_markouts,
            follower=follower_markouts,
        )

    control_digest = _decision_digest(control)
    target_digest = _decision_digest(target)
    return SameObservationReplay(
        control_decisions=tuple(control),
        target_decisions=tuple(target),
        leader_markouts=tuple(leader_markouts),
        follower_markouts=tuple(follower_markouts),
        control_digest=control_digest,
        target_digest=target_digest,
        unknown_count=unknown_count,
        invalidated=not interval_valid,
    )


def _append_markouts(
    observation: ProspectiveObservation,
    *,
    snapshot_index: _ReplaySnapshotIndex,
    tolerance: timedelta,
    leader: list[tuple[str, tuple[MarkoutLookup, ...]]],
    follower: list[tuple[str, tuple[MarkoutLookup, ...]]],
) -> None:
    leader.append(
        (
            observation.evidence_id,
            _markout_series(
                observation,
                snapshot_index=snapshot_index,
                event_time=observation.source_time,
                tolerance=tolerance,
                time_basis=MarkoutTimeBasis.LEADER_SOURCE,
            ),
        )
    )
    follower.append(
        (
            observation.evidence_id,
            _markout_series(
                observation,
                snapshot_index=snapshot_index,
                event_time=observation.observed_time,
                tolerance=tolerance,
                time_basis=MarkoutTimeBasis.FOLLOWER_OBSERVED,
            ),
        )
    )


def _markout_series(
    observation: ProspectiveObservation,
    *,
    snapshot_index: _ReplaySnapshotIndex,
    event_time: datetime | None,
    tolerance: timedelta,
    time_basis: MarkoutTimeBasis,
) -> tuple[MarkoutLookup, ...]:
    if event_time is None:
        return tuple(
            MarkoutLookup(horizon, time_basis, "UNKNOWN", None, None)
            for horizon in MARKOUT_HORIZONS
        )
    return tuple(
        snapshot_index.markout(
            market_reference=observation.market_reference,
            outcome_reference=observation.outcome_reference,
            event_time=event_time,
            horizon=horizon,
            tolerance=tolerance,
            time_basis=time_basis,
        )
        for horizon in MARKOUT_HORIZONS
    )


def _build_timeline(
    rows: list[tuple[datetime, CanonicalResearchEvent]],
    *,
    use_observed_tiebreak: bool,
) -> _SnapshotTimeline:
    if use_observed_tiebreak:
        ordered = sorted(
            rows,
            key=lambda item: (item[0], item[1].observed_time, item[1].evidence_id),
        )
    else:
        ordered = sorted(rows, key=lambda item: (item[0], item[1].evidence_id))
    return _SnapshotTimeline(
        times=tuple(item[0] for item in ordered),
        events=tuple(item[1] for item in ordered),
    )


def _is_base_snapshot(snapshot: CanonicalResearchEvent) -> bool:
    return (
        snapshot.event_kind is ObservationKind.MARKET_STATE
        and snapshot.classification is EvidenceClassification.ACCEPTED
        and snapshot.confirmation is ConfirmationStatus.CONFIRMED
    )


def _validate_markout_request(*, horizon: timedelta, tolerance: timedelta) -> None:
    if horizon not in MARKOUT_HORIZONS:
        raise ValueError("markout horizon is not in the frozen set")
    if tolerance.total_seconds() < 0:
        raise ValueError("tolerance must not be negative")


def _unknown_markout(
    *,
    horizon: timedelta,
    time_basis: MarkoutTimeBasis,
) -> MarkoutLookup:
    return MarkoutLookup(
        horizon=horizon,
        time_basis=time_basis,
        status="UNKNOWN",
        price=None,
        snapshot_evidence_id=None,
    )


def _snapshot_time(
    snapshot: CanonicalResearchEvent,
    *,
    time_basis: MarkoutTimeBasis,
) -> datetime | None:
    if time_basis is MarkoutTimeBasis.LEADER_SOURCE:
        return snapshot.source_time
    return snapshot.observed_time


def _nonnegative_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    if not parsed.is_finite() or parsed < ZERO:
        return None
    return parsed


def _decision_digest(rows: Sequence[tuple[str, object]]) -> str:
    return payload_digest(
        {
            "rows": tuple((evidence_id, str(decision)) for evidence_id, decision in rows),
        }
    )
