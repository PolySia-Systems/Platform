"""Retained native/PolyCop discovery -> shared identity -> explainable cohort.

No acquisition, account access, strategy promotion, or execution authority.
Provider observations remain separate from independent follower qualification.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from polysia.application.ports.candidate_wallets import (
    CandidateStoredSnapshot,
    CandidateWalletStorePort,
)
from polysia.application.ports.source_cohort import CandidateIdentityStorePort
from polysia.application.services.candidate_intelligence import PIPELINE_LEASE_RESOURCE
from polysia.application.services.candidate_wallet_sync import CandidateWalletSyncService
from polysia.domain.wallet_intelligence import (
    CandidateWalletDataset,
    CandidateWalletRecord,
    normalize_evm_wallet,
)
from polysia.domain.wallet_intelligence.models import JsonValue
from polysia.domain.wallet_intelligence.source_cohort import (
    CohortCandidate,
    CohortSelectionPolicy,
    FollowerQualificationEvidence,
    RetainedCandidateSnapshot,
    qualification_reasons,
    require_utc,
)


def _json(value: object) -> str:
    def encode(item: object) -> object:
        if isinstance(item, datetime):
            return require_utc(item).isoformat()
        if isinstance(item, timedelta):
            # Exact and reversible without a floating-point total_seconds round trip.
            return {"days": item.days, "seconds": item.seconds, "microseconds": item.microseconds}
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError("non-finite source evidence")
            return str(item)
        raise TypeError("unsupported source evidence")

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=encode)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class IngestedCandidateSnapshot:
    retained: RetainedCandidateSnapshot
    stored: CandidateStoredSnapshot
    wallet_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SharedCohortSelection:
    policy_version: str
    selected_at: datetime
    candidates: tuple[CohortCandidate, ...]
    sources: tuple[dict[str, object], ...]
    qualification_evidence: tuple[FollowerQualificationEvidence, ...]
    digest: str
    selection_policy: CohortSelectionPolicy | None = None

    @property
    def selected_wallet_ids(self) -> tuple[str, ...]:
        return tuple(
            candidate.wallet_id for candidate in self.candidates if candidate.state == "SELECTED"
        )

    def to_dict(self) -> dict[str, Any]:
        return json.loads(_json(asdict(self)))

    def to_console_dict(self) -> dict[str, Any]:
        """Small sanitized publication view, distinct from protected evidence.

        A selection is prospective review input. It never proves monitoring,
        creates a live subscription, or grants financial execution authority.
        """
        records = [
            {
                "wallet_id": item.wallet_id,
                "sources": list(item.sources),
                "current_sources": list(item.current_sources),
                "state": item.state,
                "eligibility": item.state,
                "execution_eligibility": "NOT_AUTHORIZED_BY_DISCOVERY_OR_SELECTION",
                "exclusions": list(item.reasons),
                "reasons": list(item.reasons),
                "rank": item.rank,
                "ranking_explanation": item.ranking_explanation,
            }
            for item in self.candidates
        ]
        return {
            "version": "source-cohort-console/v1",
            "policy_version": self.policy_version,
            "selected_at": self.selected_at.isoformat(),
            "digest": self.digest,
            "records": records,
            "funnel": {
                "discovered": len(records),
                "current_discovered": sum(bool(item.current_sources) for item in self.candidates),
                "qualified": sum(
                    item.state in {"QUALIFIED", "SELECTED"} for item in self.candidates
                ),
                "selected": len(self.selected_wallet_ids),
                "monitored": None,
            },
            "coverage": "RETAINED_DISCOVERY_AND_PROSPECTIVE_SELECTION",
        }


class _RetainedSource:
    def __init__(self, dataset: CandidateWalletDataset) -> None:
        self.source_id = dataset.source_id
        self.dataset = dataset

    async def fetch_snapshot(self) -> CandidateWalletDataset:
        return self.dataset


class SourceCohortService:
    def __init__(
        self,
        source_store: CandidateWalletStorePort,
        identity_store: CandidateIdentityStorePort,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self.source_store, self.identity_store, self.clock = source_store, identity_store, clock

    async def ingest(self, snapshot: RetainedCandidateSnapshot) -> IngestedCandidateSnapshot:
        """Persist already acquired evidence; failed/incomplete reads never promote.

        The content-bound run id permits more than one distinct same-day snapshot
        without a daily schedule replay silently discarding a later acquisition.
        """
        now = require_utc(self.clock())
        if not snapshot.complete or snapshot.observed_at > now:
            raise ValueError("incomplete or future source snapshot cannot be promoted")
        metadata = {
            "source_id": snapshot.dataset.source_id,
            "schema_version": snapshot.dataset.schema_version,
            "chain": snapshot.chain,
            "fetched_at": snapshot.dataset.fetched_at,
            "source_total_pages": snapshot.dataset.source_total_pages,
            "effective_at": snapshot.effective_at,
            "observed_at": snapshot.observed_at,
            "coverage": snapshot.coverage,
            "complete": snapshot.complete,
            "confidence": snapshot.confidence,
            "raw_dataset_digest": snapshot.dataset.dataset_digest,
        }
        records: list[CandidateWalletRecord] = []
        for record in snapshot.dataset.records:
            if "_selection_provenance" in record.metrics:
                raise ValueError("reserved source provenance field is already occupied")
            # Raw metrics and raw row digest remain available beside the envelope.
            metrics = dict(record.metrics)
            metrics["_selection_provenance"] = cast(JsonValue, json.loads(_json(metadata)))
            records.append(replace(record, metrics=metrics))
        retained_digest = _digest({"metadata": metadata, "records": [asdict(r) for r in records]})
        dataset = replace(snapshot.dataset, records=tuple(records), dataset_digest=retained_digest)
        self.source_store.initialize()
        self.identity_store.initialize()
        lease = self.identity_store.acquire_lease(
            PIPELINE_LEASE_RESOURCE,
            owner_id=str(uuid.uuid4()),
            acquired_at=now,
            lease_duration=timedelta(minutes=30),
        )
        try:
            result = await CandidateWalletSyncService(
                _RetainedSource(dataset),
                self.source_store,
                clock=self.clock,
            ).sync(
                scheduled_for=snapshot.observed_at.date(),
                run_id="retained-" + retained_digest,
            )
            identities = self.identity_store.link_source_snapshot(
                dataset.source_id,
                result.snapshot.snapshot_id,
                chain=snapshot.chain,
                lease=lease,
                linked_at=require_utc(self.clock()),
            )
        finally:
            self.identity_store.release_lease(lease)
        return IngestedCandidateSnapshot(snapshot, result.snapshot, identities)

    def select(
        self,
        snapshots: tuple[IngestedCandidateSnapshot, ...],
        evidence: Mapping[str, FollowerQualificationEvidence],
        policy: CohortSelectionPolicy,
    ) -> SharedCohortSelection:
        now = require_utc(self.clock())
        lease = self.identity_store.acquire_lease(
            PIPELINE_LEASE_RESOURCE,
            owner_id=str(uuid.uuid4()),
            acquired_at=now,
            lease_duration=timedelta(minutes=30),
        )
        try:
            for snapshot in snapshots:
                current = self.source_store.source_state(snapshot.stored.source_id)
                if current.current_snapshot_id != snapshot.stored.snapshot_id:
                    raise ValueError("selection source snapshot has been superseded")
            return self._select(snapshots, evidence, policy, now=now)
        finally:
            self.identity_store.release_lease(lease)

    def _select(
        self,
        snapshots: tuple[IngestedCandidateSnapshot, ...],
        evidence: Mapping[str, FollowerQualificationEvidence],
        policy: CohortSelectionPolicy,
        *,
        now: datetime,
    ) -> SharedCohortSelection:
        source_ids = tuple(sorted(snapshot.stored.source_id for snapshot in snapshots))
        if not source_ids or len(source_ids) != len(set(source_ids)):
            raise ValueError("selection requires one explicit retained snapshot per source")
        active: dict[str, set[str]] = defaultdict(set)
        fresh: set[str] = set()
        source_reports: list[dict[str, object]] = []
        for snapshot in sorted(snapshots, key=lambda item: item.stored.source_id):
            retained = snapshot.retained
            source_id = snapshot.stored.source_id
            age = now - retained.observed_at
            usable = retained.complete and timedelta(0) <= age <= policy.freshness
            for wallet_id in snapshot.wallet_ids:
                active[wallet_id].add(source_id)
                if usable:
                    fresh.add(wallet_id)
            source_reports.append(
                {
                    "source_id": source_id,
                    "snapshot_id": snapshot.stored.snapshot_id,
                    "raw_dataset_digest": retained.dataset.dataset_digest,
                    "stored_dataset_digest": snapshot.stored.dataset_digest,
                    "schema": retained.dataset.schema_version,
                    "effective_at": retained.effective_at,
                    "observed_at": retained.observed_at,
                    "ingested_at": snapshot.stored.accepted_at,
                    "complete": retained.complete,
                    "coverage": retained.coverage,
                    "confidence": retained.confidence,
                    "freshness": "CURRENT_OBSERVATION" if usable else "STALE_OR_FUTURE",
                    "provider_scores_comparable": False,
                }
            )
        retained_sources: dict[str, set[str]] = defaultdict(set)
        for wallet_id, source_id in self.identity_store.canonical_sources(source_ids):
            retained_sources[wallet_id].add(source_id)
        qualified: list[FollowerQualificationEvidence] = []
        candidates: dict[str, CohortCandidate] = {}
        for wallet_id in sorted(retained_sources):
            item = evidence.get(wallet_id)
            if item is not None and item.wallet_id != wallet_id:
                raise ValueError("qualification wallet identity does not match its key")
            reasons: tuple[str, ...]
            if wallet_id not in active:
                reasons = ("absent_from_current_source_snapshots",)
                state = "DISAPPEARED"
            else:
                reasons = qualification_reasons(item, policy, now=now)
                if wallet_id not in fresh:
                    reasons += ("all_discovery_observations_stale_or_future",)
                state = "EXCLUDED" if reasons else "QUALIFIED"
                if not reasons:
                    assert item is not None
                    qualified.append(item)
            candidates[wallet_id] = CohortCandidate(
                wallet_id,
                tuple(sorted(retained_sources[wallet_id])),
                tuple(sorted(active.get(wallet_id, set()))),
                state,
                reasons,
                None,
                None if item is None else item.evidence_id,
                None if item is None else item.evaluation_start,
                "Eligibility first; confidence, follower net/unit, drawdown, sample, identity. "
                "Source rank supplies no edge and source overlap supplies no score bonus.",
            )
        # All entries were explicitly checked for missing economics above.
        qualified.sort(
            key=lambda item: (
                -(item.confidence or Decimal(0)),
                -(item.follower_net_per_unit or Decimal(0)),
                item.drawdown or Decimal(0),
                -item.sample_count,
                item.wallet_id,
            )
        )
        for rank, item in enumerate(qualified, 1):
            state = "SELECTED" if rank <= policy.cohort_size else "QUALIFIED"
            candidates[item.wallet_id] = replace(candidates[item.wallet_id], rank=rank, state=state)
        ordered = tuple(
            sorted(
                candidates.values(),
                key=lambda item: (
                    item.rank is None,
                    item.rank or 0,
                    item.wallet_id,
                ),
            )
        )
        frozen_evidence = tuple(evidence[key] for key in sorted(candidates) if key in evidence)
        result = SharedCohortSelection(
            policy.version,
            now,
            ordered,
            tuple(source_reports),
            frozen_evidence,
            "",
            selection_policy=policy,
        )
        return replace(result, digest=_digest(asdict(result)))


def retained_native_candidates(publication: Mapping[str, Any]) -> RetainedCandidateSnapshot:
    """Translate the existing protected native diagnostic; never widen its sample.

    Redacted Console publications cannot be used here because addresses are
    required to reconcile canonical identity. No external request is performed.
    """
    payload = dict(publication)
    supplied_digest = payload.pop("digest", None)
    if supplied_digest != _digest(payload):
        raise ValueError("native diagnostic digest is missing or inconsistent")
    coverage = payload.get("coverage")
    if (
        payload.get("source") != "polymarket-native"
        or payload.get("profile") != "native-recent-activity/v1"
        or coverage
        not in {
            "COMPLETE_WALLET_ACTIVITY_WITH_SAMPLED_SEEDS",
            "COMPLETE_FIXED_ADMITTED_WALLET_ACTIVITY",
        }
    ):
        raise ValueError("unsupported native discovery contract")
    observed_at = require_utc(datetime.fromisoformat(payload["cutoff"]))
    start = require_utc(datetime.fromisoformat(payload["window_start"]))
    if not start < observed_at:
        raise ValueError("native observation window is invalid")
    records: list[CandidateWalletRecord] = []
    for rank, raw in enumerate(payload["candidates"], 1):
        wallet_id, _, address = normalize_evm_wallet("polygon", raw["address"])
        if raw.get("wallet_id") != wallet_id or raw.get("state") not in {
            "ACTIVITY_CONFIRMED",
            "NO_COMPLETE_ACTIVITY",
        }:
            raise ValueError("native candidate identity or activity state mismatch")
        safe = {key: value for key, value in raw.items() if key != "address"}
        metrics = cast(
            dict[str, JsonValue],
            {
                "native_sampled_activity": True,
                "skill_established": False,
                "raw_candidate": safe,
                "raw_diagnostic_digest": supplied_digest,
            },
        )
        records.append(CandidateWalletRecord(address, rank, 1, metrics, _digest(raw)))
    dataset = CandidateWalletDataset(
        "polymarket-native",
        "native-retained-candidates/v1",
        observed_at,
        1,
        tuple(records),
        _digest(payload),
    )
    return RetainedCandidateSnapshot(
        dataset, "polygon", None, observed_at, True, str(coverage), None
    )
