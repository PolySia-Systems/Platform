from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from polysia.control.models import ControlApplyCommand, ControlPlanCommand, OperationalState
from polysia.control.service import (
    ControlConflictError,
    ControlIdempotencyError,
    ControlService,
)
from polysia.control.shadow_runtime import STALE_PRICE_SHADOW_TARGET, ShadowIntentBoundary
from polysia.storage.control import ControlRepository
from polysia.storage.db import SQLiteDatabase, connect_sqlite, initialize_database

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def test_control_schema_is_additive_for_an_existing_sqlite_database(tmp_path) -> None:
    connection = connect_sqlite(tmp_path / "existing.sqlite3")
    try:
        connection.execute("CREATE TABLE existing_state (value TEXT NOT NULL)")
        connection.execute("INSERT INTO existing_state (value) VALUES ('preserved')")
        connection.commit()

        initialize_database(connection)

        assert connection.execute("SELECT value FROM existing_state").fetchone()[0] == "preserved"
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'control_desired_state_revisions'"
            ).fetchone()[0]
            == "control_desired_state_revisions"
        )
    finally:
        connection.close()


def test_control_state_survives_restart_and_replays_identical_command(tmp_path) -> None:
    path = tmp_path / "control.sqlite3"
    with SQLiteDatabase(path) as database:
        service = _service(ControlRepository(database.connection))
        plan = service.plan(_plan_command(OperationalState.PAUSED))
        first = _apply(service, plan.plan_id, "command-1", expected_revision=0)
        replay = _apply(service, plan.plan_id, "command-1", expected_revision=0)

        assert first.revision.revision == 1
        assert replay.revision.revision == 1
        assert replay.idempotent_replay is True
        assert len(service.history(STALE_PRICE_SHADOW_TARGET)) == 1

        with pytest.raises(ControlIdempotencyError, match="different control content"):
            service.apply(
                command=ControlApplyCommand(
                    plan_id=plan.plan_id,
                    command_id="command-1",
                    expected_revision=0,
                    actor="different-actor",
                    source="CLI",
                ),
                runtime=ShadowIntentBoundary(STALE_PRICE_SHADOW_TARGET),
            )

    with SQLiteDatabase(path) as reopened:
        service = _service(ControlRepository(reopened.connection))
        status = service.status(STALE_PRICE_SHADOW_TARGET)
        assert status.desired_revision == 1
        assert status.desired_state is OperationalState.PAUSED
        assert status.observed_state.value == "PAUSED"
        assert len(service.history(STALE_PRICE_SHADOW_TARGET)) == 1


def test_competing_plans_allow_one_apply_and_reject_the_stale_plan(tmp_path) -> None:
    path = tmp_path / "concurrency.sqlite3"
    with SQLiteDatabase(path) as first_database, SQLiteDatabase(path) as second_database:
        first_service = _service(ControlRepository(first_database.connection))
        second_service = _service(ControlRepository(second_database.connection))
        first_plan = first_service.plan(_plan_command(OperationalState.PAUSED))
        second_plan = second_service.plan(_plan_command(OperationalState.PAUSED))

        _apply(first_service, first_plan.plan_id, "first-command", expected_revision=0)
        with pytest.raises(ControlConflictError, match="re-plan required"):
            _apply(second_service, second_plan.plan_id, "second-command", expected_revision=0)

        assert first_service.status(STALE_PRICE_SHADOW_TARGET).desired_revision == 1
        assert len(first_service.history(STALE_PRICE_SHADOW_TARGET)) == 1


def test_audit_insert_failure_rolls_back_every_apply_write() -> None:
    with SQLiteDatabase() as database:
        repository = ControlRepository(database.connection)
        service = _service(repository)
        plan = service.plan(_plan_command(OperationalState.PAUSED))
        database.connection.execute(
            """
            CREATE TRIGGER force_control_audit_failure
            BEFORE INSERT ON control_audit_events
            BEGIN SELECT RAISE(ABORT, 'forced audit failure'); END
            """
        )
        database.connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="forced audit failure"):
            _apply(service, plan.plan_id, "command-rollback", expected_revision=0)

        for table in (
            "control_desired_state_revisions",
            "control_observed_state_events",
            "control_commands",
            "control_audit_events",
        ):
            count = database.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0


def test_persisted_control_evidence_is_immutable() -> None:
    with SQLiteDatabase() as database:
        service = _service(ControlRepository(database.connection))
        plan = service.plan(_plan_command(OperationalState.PAUSED))
        _apply(service, plan.plan_id, "command-immutable", expected_revision=0)

        with pytest.raises(sqlite3.IntegrityError, match="control revisions are immutable"):
            database.connection.execute(
                "UPDATE control_desired_state_revisions SET desired_state = 'RUNNING'"
            )
        database.connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="control audit is immutable"):
            database.connection.execute("DELETE FROM control_audit_events")
        database.connection.rollback()


def _service(repository: ControlRepository) -> ControlService:
    return ControlService(
        repository,
        supported_targets=(STALE_PRICE_SHADOW_TARGET,),
        clock=lambda: NOW,
    )


def _apply(
    service: ControlService,
    plan_id: str,
    command_id: str,
    *,
    expected_revision: int,
):
    return service.apply(
        command=ControlApplyCommand(
            plan_id=plan_id,
            command_id=command_id,
            expected_revision=expected_revision,
            actor="owner",
            source="CLI",
        ),
        runtime=ShadowIntentBoundary(STALE_PRICE_SHADOW_TARGET, clock=lambda: NOW),
    )


def _plan_command(state: OperationalState) -> ControlPlanCommand:
    return ControlPlanCommand(key=STALE_PRICE_SHADOW_TARGET, requested_state=state)
