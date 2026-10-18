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

from polysia.application.ports.wallet_intelligence_research import ResearchPublicationError
from polysia.application.services.report_integrity import (
    MAX_REPORT_ARCHIVE_BYTES,
    MAX_REPORT_BYTES,
    verify_analytical_digest,
)
from polysia.application.services.shadow_reporting import (
    ShadowReportingService,
    UnsupportedReportingWindow,
)
from polysia.cli_commands.platform_discovery import load_policy
from polysia.cli_support.native_lifecycle import native_lifecycle_poll
from polysia.cli_support.wallet_intelligence_workflow import workflow_lock
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowLifecycle
from polysia.monitoring.platform_diagnostics import retained_diagnostics
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.continuous_shadow import ContinuousShadowRepository


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as output:
        output.write(json.dumps(payload, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    if os.name != "nt":
        temporary.chmod(0o640)
    temporary.replace(path)
    if os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def worker_tick(config: Path) -> dict[str, Any]:
    value = json.loads(config.read_text(encoding="utf-8"))
    database = Path(value["database"])
    with workflow_lock(database.with_suffix(".worker.lock")):
        code_sha = Path("/opt/polysia/BUILD_COMMIT").read_text().strip()
        if code_sha != value["release_commit"]:
            raise AcquisitionBlockedError("installed_release_mismatch")
        if value.get("installation_state") == "UNCONFIGURED":
            if value.get("acquisition_enabled") is not False or value.get("admission"):
                raise AcquisitionBlockedError("unconfigured_installation_cannot_acquire")
            commands = ConsoleCommandStore(Path(value["commands"]))
            commands.initialize()
            commands.block_superseded_resumes()
            for revision, action in commands.pending(actions=("stop", "resume", "drain")):
                commands.finish(
                    revision, status="APPLIED" if action == "stop" else "BLOCKED",
                    result={"reason": "no_acquisition_authority"},
                )
            setup_result = {
                "status": "UNCONFIGURED", "release_commit": code_sha,
                "last_attempt": datetime.now(UTC).isoformat(), "real_orders": False,
                "acquisition_enabled": False, "reason": "no_acquisition_authority",
                "next_action": "Read retained evidence or use the separate fixture demo. "
                               "Observation requires separately approved authority and admission.",
            }
            atomic_json(Path(value["status"]), setup_result)
            return setup_result
        policy = load_policy(Path(value["manifest"]))
        authority = AcquisitionAuthority(Path(value["authority"]), policy)
        authority.initialize()
        recovery_fenced = value.get("recovery_requires_authority_reconciliation") is True
        if recovery_fenced:
            authority.stop()
        commands = ConsoleCommandStore(Path(value["commands"]))
        commands.initialize()
        commands.block_superseded_resumes()
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
            "authority_window": {
                "starts_at": policy.starts_at.isoformat(),
                "expires_at": policy.expires_at.isoformat(),
                "maximum_requests": policy.maximum_requests,
                "maximum_bytes": policy.maximum_bytes,
            },
            "last_success": prior.get("last_success"),
            "last_poll_started_at": prior.get("last_poll_started_at"),
            "next_due_at": prior.get("next_due_at"),
            "retry_at": prior.get("retry_at"),
            "transient_failures": prior.get("transient_failures", 0),
        }
        # Consume command receipts before any acquisition. Effects are idempotent;
        # a crash before finishing a receipt safely repeats the same requested effect.
        for revision, action in commands.pending(actions=("stop", "resume", "drain")):
            if action == "stop":
                authority.stop()
            elif action == "resume":
                blocker = (
                    "recovery_authority_reconciliation_required" if recovery_fenced else
                    "authority_not_current"
                    if not policy.starts_at <= datetime.now(UTC) < policy.expires_at else
                    "acquisition_not_enabled" if value.get("acquisition_enabled") is not True else
                    "continuous_admission_required"
                    if value.get("admission", {}).get("mode") != "CONTINUOUS" else None
                )
                if blocker:
                    commands.finish(
                        revision,
                        status="BLOCKED",
                        result={"reason": blocker},
                    )
                    continue
                try:
                    authority.resume(now=datetime.now(UTC), host=socket.gethostname())
                except AcquisitionBlockedError as error:
                    commands.finish(revision, status="BLOCKED", result={"reason": error.error_code})
                    continue
            elif action == "drain":
                try:
                    store = ContinuousShadowRepository(database)
                    active = (
                        store.active_experiment("polymarket-native") if database.exists() else None
                    )
                    if active is None:
                        commands.finish(revision, status="BLOCKED",
                                        result={"reason": "no_active_financial_session"})
                        continue
                    store.transition(active.experiment_id,
                                     lifecycle=ContinuousShadowLifecycle.DRAINING,
                                     transitioned_at=datetime.now(UTC))
                except (OSError, ValueError, sqlite3.DatabaseError) as error:
                    commands.finish(revision, status="FAILED",
                                    result={"reason": type(error).__name__})
                    continue
            commands.finish(revision, status="APPLIED")
        if authority.status()["stopped"]:
            result["reason"] = (
                "recovery_authority_reconciliation_required"
                if recovery_fenced
                else "durable_authority_stop"
            )
            result["next_action"] = (
                "Reconcile the latest authority and fence the old primary before resuming."
                if recovery_fenced
                else "Review evidence; resume needs valid authority and admission."
            )
        elif value.get("acquisition_enabled") is not True:
            result.update(
                reason="acquisition_not_enabled",
                next_action="Disabled; review policy and nonempty admission.",
            )
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
        elif prior.get("last_poll_started_at") and datetime.fromisoformat(
            prior["last_poll_started_at"]
        ) > datetime.now(UTC):
            authority.stop()
            result.update(status="BLOCKED", reason="worker_clock_regressed",
                          next_action="Inspect the UTC clock; preserve counters before resume.")
        elif prior.get("next_due_at") and datetime.fromisoformat(
            prior["next_due_at"]
        ) > datetime.now(UTC):
            result.update(status="WAITING_CADENCE", reason="scheduled_poll_not_due",
                          next_due_at=prior["next_due_at"],
                          last_poll_started_at=prior.get("last_poll_started_at"))
        else:
            if (
                os.getenv("TRADING_MODE", "DATA_ONLY") != "DATA_ONLY"
                or os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
            ):
                raise AcquisitionBlockedError("research_runtime_safety_flags_invalid")
            # Persist before any source/preparation I/O. A crash consumes this due
            # slot rather than allowing a restart to poll again immediately.
            started = datetime.now(UTC)
            result.update(status="POLL_IN_PROGRESS", last_poll_started_at=started.isoformat(),
                          next_due_at=(started + timedelta(
                              seconds=policy.cadence_seconds)).isoformat())
            atomic_json(Path(value["status"]), result)
            discovery = json.loads(Path(value["cohort"]).read_text())["discovery"]
            if value["admission"].get("mode") != "CONTINUOUS":
                raise AcquisitionBlockedError("continuous_admission_required")
            store = ContinuousShadowRepository(database)
            try:
                outcome = asyncio.run(native_lifecycle_poll(
                    database, discovery, authority=authority, code_sha=code_sha,
                    admission=value["admission"],
                    refresh_path=Path(value.get("cohort_refresh", str(
                        Path(value["authority"]).with_name("cohort-revalidation.json")))),
                    clock=lambda: datetime.now(UTC),
                ))
                result.update(
                    status="OBSERVING",
                    experiment_id=outcome.experiment.experiment_id,
                    last_success=datetime.now(UTC).isoformat(),
                    retry_at=None,
                    transient_failures=0,
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
                    active = store.active_experiment("polymarket-native")
                    if active is not None:
                        store.transition(active.experiment_id,
                                         lifecycle=ContinuousShadowLifecycle.DRAINING,
                                         transitioned_at=datetime.now(UTC))
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
                elif reason in {
                    "native_cohort_revalidation_insufficient",
                    "native_cohort_revalidation_incomplete",
                }:
                    failures = int(prior.get("transient_failures", 0)) + 1
                    result.update(status="WAITING_SOURCE_EVIDENCE", transient_failures=failures,
                                  retry_at=result["next_due_at"],
                                  next_action="Await complete fresh evidence for this cohort.")
                    if failures >= 3:
                        authority.stop()
                        result["status"] = "BLOCKED"
                else:
                    authority.stop()
                    if reason.startswith("native_") or reason == "authority_not_current":
                        result["status"] = "BLOCKED"
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
        if isinstance(error, ResearchPublicationError) and str(error) == "workflow_already_running":
            # The owning process holds the durable due slot. Do not overwrite
            # its receipt or turn a normal overlap into a failed worker state.
            typer.echo(json.dumps({"status": "WAITING_WORKER",
                                   "reason": "workflow_already_running"}))
            return
        result = {
            "status": "FAILED",
            "reason": getattr(error, "error_code", type(error).__name__),
            "last_attempt": datetime.now(UTC).isoformat(),
            "next_action": "inspect configuration or state; acquisition is blocked",
        }
        if "status_path" in locals():
            try:
                checkpoint = json.loads(status_path.read_text(encoding="utf-8"))
                for field in ("last_poll_started_at", "next_due_at", "last_success"):
                    result[field] = checkpoint.get(field)
            except (OSError, ValueError):
                pass  # No durable timing checkpoint exists to preserve.
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
        result["backup_health"] = {}
        for role in ("backup", "restore"):
            receipt_file = Path(value["publication"]).parent / (role + "-status.json")
            try:
                if receipt_file.stat().st_size > 4096:
                    raise ValueError("job_receipt_too_large")
                receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
                checked = receipt.get("checked_at", receipt.get("created_at"))
                if checked and (now - datetime.fromisoformat(checked)).total_seconds() > 86_400:
                    receipt = {
                        **receipt,
                        "status": "STALE",
                        "next_action": "inspect " + role + " job",
                    }
            except OSError, ValueError:
                receipt = (
                    {"status": "UNPROTECTED", "next_action": "Choose and verify backup protection "
                     "through the protected administrative entry."}
                    if value.get("backup_mode") == "none"
                    else {"status": "UNKNOWN", "next_action": "inspect " + role + " job"}
                )
            result["backup_health"][role] = receipt
            if receipt.get("status") in {
                "FAILED",
                "UNKNOWN",
                "STALE",
                "RECOVERY_OBJECTIVES_NOT_MET",
                "UNPROTECTED",
            }:
                result.setdefault("alerts", []).append(role + " health: " + receipt["status"])
        atomic_json(Path(value["publication"]), result)
        commands = ConsoleCommandStore(Path(value["commands"]))
        commands.initialize()
        for revision, action in commands.pending(actions=("export",)):
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
                    size = len(json.dumps(report, sort_keys=True).encode()) + 1
                    if size > MAX_REPORT_BYTES:
                        raise ValueError("report_file_size_limit")
                    if not target.exists():
                        if (
                            sum(path.stat().st_size for path in archive.glob("*.json"))
                            + size > MAX_REPORT_ARCHIVE_BYTES
                        ):
                            raise ValueError("report_archive_capacity_reached")
                        atomic_json(target, report)
                    else:
                        verify_analytical_digest(json.loads(target.read_text(encoding="utf-8")))
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
