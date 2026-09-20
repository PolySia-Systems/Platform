"""Replay recorded prospective evidence with Target Exposure v1.

Does not implement a second ledger. Current Control and Target Exposure
consume the same accepted observations.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import timedelta

from polysia.backtesting.prospective_economics import (
    ProspectiveEconomicReport,
    WalletEconomicReport,
    evaluate_prospective_economics,
)
from polysia.domain.copytrading.target_exposure import TargetExposurePolicy
from polysia.domain.research_evidence.models import (
    CanonicalResearchEvent,
    IntervalValidity,
    ObservationKind,
    ResearchInterval,
)
from polysia.domain.research_evidence.replay import (
    SameObservationReplay,
    replay_same_observations,
)
from polysia.storage.research_evidence import ResearchEvidenceStore

REPLAY_CALLS: list[str] = []


@dataclass(frozen=True, slots=True)
class RecordedExperimentReplay:
    """Replay result and the exact interval scope used to produce it."""

    result: SameObservationReplay
    valid_intervals: tuple[ResearchInterval, ...]
    invalid_intervals: tuple[ResearchInterval, ...]
    replayed_event_count: int
    excluded_event_count: int
    economics: ProspectiveEconomicReport
    wallet_economics: tuple[WalletEconomicReport, ...] = ()


def replay_identity(replay: RecordedExperimentReplay) -> tuple[object, ...]:
    """Compact identity used for deterministic comparison without retaining traces."""

    return (
        replay.result.control_digest,
        replay.result.target_digest,
        replay.result.unknown_count,
        replay.result.unknown_by_cause,
        replay.result.eligible_observation_count,
        replay.result.mapped_observation_count,
        replay.result.execution_evidence_count,
        replay.replayed_event_count,
        replay.excluded_event_count,
        replay.economics.digest,
        tuple(
            (item.leader_alias, item.economics.digest)
            for item in replay.wallet_economics
        ),
        len(replay.valid_intervals),
        len(replay.invalid_intervals),
    )


def replay_recorded_run(
    store: ResearchEvidenceStore,
    *,
    run_id: str,
    interval: ResearchInterval,
    policy: TargetExposurePolicy | None = None,
    markout_tolerance: timedelta = timedelta(seconds=1),
) -> SameObservationReplay:
    events = store.load_events(run_id=run_id)
    snapshots = tuple(
        event for event in events if event.event_kind is ObservationKind.MARKET_STATE
    )
    return replay_same_observations(
        events,
        policy=policy,
        interval_valid=interval.validity is IntervalValidity.VALID,
        snapshots=snapshots,
        markout_tolerance=markout_tolerance,
    )


def replay_recorded_experiment(
    store: ResearchEvidenceStore,
    *,
    run_id: str,
    policy: TargetExposurePolicy | None = None,
    markout_tolerance: timedelta = timedelta(seconds=1),
    record_markouts: bool = False,
    retain_traces: bool = True,
) -> RecordedExperimentReplay:
    """Replay only evidence from independently valid windows in one experiment."""

    REPLAY_CALLS.append(run_id)
    intervals = store.load_intervals_for_run(run_id)
    valid_intervals = tuple(
        interval for interval in intervals if interval.validity is IntervalValidity.VALID
    )
    invalid_intervals = tuple(
        interval for interval in intervals if interval.validity is not IntervalValidity.VALID
    )
    total_events = store.experiment_event_count(run_id)
    if not valid_intervals:
        empty = replay_same_observations((), policy=policy, interval_valid=True)
        return RecordedExperimentReplay(
            result=empty,
            valid_intervals=(),
            invalid_intervals=invalid_intervals,
            replayed_event_count=0,
            excluded_event_count=total_events,
            economics=evaluate_prospective_economics(empty, events=()),
        )
    snapshots = _collect_snapshots(store, run_id=run_id)
    events = store.iter_events(run_id=run_id, interval_validity=IntervalValidity.VALID)
    counted_events, events = _count_and_tee(events)
    replay = replay_same_observations(
        events,
        policy=policy,
        interval_valid=True,
        snapshots=snapshots,
        markout_tolerance=markout_tolerance,
        ordered=True,
        record_markouts=record_markouts,
    )
    replayed_event_count = counted_events[0]
    if replayed_event_count == 0:
        del snapshots
        empty = replay_same_observations((), policy=policy, interval_valid=True)
        return RecordedExperimentReplay(
            result=empty,
            valid_intervals=valid_intervals,
            invalid_intervals=invalid_intervals,
            replayed_event_count=0,
            excluded_event_count=total_events,
            economics=evaluate_prospective_economics(empty, events=()),
        )
    economics = evaluate_prospective_economics(replay, events=snapshots)
    wallet_economics = _evaluate_wallet_economics(
        store,
        run_id=run_id,
        aliases=tuple(
            sorted(
                {
                    row.leader_alias
                    for row in replay.evaluations
                    if row.leader_alias is not None
                }
            )
        ),
        snapshots=snapshots,
        policy=policy,
        markout_tolerance=markout_tolerance,
    )
    del snapshots
    if not retain_traces:
        replay = _compact_replay_result(replay)
    return RecordedExperimentReplay(
        result=replay,
        valid_intervals=valid_intervals,
        invalid_intervals=invalid_intervals,
        replayed_event_count=replayed_event_count,
        excluded_event_count=total_events - replayed_event_count,
        economics=economics,
        wallet_economics=wallet_economics,
    )


def _collect_snapshots(
    store: ResearchEvidenceStore, *, run_id: str
) -> tuple[CanonicalResearchEvent, ...]:
    return tuple(
        store.iter_events(
            run_id=run_id,
            interval_validity=IntervalValidity.VALID,
            event_kind=ObservationKind.MARKET_STATE,
        )
    )


def _evaluate_wallet_economics(
    store: ResearchEvidenceStore,
    *,
    run_id: str,
    aliases: tuple[str, ...],
    snapshots: tuple[CanonicalResearchEvent, ...],
    policy: TargetExposurePolicy | None,
    markout_tolerance: timedelta,
) -> tuple[WalletEconomicReport, ...]:
    reports: list[WalletEconomicReport] = []
    for alias in aliases:
        wallet_events = (
            event
            for event in store.iter_events(
                run_id=run_id,
                interval_validity=IntervalValidity.VALID,
                event_kind=ObservationKind.WALLET_TRADE,
            )
            if event.leader_alias == alias
        )
        replay = replay_same_observations(
            wallet_events,
            policy=policy,
            interval_valid=True,
            snapshots=snapshots,
            markout_tolerance=markout_tolerance,
            ordered=True,
            record_markouts=False,
        )
        reports.append(
            WalletEconomicReport(
                leader_alias=alias,
                economics=evaluate_prospective_economics(replay, events=snapshots),
            )
        )
    return tuple(reports)


def _count_and_tee(
    events: Iterable[CanonicalResearchEvent],
) -> tuple[list[int], Iterator[CanonicalResearchEvent]]:
    counted = [0]

    def iterator() -> Iterator[CanonicalResearchEvent]:
        for event in events:
            counted[0] += 1
            yield event

    return counted, iterator()


def _compact_replay_result(result: SameObservationReplay) -> SameObservationReplay:
    return replace(
        result,
        control_decisions=(),
        target_decisions=(),
        leader_markouts=(),
        follower_markouts=(),
        evaluations=(),
    )
