from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.domain.research_evidence.collector import CollectorPolicy
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    DecisionRecord,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)
from polysia.storage.research_evidence import (
    ResearchEvidenceStore,
    ResearchEvidenceStoreError,
)

OBSERVED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _event(
    evidence_id: str,
    *,
    classification: EvidenceClassification = EvidenceClassification.ACCEPTED,
    kind: ObservationKind = ObservationKind.WALLET_TRADE,
    observed: datetime = OBSERVED,
    source_time: datetime | None = None,
    digest: str | None = None,
    provenance: dict[str, object] | None = None,
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="src",
        event_kind=kind,
        classification=classification,
        market_reference="m",
        outcome_reference="o",
        side="BUY",
        price=Decimal("0.5"),
        size=Decimal("1"),
        source_time=source_time or observed,
        observed_time=observed,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.WALLET_ALIASED,
        leader_alias="pub-abc",
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=digest or payload_digest({"id": evidence_id}),
        provenance=provenance or {},
        run_id="run-1",
    )


def test_restart_does_not_duplicate_accepted_events(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    store.initialize()
    first = ProspectiveCollector(store, run_id="run-1")
    event = _event("same")
    assert first.ingest(event).classification is EvidenceClassification.ACCEPTED
    first.close()

    restarted = ProspectiveCollector(store, run_id="run-1")
    assert restarted.ingest(event).classification is EvidenceClassification.DUPLICATE
    restarted.close()
    accepted = [
        item
        for item in store.load_events()
        if item.classification is EvidenceClassification.ACCEPTED
        and item.event_kind is ObservationKind.WALLET_TRADE
    ]
    assert len(accepted) == 1
    assert store.duplicate_count("same") == 1


def test_missing_decision_evidence_fails_closed(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    store.initialize()
    collector = ProspectiveCollector(store)
    collector.ingest(_event("kept"))
    with pytest.raises(ResearchEvidenceStoreError, match="missing"):
        collector.record_decision(
            DecisionRecord(
                decision_id="d1",
                interval_id=collector.interval.interval_id,
                observed_time=OBSERVED,
                policy_id="target-exposure-v1",
                policy_version="1",
                decision="ADMIT",
                evidence_ids=("missing",),
                code_sha="abc",
                configuration_digest="cfg",
            )
        )
    assert collector.interval.validity.value == "INVALID_MISSING_EVIDENCE"


def test_queue_overload_invalidates_and_keeps_the_event(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(
        tmp_path / "research.sqlite3",
        policy=CollectorPolicy(max_queue_depth=1),
    )
    collector = ProspectiveCollector(store, policy=CollectorPolicy(max_queue_depth=1))
    collector._queue.put_nowait(_event("held"))
    overloaded = collector.ingest(_event("dropped"))
    assert overloaded.classification is EvidenceClassification.OVERLOAD
    assert collector.interval.validity.value == "INVALID_OVERLOAD"
    stored = store.load_events()
    assert any(item.evidence_id == "dropped" for item in stored)


def test_gap_reconnect_and_retention(tmp_path: Path) -> None:
    policy = CollectorPolicy(
        gap_threshold=timedelta(seconds=5),
        max_persisted_events=10,
        market_state_retention=timedelta(seconds=1),
    )
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", policy=policy)
    collector = ProspectiveCollector(store, policy=policy)
    first = _event("t1", observed=OBSERVED, provenance={"sequenced": True})
    second = _event(
        "t2",
        observed=OBSERVED + timedelta(seconds=30),
        provenance={"sequenced": True},
    )
    assert collector.ingest(first).classification is EvidenceClassification.ACCEPTED
    gapped = collector.ingest(second)
    assert gapped.classification is EvidenceClassification.ACCEPTED
    assert collector.interval.validity.value == "INVALID_GAP"
    collector.record_reconnect("src")
    backfill = _event(
        "t0",
        observed=OBSERVED + timedelta(seconds=31),
        source_time=OBSERVED - timedelta(seconds=1),
        digest="backfill",
    )
    assert collector.ingest(backfill).classification is EvidenceClassification.ACCEPTED

    old_market = CanonicalResearchEvent(
        evidence_id="old-mkt",
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="market",
        event_kind=ObservationKind.MARKET_STATE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference=None,
        outcome_reference="o",
        side=None,
        price=Decimal("0.4"),
        size=None,
        source_time=OBSERVED - timedelta(days=8),
        observed_time=OBSERVED - timedelta(days=8),
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.NOT_APPLICABLE,
        leader_alias=None,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": "old-mkt"}),
        provenance={},
        run_id="run-1",
    )
    collector.ingest(old_market)
    ids = {item.evidence_id for item in store.load_events()}
    assert "old-mkt" not in ids
    assert "t1" in ids
    collector.close()
