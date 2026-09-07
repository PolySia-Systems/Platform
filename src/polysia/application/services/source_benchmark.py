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
        wall_lags = tuple(
            lag
            for event in source_events
            if event.source_time is not None
            and event.source_time >= started
            and (lag := _wall_lag_ns(event)) is not None
        )
        identities = {
            _coverage_key(event)
            for event in source_events
            if event.event_kind is ObservationKind.WALLET_TRADE
            and event.classification is EvidenceClassification.ACCEPTED
        }
        identities.discard("")
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
                "receive_normalize_latency_ns": {
                    "p50": percentile_nearest_rank(latencies, 50),
                    "p95": percentile_nearest_rank(latencies, 95),
                    "p99": percentile_nearest_rank(latencies, 99),
                    "n": len(latencies),
                },
                "source_to_observe_wall_ns": {
                    "p50": percentile_nearest_rank(wall_lags, 50),
                    "p95": percentile_nearest_rank(wall_lags, 95),
                    "p99": percentile_nearest_rank(wall_lags, 99),
                    "n": len(wall_lags),
                    "note": "wall_clock_not_monotonic",
                },
                "reconnect_count": reconnect_counts.get(source.candidate.candidate_id, 0),
                "coverage_identity_count": len(identities),
            }
        )

    union = set().union(*wallet_identity_sets.values()) if wallet_identity_sets else set()
    coverage = {
        candidate_id: None
        if not union
        else format(Decimal(len(identities)) / Decimal(len(union)), "f")
        for candidate_id, identities in wallet_identity_sets.items()
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
    "clob_market_ws": "polymarket:clob:market-stream",
}


def _source_matches(source_id: str, candidate: SourceCandidate) -> bool:
    return source_id == _CANDIDATE_SOURCE_IDS.get(candidate.candidate_id, candidate.candidate_id)


def _coverage_key(event: CanonicalResearchEvent) -> str:
    tx_hash = event.provenance.get("has_transaction")
    return payload_digest(
        {
            "market": event.market_reference,
            "outcome": event.outcome_reference,
            "side": event.side,
            "source_time": None if event.source_time is None else event.source_time.isoformat(),
            "tx_present": tx_hash,
        }
    )


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
    wallet_rows = [row for row in rows if row["wallet_attributable"] is True]
    measured = [
        row
        for row in wallet_rows
        if row["status"] == SourceCandidateStatus.MEASURED.value
        and int(row["accepted_count"]) > 0
        and int(row["unattributable_count"]) == 0
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
        p50 = row["receive_normalize_latency_ns"]["p50"]
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
        "note": "lowest_latency_alone_does_not_win; official user WS remains UNAVAILABLE",
    }
