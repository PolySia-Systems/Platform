"""Start the private Console process with explicit Access configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from polysia.deployment.gateway import console_identity
from polysia.monitoring.console import ConsoleApplication
from polysia.storage.console_commands import ConsoleCommandStore


def serve_console(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Serve cached publications on loopback; missing identity configuration blocks startup."""
    from waitress import serve  # type: ignore[import-untyped]

    value: dict[str, Any] = json.loads(config.read_text(encoding="utf-8"))
    try:
        verifier, identity_header, listener = console_identity(value)
    except (ValueError, OSError) as error:
        # One bounded line survives the service's deliberate journal rate limit.
        typer.echo("console_identity_invalid: " + str(error)[:500], err=True)
        raise typer.Exit(1) from None
    secret = Path(value["csrf_secret_file"]).read_bytes()
    store = ConsoleCommandStore(Path(value["commands"]))
    # The supervised first-install worker creates the queue. A browser process
    # must never replace a lost queue or restart its durable receipt identities.
    application = ConsoleApplication(Path(value["publication"]), origin=value["origin"],
                                     verify=verifier, commands=store, csrf_secret=secret,
                                     identity_header=identity_header,
                                     scoped_targets=frozenset(value.get("scoped_targets", ())))
    serve(application, **listener, threads=2,
          connection_limit=20, channel_timeout=10, max_request_header_size=32_768,
          max_request_body_size=4096, expose_tracebacks=False, clear_untrusted_proxy_headers=True)
