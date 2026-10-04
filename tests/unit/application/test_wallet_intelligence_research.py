from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from polysia.adapters.wallet_intelligence import WalletIntelligenceArtifactSource
from polysia.application.services.wallet_intelligence_research import (
    WalletIntelligenceResearchService,
)
from polysia.domain.wallet_intelligence.research_intake import ResearchDisposition

NOW = datetime(2026, 10, 3, 21, tzinfo=UTC)


@pytest.fixture
def publication():
    from pathlib import Path

    path = Path(__file__).parents[2] / "fixtures/wallet_intelligence/v1.json"
    return WalletIntelligenceArtifactSource(path).read_publication()


def service(publication, now=NOW):
    return WalletIntelligenceResearchService(
        SimpleNamespace(read_publication=lambda: publication),
        clock=lambda: now,
    )


def test_descriptive_acceptance_is_separate_from_admission_and_preserves_records(publication):
    report = service(publication).intake()
    assert report.status == "ACCEPTED_FOR_RESEARCH"
    assert [decision.disposition for decision in report.decisions] == [
        ResearchDisposition.ACCEPTED,
        ResearchDisposition.WATCHLIST,
        ResearchDisposition.REJECTED,
    ]
    assert report.decisions[0].record is publication.records[0]
    assert report.publication.analytical_json == publication.analytical_json
    assert dict(report.publication.capabilities)["copyability"] == "NOT_EVALUATED"
    assert "source_outcome_ineligible" in report.decisions[2].reasons


def test_partial_requires_explicit_permission(publication):
    partial = replace(publication, status="PARTIAL")
    blocked = service(partial).intake()
    assert blocked.status == "REJECTED"
    assert blocked.reasons == ("partial_requires_explicit_opt_in",)
    assert all(d.disposition == ResearchDisposition.REJECTED for d in blocked.decisions)
    permitted = service(partial).intake(allow_partial=True)
    assert permitted.status == "ACCEPTED_FOR_RESEARCH"
    assert permitted.publication.status == "PARTIAL"


@pytest.mark.parametrize("capability", ["copyability", "accounting_reconciliation", "unknown"])
def test_missing_capability_is_explicit_and_never_filled(publication, capability):
    report = service(publication).intake(required_capabilities=(capability,))
    assert report.status == "REJECTED"
    assert report.reasons[0].startswith("capability_unavailable:" + capability + ":")
    assert all(d.disposition == ResearchDisposition.REJECTED for d in report.decisions)


def test_expiry_boundary_future_and_observation_age_use_actual_consumer_time(publication):
    assert service(publication, NOW + timedelta(hours=24)).intake().status == "REJECTED"
    assert service(publication, NOW - timedelta(seconds=1)).intake().reasons == (
        "publication_from_future",
    )
    records = (
        replace(publication.records[0], source_observed_at=NOW - timedelta(hours=25)),
        *publication.records[1:],
    )
    report = service(replace(publication, records=records)).intake()
    assert report.decisions[0].disposition == ResearchDisposition.REJECTED
    assert report.decisions[0].reasons == ("performance_observation_stale_or_unknown",)
    records = (replace(publication.records[0], expires_at=NOW), *publication.records[1:])
    assert service(replace(publication, records=records)).intake().decisions[0].reasons == (
        "record_expired",
    )


def test_valid_empty_and_bad_clock(publication):
    assert service(replace(publication, records=())).intake().status == "ACCEPTED_EMPTY"
    with pytest.raises(ValueError, match="clock must be UTC"):
        service(publication, NOW.replace(tzinfo=None)).intake()
