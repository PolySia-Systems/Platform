"""Research publications remain separate from executable candidate admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ResearchDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    WATCHLIST = "WATCHLIST"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ResearchWalletRecord:
    """Protected identity and intact source semantics; no readiness score."""

    wallet_id: str
    external_wallet_id: str
    producer_rank: int | None
    producer_outcome: str
    validity: str
    activity_state: str
    performance_state: str
    performance_value: Decimal | None
    source_observed_at: datetime | None
    expires_at: datetime
    reasons: tuple[str, ...]
    source_record_json: str


@dataclass(frozen=True, slots=True)
class ResearchWalletPublication:
    source_id: str
    schema_version: str
    run_id: str
    snapshot_digest: str
    data_cutoff: datetime
    evaluation_at: datetime
    generated_at: datetime
    expires_at: datetime
    status: str
    capabilities: tuple[tuple[str, str], ...]
    records: tuple[ResearchWalletRecord, ...]
    analytical_json: str


@dataclass(frozen=True, slots=True)
class ResearchWalletDecision:
    record: ResearchWalletRecord
    disposition: ResearchDisposition
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchIntakeReport:
    publication: ResearchWalletPublication
    assessed_at: datetime
    status: str
    policy_id: str
    allow_partial: bool
    required_capabilities: tuple[str, ...]
    reasons: tuple[str, ...]
    decisions: tuple[ResearchWalletDecision, ...]
