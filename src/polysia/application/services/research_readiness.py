"""Read-only, provisional sample progress for a frozen v3 Research run."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polysia.backtesting.prospective_replay import replay_recorded_experiment
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.storage.research_evidence import ResearchEvidenceStore

READINESS_VERSION = "research-sample-readiness-v1"


def research_readiness(
    database: Path,
    *,
    run_id: str,
    t0: datetime,
    observed_at: datetime,
    minimum_observation_seconds: int,
    hard_limit_seconds: int,
    source_health: Mapping[str, object],
) -> dict[str, object]:
    """Replay closed valid windows; a provisional signal never closes a run."""

    if (
        t0.tzinfo is None or t0.utcoffset() != timedelta(0)
        or observed_at.tzinfo is None or observed_at.utcoffset() != timedelta(0)
        or observed_at < t0 or not 0 < minimum_observation_seconds <= hard_limit_seconds
    ):
        raise ValueError("research readiness clocks or frozen bounds are invalid")
    elapsed = min(int((observed_at - t0).total_seconds()), hard_limit_seconds)
    store = ResearchEvidenceStore(database, read_only=True)
    replay = replay_recorded_experiment(
        store, run_id=run_id, retain_traces=False,
    )
    report = replay.economics
    eligible = report.eligible_observations
    elapsed_rate = (
        None if elapsed <= 0 else
        format(Decimal(eligible) * Decimal(3600) / Decimal(elapsed), ".3f")
    )
    missing = max(0, CONTRACT_V1.canary_min_eligible - eligible)
    source_ok = source_health.get("research_data_eligible") is True
    complete_windows = len(replay.valid_intervals)
    coverage_pass = report.data_canary_status == "PASS"
    if not source_ok or replay.invalid_intervals:
        state = "BLOCKED_COVERAGE"
    elif complete_windows == 0:
        state = "WAITING_FOR_CLOSED_WINDOW"
    elif elapsed < minimum_observation_seconds:
        state = "WAITING_MINIMUM_PERIOD"
    elif coverage_pass:
        state = "PROVISIONALLY_SUFFICIENT"
    else:
        state = "INSUFFICIENT_DATA"
    return {
        "version": READINESS_VERSION,
        "status": state,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "eligible_observations": eligible,
        "missing_eligible_observations": missing,
        "mapping_ratio": format(report.mapping_ratio, "f"),
        "execution_evidence_ratio": format(report.execution_evidence_ratio, "f"),
        "minimum_eligible": CONTRACT_V1.canary_min_eligible,
        "minimum_mapping_ratio": format(CONTRACT_V1.canary_mapping_ratio, "f"),
        "minimum_execution_ratio": format(CONTRACT_V1.canary_execution_ratio, "f"),
        "valid_windows": complete_windows,
        "invalid_windows": len(replay.invalid_intervals),
        "elapsed_seconds": elapsed,
        "minimum_observation_seconds": minimum_observation_seconds,
        "hard_limit_seconds": hard_limit_seconds,
        "eligible_events_per_hour_observed": elapsed_rate,
        "rate_uncertainty": "high; correlated observations and future activity may differ",
        "economic_status": "NOT_FINALIZED",
        "completion_note": (
            "Provisional readiness does not bypass window closure, durable "
            "finalization, replay verification, or operational checks."
        ),
    }
