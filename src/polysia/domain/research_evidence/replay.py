"""Same-observation Current Control vs Target Exposure replay.

Reuses frozen Target Exposure v1. Does not create a second accounting engine
or a Live/Risk/Execution path. Missing books, prices, marks, and gaps stay
UNKNOWN. Event-time markouts never interpolate.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
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
from polysia.domain.research_evidence.economic_contract import taker_fee
from polysia.domain.research_evidence.models import (
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)

REPLAY_ENGINE_VERSION = "same-observation-replay-v1"
MARKOUT_HORIZONS: tuple[timedelta, ...] = (
    timedelta(seconds=5),
    timedelta(seconds=30),
    timedelta(minutes=5),
)
EXECUTION_EVIDENCE_MAX_AGE = timedelta(seconds=30)
EXECUTION_EVIDENCE_ACQUISITION_MAX_DELAY = timedelta(seconds=30)


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
    notional: Decimal = ZERO
    slippage: Decimal = ZERO
    partial_fill: bool = False
    fee_rate: Decimal | None = None
    fee_model_version: str = "legacy-recorded-fee"
    economically_complete: bool = False


@dataclass(frozen=True, slots=True)
class ObservationEvaluation:
    evidence_id: str
    leader_alias: str | None
    market_reference: str
    outcome_reference: str
    side: str
    decision_time: datetime
    execution: ExecutionEvidence | None
    unknown_reason: str | None
    control_decision: str
    target_decision: str


@dataclass(slots=True)
class _EpisodeState:
    open: bool = False
    first_price: Decimal | None = None
    exposure: Decimal = ZERO
    quantity: Decimal = ZERO
    closed: bool = False


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
    unknown_by_cause: tuple[tuple[str, int], ...] = ()
    evaluations: tuple[ObservationEvaluation, ...] = ()
    eligible_observation_count: int = 0
    mapped_observation_count: int = 0
    execution_evidence_count: int = 0
    partial_fill_count: int = 0


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
            if snapshot.outcome_reference is None:
                continue
            if (
                _is_base_snapshot(snapshot)
                and snapshot.price is not None
                and snapshot.provenance.get("markout_eligible") is not False
            ):
                markouts[
                    (snapshot.outcome_reference, MarkoutTimeBasis.FOLLOWER_OBSERVED)
                ].append((snapshot.observed_time, snapshot))
                if snapshot.source_time is not None:
                    markouts[
                        (snapshot.outcome_reference, MarkoutTimeBasis.LEADER_SOURCE)
                    ].append((snapshot.source_time, snapshot))
            if _is_execution_candidate(snapshot):
                assert snapshot.side is not None
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
        self._execution_markets = {
            key: frozenset(
                snapshot.market_reference
                for snapshot in timeline.events
                if snapshot.market_reference is not None
            )
            for key, timeline in self._executions.items()
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
        acquisition_max_delay: timedelta,
        entry_budget: Decimal,
    ) -> tuple[ExecutionEvidence | None, str | None, bool, datetime]:
        if max_age.total_seconds() < 0 or acquisition_max_delay.total_seconds() < 0:
            raise ValueError("execution evidence time bounds must not be negative")
        timeline = self._executions.get(
            (observation.outcome_reference, observation.side)
        )
        if timeline is None:
            mapped = any(
                key[0] == observation.outcome_reference for key in self._executions
            )
            return (
                None,
                "missing_quote" if mapped else "missing_market_token_mapping",
                mapped,
                observation.observed_time,
            )
        cutoff = observation.observed_time - max_age
        future_cutoff = observation.observed_time + acquisition_max_delay
        markets = self._execution_markets.get(
            (observation.outcome_reference, observation.side), frozenset()
        )
        if observation.market_reference not in markets:
            return None, "missing_market_token_mapping", False, observation.observed_time
        first_failure: tuple[str, datetime] | None = None
        left = bisect_left(timeline.times, cutoff)
        mid = bisect_right(timeline.times, observation.observed_time)
        future_right = bisect_right(timeline.times, future_cutoff)
        for index in range(mid - 1, left - 1, -1):
            snapshot = timeline.events[index]
            if snapshot.market_reference != observation.market_reference:
                continue
            evidence, reason, decision_time = _execution_from_snapshot(
                snapshot,
                observation=observation,
                entry_budget=entry_budget,
            )
            if evidence is not None:
                return evidence, None, True, decision_time
            if first_failure is None and reason is not None:
                first_failure = (reason, decision_time)
        for index in range(mid, future_right):
            snapshot = timeline.events[index]
            if snapshot.market_reference != observation.market_reference:
                continue
            evidence, reason, decision_time = _execution_from_snapshot(
                snapshot,
                observation=observation,
                entry_budget=entry_budget,
            )
            if evidence is not None:
                return evidence, None, True, decision_time
            if first_failure is None and reason is not None:
                first_failure = (reason, decision_time)
        if first_failure is not None:
            return None, first_failure[0], True, first_failure[1]
        stale = any(
            timeline.events[index].market_reference == observation.market_reference
            for index in range(left)
        )
        if stale:
            return None, "stale_quote", True, observation.observed_time
        return None, "missing_quote", True, observation.observed_time


def _execution_from_snapshot(
    snapshot: CanonicalResearchEvent,
    *,
    observation: ProspectiveObservation,
    entry_budget: Decimal,
) -> tuple[ExecutionEvidence | None, str | None, datetime]:
    decision_time = max(observation.observed_time, snapshot.observed_time)
    if snapshot.provenance.get("execution_evidence_version") == "order-book-depth-v1":
        evidence, reason = depth_execution_from_snapshot(
            snapshot,
            observation=observation,
            entry_budget=entry_budget,
        )
        if evidence is not None:
            return evidence, None, decision_time
        return None, reason or "missing_quote", decision_time
    fee = _nonnegative_decimal(snapshot.provenance.get("recorded_fee"))
    if fee is not None and snapshot.price is not None and snapshot.size is not None:
        return (
            ExecutionEvidence(
                snapshot_evidence_id=snapshot.evidence_id,
                executable_price=snapshot.price,
                available_quantity=snapshot.size,
                recorded_fee=fee,
            ),
            None,
            decision_time,
        )
    return (
        None,
        str(snapshot.provenance.get("execution_failure") or "missing_fee"),
        decision_time,
    )


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
    events: Iterable[CanonicalResearchEvent],
    *,
    policy: TargetExposurePolicy | None = None,
    interval_valid: bool = True,
    snapshots: Sequence[CanonicalResearchEvent] = (),
    markout_tolerance: timedelta = timedelta(seconds=1),
    execution_evidence_max_age: timedelta = EXECUTION_EVIDENCE_MAX_AGE,
    execution_evidence_acquisition_max_delay: timedelta = (
        EXECUTION_EVIDENCE_ACQUISITION_MAX_DELAY
    ),
    ordered: bool = False,
    record_markouts: bool = True,
) -> SameObservationReplay:
    """Consume one observation stream for Current Control and Target Exposure."""

    policy = policy or TargetExposurePolicy()
    ordered_events: Iterable[CanonicalResearchEvent]
    if ordered:
        ordered_events = events
    else:
        ordered_events = tuple(
            sorted(
                events,
                key=lambda item: (item.observed_time, item.evidence_id),
            )
        )
    snapshot_index = _ReplaySnapshotIndex(tuple(snapshots))
    control: list[tuple[str, ControlAdmission]] = []
    target: list[tuple[str, TargetExposureDecision | str]] = []
    leader_markouts: list[tuple[str, tuple[MarkoutLookup, ...]]] = []
    follower_markouts: list[tuple[str, tuple[MarkoutLookup, ...]]] = []
    evaluations: list[ObservationEvaluation] = []
    unknown_by_cause: dict[str, int] = defaultdict(int)
    unknown_count = 0
    eligible_count = 0
    mapped_count = 0
    execution_count = 0
    partial_count = 0
    target_episodes: dict[tuple[str, str], _EpisodeState] = {}
    control_episodes: dict[tuple[str, str], _EpisodeState] = {}
    control_cash = Decimal("1000")
    target_cash = Decimal("1000")

    for event in ordered_events:
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
        eligible_count += 1
        key = (observation.market_reference, observation.outcome_reference)
        episode = target_episodes.setdefault(key, _EpisodeState())
        control_episode = control_episodes.setdefault(key, _EpisodeState())
        execution, unknown_reason, mapped, decision_time = snapshot_index.execution(
            observation=observation,
            max_age=execution_evidence_max_age,
            acquisition_max_delay=execution_evidence_acquisition_max_delay,
            entry_budget=policy.entry_budget,
        )
        if mapped:
            mapped_count += 1
        if execution is not None and execution.economically_complete:
            execution_count += 1
            if execution.partial_fill:
                partial_count += 1
        control_decision: ControlAdmission
        target_decision: TargetExposureDecision | str
        if execution is None:
            reason = unknown_reason or "missing_quote"
            unknown_count += 1
            unknown_by_cause[reason] += 1
            control_decision = ControlAdmission.UNKNOWN
            target_decision = "UNKNOWN"
            control.append((observation.evidence_id, control_decision))
            target.append((observation.evidence_id, target_decision))
            evaluations.append(
                ObservationEvaluation(
                    evidence_id=observation.evidence_id,
                    leader_alias=event.leader_alias,
                    market_reference=observation.market_reference,
                    outcome_reference=observation.outcome_reference,
                    side=observation.side,
                    decision_time=decision_time,
                    execution=None,
                    unknown_reason=reason,
                    control_decision=control_decision.value,
                    target_decision=str(target_decision),
                )
            )
            _append_markouts(
                observation,
                snapshot_index=snapshot_index,
                tolerance=markout_tolerance,
                leader=leader_markouts,
                follower=follower_markouts,
                follower_event_time=decision_time,
            )
            continue
        if observation.side == "BUY":
            control_notional = execution.notional or min(
                policy.entry_budget,
                execution.executable_price * execution.available_quantity,
            )
            control_quantity = control_notional / execution.executable_price
            requested = control_quantity
            control_fee = (
                execution.recorded_fee
                if execution.notional > ZERO
                else execution.recorded_fee
                * control_quantity
                / execution.available_quantity
            )
            requested_fee = control_fee
            market_exposure = sum(
                item.exposure
                for episode_key, item in control_episodes.items()
                if episode_key[0] == key[0]
            )
            if (
                control_cash >= control_notional + control_fee
                and market_exposure + control_notional <= policy.market_exposure_cap
            ):
                control_decision = ControlAdmission.ADMIT
                control_cash -= control_notional + control_fee
                control_episode.open = True
                control_episode.quantity += control_quantity
                control_episode.exposure += control_notional
            else:
                control_decision = ControlAdmission.SKIP
            control.append((observation.evidence_id, control_decision))
            admission = decide_entry(
                policy,
                episode_open=episode.open,
                episode_closed=episode.closed,
                first_entry_price=episode.first_price,
                executable_price=execution.executable_price,
                requested_quantity=requested,
                recorded_fee=requested_fee,
                opposing_quantity=sum(
                    (
                        item.quantity
                        for episode_key, item in target_episodes.items()
                        if episode_key[0] == key[0] and episode_key != key
                    ),
                    ZERO,
                ),
                market_exposure=sum(
                    (
                        item.exposure
                        for episode_key, item in target_episodes.items()
                        if episode_key[0] == key[0]
                    ),
                    ZERO,
                ),
                cash=target_cash,
            )
            target_decision = admission.decision
            target.append((observation.evidence_id, target_decision))
            if admission.accepted:
                episode.open = True
                episode.first_price = execution.executable_price
                target_cash -= admission.notional + admission.fee
                episode.exposure += admission.notional
                episode.quantity += admission.target_quantity
        else:
            if control_episode.quantity > ZERO:
                control_decision = ControlAdmission.ADMIT
                exit_quantity = min(control_episode.quantity, execution.available_quantity)
                ratio = exit_quantity / control_episode.quantity
                released = control_episode.exposure * ratio
                control_episode.quantity -= exit_quantity
                control_episode.exposure -= released
                control_cash += execution.executable_price * exit_quantity - (
                    execution.recorded_fee * exit_quantity / execution.available_quantity
                )
                if control_episode.quantity <= Decimal("0.000001"):
                    control_episode.quantity = ZERO
                    control_episode.exposure = ZERO
                    control_episode.open = False
                    control_episode.closed = True
            else:
                control_decision = ControlAdmission.SKIP
            if episode.quantity > ZERO:
                target_decision = "EXIT"
                exit_quantity = min(episode.quantity, execution.available_quantity)
                ratio = exit_quantity / episode.quantity
                released = episode.exposure * ratio
                episode.quantity -= exit_quantity
                episode.exposure -= released
                target_cash += execution.executable_price * exit_quantity - (
                    execution.recorded_fee * exit_quantity / execution.available_quantity
                )
                if episode.quantity <= Decimal("0.000001"):
                    episode.quantity = ZERO
                    episode.exposure = ZERO
                    episode.open = False
                    episode.closed = True
            else:
                target_decision = TargetExposureDecision.SKIP_REPEAT_SIGNAL
            control.append((observation.evidence_id, control_decision))
            target.append((observation.evidence_id, target_decision))

        evaluations.append(
            ObservationEvaluation(
                evidence_id=observation.evidence_id,
                leader_alias=event.leader_alias,
                market_reference=observation.market_reference,
                outcome_reference=observation.outcome_reference,
                side=observation.side,
                decision_time=decision_time,
                execution=execution,
                unknown_reason=None,
                control_decision=control_decision.value,
                target_decision=str(target_decision),
            )
        )

        if record_markouts:
            _append_markouts(
                observation,
                snapshot_index=snapshot_index,
                tolerance=markout_tolerance,
                leader=leader_markouts,
                follower=follower_markouts,
                follower_event_time=decision_time,
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
        unknown_by_cause=tuple(sorted(unknown_by_cause.items())),
        evaluations=tuple(evaluations),
        eligible_observation_count=eligible_count,
        mapped_observation_count=mapped_count,
        execution_evidence_count=execution_count,
        partial_fill_count=partial_count,
    )


def _append_markouts(
    observation: ProspectiveObservation,
    *,
    snapshot_index: _ReplaySnapshotIndex,
    tolerance: timedelta,
    leader: list[tuple[str, tuple[MarkoutLookup, ...]]],
    follower: list[tuple[str, tuple[MarkoutLookup, ...]]],
    follower_event_time: datetime,
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
                event_time=follower_event_time,
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


def _is_execution_candidate(snapshot: CanonicalResearchEvent) -> bool:
    return (
        snapshot.event_kind is ObservationKind.MARKET_STATE
        and snapshot.classification is EvidenceClassification.ACCEPTED
        and snapshot.outcome_reference is not None
        and snapshot.side in {"BUY", "SELL"}
        and (
            snapshot.provenance.get("execution_evidence_version")
            == "order-book-depth-v1"
            or snapshot.provenance.get("execution_evidence") is True
        )
    )


def depth_execution_from_snapshot(
    snapshot: CanonicalResearchEvent,
    *,
    observation: ProspectiveObservation,
    entry_budget: Decimal,
) -> tuple[ExecutionEvidence | None, str | None]:
    enabled = snapshot.provenance.get("fees_enabled")
    rate = _nonnegative_decimal(snapshot.provenance.get("fee_rate"))
    exponent = _nonnegative_decimal(snapshot.provenance.get("fee_exponent"))
    taker_only = snapshot.provenance.get("fee_taker_only")
    if enabled is False:
        rate = ZERO
        exponent = ZERO
        taker_only = True
    if rate is None or exponent is None or taker_only is not True:
        return None, "missing_fee"
    raw_levels = snapshot.provenance.get("book_levels")
    if not isinstance(raw_levels, list | tuple) or not raw_levels:
        return None, "missing_depth"
    levels: list[tuple[Decimal, Decimal]] = []
    for raw in raw_levels:
        if not isinstance(raw, dict):
            return None, "missing_depth"
        price = _positive_decimal(raw.get("price"))
        size = _positive_decimal(raw.get("size"))
        if price is None or size is None:
            return None, "missing_depth"
        levels.append((price, size))
    remaining_quantity = observation.size
    requested_notional = min(entry_budget, observation.price * observation.size)
    remaining_notional = requested_notional
    filled = ZERO
    notional = ZERO
    fee = ZERO
    for price, available in levels:
        if observation.side == "BUY":
            quantity = min(available, remaining_quantity, remaining_notional / price)
        else:
            quantity = min(available, remaining_quantity)
        if quantity <= ZERO:
            continue
        filled += quantity
        level_notional = price * quantity
        notional += level_notional
        fee += taker_fee(
            shares=quantity,
            price=price,
            rate=rate,
            exponent=exponent,
        )
        remaining_quantity -= quantity
        if observation.side == "BUY":
            remaining_notional -= level_notional
            if remaining_notional <= Decimal("0.000000000001"):
                break
        elif remaining_quantity <= ZERO:
            break
    if filled <= ZERO or notional <= ZERO:
        return None, "insufficient_depth"
    quantity_remaining = remaining_quantity > Decimal("0.000001")
    partial = (
        quantity_remaining and remaining_notional > Decimal("0.000001")
        if observation.side == "BUY"
        else quantity_remaining
    )
    vwap = notional / filled
    slippage_per_share = (
        max(ZERO, vwap - observation.price)
        if observation.side == "BUY"
        else max(ZERO, observation.price - vwap)
    )
    return (
        ExecutionEvidence(
            snapshot_evidence_id=snapshot.evidence_id,
            executable_price=vwap,
            available_quantity=filled,
            recorded_fee=fee,
            notional=notional,
            slippage=slippage_per_share * filled,
            partial_fill=partial,
            fee_rate=rate,
            fee_model_version=str(
                snapshot.provenance.get("fee_calculation_version")
                or "polymarket-taker-fee-v1"
            ),
            economically_complete=True,
        ),
        None,
    )


def _positive_decimal(value: object) -> Decimal | None:
    parsed = _nonnegative_decimal(value)
    if parsed is None or parsed <= ZERO:
        return None
    return parsed


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


__all__ = [
    "ControlAdmission",
    "ExecutionEvidence",
    "MarkoutLookup",
    "MarkoutTimeBasis",
    "ObservationEvaluation",
    "ProspectiveObservation",
    "REPLAY_ENGINE_VERSION",
    "SameObservationReplay",
    "depth_execution_from_snapshot",
    "lookup_event_time_mark",
    "lookup_execution_evidence",
    "observation_from_event",
    "replay_same_observations",
]
