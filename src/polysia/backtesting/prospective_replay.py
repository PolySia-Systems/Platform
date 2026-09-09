"""Replay recorded prospective evidence with Target Exposure v1.

Does not implement a second ledger. Current Control and Target Exposure
consume the same accepted observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from polysia.backtesting.prospective_economics import (
    ProspectiveEconomicReport,
    evaluate_prospective_economics,
)
from polysia.domain.copytrading.target_exposure import TargetExposurePolicy
from polysia.domain.research_evidence.models import IntervalValidity, ResearchInterval
from polysia.domain.research_evidence.replay import (
    SameObservationReplay,
    replay_same_observations,
)
from polysia.storage.research_evidence import ResearchEvidenceStore


@dataclass(frozen=True, slots=True)
class RecordedExperimentReplay:
    """Replay result and the exact interval scope used to produce it."""

    result: SameObservationReplay
    valid_intervals: tuple[ResearchInterval, ...]
    invalid_intervals: tuple[ResearchInterval, ...]
    replayed_event_count: int
    excluded_event_count: int
    economics: ProspectiveEconomicReport


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
        event for event in events if event.event_kind.value == "MARKET_STATE"
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
) -> RecordedExperimentReplay:
    """Replay only evidence from independently valid windows in one experiment."""

    intervals = store.load_intervals_for_run(run_id)
    valid_intervals = tuple(
        interval for interval in intervals if interval.validity is IntervalValidity.VALID
    )
    invalid_intervals = tuple(
        interval for interval in intervals if interval.validity is not IntervalValidity.VALID
    )
    if not valid_intervals:
        raise ValueError("experiment has no valid replayable interval")
    events = store.load_events(
        run_id=run_id,
        interval_validity=IntervalValidity.VALID,
    )
    if not events:
        raise ValueError("experiment has no evidence in a valid interval")
    snapshots = tuple(
        event for event in events if event.event_kind.value == "MARKET_STATE"
    )
    replay = replay_same_observations(
        events,
        policy=policy,
        interval_valid=True,
        snapshots=snapshots,
        markout_tolerance=markout_tolerance,
    )
    total_events = store.experiment_event_count(run_id)
    return RecordedExperimentReplay(
        result=replay,
        valid_intervals=valid_intervals,
        invalid_intervals=invalid_intervals,
        replayed_event_count=len(events),
        excluded_event_count=total_events - len(events),
        economics=evaluate_prospective_economics(replay, events=events),
    )
