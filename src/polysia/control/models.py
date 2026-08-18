from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ControlRuntimeMode(StrEnum):
    SHADOW = "SHADOW"


class OperationalState(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class ObservedOperationalState(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    UNKNOWN = "UNKNOWN"


class ReconciliationStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class _FrozenControlModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyControlKey(_FrozenControlModel):
    strategy_id: str
    strategy_version: str
    runtime_mode: ControlRuntimeMode = ControlRuntimeMode.SHADOW

    @field_validator("strategy_id", "strategy_version")
    @classmethod
    def require_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("strategy control identity must not be empty")
        return normalized

    @property
    def scope(self) -> str:
        return f"{self.runtime_mode.value}:{self.strategy_id}@{self.strategy_version}"


class ControlPlanCommand(_FrozenControlModel):
    key: StrategyControlKey
    requested_state: OperationalState


class ControlApplyCommand(_FrozenControlModel):
    plan_id: str
    command_id: str
    expected_revision: int
    actor: str
    source: str

    @field_validator("plan_id", "command_id", "actor", "source")
    @classmethod
    def require_command_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("control command fields must not be empty")
        return normalized

    @field_validator("expected_revision")
    @classmethod
    def require_non_negative_revision(cls, value: int) -> int:
        if value < 0:
            raise ValueError("expected_revision must not be negative")
        return value


class ControlPlan(_FrozenControlModel):
    plan_id: str
    key: StrategyControlKey
    expected_revision: int
    previous_state: OperationalState
    requested_state: OperationalState
    impact: tuple[str, ...]
    validation_result: Literal["PASS"] = "PASS"
    policy_result: Literal["ALLOW_SHADOW_ONLY"] = "ALLOW_SHADOW_ONLY"
    approval_required: bool = False
    approval_result: Literal["NOT_REQUIRED"] = "NOT_REQUIRED"
    created_at: datetime

    @field_validator("plan_id")
    @classmethod
    def require_plan_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("plan_id must not be empty")
        return normalized

    @field_validator("expected_revision")
    @classmethod
    def require_non_negative_revision(cls, value: int) -> int:
        if value < 0:
            raise ValueError("expected_revision must not be negative")
        return value

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def require_state_change(self) -> ControlPlan:
        if self.previous_state is self.requested_state:
            raise ValueError("control plan must describe an operational-state change")
        if not self.impact:
            raise ValueError("control plan must describe its impact")
        return self


class DesiredStateRevision(_FrozenControlModel):
    key: StrategyControlKey
    revision: int
    previous_revision: int
    desired_state: OperationalState
    command_id: str
    plan_id: str
    created_at: datetime
    based_on_revision: int | None = None

    @field_validator("command_id", "plan_id")
    @classmethod
    def require_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("control references must not be empty")
        return normalized

    @field_validator("revision")
    @classmethod
    def require_positive_revision(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("persisted desired-state revision must be positive")
        return value

    @field_validator("previous_revision")
    @classmethod
    def require_non_negative_previous_revision(cls, value: int) -> int:
        if value < 0:
            raise ValueError("previous_revision must not be negative")
        return value

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def require_adjacent_revision(self) -> DesiredStateRevision:
        if self.revision != self.previous_revision + 1:
            raise ValueError("desired-state revisions must be adjacent")
        return self


class RuntimeObservation(_FrozenControlModel):
    observation_id: str
    key: StrategyControlKey
    desired_revision: int
    observed_state: ObservedOperationalState
    reconciliation_status: ReconciliationStatus
    observed_at: datetime
    error: str | None = None

    @field_validator("observation_id")
    @classmethod
    def require_observation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("observation_id must not be empty")
        return normalized

    @field_validator("desired_revision")
    @classmethod
    def require_non_negative_revision(cls, value: int) -> int:
        if value < 0:
            raise ValueError("desired_revision must not be negative")
        return value

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def require_honest_observation(self) -> RuntimeObservation:
        if self.reconciliation_status is ReconciliationStatus.SUCCESS:
            if self.observed_state is ObservedOperationalState.UNKNOWN or self.error is not None:
                raise ValueError("successful reconciliation requires a known state and no error")
        elif self.reconciliation_status is ReconciliationStatus.FAILED:
            if self.observed_state is not ObservedOperationalState.UNKNOWN:
                raise ValueError("failed reconciliation must report UNKNOWN observed state")
            if not self.error:
                raise ValueError("failed reconciliation must include a sanitized error")
        return self


class ControlAuditRecord(_FrozenControlModel):
    audit_id: str
    command_id: str
    actor: str
    source: str
    plan: ControlPlan
    created_revision: int
    reconciliation_status: ReconciliationStatus
    observed_state: ObservedOperationalState
    error: str | None
    occurred_at: datetime

    @field_validator("audit_id", "command_id", "actor", "source")
    @classmethod
    def require_audit_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("control audit fields must not be empty")
        return normalized

    @field_validator("created_revision")
    @classmethod
    def require_positive_revision(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("created_revision must be positive")
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurred_at(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ControlApplyResult(_FrozenControlModel):
    command_id: str
    revision: DesiredStateRevision
    observation: RuntimeObservation
    audit: ControlAuditRecord
    idempotent_replay: bool = False


class ControlStatus(_FrozenControlModel):
    key: StrategyControlKey
    desired_revision: int
    desired_state: OperationalState
    observed_state: ObservedOperationalState
    reconciliation_status: ReconciliationStatus
    last_reconciled_revision: int | None
    error: str | None = None
