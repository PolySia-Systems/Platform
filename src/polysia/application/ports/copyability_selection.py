from __future__ import annotations

from datetime import datetime
from typing import Protocol

from polysia.domain.wallet_intelligence import CandidatePipelineLease
from polysia.domain.wallet_intelligence.copyability_selection import (
    CopyabilityEvidence,
    CopyabilityMembership,
    CopyabilityPoolRow,
    CopyabilityProcessingKey,
    CopyabilityScore,
    CopyabilitySelectionRun,
    CopyabilitySelectionState,
    SelectionPoolId,
    SelectionStatus,
)


class CopyabilitySelectionStorePort(Protocol):
    """Persistence boundary for Stage 3 copyability selection."""

    def initialize(self) -> None: ...

    def load_evidence(
        self,
        source_id: str,
        stage2_run_id: str,
    ) -> tuple[CopyabilityEvidence, ...]: ...

    def successful_run(self, key: CopyabilityProcessingKey) -> CopyabilitySelectionRun | None: ...

    def start_run(
        self,
        key: CopyabilityProcessingKey,
        *,
        source_id: str,
        source_snapshot_id: str,
        started_at: datetime,
    ) -> str: ...

    def fail_run(
        self,
        run_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    def publish_run(
        self,
        run_id: str,
        *,
        lease: CandidatePipelineLease,
        scores: tuple[CopyabilityScore, ...],
        memberships: tuple[CopyabilityMembership, ...],
        published_at: datetime,
    ) -> CopyabilitySelectionRun: ...

    def current_run(self, source_id: str) -> CopyabilitySelectionRun | None: ...

    def state(self, source_id: str) -> CopyabilitySelectionState: ...

    def current_pool(
        self,
        source_id: str,
        pool_id: SelectionPoolId,
        *,
        limit: int | None = None,
    ) -> tuple[CopyabilityPoolRow, ...]: ...

    def current_status_rows(
        self,
        source_id: str,
        status: SelectionStatus,
        *,
        limit: int | None = None,
    ) -> tuple[CopyabilityPoolRow, ...]: ...

    def prune_history(self, *, cutoff: datetime) -> None: ...
