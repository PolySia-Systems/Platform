from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")


class StrategyLifecycleStatus(StrEnum):
    EXPERIMENTAL = "experimental"
    PAPER = "paper"
    SHADOW = "shadow"
    LIMITED_LIVE = "limited_live"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class StrategyDefinition(_FrozenModel):
    strategy_id: str
    name: str
    version: str
    family: str
    category: str
    description: str
    hypothesis: str
    supported_market_types: tuple[str, ...]
    supported_venues: tuple[str, ...]
    decision_horizon: str
    allowed_runtime_modes: tuple[str, ...]
    lifecycle_status: StrategyLifecycleStatus
    risk_class: str
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()
    owner: str
    created_at: datetime
    code_reference: str
    test_reference: str

    @field_validator(
        "strategy_id",
        "name",
        "family",
        "category",
        "description",
        "hypothesis",
        "decision_horizon",
        "risk_class",
        "owner",
        "code_reference",
        "test_reference",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("strategy metadata fields must not be empty")
        return text

    @field_validator("version")
    @classmethod
    def require_semantic_version(cls, value: str) -> str:
        if _SEMVER.fullmatch(value) is None:
            raise ValueError("strategy version must be semantic version text")
        return value

    @field_validator(
        "supported_market_types",
        "supported_venues",
        "allowed_runtime_modes",
    )
    @classmethod
    def require_non_empty_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values if value.strip())
        if not normalized:
            raise ValueError("strategy capability metadata must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("strategy capability metadata must not contain duplicates")
        return normalized

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class StrategyRun(_FrozenModel):
    strategy_id: str
    strategy_version: str
    run_id: str
    runtime_mode: str
    venue: str
    market: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] = Field(default_factory=dict)
    risk_result: dict[str, Any] = Field(default_factory=dict)
    orders: tuple[dict[str, Any], ...] = ()
    fills: tuple[dict[str, Any], ...] = ()
    fees: Decimal = Decimal("0")
    position_outcome: dict[str, Any] = Field(default_factory=dict)
    reconciliation_result: dict[str, Any] = Field(default_factory=dict)
    errors: tuple[str, ...] = ()
    stop_reason: str | None = None
    evidence_references: tuple[str, ...] = ()

    @field_validator("strategy_id", "strategy_version", "run_id", "runtime_mode", "venue")
    @classmethod
    def require_run_identity(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("strategy run identity fields must not be empty")
        return text

    @field_validator("started_at", "ended_at")
    @classmethod
    def require_aware_run_time(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
    @model_validator(mode="after")
    def validate_run_timeline(self) -> StrategyRun:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("strategy run ended_at must not precede started_at")
        if self.fees < Decimal("0"):
            raise ValueError("strategy run fees must not be negative")
        return self


class StrategyPerformanceSummary(_FrozenModel):
    strategy_id: str
    strategy_version: str
    run_count: int = 0
    trade_count: int = 0
    fill_rate: Decimal | None = None
    gross_pnl: Decimal | None = None
    net_pnl: Decimal | None = None
    fees: Decimal | None = None
    maximum_drawdown: Decimal | None = None
    win_rate: Decimal | None = None
    average_holding_period: str | None = None
    execution_quality: str | None = None
    reconciliation_quality: str | None = None
    last_evaluation_date: datetime | None = None
    evidence_sufficiency: str = "insufficient"
    score_status: str = "unrated"

    @field_validator("run_count", "trade_count")
    @classmethod
    def require_non_negative_counts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("performance counts must not be negative")
        return value

    @field_validator("last_evaluation_date")
    @classmethod
    def require_aware_evaluation_time(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)
