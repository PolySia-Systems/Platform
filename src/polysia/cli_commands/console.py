"""Start the private Console process with explicit Access configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from polysia.monitoring.console import AccessVerifier, ConsoleApplication
from polysia.storage.console_commands import ConsoleCommandStore


def serve_console(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Serve cached publications on loopback; missing identity configuration blocks startup."""
    from waitress import serve  # type: ignore[import-untyped]

    value: dict[str, Any] = json.loads(config.read_text(encoding="utf-8"))
    verifier = AccessVerifier(
        issuer=value["issuer"], audience=value["audience"], roles=value["roles"],
    )
    secret = Path(value["csrf_secret_file"]).read_bytes()
    store = ConsoleCommandStore(Path(value["commands"]))
    store.initialize()
    application = ConsoleApplication(Path(value["publication"]), origin=value["origin"],
                                     verify=verifier, commands=store, csrf_secret=secret)
    serve(application, host="127.0.0.1", port=int(value.get("port", 8765)), threads=2,
          connection_limit=20, channel_timeout=10, max_request_header_size=32_768,
          max_request_body_size=4096, expose_tracebacks=False, clear_untrusted_proxy_headers=True)
