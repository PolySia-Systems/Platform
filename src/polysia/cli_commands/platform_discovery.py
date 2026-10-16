"""New Platform-only bounded diagnostics; never invokes the WI application."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from polysia.adapters.polycop.candidate_wallet_source import PolyCopCandidateWalletSource
from polysia.adapters.polymarket.bounded_market import BoundedMarketAdapter
from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.data_api_v2 import IncompleteWalletWindowError
from polysia.adapters.polymarket.native_discovery import discover_native_activity
from polysia.application.services.shadow_reporting import ShadowReportingService
from polysia.cli_support.native_research import native_shadow_service
from polysia.cli_support.wallet_intelligence_workflow import workflow_lock
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
    shadow_cycles: Annotated[int, typer.Option("--shadow-cycles", min=0, max=3)] = 0,
) -> None:
    """Complete one charged diagnostic and atomically publish its receipt."""
    with workflow_lock(state.with_suffix(".diagnostic.lock")):
        if output.exists() or (
            shadow_cycles and (output.parent / "isolated-shadow.sqlite3").exists()
        ):
            raise typer.BadParameter("diagnostic output must be a new isolated root")
        _execute_diagnostic(manifest, state, output, route, lookback_seconds, shadow_cycles)


class NoEligibleEvidence(ValueError):
    """Source receipt establishes insufficiency; no simulation is invented."""


def _execute_diagnostic(
    manifest: Path,
    state: Path,
    output: Path,
    route: str,
    lookback_seconds: int,
    shadow_cycles: int,
) -> None:
    if route not in {"native", "polycop"}:
        raise typer.BadParameter("route must be native or polycop")
    policy = load_policy(manifest)
    authority = AcquisitionAuthority(state, policy)
    authority.initialize()
    transport = BoundedPublicTransport(authority)
    cutoff = datetime.now(UTC).replace(microsecond=0)

    async def run() -> dict[str, Any]:
        if route == "native":
            discovered = await discover_native_activity(
                transport,
                cutoff=cutoff,
                cohort_limit=policy.cohort_limit,
                lookback=timedelta(seconds=lookback_seconds),
            )
            market_adapter = BoundedMarketAdapter(transport)
            for candidate in discovered["candidates"]:
                condition, token = candidate["market_reference"], candidate["outcome_reference"]
                if not isinstance(condition, str) or not isinstance(token, str):
                    candidate["execution_eligibility"] = "UNKNOWN_MISSING_MARKET_TOKEN"
                    continue
                try:
                    market = await market_adapter.get_market_by_condition_id(condition)
                    book = await market_adapter.get_order_book(token)
                    mapped = any(outcome.token_id == token for outcome in market.outcomes)
                    fee = market.fee_schedule
                    fee_known = fee is not None and (
                        fee.enabled is False or fee.rate is not None and fee.exponent is not None
                    )
                    current = book.timestamp is not None and (
                        0 <= (datetime.now(UTC) - book.timestamp).total_seconds() <= 30
                    )
                    candidate["execution_eligibility"] = (
                        "ELIGIBLE_FOR_RESEARCH"
                        if mapped
                        and fee_known
                        and current
                        and book.asks
                        and book.bids
                        and market.active
                        and not market.closed
                        else "UNKNOWN_MAPPING_FEE_BOOK_OR_MARKET_STATE"
                    )
                    candidate["mapping_verified"] = mapped
                    candidate["fee_known"] = fee_known
                    candidate["book_current"] = current
                    candidate["exclusions"] = [
                        reason
                        for passed, reason in (
                            (mapped, "market_token_mapping_unverified"),
                            (fee_known, "fee_evidence_missing"),
                            (current, "book_stale_or_timestamp_missing"),
                            (bool(book.asks and book.bids), "executable_depth_missing"),
                            (market.active and not market.closed, "market_not_active"),
                        )
                        if not passed
                    ]
                except ValueError:
                    candidate["execution_eligibility"] = "INVALID_MARKET_OR_BOOK_SCHEMA"
            discovered["frozen_at"] = datetime.now(UTC).isoformat()
            # Rebind the publication identity after all execution eligibility evidence.
            import hashlib

            discovered.pop("digest", None)
            discovered["digest"] = hashlib.sha256(
                json.dumps(
                    discovered,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            return discovered
        dataset = await PolyCopCandidateWalletSource(
            transport=_PolyCopTransport(transport),
            consistency_attempts=1,
        ).fetch_snapshot()
        return {
            "source": dataset.source_id,
            "schema_version": dataset.schema_version,
            "dataset_digest": dataset.dataset_digest,
            "source_total_pages": dataset.source_total_pages,
            "records": len(dataset.records),
            "cutoff": dataset.fetched_at.isoformat(),
            "policy": "polycop-discovery/v1",
        }

    result: dict[str, Any] = {
        "schema_version": "platform-discovery-diagnostic/v1",
        "route": route,
        "policy_digest": policy.digest,
        "started_at": cutoff.isoformat(),
        "status": "FAILED",
        "real_orders": False,
    }
    database: Path | None = None
    experiment_id: str | None = None
    try:
        result["discovery"] = asyncio.run(run())
        if route == "native" and not any(
            row.get("execution_eligibility") == "ELIGIBLE_FOR_RESEARCH"
            for row in result["discovery"]["candidates"]
        ):
            result["status"] = result["discovery"]["source_condition"]
            if result["status"] == "SAMPLED":
                result["status"] = "INSUFFICIENT_ELIGIBLE_EVIDENCE"
            raise NoEligibleEvidence("no_eligible_native_cohort")
        if route == "native" and shadow_cycles:
            code_sha = Path("/opt/polysia/BUILD_COMMIT").read_text().strip()
            discovery = result["discovery"]
            database = output.parent / "isolated-shadow.sqlite3"
            if database.exists():
                raise ValueError("diagnostic financial root already exists")
            service = native_shadow_service(
                database,
                discovery,
                authority=authority,
                code_sha=code_sha,
                admission={
                    "contract": "native-research-admission/v1",
                    "code_sha": code_sha,
                    "cohort_digest": discovery["digest"],
                    "mode": "ISOLATED_DIAGNOSTIC",
                },
            )
            experiment = service.start("polymarket-native")
            experiment_id = experiment.experiment_id
            simulations = 0
            for _ in range(shadow_cycles):
                time.sleep(policy.cadence_seconds)
                outcome = asyncio.run(service.poll("polymarket-native"))
                simulations += outcome.simulated_count
            service.drain("polymarket-native")
            result["shadow"] = {
                "experiment_id": experiment.experiment_id,
                "persisted_simulations": simulations,
                "report": ShadowReportingService(database).report(experiment.experiment_id),
                "admission": "NONEMPTY" if simulations else "INSUFFICIENT_NONEMPTY_EVIDENCE",
            }
        result["status"] = "COMPLETE"
    except Exception as error:
        # Boundary catch intentionally preserves a terminal receipt and charged
        # authority for every failure; no exception is reported as insufficiency.
        result["reason"] = type(error).__name__
        cause: BaseException | None = error
        while cause is not None:
            if isinstance(cause, AcquisitionBlockedError | IncompleteWalletWindowError):
                result["root_error_code"] = str(cause)
                break
            cause = cause.__cause__
        result["error_code"] = (
            str(error)
            if isinstance(error, AcquisitionBlockedError | IncompleteWalletWindowError)
            else getattr(error, "error_code", "diagnostic_failed")
        )
        result["next_action"] = "inspect retained diagnostic; do not repeat unchanged workload"
        if database is not None and database.exists() and experiment_id is not None:
            try:
                result["partial_shadow_report"] = ShadowReportingService(database).report(
                    experiment_id
                )
            except Exception as report_error:
                result["partial_shadow_report"] = {
                    "status": "UNAVAILABLE_INTEGRITY_REVIEW_REQUIRED",
                    "error_type": type(report_error).__name__,
                }
    result["authority"] = authority.status()
    result["completed_at"] = datetime.now(UTC).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(output)
    typer.echo(
        json.dumps(
            {key: result[key] for key in ("status", "policy_digest", "authority")}, sort_keys=True
        )
    )
    if result["status"] != "COMPLETE":
        raise typer.Exit(1)


def continue_acquisition_policy(
    previous_manifest: Annotated[Path, typer.Option("--previous-manifest", exists=True)],
    next_manifest: Annotated[Path, typer.Option("--next-manifest", exists=True)],
    state: Annotated[Path, typer.Option("--state", exists=True)],
    authorization_reference: Annotated[str, typer.Option("--authorization-reference")],
    apply: Annotated[bool, typer.Option("--apply")] = False,
) -> None:
    """Explicit owner-directed continuation; never raises caps or erases charges."""
    old, new = load_policy(previous_manifest), load_policy(next_manifest)
    authority = AcquisitionAuthority(state, old)
    before = authority.status()
    if not apply:
        typer.echo(
            json.dumps(
                {
                    "status": "PREVIEW",
                    "before": before,
                    "replacement_digest": new.digest,
                    "replacement": new.to_dict(),
                },
                sort_keys=True,
            )
        )
        return
    updated = authority.transition_policy(new, authorization_reference=authorization_reference)
    typer.echo(
        json.dumps(
            {"status": "APPLIED", "before": before, "after": updated.status()}, sort_keys=True
        )
    )
