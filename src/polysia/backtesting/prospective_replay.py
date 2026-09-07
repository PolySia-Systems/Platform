"""Replay recorded prospective evidence with Target Exposure v1.

Does not implement a second ledger. Current Control and Target Exposure
consume the same accepted observations.
"""

from __future__ import annotations

from datetime import timedelta

from polysia.domain.copytrading.target_exposure import TargetExposurePolicy
from polysia.domain.research_evidence.models import IntervalValidity, ResearchInterval
from polysia.domain.research_evidence.replay import (
    SameObservationReplay,
    replay_same_observations,
)
from polysia.storage.research_evidence import ResearchEvidenceStore


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
