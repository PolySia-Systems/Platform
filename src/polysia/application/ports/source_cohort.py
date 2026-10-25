"""Canonical identity operations shared by retained source selection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from polysia.domain.wallet_intelligence import CandidatePipelineLease


class CandidateIdentityStorePort(Protocol):
    def initialize(self) -> None: ...

    def acquire_lease(
        self,
        resource: str,
        *,
        owner_id: str,
        acquired_at: datetime,
        lease_duration: timedelta,
    ) -> CandidatePipelineLease: ...

    def release_lease(self, lease: CandidatePipelineLease) -> None: ...

    def link_source_snapshot(
        self,
        source_id: str,
        source_snapshot_id: str,
        *,
        chain: str,
        lease: CandidatePipelineLease,
        linked_at: datetime,
    ) -> tuple[str, ...]: ...

    def canonical_sources(self, source_ids: tuple[str, ...]) -> tuple[tuple[str, str], ...]: ...
