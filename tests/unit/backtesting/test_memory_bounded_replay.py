from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.backtesting.prospective_replay import (
    replay_identity,
    replay_recorded_experiment,
)
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)
from polysia.storage.research_evidence import EVENT_FETCH_CHUNK, ResearchEvidenceStore

OBSERVED = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def _wallet(evidence_id: str, *, run_id: str, observed: datetime) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="wallet",
        event_kind=ObservationKind.WALLET_TRADE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference="m1",
        outcome_reference="o1",
        side="BUY",
        price=Decimal("0.4"),
        size=Decimal("2"),
        source_time=observed,
        observed_time=observed,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.WALLET_ALIASED,
        leader_alias="pub-one",
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance={},
        source_event_id=f"src-{evidence_id}",
        run_id=run_id,
    )


def _market(evidence_id: str, *, run_id: str, observed: datetime) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="market",
        event_kind=ObservationKind.MARKET_STATE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference="m1",
        outcome_reference="o1",
        side="SELL",
        price=Decimal("0.41"),
        size=Decimal("10"),
        source_time=observed,
        observed_time=observed,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.NOT_APPLICABLE,
        leader_alias=None,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance={
            "execution_evidence": True,
            "recorded_fee": "0.01",
            "quote_status": "present",
        },
        run_id=run_id,
    )


def _recorded_store(tmp_path: Path, *, run_id: str, events: int = 5) -> ResearchEvidenceStore:
    store = ResearchEvidenceStore(tmp_path / "research-evidence.sqlite3")
    store.start_or_resume_experiment(
        requested_run_id=run_id,
        duration=timedelta(hours=1),
        max_events=100,
        max_bytes=10_000_000,
        code_sha="a" * 40,
        configuration_digest="config",
    )
    collector = ProspectiveCollector(store, run_id=run_id)
    for index in range(events):
        observed = OBSERVED + timedelta(seconds=index)
        collector.ingest(_market(f"market-{index}", run_id=run_id, observed=observed))
        collector.ingest(_wallet(f"wallet-{index}", run_id=run_id, observed=observed))
    collector.close_window(complete=True)
    return store


def test_iter_events_is_chunked_and_matches_load_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _recorded_store(tmp_path, run_id="chunk-run", events=5)
    sizes: list[int] = []

    def tracked(cursor: object, chunk_size: int) -> list[object]:
        sizes.append(chunk_size)
        return original(cursor, chunk_size)

    from polysia.storage import research_evidence as store_module

    original = store_module._fetch_event_chunk
    monkeypatch.setattr(store_module, "_fetch_event_chunk", tracked)
    loaded = tuple(store.iter_events(run_id="chunk-run", chunk_size=2))
    assert sizes == [2, 2, 2, 2, 2, 2]
    assert loaded == store.load_events(run_id="chunk-run")
    assert len(loaded) == 10
    assert EVENT_FETCH_CHUNK == 256
    with pytest.raises(ValueError, match="chunk_size"):
        tuple(store.iter_events(run_id="chunk-run", chunk_size=0))


def test_snapshot_iteration_does_not_load_wallet_trades(tmp_path: Path) -> None:
    store = _recorded_store(tmp_path, run_id="kind-run", events=3)
    snapshots = tuple(
        store.iter_events(run_id="kind-run", event_kind=ObservationKind.MARKET_STATE)
    )
    wallets = tuple(
        store.iter_events(run_id="kind-run", event_kind=ObservationKind.WALLET_TRADE)
    )
    assert len(snapshots) == 3
    assert len(wallets) == 3
    assert all(item.event_kind is ObservationKind.MARKET_STATE for item in snapshots)


def test_experiment_replay_is_deterministic_and_can_drop_traces(tmp_path: Path) -> None:
    store = _recorded_store(tmp_path, run_id="replay-run", events=3)
    first = replay_recorded_experiment(store, run_id="replay-run")
    second = replay_recorded_experiment(store, run_id="replay-run", retain_traces=False)
    assert replay_identity(first) == replay_identity(second)
    assert first.replayed_event_count == 6
    assert first.result.evaluations
    assert second.result.evaluations == ()
    assert first.economics.digest == second.economics.digest
