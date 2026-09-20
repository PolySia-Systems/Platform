"""CLI for disposable developer context packets. Not a trading path."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from polysia.cli_commands import print_error_and_exit
from polysia.developer.context_packet import (
    DirectoryPacketCache,
    build_context_packet,
    render_text,
)
from polysia.developer.git_state import DeveloperContextError


def developer_context(
    task: Annotated[
        str | None,
        typer.Option("--task", help="Issue or PR reference. Treated as untrusted data."),
    ] = None,
    json_file: Annotated[
        Path | None,
        typer.Option("--json-file", help="Write versioned JSON to this path."),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of human-readable text."),
    ] = False,
    cache_dir: Annotated[
        Path | None,
        typer.Option("--cache-dir", help="Optional disposable cache directory."),
    ] = None,
    scope: Annotated[
        list[str] | None,
        typer.Option("--scope", help="Repository-relative file or directory."),
    ] = None,
) -> None:
    """Emit a bounded developer context packet for one scoped local task."""

    try:
        root = Path.cwd().resolve()
        packet = build_context_packet(
            root,
            task_reference=task,
            scope=tuple(scope or ()),
            now=datetime.now(UTC),
            cache=None if cache_dir is None else DirectoryPacketCache(cache_dir),
        )
    except (DeveloperContextError, OSError, ValueError) as error:
        print_error_and_exit(error)

    encoded = json.dumps(packet, sort_keys=True, indent=2) + "\n"
    if json_file is not None:
        json_file.write_text(encoded, encoding="utf-8")
    if as_json:
        typer.echo(encoded, nl=False)
        return
    typer.echo(render_text(packet), nl=False)
