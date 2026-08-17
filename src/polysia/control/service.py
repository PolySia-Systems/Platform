from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from polysia.control.models import (
    ControlApplyCommand,
    ControlApplyResult,
    ControlAuditRecord,
    ControlPlan,
    ControlPlanCommand,
    ControlStatus,
    DesiredStateRevision,
    ObservedOperationalState,
    OperationalState,
    ReconciliationStatus,
    RuntimeObservation,
    StrategyControlKey,
)

Clock = Callable[[], datetime]
IdentifierFactory = Callable[[], str]
_AUDIT_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,63}$")


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_identifier() -> str:
    return str(uuid4())


class ControlError(RuntimeError):
    """Base class for safe operator-visible Control Kernel failures."""


class ControlValidationError(ControlError):
    """Raised when a request is outside the supported Shadow slice."""


class ControlConflictError(ControlError):
    """Raised when expected revision no longer matches persisted state."""


class ControlIdempotencyError(ControlError):
    """Raised when an idempotency key is reused for different content."""


class ControlNotFoundError(ControlError):
    """Raised when a referenced immutable plan does not exist."""


@dataclass(frozen=True, slots=True)
class StoredCommandResult:
    payload_digest: str
    result: ControlApplyResult


class ControlStore(Protocol):
    def add_plan(self, plan: ControlPlan) -> None: ...

    def get_plan(self, plan_id: str) -> ControlPlan | None: ...

    def current_desired(self, key: StrategyControlKey) -> DesiredStateRevision | None: ...

    def command_result(self, command_id: str) -> StoredCommandResult | None: ...

    def commit_apply(
        self,
        *,
        plan: ControlPlan,
        payload_digest: str,
        result: ControlApplyResult,
    ) -> ControlApplyResult: ...

    def status(self, key: StrategyControlKey) -> ControlStatus: ...

    def history(self, key: StrategyControlKey) -> tuple[ControlAuditRecord, ...]: ...


class RuntimeControlPort(Protocol):
    def reconcile(self, revision: DesiredStateRevision) -> RuntimeObservation: ...


class ControlService:
    """Plan and atomically apply one explicitly supported Shadow state transition."""

    def __init__(
        self,
        store: ControlStore,
        *,
        supported_targets: Collection[StrategyControlKey],
        clock: Clock = utc_now,
        identifier_factory: IdentifierFactory = new_identifier,
    ) -> None:
        self._store = store
        self._supported_targets = frozenset(target.scope for target in supported_targets)
        self._clock = clock
        self._identifier_factory = identifier_factory

    def plan(self, command: ControlPlanCommand) -> ControlPlan:
        key = command.key
        requested_state = command.requested_state
        self._require_supported(key)
        current = self._store.current_desired(key)
        expected_revision = current.revision if current is not None else 0
        previous_state = current.desired_state if current is not None else OperationalState.RUNNING
        if previous_state is requested_state:
            raise ControlValidationError(
                f"{key.scope} is already {requested_state.value}; no state change was planned"
            )
        plan = ControlPlan(
            plan_id=self._identifier_factory(),
            key=key,
            expected_revision=expected_revision,
            previous_state=previous_state,
            requested_state=requested_state,
            impact=_impact(requested_state),
            created_at=self._clock(),
        )
        self._store.add_plan(plan)
        return plan

    def apply(
        self,
        *,
        command: ControlApplyCommand,
        runtime: RuntimeControlPort,
    ) -> ControlApplyResult:
        plan = self._store.get_plan(command.plan_id)
        if plan is None:
            raise ControlNotFoundError(f"control plan {command.plan_id!r} was not found")
        self._require_supported(plan.key)
        if command.expected_revision != plan.expected_revision:
            raise ControlConflictError(
                "apply expected_revision does not match the immutable plan; re-plan required"
            )
        normalized_command_id = _require_audit_label("command_id", command.command_id)
        normalized_actor = _require_audit_label("actor", command.actor)
        normalized_source = _require_audit_label("source", command.source)
        payload_digest = _command_digest(
            plan=plan,
            command_id=normalized_command_id,
            expected_revision=command.expected_revision,
            actor=normalized_actor,
            source=normalized_source,
        )
        existing = self._store.command_result(normalized_command_id)
        if existing is not None:
            if existing.payload_digest != payload_digest:
                raise ControlIdempotencyError(
                    "command_id was already used with different control content"
                )
            return existing.result.model_copy(update={"idempotent_replay": True})

        timestamp = self._clock()
        revision = DesiredStateRevision(
            key=plan.key,
            revision=command.expected_revision + 1,
            previous_revision=command.expected_revision,
            desired_state=plan.requested_state,
            command_id=normalized_command_id,
            plan_id=plan.plan_id,
            created_at=timestamp,
        )
        observation = _reconcile_safely(runtime, revision, timestamp, self._identifier_factory)
        audit = ControlAuditRecord(
            audit_id=self._identifier_factory(),
            command_id=normalized_command_id,
            actor=normalized_actor,
            source=normalized_source,
            plan=plan,
            created_revision=revision.revision,
            reconciliation_status=observation.reconciliation_status,
            observed_state=observation.observed_state,
            error=observation.error,
            occurred_at=timestamp,
        )
        result = ControlApplyResult(
            command_id=normalized_command_id,
            revision=revision,
            observation=observation,
            audit=audit,
        )
        return self._store.commit_apply(
            plan=plan,
            payload_digest=payload_digest,
            result=result,
        )

    def status(self, key: StrategyControlKey) -> ControlStatus:
        self._require_supported(key)
        return self._store.status(key)

    def history(self, key: StrategyControlKey) -> tuple[ControlAuditRecord, ...]:
        self._require_supported(key)
        return self._store.history(key)

    def _require_supported(self, key: StrategyControlKey) -> None:
        if key.scope not in self._supported_targets:
            raise ControlValidationError(
                f"{key.scope} is outside the first SHADOW-only Control Kernel slice"
            )


