from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from polysia.application.ports.wallet_intelligence_research import ResearchWalletSourcePort
from polysia.domain.clock import SystemClock
from polysia.domain.wallet_intelligence.research_intake import (
    ResearchDisposition,
    ResearchIntakeReport,
    ResearchWalletDecision,
)


class WalletIntelligenceResearchService:
    """Read-only research acceptance; never publishes executable selection pools."""

    def __init__(
        self,
        source: ResearchWalletSourcePort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.source = source
        self.clock = clock or SystemClock().now

    def intake(
        self,
        *,
        allow_partial: bool = False,
        required_capabilities: tuple[str, ...] = ("descriptive_screening",),
    ) -> ResearchIntakeReport:
        publication = self.source.read_publication()
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("research intake clock must be UTC")
        now = now.astimezone(UTC)
        reasons: list[str] = []
        if publication.generated_at > now:
            reasons.append("publication_from_future")
        if publication.expires_at <= now:
            reasons.append("publication_expired")
        if publication.status == "PARTIAL" and not allow_partial:
            reasons.append("partial_requires_explicit_opt_in")
        capabilities = dict(publication.capabilities)
        reasons.extend(
            f"capability_unavailable:{name}:{capabilities.get(name, 'UNKNOWN')}"
            for name in required_capabilities
            if capabilities.get(name) != "AVAILABLE"
        )
        decisions: list[ResearchWalletDecision] = []
        for record in publication.records:
            record_reasons = list(reasons)
            disposition = ResearchDisposition.REJECTED
            if not record_reasons:
                if record.expires_at <= now:
                    record_reasons.append("record_expired")
                elif record.validity != "VALID":
                    record_reasons.append("source_data_invalid")
                elif record.producer_outcome in {"EXCLUDED", "DATA_HOLD", "NOT_EXAMINED"}:
                    record_reasons.extend(("source_outcome_ineligible", *record.reasons))
                elif record.producer_outcome == "WATCHLIST":
                    disposition = ResearchDisposition.WATCHLIST
                    record_reasons.extend(record.reasons)
                elif (
                    record.source_observed_at is None
                    or now - record.source_observed_at
                    > timedelta(
                        hours=24,
                    )
                ):
                    record_reasons.append("performance_observation_stale_or_unknown")
                else:
                    disposition = ResearchDisposition.ACCEPTED
                    record_reasons.append("supported_descriptive_research")
            decisions.append(ResearchWalletDecision(record, disposition, tuple(record_reasons)))
        status = (
            "REJECTED"
            if reasons
            else ("ACCEPTED_EMPTY" if not decisions else "ACCEPTED_FOR_RESEARCH")
        )
        return ResearchIntakeReport(
            publication,
            now,
            status,
            "wallet-intelligence-research/v1",
            allow_partial,
            required_capabilities,
            tuple(reasons),
            tuple(decisions),
        )
