from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from polysia.application.ports.wallet_intelligence_research import ResearchPublicationError
from polysia.cli_support.wallet_intelligence_workflow import (
    WorkflowPaths,
    execute_workflow,
    human_summary,
)


def local(
    producer_dir: Annotated[Path | None, typer.Option("--producer-dir")] = None,
    producer_executable: Annotated[Path | None, typer.Option("--producer-executable")] = None,
    producer_config: Annotated[Path | None, typer.Option("--producer-config")] = None,
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    output_root: Annotated[Path | None, typer.Option("--output-root")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Force one bounded immediate refresh")
    ] = False,
    allow_partial: Annotated[bool, typer.Option("--allow-partial")] = False,
    no_view: Annotated[bool, typer.Option("--no-view")] = False,
    open_view: Annotated[bool, typer.Option("--open-view")] = False,
) -> None:
    """Refresh when due, open an optional local view, and assess one pinned snapshot."""
    producer = (producer_dir or Path.home() / "Documents/PolySia-Wallet-Intelligence").resolve()
    executable = producer_executable or producer / (
        ".venv/Scripts/wallet-intelligence.exe"
        if os.name == "nt"
        else ".venv/bin/wallet-intelligence"
    )
    output = output_root or Path.home() / "Documents/PolySia/artifacts/wallet-intelligence-workflow"
    paths = WorkflowPaths(
        producer,
        executable.resolve(),
        (producer_config or producer / "config/acceptance.toml").resolve(),
        (data_root or producer / "artifacts/acceptance").resolve(),
        output.resolve(),
    )
    try:
        result = execute_workflow(
            paths, force=force, allow_partial=allow_partial, render_view=not no_view
        )
    except (ResearchPublicationError, OSError) as exc:
        reason = (
            exc.code if isinstance(exc, ResearchPublicationError) else "workflow_output_unavailable"
        )
        typer.echo(f"Wallet Intelligence: FAILED ({reason}); no new result", err=True)
        raise typer.Exit(2) from exc
    typer.echo(human_summary(result))
    if (
        open_view
        and result.get("human_view")
        and not webbrowser.open(Path(result["human_view"]).as_uri())
    ):
        typer.echo("Warning: could not open Human View; use the printed path.")
    if result["status"] in {"FAILED", "REJECTED"}:
        raise typer.Exit(2)