def _impact(requested_state: OperationalState) -> tuple[str, ...]:
    action = "suppressed" if requested_state is OperationalState.PAUSED else "allowed"
    return (
        f"new Shadow strategy intents will be {action}",
        "Risk, reconciliation, monitoring, and emergency controls remain independent",
        "no Live broker, venue mutation, cancellation, or position closure is authorized",
    )


def _command_digest(
    *,
    plan: ControlPlan,
    command_id: str,
    expected_revision: int,
    actor: str,
    source: str,
) -> str:
    payload = {
        "actor": actor,
        "command_id": command_id,
        "expected_revision": expected_revision,
        "plan": plan.model_dump(mode="json"),
        "source": source,
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reconcile_safely(
    runtime: RuntimeControlPort,
    revision: DesiredStateRevision,
    timestamp: datetime,
    identifier_factory: IdentifierFactory,
) -> RuntimeObservation:
    try:
        observation = runtime.reconcile(revision)
    except Exception as error:
        return RuntimeObservation(
            observation_id=identifier_factory(),
            key=revision.key,
            desired_revision=revision.revision,
            observed_state=ObservedOperationalState.UNKNOWN,
            reconciliation_status=ReconciliationStatus.FAILED,
            observed_at=timestamp,
            error=f"{type(error).__name__}: Shadow reconciliation failed",
        )
    if observation.key != revision.key or observation.desired_revision != revision.revision:
        return RuntimeObservation(
            observation_id=identifier_factory(),
            key=revision.key,
            desired_revision=revision.revision,
            observed_state=ObservedOperationalState.UNKNOWN,
            reconciliation_status=ReconciliationStatus.FAILED,
            observed_at=timestamp,
            error="RuntimeObservationMismatch: Shadow runtime acknowledged a different revision",
        )
    return observation


def _require_audit_label(field_name: str, value: str) -> str:
    normalized = value.strip()
    if _AUDIT_LABEL.fullmatch(normalized) is None:
        raise ControlValidationError(
            f"{field_name} must be a 1-64 character non-secret audit label"
        )
    return normalized


__all__ = [
    "ControlConflictError",
    "ControlError",
    "ControlIdempotencyError",
    "ControlNotFoundError",
    "ControlService",
    "ControlStore",
    "ControlValidationError",
    "RuntimeControlPort",
]
