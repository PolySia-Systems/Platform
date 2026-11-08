"""Bounded encryption and isolated verification commands for Platform recovery."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from polysia.deployment.platform_recovery import (
    RecoveryDiagnostic,
    create_encrypted_backup,
    extract_and_verify_recovery,
)


def _fail(diagnostic: RecoveryDiagnostic, error: Exception) -> None:
    code = (
        "TIMEOUT" if isinstance(error, (TimeoutError, subprocess.TimeoutExpired))
        else "PROCESS_FAILED" if isinstance(error, subprocess.CalledProcessError)
        else "DATABASE_ERROR" if isinstance(error, sqlite3.Error)
        else "INVALID_EVIDENCE" if isinstance(error, (ValueError, KeyError, TypeError))
        else "IO_ERROR" if isinstance(error, OSError)
        else "UNEXPECTED_ERROR"
    )
    typer.echo(json.dumps({
        "contract": "platform-recovery-diagnostic/v1",
        "stage": diagnostic.stage,
        "error_code": code,
    }, sort_keys=True), err=True)
    raise typer.Exit(1) from None


def platform_backup(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
    image_archive: Annotated[Path, typer.Option("--image-archive", exists=True, dir_okay=False)],
    release_manifest: Annotated[
        Path, typer.Option("--release-manifest", exists=True, dir_okay=False),
    ],
    recipient: Annotated[str, typer.Option("--recipient")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Encrypt snapshots using only the public recovery recipient."""
    diagnostic = RecoveryDiagnostic()
    try:
        result = create_encrypted_backup(
            config, image_archive=image_archive, release_manifest=release_manifest,
            recipient=recipient, output=output, diagnostic=diagnostic,
        )
    except Exception as error:
        _fail(diagnostic, error)
    else:
        typer.echo(json.dumps(result, sort_keys=True))


def platform_restore_verify(
    archive: Annotated[Path, typer.Option("--archive", exists=True, dir_okay=False)],
    destination: Annotated[Path, typer.Option("--destination")],
    trusted_release_manifest: Annotated[
        Path, typer.Option("--trusted-release-manifest", exists=True, dir_okay=False),
    ],
) -> None:
    """Verify a decrypted archive into a new root, with acquisition disabled."""
    diagnostic = RecoveryDiagnostic()
    try:
        result = extract_and_verify_recovery(
            archive, destination, trusted_release_manifest=trusted_release_manifest,
            diagnostic=diagnostic,
        )
    except Exception as error:
        _fail(diagnostic, error)
    else:
        typer.echo(json.dumps(result, sort_keys=True))
