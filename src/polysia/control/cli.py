from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from polysia.control.models import (
    ControlApplyCommand,
    ControlPlanCommand,
    OperationalState,
    StrategyControlKey,
)
from polysia.control.service import ControlError, ControlService
from polysia.control.shadow_runtime import STALE_PRICE_SHADOW_TARGET, ShadowIntentBoundary
from polysia.storage.control import ControlRepository
from polysia.storage.db import SQLiteDatabase

control_app = typer.Typer(
    help="Plan and apply the bounded SHADOW-only operational-state slice.",
    no_args_is_help=True,
)

DEFAULT_CONTROL_DATABASE = Path("data/polysia.sqlite3")


@control_app.command("plan")
def plan_control_change(
    requested_state: Annotated[OperationalState, typer.Argument()],
    database_path: Annotated[
        Path,
        typer.Option("--database-path", help="SQLite control-state database."),
    ] = DEFAULT_CONTROL_DATABASE,
    strategy_id: Annotated[str, typer.Option("--strategy-id")] = "stale-price",
    strategy_version: Annotated[str, typer.Option("--strategy-version")] = "0.1.0",
) -> None:
    """Create an immutable impact plan against the current SHADOW revision."""
    try:
        key = StrategyControlKey(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
        with SQLiteDatabase(database_path) as database:
            service = _service(ControlRepository(database.connection))
            plan = service.plan(
                ControlPlanCommand(key=key, requested_state=requested_state)
            )
    except (ControlError, ValidationError, ValueError, sqlite3.DatabaseError) as error:
        _fail(error)
    typer.echo(json.dumps(plan.model_dump(mode="json"), sort_keys=True))


@control_app.command("apply")
def apply_control_change(
    plan_id: Annotated[str, typer.Option("--plan-id")],
    command_id: Annotated[str, typer.Option("--command-id")],
    expected_revision: Annotated[int, typer.Option("--expected-revision", min=0)],
    actor: Annotated[
        str,
        typer.Option("--actor", help="Audit label only; this is not authentication."),
    ],
    database_path: Annotated[
        Path,
        typer.Option("--database-path", help="SQLite control-state database."),
    ] = DEFAULT_CONTROL_DATABASE,
) -> None:
    """Apply one planned SHADOW transition with concurrency and idempotency checks."""
    try:
        with SQLiteDatabase(database_path) as database:
            repository = ControlRepository(database.connection)
            service = _service(repository)
            runtime = ShadowIntentBoundary(STALE_PRICE_SHADOW_TARGET)
            result = service.apply(
                command=ControlApplyCommand(
                    plan_id=plan_id,
                    command_id=command_id,
                    expected_revision=expected_revision,
                    actor=actor,
                    source="CLI",
                ),
                runtime=runtime,
            )
    except (ControlError, ValidationError, ValueError, sqlite3.DatabaseError) as error:
        _fail(error)
    typer.echo(json.dumps(result.model_dump(mode="json"), sort_keys=True))


@control_app.command("status")
def control_status(
    database_path: Annotated[
        Path,
        typer.Option("--database-path", help="SQLite control-state database."),
    ] = DEFAULT_CONTROL_DATABASE,
    strategy_id: Annotated[str, typer.Option("--strategy-id")] = "stale-price",
    strategy_version: Annotated[str, typer.Option("--strategy-version")] = "0.1.0",
) -> None:
    """Show desired and last genuinely observed SHADOW state separately."""
    try:
        key = StrategyControlKey(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
        with SQLiteDatabase(database_path) as database:
            status = _service(ControlRepository(database.connection)).status(key)
    except (ControlError, ValidationError, ValueError, sqlite3.DatabaseError) as error:
        _fail(error)
    typer.echo(json.dumps(status.model_dump(mode="json"), sort_keys=True))


@control_app.command("history")
def control_history(
    database_path: Annotated[
        Path,
        typer.Option("--database-path", help="SQLite control-state database."),
    ] = DEFAULT_CONTROL_DATABASE,
    strategy_id: Annotated[str, typer.Option("--strategy-id")] = "stale-price",
    strategy_version: Annotated[str, typer.Option("--strategy-version")] = "0.1.0",
) -> None:
    """Show append-only, sanitized SHADOW control audit records."""
    try:
        key = StrategyControlKey(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
        with SQLiteDatabase(database_path) as database:
            history = _service(ControlRepository(database.connection)).history(key)
    except (ControlError, ValidationError, ValueError, sqlite3.DatabaseError) as error:
        _fail(error)
    typer.echo(
        json.dumps(
            [record.model_dump(mode="json") for record in history],
            sort_keys=True,
        )
    )


def _service(repository: ControlRepository) -> ControlService:
    return ControlService(
        repository,
        supported_targets=(STALE_PRICE_SHADOW_TARGET,),
    )


def _fail(error: Exception) -> None:
    if isinstance(error, ControlError):
        message = str(error)
    elif isinstance(error, sqlite3.DatabaseError):
        message = "SQLite control storage failed safely"
    else:
        message = "control input validation failed"
    typer.echo(
        json.dumps(
            {
                "error": type(error).__name__,
                "message": message,
                "status": "blocked",
            },
            sort_keys=True,
        ),
        err=True,
    )
    raise typer.Exit(code=1)


__all__ = ["control_app"]
