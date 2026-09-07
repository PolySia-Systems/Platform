from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.ports.research_evidence import SourceCandidate
from polysia.application.services.source_benchmark import run_source_benchmark
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    SourceCandidateStatus,
    payload_digest,
)
from polysia.storage.research_evidence import ResearchEvidenceStore

OBSERVED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class FakeSource:
    def __init__(
        self,
        candidate: SourceCandidate,
        events: tuple[CanonicalResearchEvent, ...],
    ) -> None:
        self.candidate = candidate
        self._events = events
        self.reconnect_count = 0

    async def run(self, *, run_id: str, deadline: datetime):
        del run_id, deadline
        for event in self._events:
            yield event


def _wallet_event(evidence_id: str, source_id: str) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id=source_id,
        event_kind=ObservationKind.WALLET_TRADE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference="m",
        outcome_reference="token-1",
        side="BUY",
        price=Decimal("0.5"),
        size=Decimal("2"),
        source_time=OBSERVED - timedelta(seconds=1),
        observed_time=OBSERVED,
        receive_monotonic_ns=10,
        normalize_monotonic_ns=20,
        attribution_status=AttributionStatus.WALLET_ALIASED,
        leader_alias="pub-abc",
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance={"has_transaction": True},
        source_event_id=evidence_id,
        run_id="pending",
    )


@pytest.mark.asyncio
async def test_benchmark_separates_market_and_wallet_and_replays(tmp_path: Path) -> None:
    activity = FakeSource(
        SourceCandidate(
            candidate_id="rest_activity",
            display_name="activity",
            kind="wallet_event",
            wallet_attributable=True,
            status=SourceCandidateStatus.MEASURED,
        ),
        (_wallet_event("a1", "polymarket:data-api:activity"),),
    )
    trades = FakeSource(
        SourceCandidate(
            candidate_id="rest_trades",
            display_name="trades",
            kind="wallet_event",
            wallet_attributable=True,
            status=SourceCandidateStatus.MEASURED,
        ),
        (_wallet_event("t1", "polymarket:data-api:trades"),),
    )
    market = FakeSource(
        SourceCandidate(
            candidate_id="clob_market_ws",
            display_name="market",
            kind="market_state",
            wallet_attributable=False,
            status=SourceCandidateStatus.MEASURED,
        ),
        (
            CanonicalResearchEvent(
                evidence_id="m1",
                schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
                source_id="polymarket:clob:market-stream",
                event_kind=ObservationKind.MARKET_STATE,
                classification=EvidenceClassification.ACCEPTED,
                market_reference=None,
                outcome_reference="token-1",
                side=None,
                price=Decimal("0.49"),
                size=None,
                source_time=OBSERVED - timedelta(milliseconds=50),
                observed_time=OBSERVED - timedelta(milliseconds=40),
                receive_monotonic_ns=1,
                normalize_monotonic_ns=2,
                attribution_status=AttributionStatus.NOT_APPLICABLE,
                leader_alias=None,
                confirmation=ConfirmationStatus.CONFIRMED,
                payload_digest=payload_digest({"id": "m1"}),
                provenance={},
                run_id="pending",
            ),
        ),
    )
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    report = await run_source_benchmark(
        (activity, trades, market),
        store=store,
        duration=timedelta(seconds=1),
        clock=lambda: OBSERVED,
        code_sha="deadbeef",
        unavailable=(
            SourceCandidate(
                candidate_id="clob_user_ws",
                display_name="user",
                kind="wallet_event",
                wallet_attributable=True,
                status=SourceCandidateStatus.UNAVAILABLE,
                unavailable_reason="authenticated_user_channel_requires_credentials",
            ),
        ),
    )
    payload = report.payload
    kinds = {row["candidate_id"]: row["wallet_attributable"] for row in payload["sources"]}
    assert kinds["rest_activity"] is True
    assert kinds["clob_market_ws"] is False
    assert payload["unavailable"][0]["status"] == "UNAVAILABLE"
    assert payload["selection"]["fast_wallet_stream_qualified"] is False
    assert payload["replay"]["control_digest"]
    assert payload["replay"]["target_digest"]
    assert payload["market_freshness_when_wallet_event_ns"]["note"] == (
        "market_ws_does_not_supply_wallet_identity"
    )
