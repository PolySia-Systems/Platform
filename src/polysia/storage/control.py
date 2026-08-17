from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from polysia.control.models import (
    ControlApplyResult,
    ControlAuditRecord,
    ControlPlan,
    ControlStatus,
    DesiredStateRevision,
    ObservedOperationalState,
    OperationalState,
    ReconciliationStatus,
    RuntimeObservation,
    StrategyControlKey,
)
from polysia.control.service import (
    ControlConflictError,
    ControlIdempotencyError,
    StoredCommandResult,
)
from polysia.storage.db import transaction


class ControlRepository:
    """Append-only SQLite storage for the first Shadow Control Kernel slice."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_plan(self, plan: ControlPlan) -> None:
        with transaction(self._connection) as connection:
            connection.execute(
                """
                INSERT INTO control_change_plans (
                    plan_id, strategy_id, strategy_version, runtime_mode,
                    expected_revision, requested_state, plan_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.key.strategy_id,
                    plan.key.strategy_version,
                    plan.key.runtime_mode.value,
                    plan.expected_revision,
                    plan.requested_state.value,
                    plan.model_dump_json(),
                    plan.created_at.isoformat(),
                ),
            )

    def get_plan(self, plan_id: str) -> ControlPlan | None:
        row = self._connection.execute(
            "SELECT plan_json FROM control_change_plans WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()
        return None if row is None else ControlPlan.model_validate_json(str(row["plan_json"]))

    def current_desired(self, key: StrategyControlKey) -> DesiredStateRevision | None:
        row = self._connection.execute(
            """
            SELECT revision_json
            FROM control_desired_state_revisions
            WHERE strategy_id = ? AND strategy_version = ? AND runtime_mode = ?
            ORDER BY revision DESC
            LIMIT 1
            """,
            (key.strategy_id, key.strategy_version, key.runtime_mode.value),
        ).fetchone()
        if row is None:
            return None
        return DesiredStateRevision.model_validate_json(str(row["revision_json"]))

    def command_result(self, command_id: str) -> StoredCommandResult | None:
        row = self._connection.execute(
            """
            SELECT payload_digest, result_json
            FROM control_commands
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return StoredCommandResult(
            payload_digest=str(row["payload_digest"]),
            result=ControlApplyResult.model_validate_json(str(row["result_json"])),
        )

    def commit_apply(
        self,
        *,
        plan: ControlPlan,
        payload_digest: str,
        result: ControlApplyResult,
    ) -> ControlApplyResult:
        with _immediate_transaction(self._connection) as connection:
            existing = _command_result(connection, result.command_id)
            if existing is not None:
                if existing.payload_digest != payload_digest:
                    raise ControlIdempotencyError(
                        "command_id was concurrently used with different control content"
                    )
                return existing.result.model_copy(update={"idempotent_replay": True})

            current_revision = _current_revision(connection, plan.key)
            if current_revision != plan.expected_revision:
                raise ControlConflictError(
                    f"expected revision {plan.expected_revision}, found {current_revision}; "
                    "re-plan required"
                )

            revision = result.revision
            observation = result.observation
            audit = result.audit
            connection.execute(
                """
                INSERT INTO control_desired_state_revisions (
                    strategy_id, strategy_version, runtime_mode, revision,
                    previous_revision, desired_state, command_id, plan_id,
                    revision_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision.key.strategy_id,
                    revision.key.strategy_version,
                    revision.key.runtime_mode.value,
                    revision.revision,
                    revision.previous_revision,
                    revision.desired_state.value,
                    revision.command_id,
                    revision.plan_id,
                    revision.model_dump_json(),
                    revision.created_at.isoformat(),
                ),
            )
            _insert_observation(connection, observation)
            connection.execute(
                """
                INSERT INTO control_commands (
                    command_id, payload_digest, result_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    result.command_id,
                    payload_digest,
                    result.model_dump_json(),
                    audit.occurred_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO control_audit_events (
                    audit_id, command_id, strategy_id, strategy_version,
                    runtime_mode, revision, reconciliation_status,
                    audit_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit.audit_id,
                    audit.command_id,
                    audit.plan.key.strategy_id,
                    audit.plan.key.strategy_version,
                    audit.plan.key.runtime_mode.value,
                    audit.created_revision,
                    audit.reconciliation_status.value,
                    audit.model_dump_json(),
                    audit.occurred_at.isoformat(),
                ),
            )
        return result

    def record_runtime_observation(self, observation: RuntimeObservation) -> None:
        with transaction(self._connection) as connection:
            _insert_observation(connection, observation)

    def status(self, key: StrategyControlKey) -> ControlStatus:
        desired = self.current_desired(key)
        desired_revision = desired.revision if desired is not None else 0
        desired_state = desired.desired_state if desired is not None else OperationalState.RUNNING
        row = self._connection.execute(
            """
            SELECT observation_json
            FROM control_observed_state_events
            WHERE strategy_id = ? AND strategy_version = ? AND runtime_mode = ?
              AND desired_revision = ?
            ORDER BY observed_at DESC, rowid DESC
            LIMIT 1
            """,
            (
                key.strategy_id,
                key.strategy_version,
                key.runtime_mode.value,
                desired_revision,
            ),
        ).fetchone()
        if row is None:
            return ControlStatus(
                key=key,
                desired_revision=desired_revision,
                desired_state=desired_state,
                observed_state=ObservedOperationalState.UNKNOWN,
                reconciliation_status=ReconciliationStatus.PENDING,
                last_reconciled_revision=None,
            )
        observation = RuntimeObservation.model_validate_json(str(row["observation_json"]))
        return ControlStatus(
            key=key,
            desired_revision=desired_revision,
            desired_state=desired_state,
            observed_state=observation.observed_state,
            reconciliation_status=observation.reconciliation_status,
            last_reconciled_revision=observation.desired_revision,
            error=observation.error,
        )

    def history(self, key: StrategyControlKey) -> tuple[ControlAuditRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT audit_json
            FROM control_audit_events
            WHERE strategy_id = ? AND strategy_version = ? AND runtime_mode = ?
            ORDER BY revision, created_at, audit_id
            """,
            (key.strategy_id, key.strategy_version, key.runtime_mode.value),
        ).fetchall()
        return tuple(
            ControlAuditRecord.model_validate_json(str(row["audit_json"])) for row in rows
        )


def _current_revision(connection: sqlite3.Connection, key: StrategyControlKey) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(revision), 0) AS revision
        FROM control_desired_state_revisions
        WHERE strategy_id = ? AND strategy_version = ? AND runtime_mode = ?
        """,
        (key.strategy_id, key.strategy_version, key.runtime_mode.value),
    ).fetchone()
    return int(row["revision"])


def _command_result(
    connection: sqlite3.Connection,
    command_id: str,
) -> StoredCommandResult | None:
    row = connection.execute(
        "SELECT payload_digest, result_json FROM control_commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if row is None:
        return None
    return StoredCommandResult(
        payload_digest=str(row["payload_digest"]),
        result=ControlApplyResult.model_validate_json(str(row["result_json"])),
    )


def _insert_observation(
    connection: sqlite3.Connection,
    observation: RuntimeObservation,
) -> None:
    connection.execute(
        """
        INSERT INTO control_observed_state_events (
            observation_id, strategy_id, strategy_version, runtime_mode,
            desired_revision, observed_state, reconciliation_status,
            observation_json, observed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation.observation_id,
            observation.key.strategy_id,
            observation.key.strategy_version,
            observation.key.runtime_mode.value,
            observation.desired_revision,
            observation.observed_state.value,
            observation.reconciliation_status.value,
            observation.model_dump_json(),
            observation.observed_at.isoformat(),
        ),
    )


@contextmanager
def _immediate_transaction(
    connection: sqlite3.Connection,
) -> Iterator[sqlite3.Connection]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


__all__ = ["ControlRepository"]
