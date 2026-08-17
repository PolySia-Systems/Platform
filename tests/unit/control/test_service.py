from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polysia.control.models import (
    ControlApplyCommand,
    ControlPlanCommand,
    ObservedOperationalState,
    OperationalState,
    ReconciliationStatus,
    StrategyControlKey,
)
from polysia.control.service import ControlService, ControlValidationError
from polysia.control.shadow_runtime import STALE_PRICE_SHADOW_TARGET
from polysia.storage.control import ControlRepository
from polysia.storage.db import SQLiteDatabase

NOW = datetime(2026, 8, 17, tzinfo=UTC)


class FailingRuntime:
    def reconcile(self, revision):
        raise RuntimeError("sensitive internal detail must not be stored")


def test_failed_reconciliation_is_persisted_as_unknown_without_optimistic_success() -> None:
    with SQLiteDatabase() as database:
        repository = ControlRepository(database.connection)
        service = _service(repository)
        plan = service.plan(_plan_command(STALE_PRICE_SHADOW_TARGET, OperationalState.PAUSED))

        result = service.apply(
            command=ControlApplyCommand(
                plan_id=plan.plan_id,
                command_id="command-failed",
                expected_revision=0,
                actor="owner",
                source="CLI",
            ),
            runtime=FailingRuntime(),
        )
        status = service.status(STALE_PRICE_SHADOW_TARGET)

    assert result.revision.desired_state is OperationalState.PAUSED
    assert result.observation.observed_state is ObservedOperationalState.UNKNOWN
    assert result.observation.reconciliation_status is ReconciliationStatus.FAILED
    assert "sensitive internal detail" not in (result.observation.error or "")
    assert status.desired_state is OperationalState.PAUSED
    assert status.observed_state is ObservedOperationalState.UNKNOWN
    assert status.reconciliation_status is ReconciliationStatus.FAILED


def test_service_rejects_an_unapproved_shadow_target_and_noop_plan() -> None:
    with SQLiteDatabase() as database:
        service = _service(ControlRepository(database.connection))
        unsupported = StrategyControlKey(
            strategy_id="passive-market-maker",
            strategy_version="0.1.0",
        )

        with pytest.raises(ControlValidationError, match="outside"):
            service.plan(_plan_command(unsupported, OperationalState.PAUSED))
        with pytest.raises(ControlValidationError, match="already RUNNING"):
            service.plan(_plan_command(STALE_PRICE_SHADOW_TARGET, OperationalState.RUNNING))


def _service(repository: ControlRepository) -> ControlService:
    return ControlService(
        repository,
        supported_targets=(STALE_PRICE_SHADOW_TARGET,),
        clock=lambda: NOW,
    )


def _plan_command(
    key: StrategyControlKey,
    state: OperationalState,
) -> ControlPlanCommand:
    return ControlPlanCommand(key=key, requested_state=state)
