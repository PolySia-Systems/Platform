"""Supervised bounded worker ticks and separately scheduled report publication."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from polysia.application.services.shadow_reporting import (
    ShadowReportingService,
    UnsupportedReportingWindow,
)
from polysia.cli_commands.platform_discovery import load_policy
from polysia.cli_support.native_research import native_shadow_service
from polysia.cli_support.wallet_intelligence_workflow import workflow_lock
from polysia.monitoring.platform_diagnostics import retained_diagnostics
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.continuous_shadow import ContinuousShadowRepository


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o640)
    temporary.replace(path)


def worker_tick(config: Path) -> dict[str, Any]:
    value = json.loads(config.read_text(encoding="utf-8"))
    database = Path(value["database"])
    with workflow_lock(database.with_suffix(".worker.lock")):
        code_sha = Path("/opt/polysia/BUILD_COMMIT").read_text().strip()
        if code_sha != value["release_commit"]:
            raise ValueError("installed_release_mismatch")
        policy = load_policy(Path(value["manifest"]))
        authority = AcquisitionAuthority(Path(value["authority"]), policy)
        authority.initialize()
        commands = ConsoleCommandStore(Path(value["commands"]))
        commands.initialize()
        prior = {}
        if Path(value["status"]).exists():
            prior = json.loads(Path(value["status"]).read_text())
        result: dict[str, Any] = {
            "status": "STOPPED",
            "dataset_role": value.get("dataset_role", "new_platform_epoch"),
            "release_commit": code_sha,
            "policy_digest": policy.digest,
            "last_attempt": datetime.now(UTC).isoformat(),
            "real_orders": False,
            "last_success": prior.get("last_success"),
        }
        # Consume command receipts before any acquisition. Effects are idempotent;
        # a crash before finishing a receipt safely repeats the same requested effect.
        for revision, action in commands.pending():
            if action == "stop":
                authority.stop()
            elif action == "resume":
                try:
                    authority.resume(now=datetime.now(UTC), host=socket.gethostname())
                except AcquisitionBlockedError:
                    commands.finish(revision, status="BLOCKED")
                    continue
            elif action == "drain":
                # Retain this receipt until the financial service is available.
                continue
            elif action == "export":
                # The independent report timer performs the bounded snapshot job.
                continue
            commands.finish(revision, status="APPLIED")
        if authority.status()["stopped"]:
            result["reason"] = "durable_authority_stop"
        elif value.get("acquisition_enabled") is not True:
            result["reason"] = "acquisition_not_enabled"
        elif not policy.starts_at <= datetime.now(UTC) < policy.expires_at:
            result.update(
                status="TERMINAL",
                reason="authority_expired",
                next_action="inspect final retained evidence; acquisition is disabled",
            )
        elif prior.get("retry_at") and datetime.fromisoformat(prior["retry_at"]) > datetime.now(
            UTC
        ):
            result.update(
                status="WAITING_RETRY",
                retry_at=prior["retry_at"],
                transient_failures=prior.get("transient_failures", 0),
                reason=prior.get("reason"),
            )
        else:
            if (
                os.getenv("TRADING_MODE", "DATA_ONLY") != "DATA_ONLY"
                or os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
            ):
                raise ValueError("research_runtime_safety_flags_invalid")
            discovery = json.loads(Path(value["cohort"]).read_text())["discovery"]
            if value["admission"].get("mode") != "CONTINUOUS":
                raise ValueError("continuous_admission_required")
            store = ContinuousShadowRepository(database)
            service = native_shadow_service(
                database,
                discovery,
                authority=authority,
                code_sha=code_sha,
                admission=value["admission"],
            )
            store.initialize()
            experiment = store.active_experiment("polymarket-native")
            if experiment is None:
                experiment = service.start("polymarket-native")
            if experiment.config.code_sha != code_sha:
                raise ValueError("active_financial_session_requires_pinned_release")
            for revision, action in commands.pending():
                if action == "drain":
                    experiment = service.drain("polymarket-native")
                    commands.finish(revision, status="APPLIED")
            if experiment.lifecycle.value == "DRAINING":
                service = native_shadow_service(
                    database,
                    discovery,
                    authority=authority,
                    code_sha=code_sha,
                    admission=value["admission"],
                    closure=True,
                )
            try:
                outcome = asyncio.run(service.poll("polymarket-native"))
                result.update(
                    status="OBSERVING",
                    experiment_id=outcome.experiment.experiment_id,
                    last_success=datetime.now(UTC).isoformat(),
                    health=store.health(
                        "polymarket-native",
                        now=datetime.now(UTC),
                        poll_interval_seconds=policy.cadence_seconds,
                    ).to_dict(),
                )
            except Exception as error:
                cause: BaseException | None = error
                reason = getattr(error, "error_code", type(error).__name__)
                provider_retry = 0
                while cause is not None:
                    if isinstance(cause, AcquisitionBlockedError):
                        reason = str(cause)
                        provider_retry = cause.retry_after_seconds or 0
                        break
                    cause = cause.__cause__
                result.update(
                    status="FAILED",
                    reason=reason,
                    next_action="inspect retained failure; do not expand limits",
                )
                if reason in {"request_budget_exhausted", "byte_budget_exhausted"}:
                    service.drain("polymarket-native")
                    result["status"] = "DRAINING"
                elif reason in {"request_window_exhausted", "byte_window_exhausted"}:
                    result.update(
                        status="WAITING_AUTHORIZATION_WINDOW",
                        retry_at=(
                            datetime.now(UTC) + timedelta(seconds=policy.window_seconds)
                        ).isoformat(),
                    )
                elif reason.startswith("provider_http_") and reason not in {
                    "provider_http_429",
                    "provider_http_500",
                    "provider_http_502",
                    "provider_http_503",
                    "provider_http_504",
                }:
                    authority.stop()
                    result["status"] = "BLOCKED"
                elif reason in {
                    "provider_transport_failed",
                    "provider_http_429",
                    "provider_http_500",
                    "provider_http_502",
                    "provider_http_503",
                    "provider_http_504",
                }:
                    failures = int(prior.get("transient_failures", 0)) + 1
                    result["transient_failures"] = failures
                    result["retry_at"] = (
                        datetime.now(UTC)
                        + timedelta(
                            seconds=max(provider_retry, 60 * 2 ** min(failures, 3)),
                        )
                    ).isoformat()
                    if failures >= 3:
                        authority.stop()
                        result["status"] = "BLOCKED"
                else:
                    authority.stop()
        result["authority"] = authority.status()
        atomic_json(Path(value["status"]), result)
        return result


def platform_tick(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Run one serialized acquisition/control tick under an existing numeric policy."""
    try:
        value = json.loads(config.read_text())
        status_path = Path(value["status"])
        result = worker_tick(config)
    except Exception as error:
        result = {
            "status": "FAILED",
            "reason": type(error).__name__,
            "last_attempt": datetime.now(UTC).isoformat(),
            "next_action": "inspect configuration or state; acquisition is blocked",
        }
        if "status_path" in locals():
            atomic_json(status_path, result)
    typer.echo(json.dumps({"status": result["status"], "reason": result.get("reason")}))
    if result["status"] == "FAILED":
        raise typer.Exit(1)


