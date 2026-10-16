"""Bounded encryption and isolated verification commands for Platform recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from polysia.deployment.platform_recovery import (
    create_encrypted_backup,
    extract_and_verify_recovery,
)


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
    typer.echo(json.dumps(create_encrypted_backup(
        config, image_archive=image_archive, release_manifest=release_manifest,
        recipient=recipient, output=output,
    ), sort_keys=True))


def platform_restore_verify(
    archive: Annotated[Path, typer.Option("--archive", exists=True, dir_okay=False)],
    destination: Annotated[Path, typer.Option("--destination")],
    trusted_release_manifest: Annotated[
        Path, typer.Option("--trusted-release-manifest", exists=True, dir_okay=False),
    ],
) -> None:
    """Verify a decrypted archive into a new root, with acquisition disabled."""
    typer.echo(json.dumps(extract_and_verify_recovery(
        archive, destination, trusted_release_manifest=trusted_release_manifest,
    ), sort_keys=True))
