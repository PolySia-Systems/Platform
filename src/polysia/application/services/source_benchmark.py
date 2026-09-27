"""Concurrent public-source benchmark for prospective research collection."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from polysia.application.ports.research_evidence import (
    ResearchObservationSource,
    SourceCandidate,
)
from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.domain.research_evidence.collector import percentile_nearest_rank
from polysia.domain.research_evidence.models import (
    CanonicalResearchEvent,
    EvidenceClassification,
    ObservationKind,
    SourceCandidateStatus,
    payload_digest,
)
from polysia.domain.research_evidence.replay import replay_same_observations
from polysia.storage.research_evidence import ResearchEvidenceStore


@dataclass(frozen=True, slots=True)
class SourceBenchmarkReport:
    payload: dict[str, Any]


async def run_source_benchmark(
    sources: tuple[ResearchObservationSource, ...],
    *,
    store: ResearchEvidenceStore,
    duration: timedelta,
    clock: Callable[[], datetime] | None = None,
    code_sha: str | None = None,
    configuration: Mapping[str, object] | None = None,
    unavailable: tuple[SourceCandidate, ...] = (),
) -> SourceBenchmarkReport:
    """Run all provided sources concurrently into one collector window."""

    if duration < timedelta(seconds=1) or duration > timedelta(minutes=20):
        raise ValueError("benchmark duration must be within 1 second and 20 minutes")
    wall = clock or (lambda: datetime.now(UTC))
    started = wall()
    deadline = started + duration
    config = dict(configuration or {"duration_seconds": int(duration.total_seconds())})
    configuration_digest = payload_digest(config)
    collector = ProspectiveCollector(
        store,
        code_sha=code_sha,
        configuration_digest=configuration_digest,
    )
    for source in sources:
        set_pending_observer = getattr(source, "set_pending_observer", None)
        if callable(set_pending_observer):
            set_pending_observer(store.capture_pending_observations)
        set_progress_store = getattr(source, "set_progress_store", None)
        if callable(set_progress_store):
            set_progress_store(
                store.completed_source_windows, store.record_completed_source_windows
            )

    async def drain(source: ResearchObservationSource) -> tuple[str, int]:
        count = 0
        errors = 0
        async for event in source.run(run_id=collector.run_id, deadline=deadline):
            persisted = await collector.ingest_async(event)
            count += 1
            if persisted.classification is EvidenceClassification.INCOMPLETE and (
                persisted.event_kind is ObservationKind.CONTROL
            ):
                errors += 1
        return source.candidate.candidate_id, count

    results = await asyncio.gather(*(drain(source) for source in sources), return_exceptions=True)
    interval = collector.close()
    events = store.load_events(run_id=collector.run_id)
    replay = replay_same_observations(events, interval_valid=interval.validity.value == "VALID")
    payload = summarize_benchmark(
        events,
        sources=sources,
        unavailable=unavailable,
        started=started,
        ended=wall(),
        run_id=collector.run_id,
        interval_validity=interval.validity.value,
        interval_reason=interval.reason,
        drain_results=tuple(results),
        replay_control_digest=replay.control_digest,
        replay_target_digest=replay.target_digest,
        replay_unknown_count=replay.unknown_count,
        code_sha=code_sha,
        configuration_digest=configuration_digest,
        reconnect_counts={
            source.candidate.candidate_id: int(getattr(source, "reconnect_count", 0))
            for source in sources
        },
    )
    return SourceBenchmarkReport(payload=payload)


def summarize_benchmark(
    events: tuple[CanonicalResearchEvent, ...],
    *,
    sources: tuple[ResearchObservationSource, ...],
    unavailable: tuple[SourceCandidate, ...],
    started: datetime,
    ended: datetime,
    run_id: str,
    interval_validity: str,
    interval_reason: str,
    drain_results: tuple[object, ...],
    replay_control_digest: str,
    replay_target_digest: str,
    replay_unknown_count: int,
    code_sha: str | None,
    configuration_digest: str,
    reconnect_counts: Mapping[str, int],
) -> dict[str, Any]:
    by_source: dict[str, list[CanonicalResearchEvent]] = defaultdict(list)
    for event in events:
        by_source[event.source_id].append(event)

    source_rows = []
    wallet_identity_sets: dict[str, set[str]] = {}
    matched_observations: dict[str, dict[str, datetime]] = {}
    for source in sources:
        source_events = tuple(
            event
            for event in events
            if _source_matches(event.source_id, source.candidate)
        )
        latencies = tuple(
            event.receive_normalize_latency_ns
            for event in source_events
            if event.event_kind is not ObservationKind.CONTROL
        )
        wall_lags_all = tuple(
            lag
            for event in source_events
            if event.source_time is not None
            and (lag := _wall_lag_ns(event)) is not None
        )
        wall_lags = tuple(lag for lag in wall_lags_all if lag >= 0)
        identity_groups: dict[str, list[CanonicalResearchEvent]] = defaultdict(list)
        unmatchable_count = 0
        for event in source_events:
            if (
                event.event_kind is ObservationKind.WALLET_TRADE
                and event.classification is EvidenceClassification.ACCEPTED
            ):
                key = _coverage_key(event)
                if key is None:
                    unmatchable_count += 1
                else:
                    identity_groups[key].append(event)
        ambiguous_keys = {
            key for key, group in identity_groups.items() if len(group) != 1
        }
        identities = set(identity_groups) - ambiguous_keys
        matched_observations[source.candidate.candidate_id] = {
            key: identity_groups[key][0].observed_time for key in identities
        }
        if source.candidate.wallet_attributable:
            wallet_identity_sets[source.candidate.candidate_id] = identities
        classified = _count_classifications(source_events)
        attributed = sum(
            1
            for event in source_events
            if event.attribution_status.value == "WALLET_ALIASED"
        )
        source_rows.append(
            {
                "candidate_id": source.candidate.candidate_id,
                "display_name": source.candidate.display_name,
                "kind": source.candidate.kind,
                "wallet_attributable": source.candidate.wallet_attributable,
                "status": source.candidate.status.value,
                "sample_count": len(source_events),
                "accepted_count": classified.get(EvidenceClassification.ACCEPTED.value, 0),
                "duplicate_count": classified.get(EvidenceClassification.DUPLICATE.value, 0),
                "late_count": classified.get(EvidenceClassification.LATE.value, 0),
                "conflicting_count": classified.get(EvidenceClassification.CONFLICTING.value, 0),
                "reverted_count": classified.get(EvidenceClassification.REVERTED.value, 0),
                "unattributable_count": classified.get(
                    EvidenceClassification.UNATTRIBUTABLE.value, 0
                ),
                "gap_count": classified.get(EvidenceClassification.GAP.value, 0),
                "overload_count": classified.get(EvidenceClassification.OVERLOAD.value, 0),
                "incomplete_count": classified.get(EvidenceClassification.INCOMPLETE.value, 0),
                "wallet_attributed_count": attributed,
                "receive_normalize_latency_ns": _latency_stats(latencies),
                "source_to_observe_wall_ns": {
                    **_latency_stats(wall_lags),
                    "clock_skew_count": len(wall_lags_all) - len(wall_lags),
                    "note": "wall_clock_with_source_timestamp_precision_and_skew_limits",
                },
                "reconnect_count": reconnect_counts.get(source.candidate.candidate_id, 0),
                "coverage_identity_count": len(identities),
                "coverage_identity_scope": "relative_union_of_unambiguous_wallet_trades",
                "unmatchable_trade_count": unmatchable_count,
                "ambiguous_identity_count": len(ambiguous_keys),
                "source_health": (
                    dict(snapshot())
                    if callable(snapshot := getattr(source, "health_snapshot", None))
                    else None
                ),
            }
        )

    union = set().union(*wallet_identity_sets.values()) if wallet_identity_sets else set()
    coverage = {
        candidate_id: None
        if not union
        else format(Decimal(len(identities)) / Decimal(len(union)), "f")
        for candidate_id, identities in wallet_identity_sets.items()
    }

    paired_differences: dict[str, dict[str, object]] = {}
    candidate_ids = sorted(wallet_identity_sets)
    for left_index, left in enumerate(candidate_ids):
        for right in candidate_ids[left_index + 1 :]:
            shared = wallet_identity_sets[left] & wallet_identity_sets[right]
            differences = tuple(
                int(
                    (matched_observations[left][key] - matched_observations[right][key])
                    .total_seconds()
                    * 1_000_000_000
                )
                for key in sorted(shared)
            )
            paired_differences[f"{left}_minus_{right}"] = {
                "n": len(differences),
                "p50_ns": percentile_nearest_rank(differences, 50),
                "p95_ns": (
                    percentile_nearest_rank(differences, 95)
                    if len(differences) >= 20
                    else None
                ),
                "p99_ns": (
                    percentile_nearest_rank(differences, 99)
                    if len(differences) >= 100
                    else None
                ),
                "note": "wall_clock_first_observation_difference_for_matched_trades",
            }

    freshness = _market_freshness_when_wallet_arrives(events)
    drain_errors = [
        str(item) for item in drain_results if isinstance(item, BaseException)
    ]
    selection = _select_source(source_rows, unavailable=unavailable)
    return {
        "code_sha": code_sha,
        "configuration_digest": configuration_digest,
        "coverage_vs_union": coverage,
        "coverage_note": "relative_source_union_not_upstream_ground_truth",
        "trade_matching_note": (
            "derived_from_wallet_alias_and_available_trade_fields; "
            "no_provider_unique_id_is_assumed"
        ),
        "resource_use": "not_measured_by_local_benchmark",
        "paired_first_observation_differences": paired_differences,
        "drain_errors": drain_errors,
        "ended_at": ended.isoformat(),
        "interval_reason": interval_reason,
        "interval_validity": interval_validity,
        "market_freshness_when_wallet_event_ns": freshness,
        "replay": {
            "control_digest": replay_control_digest,
            "target_digest": replay_target_digest,
            "unknown_count": replay_unknown_count,
            "note": "same_observations_current_control_and_target_exposure_v1",
        },
        "run_id": run_id,
        "selection": selection,
        "sources": source_rows,
        "started_at": started.isoformat(),
        "unavailable": [
            {
                "candidate_id": item.candidate_id,
                "reason": item.unavailable_reason,
                "status": item.status.value,
                "wallet_attributable": item.wallet_attributable,
            }
            for item in unavailable
        ],
        "window_seconds": int((ended - started).total_seconds()),
    }


_CANDIDATE_SOURCE_IDS = {
    "rest_activity": "polymarket:data-api:activity",
    "rest_trades": "polymarket:data-api:trades",
    "global_trades": "polymarket:data-api:global-trades",
    "clob_market_ws": "polymarket:clob:market-stream",
}


def _source_matches(source_id: str, candidate: SourceCandidate) -> bool:
    return source_id == _CANDIDATE_SOURCE_IDS.get(candidate.candidate_id, candidate.candidate_id)


def _coverage_key(event: CanonicalResearchEvent) -> str | None:
    if event.leader_alias is None or event.provenance.get("has_transaction") is not True:
        return None
    trade_id = event.provenance.get("source_match_id") or event.source_event_id
    if not isinstance(trade_id, str) or not trade_id:
        return None
    return payload_digest(
        {"leader_alias": event.leader_alias, "source_match_id": trade_id}
    )


def _latency_stats(values: tuple[int, ...]) -> dict[str, int | None]:
    return {
        "p50": percentile_nearest_rank(values, 50),
        "p95": percentile_nearest_rank(values, 95) if len(values) >= 20 else None,
        "p99": percentile_nearest_rank(values, 99) if len(values) >= 100 else None,
        "n": len(values),
    }


def _count_classifications(events: tuple[CanonicalResearchEvent, ...]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        counts[event.classification.value] += 1
    return dict(counts)


def _wall_lag_ns(event: CanonicalResearchEvent) -> int | None:
    if event.source_time is None:
        return None
    delta = event.observed_time - event.source_time
    return int(delta.total_seconds() * 1_000_000_000)


def _market_freshness_when_wallet_arrives(
    events: tuple[CanonicalResearchEvent, ...],
) -> dict[str, object]:
    market_by_token: dict[str, list[CanonicalResearchEvent]] = defaultdict(list)
    for event in events:
        if (
            event.event_kind is ObservationKind.MARKET_STATE
            and event.outcome_reference
            and event.classification is EvidenceClassification.ACCEPTED
        ):
            market_by_token[event.outcome_reference].append(event)
    lags: list[int] = []
    missing = 0
    wallet_events = [
        event
        for event in events
        if event.event_kind is ObservationKind.WALLET_TRADE
        and event.classification is EvidenceClassification.ACCEPTED
    ]
    for wallet in wallet_events:
        token = wallet.outcome_reference
        if token is None:
            missing += 1
            continue
        prior = [
            market
            for market in market_by_token.get(token, ())
            if market.observed_time <= wallet.observed_time
        ]
        if not prior:
            missing += 1
            continue
        latest = max(prior, key=lambda item: item.observed_time)
        lags.append(
            int((wallet.observed_time - latest.observed_time).total_seconds() * 1_000_000_000)
        )
    return {
        "n_wallet_events": len(wallet_events),
        "n_with_market_state": len(lags),
        "n_missing_market_state": missing,
        "p50": percentile_nearest_rank(tuple(lags), 50),
        "p95": percentile_nearest_rank(tuple(lags), 95),
        "p99": percentile_nearest_rank(tuple(lags), 99),
        "note": "market_ws_does_not_supply_wallet_identity",
    }


def _select_source(
    rows: list[dict[str, Any]],
    *,
    unavailable: tuple[SourceCandidate, ...],
) -> dict[str, Any]:
    wallet_rows = [
        row for row in rows
        if row["wallet_attributable"] is True and row["candidate_id"] != "global_trades"
    ]
    measured = [
        row
        for row in wallet_rows
        if row["status"] == SourceCandidateStatus.MEASURED.value
        and int(row["accepted_count"]) > 0
        and int(row["unattributable_count"]) == 0
        and int(row["incomplete_count"]) == 0
        and int(row["unmatchable_trade_count"]) == 0
        and int(row["ambiguous_identity_count"]) == 0
        and int(row["source_to_observe_wall_ns"]["clock_skew_count"]) == 0
        and int(row["coverage_identity_count"]) > 0
        and int(row["source_to_observe_wall_ns"]["n"]) > 0
    ]
    if not measured:
        return {
            "qualified": False,
            "selected_candidate_id": None,
            "reason": "no_public_wallet_source_met_attribution_and_sample_bar",
            "unavailable_count": len(unavailable),
            "fast_wallet_stream_qualified": False,
            "note": "lowest_latency_alone_does_not_win; no unauthenticated wallet stream",
        }
    # Integrity first: fewer conflicts/gaps/overloads, then coverage, then latency.
    def key(row: dict[str, Any]) -> tuple[int, int, int, int]:
        p50 = row["source_to_observe_wall_ns"]["p50"]
        latency = 10**18 if p50 is None else int(p50)
        return (
            int(row["conflicting_count"]) + int(row["gap_count"]) + int(row["overload_count"]),
            -int(row["coverage_identity_count"]),
            latency,
            -int(row["accepted_count"]),
        )

    winner = sorted(measured, key=key)[0]
    return {
        "qualified": True,
        "selected_candidate_id": winner["candidate_id"],
        "reason": "best_public_rest_wallet_source_not_a_fast_stream",
        "unavailable_count": len(unavailable),
        "fast_wallet_stream_qualified": False,
        "promotion_qualified": False,
        "promotion_reason": "requires_measured_coverage_latency_and_resource_acceptance",
        "note": "lowest_latency_alone_does_not_win; official user WS remains UNAVAILABLE",
    }
