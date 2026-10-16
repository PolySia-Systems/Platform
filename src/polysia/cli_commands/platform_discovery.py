"""New Platform-only bounded diagnostics; never invokes the WI application."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from polysia.adapters.polycop.candidate_wallet_source import PolyCopCandidateWalletSource
from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.native_discovery import discover_native_activity
from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError


def load_policy(path: Path) -> AcquisitionPolicy:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["starts_at"] = datetime.fromisoformat(payload["starts_at"])
    payload["expires_at"] = datetime.fromisoformat(payload["expires_at"])
    payload["endpoints"] = tuple(payload["endpoints"])
    return AcquisitionPolicy(**payload)


class _PolyCopTransport:
    def __init__(self, transport: BoundedPublicTransport) -> None:
        self._transport = transport

    async def get_json(self, path: str, params: Mapping[str, str | int]) -> Any:
        return await self._transport.get_json("https://polycop.fun", path, params)


def discovery_diagnostic(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, dir_okay=False)],
    state: Annotated[Path, typer.Option("--state")],
    output: Annotated[Path, typer.Option("--output")],
    route: Annotated[str, typer.Option("--route")] = "native",
    lookback_seconds: Annotated[int, typer.Option("--lookback-seconds", min=1, max=3600)] = 60,
) -> None:
    """Complete one charged diagnostic and atomically publish its receipt."""
    if route not in {"native", "polycop"}:
        raise typer.BadParameter("route must be native or polycop")
    policy = load_policy(manifest)
    authority = AcquisitionAuthority(state, policy)
    authority.initialize()
    transport = BoundedPublicTransport(authority)
    cutoff = datetime.now(UTC).replace(microsecond=0)

    async def run() -> dict[str, Any]:
        if route == "native":
            return await discover_native_activity(
                transport, cutoff=cutoff, cohort_limit=policy.cohort_limit,
                lookback=timedelta(seconds=lookback_seconds),
            )
        dataset = await PolyCopCandidateWalletSource(
            transport=_PolyCopTransport(transport), consistency_attempts=1,
        ).fetch_snapshot()
        return {
            "source": dataset.source_id, "schema_version": dataset.schema_version,
            "dataset_digest": dataset.dataset_digest,
            "source_total_pages": dataset.source_total_pages,
            "records": len(dataset.records), "cutoff": dataset.fetched_at.isoformat(),
            "policy": "polycop-discovery/v1",
        }

    result: dict[str, Any] = {
        "schema_version": "platform-discovery-diagnostic/v1", "route": route,
        "policy_digest": policy.digest, "started_at": cutoff.isoformat(),
        "status": "FAILED", "real_orders": False,
    }
    try:
        result["discovery"] = asyncio.run(run())
        result["status"] = "COMPLETE"
    except Exception as error:
        # Boundary catch intentionally preserves a terminal receipt and charged
        # authority for every failure; no exception is reported as insufficiency.
        result["reason"] = type(error).__name__
        result["error_code"] = (
            str(error) if isinstance(error, AcquisitionBlockedError)
            else getattr(error, "error_code", "diagnostic_failed")
        )
        result["next_action"] = "inspect retained diagnostic; do not repeat unchanged workload"
    result["authority"] = authority.status()
    result["completed_at"] = datetime.now(UTC).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(output)
    typer.echo(json.dumps({
        key: result[key] for key in ("status", "policy_digest", "authority")
    }, sort_keys=True))
    if result["status"] != "COMPLETE":
        raise typer.Exit(1)
