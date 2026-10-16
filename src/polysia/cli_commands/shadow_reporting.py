"""Bounded, provider-free snapshot reports."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from polysia.application.services.shadow_reporting import (
    ShadowReportingService,
    UnsupportedReportingWindow,
    comparison_csv,
)
from polysia.storage.continuous_shadow import ContinuousShadowStoreError


def shadow_report(
    database: Annotated[Path, typer.Option("--database", exists=True, dir_okay=False)],
    experiment_id: Annotated[str, typer.Option("--experiment-id")],
    output_format: Annotated[str, typer.Option("--format")] = "json",
    start: Annotated[
        datetime | None,
        typer.Option("--start", formats=["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"]),
    ] = None,
    end: Annotated[
        datetime | None,
        typer.Option("--end", formats=["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"]),
    ] = None,
) -> None:
    """Snapshot one financial session and report without acquiring provider data."""
    if output_format not in {"json", "csv"}:
        raise typer.BadParameter("format must be json or csv")
    try:
        report = ShadowReportingService(database).report(experiment_id, start=start, end=end)
    except UnsupportedReportingWindow as error:
        typer.echo(json.dumps({"status": "UNSUPPORTED_RANGE", "reason": str(error)}), err=True)
        raise typer.Exit(2) from None
    except OSError, ValueError, sqlite3.DatabaseError, ContinuousShadowStoreError:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason": "snapshot_or_report_invalid",
                    "next_action": "inspect financial-store integrity and experiment identity",
                }
            ),
            err=True,
        )
        raise typer.Exit(1) from None
    typer.echo(
        comparison_csv(report)
        if output_format == "csv"
        else json.dumps(
            report,
            sort_keys=True,
        )
    )
