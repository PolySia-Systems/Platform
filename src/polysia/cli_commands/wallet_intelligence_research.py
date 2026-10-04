from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from polysia.adapters.wallet_intelligence import WalletIntelligenceArtifactSource
from polysia.application.ports.wallet_intelligence_research import ResearchPublicationError
from polysia.application.services.wallet_intelligence_research import (
    WalletIntelligenceResearchService,
)
from polysia.cli_support.wallet_intelligence_research import report_payload, write_report


def intake(
    artifact: Annotated[
        Path, typer.Option("--artifact", help="wallet-intelligence/v1 JSON artifact")
    ],
    output: Annotated[
        Path | None, typer.Option("--output", help="Atomic local research report")
    ] = None,
    allow_partial: Annotated[bool, typer.Option("--allow-partial")] = False,
    require_copyability: Annotated[bool, typer.Option("--require-copyability")] = False,
    include_identities: Annotated[
        bool,
        typer.Option(
            "--include-identities",
            help="Include protected account identities in this local report",
        ),
    ] = False,
) -> None:
    """Intake a local Wallet Intelligence publication for descriptive research."""
    try:
        if output is not None and output.resolve() == artifact.resolve():
            raise ResearchPublicationError("output_would_overwrite_source")
        required = (
            ("descriptive_screening", "copyability")
            if require_copyability
            else ("descriptive_screening",)
        )
        report = WalletIntelligenceResearchService(
            WalletIntelligenceArtifactSource(artifact)
        ).intake(
            allow_partial=allow_partial,
            required_capabilities=required,
        )
        payload = report_payload(report, include_identities=include_identities)
        if output is not None and report.status != "REJECTED":
            write_report(output, payload)
    except (ResearchPublicationError, OSError) as exc:
        code = exc.code if isinstance(exc, ResearchPublicationError) else "report_write_failed"
        typer.echo(json.dumps({"status": "REJECTED", "error_code": code}), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    if report.status == "REJECTED":
        raise typer.Exit(code=2)
