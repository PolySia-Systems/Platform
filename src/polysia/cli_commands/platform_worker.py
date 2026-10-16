"""Supervised bounded worker ticks and separately scheduled report publication."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from polysia.application.services.shadow_reporting import ShadowReportingService
from polysia.cli_commands.platform_discovery import load_policy
from polysia.cli_support.native_research import native_shadow_service
from polysia.cli_support.wallet_intelligence_workflow import workflow_lock
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
            "status": "STOPPED", "release_commit": code_sha,
            "policy_digest": policy.digest, "last_attempt": datetime.now(UTC).isoformat(),
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
            result.update(status="TERMINAL", reason="authority_expired",
                          next_action="inspect final retained evidence; acquisition is disabled")
        elif (prior.get("retry_at")
              and datetime.fromisoformat(prior["retry_at"]) > datetime.now(UTC)):
            result.update(status="WAITING_RETRY", retry_at=prior["retry_at"],
                          transient_failures=prior.get("transient_failures", 0),
                          reason=prior.get("reason"))
        else:
            if (os.getenv("TRADING_MODE", "DATA_ONLY") != "DATA_ONLY"
                    or os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"):
                raise ValueError("research_runtime_safety_flags_invalid")
            discovery = json.loads(Path(value["cohort"]).read_text())["discovery"]
            store = ContinuousShadowRepository(database)
            service = native_shadow_service(
                database, discovery, authority=authority, code_sha=code_sha,
                admission=value["admission"],
            )
            store.initialize()
            experiment = store.active_experiment("polymarket-native")
            if experiment is None:
                experiment = service.start("polymarket-native")
            for revision, action in commands.pending():
                if action == "drain":
                    experiment = service.drain("polymarket-native")
                    commands.finish(revision, status="APPLIED")
            if experiment.lifecycle.value == "DRAINING":
                service = native_shadow_service(
                    database, discovery, authority=authority, code_sha=code_sha,
                    admission=value["admission"], closure=True,
                )
            try:
                outcome = asyncio.run(service.poll("polymarket-native"))
                result.update(status="OBSERVING", experiment_id=outcome.experiment.experiment_id,
                              last_success=datetime.now(UTC).isoformat(),
                              health=store.health("polymarket-native", now=datetime.now(UTC),
                                                  poll_interval_seconds=policy.cadence_seconds
                                                  ).to_dict())
            except Exception as error:
                cause: BaseException | None = error
                reason = getattr(error, "error_code", type(error).__name__)
                while cause is not None:
                    if isinstance(cause, AcquisitionBlockedError):
                        reason = str(cause)
                        break
                    cause = cause.__cause__
                result.update(
                    status="FAILED", reason=reason,
                    next_action="inspect retained failure; do not expand limits",
                )
                if reason in {"request_budget_exhausted", "byte_budget_exhausted"}:
                    service.drain("polymarket-native")
                    result["status"] = "DRAINING"
                elif reason.startswith("provider_http_") and reason not in {
                    "provider_http_429", "provider_http_500", "provider_http_502",
                    "provider_http_503", "provider_http_504",
                }:
                    authority.stop()
                    result["status"] = "BLOCKED"
                elif reason in {"provider_transport_failed", "provider_http_429",
                                "provider_http_500", "provider_http_502",
                                "provider_http_503", "provider_http_504"}:
                    failures = int(prior.get("transient_failures", 0)) + 1
                    result["transient_failures"] = failures
                    result["retry_at"] = (
                        datetime.now(UTC) + timedelta(seconds=60 * 2**min(failures, 3))
                    ).isoformat()
                    if failures >= 3:
                        authority.stop()
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
        result = {"status": "FAILED", "reason": type(error).__name__,
                  "last_attempt": datetime.now(UTC).isoformat(),
                  "next_action": "inspect configuration or state; acquisition is blocked"}
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
    with workflow_lock(Path(value["publication"]).with_suffix(".publisher.lock")):
        result = json.loads(Path(value["status"]).read_text(encoding="utf-8"))
        result["published_at"] = datetime.now(UTC).isoformat()
        database = Path(value["database"])
        if database.exists():
            experiment = ContinuousShadowRepository(database).latest_experiment("polymarket-native")
            if experiment:
                result["report"] = ShadowReportingService(database).report(experiment.experiment_id)
        cohort = Path(value["cohort"])
        result["diagnostic"] = (
            json.loads(cohort.read_text(encoding="utf-8")) if cohort.exists()
            else {"status": "UNAVAILABLE", "reason": "new_epoch_no_retained_cohort"}
        )
        atomic_json(Path(value["publication"]), result)
        commands = ConsoleCommandStore(Path(value["commands"]))
        commands.initialize()
        for revision, action in commands.pending():
            if action == "export":
                commands.finish(revision, status="APPLIED")
