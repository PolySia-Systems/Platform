"""Shared composition helpers for PolySia CLI command modules."""

from __future__ import annotations

import json

import typer


def print_error_and_exit(error: Exception) -> None:
    """Render a safe CLI error payload and exit with status one."""
    error_payload = {
        "message": str(error),
        "status": "error",
    }
    typer.echo(json.dumps(error_payload, sort_keys=True), err=True)
    raise typer.Exit(code=1) from error


__all__ = ["print_error_and_exit"]
