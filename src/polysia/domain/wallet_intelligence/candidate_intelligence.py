from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

_EVM_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-fA-F]{40}$")
_CHAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,31}$")


class DataReadinessStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class CandidateStatus(StrEnum):
    SELECTED = "SELECTED"
    WATCHLIST = "WATCHLIST"
    INELIGIBLE = "INELIGIBLE"


@dataclass(frozen=True, slots=True)
class CandidateProcessingKey:
    source_snapshot_id: str
    feature_set_version: str
    policy_id: str
    policy_version: str
    ranking_version: str


@dataclass(frozen=True, slots=True)
class CandidatePipelineLease:
    resource: str
    owner_id: str
    fencing_token: int
    acquired_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class CandidateSourceSnapshot:
    snapshot_id: str
    captured_at: datetime
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class CandidateSourceObservation:
    snapshot_id: str
    wallet_key: str
    external_wallet_id: str
    source_rank: int
    source_score: Decimal | None
    source_metrics_json: str
    captured_at: datetime
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class CandidateSourceHistory:
    source_id: str
    current_snapshot_id: str
    snapshots: tuple[CandidateSourceSnapshot, ...]
    current_observations: tuple[CandidateSourceObservation, ...]


@dataclass(frozen=True, slots=True)
class CandidateWalletFeature:
    wallet_id: str
    chain: str
    normalized_address: str
    source_wallet_key: str
    source_rank: int
    source_score: Decimal | None
    source_metrics_json: str
    effective_at: datetime
    observed_at: datetime
    ingested_at: datetime
    calculated_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int
    observed_days: int
    eligible_snapshot_count: int
    presence_ratio: Decimal
    data_age_seconds: int
    stale_after_seconds: int
    is_stale: bool
    previous_rank: int | None
    rank_delta_previous: int | None
    rank_delta_1d: int | None
    rank_delta_7d: int | None
    rank_delta_30d: int | None
    best_rank: int
    worst_rank: int
    rank_volatility: Decimal | None
    rank_stability: Decimal | None
    score_delta_previous: Decimal | None
    score_delta_1d: Decimal | None
    score_delta_7d: Decimal | None
    score_delta_30d: Decimal | None
    score_volatility: Decimal | None
    score_stability: Decimal | None
    data_readiness_status: DataReadinessStatus
    readiness_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidatePolicyEvaluation:
    wallet_id: str
    candidate_status: CandidateStatus
    candidate_rank: int | None
    policy_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidatePoolRun:
    run_id: str
    key: CandidateProcessingKey
    source_id: str
    calculated_at: datetime
    published_at: datetime
    evaluated_count: int
    selected_count: int
    watchlist_count: int
    ineligible_count: int
    ready_count: int
    partial_count: int
    stale_count: int
    invalid_count: int
    unknown_count: int


@dataclass(frozen=True, slots=True)
class CandidateIntelligenceState:
    source_id: str
    current_run: CandidatePoolRun | None
    last_run_id: str | None
    last_run_status: str | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class CandidatePoolRow:
    wallet_id: str
    chain: str
    source_id: str
    source_snapshot_id: str
    source_rank: int
    source_score: Decimal | None
    presence_ratio: Decimal
    data_age_seconds: int
    data_readiness_status: DataReadinessStatus
    candidate_status: CandidateStatus
    candidate_rank: int | None
    effective_at: datetime
    ingested_at: datetime
    calculated_at: datetime
    feature_set_version: str
    policy_id: str
    policy_version: str
    ranking_version: str


def normalize_evm_wallet(chain: str, address: str) -> tuple[str, str, str]:
    normalized_chain = chain.strip().lower()
    if not _CHAIN_PATTERN.fullmatch(normalized_chain):
        raise ValueError("chain is invalid")
    normalized_address = address.strip().lower()
    if not _EVM_ADDRESS_PATTERN.fullmatch(normalized_address):
        raise ValueError("wallet address is not a valid EVM address")
    wallet_id = hashlib.sha256(
        f"{normalized_chain}\0{normalized_address}".encode()
    ).hexdigest()
    return wallet_id, normalized_chain, normalized_address
