"""Platform-owned structural reader of the wallet-intelligence/v1 JSON contract.

Additive fields remain intact. No producer Python types or storage are imported.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow", frozen=True)


class SourceReference(ContractModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    query_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    page: int = Field(ge=1, le=20)
    fetched_at: str
    url: str
    body_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AccountIdentity(ContractModel):
    venue: Literal["polymarket"]
    chain_id: Literal[137]
    account_wallet: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    wallet_type: str


class Activity(ContractModel):
    state: Literal["ACTIVE", "INACTIVE", "UNKNOWN"]
    window_days: int = Field(ge=1)
    window_start: str
    window_end: str
    last_trade_at: str | None
    source_rows: int = Field(ge=0)
    issues: list[str]
    acquisition: Literal["COMPLETE_FOR_QUERY", "INCOMPLETE"]
    existence_only: bool


class Component(ContractModel):
    value: str | None
    unit: Literal["USDC"]
    basis: str
    reason: str


class Performance(ContractModel):
    state: Literal["POSITIVE", "NON_POSITIVE", "UNKNOWN"]
    value: str | None
    metric: Literal["source-reported-position-pnl-change"]
    unit: Literal["USDC"]
    target_days: int = Field(ge=1, le=29)
    boundary_policy: Literal["preceding-anchor-one-day/v1"]
    source_fidelity: str
    freshness: Literal["FRESH", "STALE", "UNKNOWN"]
    source_observed_at: str | None
    start: str | None
    end: str | None
    span_seconds: int | None = Field(ge=0)
    components: dict[str, Component]
    reason: str


class Quality(ContractModel):
    descriptive: Literal["AVAILABLE", "UNKNOWN"]
    predictive: Literal["NOT_EVALUATED", "UNKNOWN"]


class Copyability(ContractModel):
    state: Literal["NOT_EVALUATED", "UNKNOWN"]
    reason: str


class SourceRecord(ContractModel):
    wallet_id: str
    identity: AccountIdentity
    outcome: Literal["CANDIDATE", "WATCHLIST", "EXCLUDED", "DATA_HOLD", "NOT_EXAMINED"]
    candidate_rank: int | None = Field(ge=1, le=20)
    discovery: list[dict[str, Any]]
    activity: Activity
    performance: Performance
    reasons: list[str]
    freshness: Literal["FRESH", "STALE", "UNKNOWN"]
    features: dict[str, Any]
    labels: list[dict[str, Any]]
    evidence_depth: dict[str, Any]
    quality: Quality
    copyability: Copyability
    rank_policy: Literal["period-pnl-activity-identity/v1"]
    observed_at: str | None
    fetched_at: str | None
    computed_at: str
    expires_at: str
    evidence_references: list[SourceReference]
    data_validity: Literal["VALID", "INVALID", "UNKNOWN"]


class Coverage(ContractModel):
    discovered: int = Field(ge=0, le=500)
    examined: int = Field(ge=0, le=100)
    unexamined: int = Field(ge=0, le=500)
    active: int = Field(ge=0, le=100)
    performance_supported: int = Field(ge=0, le=100)
    published: int = Field(ge=0, le=20)
    outcomes: dict[str, int]
    discovery_routes: list[dict[str, Any]]
    missing_partitions: list[str]
    scope: Literal["bounded_discovered_population_not_all_users"]
    limits: dict[str, int]
    discovery_mode: Literal["automatic", "retained_registry_refresh"]
    discovery_at: str


class ProducerProfile(ContractModel):
    id: Literal["research-candidates"]
    version: Literal["1"]


class Capabilities(ContractModel):
    descriptive_screening: Literal["AVAILABLE"]
    accounting_reconciliation: Literal["NOT_EVALUATED", "UNKNOWN"]
    predictive_quality: Literal["NOT_EVALUATED", "UNKNOWN"]
    copyability: Literal["NOT_EVALUATED", "UNKNOWN"]


class Publication(ContractModel):
    schema_version: Literal["wallet-intelligence/v1"]
    producer_version: str = Field(min_length=1)
    code_revision: str = Field(min_length=1)
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    profile: ProducerProfile
    config_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_set_version: Literal["descriptive/v1"]
    input_manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_cutoff: str
    evaluation_at: str
    generated_at: str
    expires_at: str
    coverage: Coverage
    status: Literal["PARTIAL", "COMPLETE_FOR_SCOPE"]
    reasons: list[str]
    records: list[SourceRecord] = Field(max_length=100)
    candidates: list[str] = Field(max_length=20)
    capabilities: Capabilities
    source_references: list[SourceReference]
    diagnostics: dict[str, Any]
