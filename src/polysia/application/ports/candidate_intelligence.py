from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from polysia.domain.wallet_intelligence import (
    CandidateIntelligenceState,
    CandidatePipelineLease,
    CandidatePolicyEvaluation,
    CandidatePoolRow,
    CandidatePoolRun,
    CandidateProcessingKey,
    CandidateSourceHistory,
    CandidateSourceObservation,
    CandidateWalletFeature,
)


class CandidatePipelineBusyError(RuntimeError):
    """Another live process owns the wallet-intelligence pipeline lease."""


class CandidatePipelineLeaseLostError(RuntimeError):
    """The caller no longer owns the live fenced pipeline lease."""


class CandidateIntelligenceStorePort(Protocol):
    """Persistence boundary for Stage 2 history and atomic current publication."""

    def initialize(self) -> None: ...

    def acquire_lease(
        self,
        resource: str,
        *,
        owner_id: str,
        acquired_at: datetime,
        lease_duration: timedelta,
    ) -> CandidatePipelineLease: ...

    def renew_lease(
        self,
        lease: CandidatePipelineLease,
        *,
        renewed_at: datetime,
        lease_duration: timedelta,
    ) -> CandidatePipelineLease: ...

    def release_lease(self, lease: CandidatePipelineLease) -> None: ...

    def load_source_history(
        self,
        source_id: str,
        source_snapshot_id: str,
    ) -> CandidateSourceHistory: ...

    def load_wallet_histories(
        self,
        source_id: str,
        source_snapshot_id: str,
        wallet_keys: tuple[str, ...],
    ) -> dict[str, tuple[CandidateSourceObservation, ...]]: ...

    def successful_run(self, key: CandidateProcessingKey) -> CandidatePoolRun | None: ...

    def start_run(
        self,
        key: CandidateProcessingKey,
        *,
        source_id: str,
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
        features: tuple[CandidateWalletFeature, ...],
        evaluations: tuple[CandidatePolicyEvaluation, ...],
        published_at: datetime,
    ) -> CandidatePoolRun: ...

    def current_run(self, source_id: str) -> CandidatePoolRun | None: ...

    def state(self, source_id: str) -> CandidateIntelligenceState: ...

    def current_pool(
        self,
        source_id: str,
        *,
        limit: int | None = None,
        selected_only: bool = False,
    ) -> tuple[CandidatePoolRow, ...]: ...

    def prune_history(self, *, cutoff: datetime) -> None: ...
