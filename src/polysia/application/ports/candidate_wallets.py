from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from polysia.domain.wallet_intelligence import CandidateWalletDataset


class CandidateSourceReadError(RuntimeError):
    """Safe external read failure with no source identity or payload content."""

    error_code = "source_read_failed"


class CandidateSourceSchemaError(CandidateSourceReadError):
    """External response no longer matches the reviewed source contract."""

    error_code = "source_schema_changed"

    def __init__(self, reason_code: str, sample: object, schema_fingerprint: str) -> None:
        super().__init__(f"Candidate-wallet source schema changed ({reason_code}).")
        self.reason_code = reason_code
        self.sample = sample
        self.schema_fingerprint = schema_fingerprint


class CandidateWalletSourcePort(Protocol):
    """Read-only boundary for one complete candidate-wallet source."""

    @property
    def source_id(self) -> str: ...

    async def fetch_snapshot(self) -> CandidateWalletDataset: ...


@dataclass(frozen=True, slots=True)
class CandidateRunStart:
    run_id: str
    snapshot_id: str
    already_succeeded: bool


@dataclass(frozen=True, slots=True)
class CandidateStoredSnapshot:
    run_id: str
    snapshot_id: str
    source_id: str
    accepted_at: datetime
    source_total_pages: int
    record_count: int
    dataset_digest: str
    warning_code: str | None


@dataclass(frozen=True, slots=True)
class CandidateSourceState:
    source_id: str
    current_snapshot_id: str | None
    last_success_at: datetime | None
    current_record_count: int | None
    current_page_count: int | None
    last_run_id: str | None
    last_run_status: str | None
    last_error_code: str | None
    last_warning_code: str | None


class CandidateWalletStorePort(Protocol):
    """Persistence boundary for atomic source runs and accepted snapshots."""

    def initialize(self) -> None: ...

    def start_run(
        self,
        source_id: str,
        *,
        scheduled_for: date,
        started_at: datetime,
        force_new: bool = False,
        run_id: str | None = None,
    ) -> CandidateRunStart: ...

    def complete_run(
        self,
        start: CandidateRunStart,
        dataset: CandidateWalletDataset,
        *,
        accepted_at: datetime,
    ) -> CandidateStoredSnapshot: ...

    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
        completed_at: datetime,
    ) -> None: ...

    def quarantine_run(
        self,
        run_id: str,
        *,
        reason_code: str,
        schema_fingerprint: str,
        sample_gzip: bytes,
        sample_sha256: str,
        completed_at: datetime,
    ) -> None: ...

    def source_state(self, source_id: str) -> CandidateSourceState: ...

    def stored_snapshot(self, run_id: str) -> CandidateStoredSnapshot: ...

    def prune_history(
        self,
        *,
        snapshot_cutoff: datetime,
        quarantine_cutoff: datetime,
    ) -> None: ...