def platform_publish(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Publish from retained evidence; this command performs no provider reads."""
    value = json.loads(config.read_text(encoding="utf-8"))
    status_path = Path(value["publication"]).parent / "publisher-status.json"
    try:
        _publish_retained(value)
    except Exception as error:
        receipt = {
            "status": "FAILED",
            "reason": type(error).__name__,
            "checked_at": datetime.now(UTC).isoformat(),
            "next_action": "inspect report publisher; retained publication may be stale",
        }
        atomic_json(status_path, receipt)
        typer.echo(json.dumps(receipt, sort_keys=True))
        raise typer.Exit(1) from None
    atomic_json(status_path, {"status": "PUBLISHED", "checked_at": datetime.now(UTC).isoformat()})


def _publish_retained(value: dict[str, Any]) -> None:
    with workflow_lock(Path(value["publication"]).with_suffix(".publisher.lock")):
        result = json.loads(Path(value["status"]).read_text(encoding="utf-8"))
        now = datetime.now(UTC)
        result["published_at"] = now.isoformat()
        last_attempt = result.get("last_attempt")
        if last_attempt and (now - datetime.fromisoformat(last_attempt)).total_seconds() > 180:
            result.update(status="STALE_WORKER_RECEIPT", next_action="inspect worker journal")
        database = Path(value["database"])
        if database.exists():
            experiment = ContinuousShadowRepository(database).latest_experiment("polymarket-native")
            if experiment:
                reporting = ShadowReportingService(database)
                result["report"] = reporting.report(experiment.experiment_id)
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                cutoff = result["report"]["analytical"].get("source_poll_cutoff")
                try:
                    result["daily_report"] = reporting.report(
                        experiment.experiment_id,
                        start=midnight,
                        end=datetime.fromisoformat(cutoff) if cutoff else now,
                    )
                except UnsupportedReportingWindow as error:
                    result["daily_report"] = {"status": "UNSUPPORTED_RANGE", "reason": str(error)}
        cohort = Path(value["cohort"])
        result["diagnostic"] = (
            json.loads(cohort.read_text(encoding="utf-8"))
            if cohort.exists()
            else {"status": "UNAVAILABLE", "reason": "new_epoch_no_retained_cohort"}
        )
        result["diagnostics"] = retained_diagnostics(
            Path(value["authority"]),
            result["diagnostic"].get("discovery", {}),
        )
        atomic_json(Path(value["publication"]), result)
        commands = ConsoleCommandStore(Path(value["commands"]))
        commands.initialize()
        for revision, action in commands.pending():
            if action == "export":
                try:
                    if "report" not in result:
                        raise UnsupportedReportingWindow("no_retained_financial_session")
                    parameters = commands.parameters(revision)
                    report = ShadowReportingService(database).report(
                        result["report"]["analytical"]["experiment_id"],
                        start=datetime.fromisoformat(parameters["start"]) if parameters else None,
                        end=datetime.fromisoformat(parameters["end"]) if parameters else None,
                    )
                    archive = Path(value["publication"]).parent / "reports"
                    archive.mkdir(exist_ok=True)
                    target = archive / (report["analytical_digest"] + ".json")
                    if not target.exists():
                        if (
                            sum(path.stat().st_size for path in archive.glob("*.json"))
                            + len(json.dumps(report, sort_keys=True).encode())
                            > 33_554_432
                        ):
                            raise ValueError("report_archive_capacity_reached")
                        atomic_json(target, report)
                    commands.finish(
                        revision,
                        status="APPLIED",
                        result={
                            "analytical_digest": report["analytical_digest"],
                            "download": "/reports/" + target.name,
                        },
                    )
                except UnsupportedReportingWindow as error:
                    commands.finish(
                        revision,
                        status="BLOCKED",
                        result={
                            "reason": "UNSUPPORTED_RANGE",
                            "detail": str(error),
                        },
                    )
                except (OSError, ValueError, sqlite3.DatabaseError) as error:
                    commands.finish(
                        revision, status="FAILED", result={"reason": type(error).__name__}
                    )


def platform_stop(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Protected administrative STOP when Console/Cloudflare is unavailable."""
    value = json.loads(config.read_text(encoding="utf-8"))
    policy = load_policy(Path(value["manifest"]))
    authority = AcquisitionAuthority(Path(value["authority"]), policy)
    authority.initialize()
    authority.stop()  # STOP does not need fresh provider access or admission.
    commands = ConsoleCommandStore(Path(value["commands"]))
    commands.initialize()
    try:
        receipt = commands.submit(
            subject="protected-administrative-route",
            action="stop",
            expected_revision=int(str(commands.status()["revision"])),
            idempotency_key=str(uuid.uuid4()),
        )
        commands.finish(int(str(receipt["revision"])), status="APPLIED")
    except ValueError:
        # A racing queue revision cannot undo the durable authority STOP.
        receipt = {"status": "STOP_APPLIED_RECEIPT_REVISION_RACED"}
    typer.echo(
        json.dumps(
            {"status": "STOPPED", "authority": authority.status(), "receipt": receipt},
            sort_keys=True,
        )
    )
