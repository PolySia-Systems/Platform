"""Provider-neutral ports for prospective research collection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from polysia.domain.research_evidence.models import (
    CanonicalResearchEvent,
    SourceCandidateStatus,
)


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    candidate_id: str
    display_name: str
    kind: str
    wallet_attributable: bool
    status: SourceCandidateStatus
    unavailable_reason: str | None = None


class ResearchObservationSource(Protocol):
    """Async observation producer. Adapters own venue translation."""

    candidate: SourceCandidate

    def run(
        self,
        *,
        run_id: str,
        deadline: datetime,
    ) -> AsyncIterator[CanonicalResearchEvent]: ...
