"""Local explicit operational entry points; no authority issuer or browser provisioning."""

from __future__ import annotations

import asyncio
import base64
import time
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from pydantic import TypeAdapter

from polysia.application.services.follower_qualification import produce_qualification
from polysia.backtesting.shadow_policy_lab import ShadowFrame, compare_policy_stream
from polysia.config.settings import TradingMode
from polysia.control.service import ControlService
from polysia.deployment.financial_recovery import prepare_recovery
from polysia.deployment.financial_session_runtime import (
    SessionRuntimeConfig,
    binding_for,
    compose_session,
    inspect_configuration,
    load_authority,
    load_runtime_config,
    provision_session,
    publish_redacted,
    read_small_json,
    validate_runtime_binding,
)
from polysia.deployment.session_account_qualification import qualify_account
from polysia.deployment.session_supervision import (
    CheckpointPublisher,
    SessionSupervisor,
    SupervisionPolicy,
)
from polysia.deployment.shadow_lab import ShadowLabConfiguration, load_shadow_lab
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.copytrading.copy_policy import CopyPolicy
from polysia.domain.financial_session import (
    InstrumentScope,
    SessionAuthorization,
    SessionBlocked,
    canonical_json,
)
from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy
from polysia.monitoring.session_incidents import SessionIncidents
from polysia.security.session_authority import SessionCustody, SessionReceiptVerifier
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.financial_session import FinancialSessionJournal
from polysia.storage.follower_samples import retained_follower_samples
from polysia.storage.research_evidence import ExclusiveWriterLock

session_app = typer.Typer(
    help="Inspect, validate or rehearse a disabled bounded session.", no_args_is_help=True
)
ConfigPath = Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)]


@session_app.command("schema")
def schema(kind: Literal["config", "authority", "policy", "shadow", "acquisition", "tape"]) -> None:
    """Print the installed artifact's input contract; performs no I/O or issuance."""
    contracts: dict[str, Any] = {
        "config": SessionRuntimeConfig,
        "authority": SessionAuthorization,
        "policy": CopyPolicy,
        "shadow": ShadowLabConfiguration,
        "acquisition": AcquisitionPolicy,
        "tape": tuple[ShadowFrame, ...],
    }
    typer.echo(canonical_json(TypeAdapter(contracts[kind]).json_schema()))


def _verifier(path: Path) -> SessionReceiptVerifier:
    # Operator-installed public keys only. Issuer private keys have no entry point.
    value = read_small_json(path)
    if not isinstance(value, dict) or not value:
        raise SessionBlocked("trusted_public_key_registry_required")
    return SessionReceiptVerifier(
        {key: base64.b64decode(encoded, validate=True) for key, encoded in value.items()}
    )


@session_app.command("inspect")
def inspect(config: ConfigPath) -> None:
    typer.echo(canonical_json(inspect_configuration(load_runtime_config(config))))


@session_app.command("qualify-account")
def qualify_account_command(
    config: ConfigPath,
    scopes: Annotated[Path, typer.Option(exists=True)],
    policy: Annotated[Path, typer.Option(exists=True)],
    allowance_store: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
    read_account: bool = False,
) -> None:
    prepared = load_runtime_config(config)
    if (
        not allowance_store.is_absolute()
        or not output.is_absolute()
        or output.exists()
        or any(
            allowance_store.resolve().is_relative_to(root.resolve())
            or output.resolve().is_relative_to(root.resolve())
            for root in (
                prepared.financial_path.parent,
                prepared.witness_root,
                prepared.custody_path.parent,
                prepared.publication_path.parent,
            )
        )
    ):
        raise typer.BadParameter(
            "unused protected output and separate read-only allowance required"
        )
    instruments = TypeAdapter(tuple[InstrumentScope, ...]).validate_python(
        read_small_json(scopes), extra="forbid"
    )
    allowance = TypeAdapter(AcquisitionPolicy).validate_python(
        read_small_json(policy), extra="forbid"
    )
    try:
        result = asyncio.run(
            qualify_account(
                prepared,
                instruments,
                AcquisitionAuthority(allowance_store, allowance),
                read_account=read_account,
                clock=lambda: datetime.now(UTC),
            )
        )
        if read_account:
            # Protected account evidence, deliberately not a Console projection.
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            import os

            descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(canonical_json(result))
        typer.echo(canonical_json({"status": result["status"], "live_activation": "NOT_PERFORMED"}))
    except Exception as error:
        typer.echo(canonical_json({"status": "BLOCKED", "reason": type(error).__name__}), err=True)
        raise typer.Exit(1) from None


@session_app.command("validate")
def validate(
    config: ConfigPath,
    authority: Annotated[Path, typer.Option(exists=True)],
    trust: Annotated[Path, typer.Option(exists=True)],
) -> None:
    prepared, envelope = load_runtime_config(config), load_authority(authority)
    now = datetime.now(UTC)
    validate_runtime_binding(prepared, envelope)
    action = "ENTRY" if now < envelope.expires_at else "CANCEL"
    result = _verifier(trust).verify(envelope, binding_for(prepared), now=now, action=action)
    typer.echo(
        canonical_json(
            {
                "status": "RECEIPT_VERIFIED_ONLY",
                "receipt_id": result.receipt_id,
                "account_read": "NOT_PERFORMED",
                "live_activation": "NOT_PERFORMED",
            }
        )
    )


@session_app.command("provision")
def provision(
    config: ConfigPath,
    authority: Annotated[Path, typer.Option(exists=True)],
    trust: Annotated[Path, typer.Option(exists=True)],
    commission: bool = False,
) -> None:
    if not commission:
        raise typer.BadParameter(
            "Explicit --commission and an already signed opening observation required"
        )
    prepared, envelope = load_runtime_config(config), load_authority(authority)
    custody = SessionCustody(prepared.custody_path)
    custody.initialize()
    provision_session(prepared, envelope, _verifier(trust), custody, now=datetime.now(UTC))
    journal = FinancialSessionJournal(prepared.financial_path, prepared.witness_root, envelope)
    try:
        journal.open()
        CheckpointPublisher(
            envelope,
            custody,
            prepared.outbox_path,
            clock=lambda: datetime.now(UTC),
            timeout_seconds=prepared.checkpoint_handshake_seconds,
        ).publish(journal.checkpoint(), acknowledge=False)
    finally:
        journal.close()
    typer.echo(
        "PROVISIONED_STOPPED: independent supervision and explicit STOP release remain required"
    )


@session_app.command("supervise")
def supervise(
    config: ConfigPath,
    authority: Annotated[Path, typer.Option(exists=True)],
    trust: Annotated[Path, typer.Option(exists=True)],
    backup: Annotated[Path, typer.Option(exists=True)],
    ticks: Annotated[int, typer.Option(min=1, max=100000)] = 1,
    release_stop: bool = False,
) -> None:
    prepared, envelope = load_runtime_config(config), load_authority(authority)
    now = datetime.now(UTC)
    action = "ENTRY" if now < envelope.expires_at else "CANCEL"
    _verifier(trust).verify(envelope, binding_for(prepared), now=now, action=action)
    journal = FinancialSessionJournal(prepared.financial_path, prepared.witness_root, envelope)
    custody = SessionCustody(prepared.custody_path)
    incidents = SessionIncidents(
        prepared.custody_path.with_suffix(".incidents.sqlite3"), clock=lambda: datetime.now(UTC)
    )
    incidents.initialize()
    commands = ConsoleCommandStore(prepared.commands_path)
    supervisor = SessionSupervisor(
        envelope,
        custody,
        journal=journal.path,
        witness=journal.witness,
        outbox=prepared.outbox_path,
        backup_receipt=backup,
        policy=SupervisionPolicy(
            prepared.minimum_free_disk_bytes,
            prepared.maximum_backup_age_seconds,
            prepared.checkpoint_handshake_seconds,
        ),
        clock=lambda: datetime.now(UTC),
        commands=commands,
        incidents=incidents,
    )
    with ExclusiveWriterLock(prepared.custody_path.with_suffix(".supervisor")):
        commands.retire_scoped_claims(targets=frozenset({envelope.run_id + ":stop"}))
        for index in range(ticks):
            try:
                checkpoint = supervisor.inspect()
            finally:
                observed = datetime.now(UTC)
                snapshot = custody.snapshot(envelope.fingerprint)
                with suppress(OSError, SessionBlocked):
                    publish_redacted(
                        prepared.publication_path.parent / "supervisor-status.json",
                        {
                            "status": "STOP"
                            if snapshot["stopped"] or snapshot["revoked"]
                            else "SUPERVISED",
                            "observed_at": observed.isoformat(),
                            "expires_at": (
                                observed + timedelta(seconds=envelope.supervision_timeout_seconds)
                            ).isoformat(),
                            "scope": envelope.run_id,
                            "reason": snapshot["reason"],
                            "next_action": "Inspect independent custody and exact recovery proof",
                        },
                    )
            if release_stop and index == 0:
                custody.release_stop(envelope.fingerprint, expected=checkpoint)
            if index + 1 < ticks:
                time.sleep(min(0.05, envelope.supervision_timeout_seconds / 8))
    typer.echo(
        canonical_json(
            {"status": "SUPERVISION_CHECKED", "ticks": ticks, "sequence": checkpoint.sequence}
        )
    )


@session_app.command("stop")
def stop(config: ConfigPath, authority: Annotated[Path, typer.Option(exists=True)]) -> None:
    prepared, envelope = load_runtime_config(config), load_authority(authority)
    SessionCustody(prepared.custody_path).stop(envelope.fingerprint, reason="explicit_local_STOP")
    typer.echo("STOP_RETAINED: external orders and holdings still require read-only reconciliation")


@session_app.command("emergency-stop")
def emergency_stop(custody: Annotated[Path, typer.Option(exists=True)], fingerprint: str) -> None:
    """OS-protected restrictive control, independent of config/schema activation."""
    SessionCustody(custody).stop(fingerprint, reason="explicit_local_emergency_STOP")
    typer.echo("STOP_RETAINED")


@session_app.command("revoke")
def revoke(config: ConfigPath, key_id: str | None = None, receipt_id: str | None = None) -> None:
    """Privileged local revocation only; no issuer or browser authority."""
    prepared = load_runtime_config(config)
    SessionCustody(prepared.custody_path).revoke(key_id=key_id, receipt_id=receipt_id)
    typer.echo("REVOCATION_RETAINED_NO_RESUME_AUTHORITY")


@session_app.command("verify-recovery")
def verify_recovery_command(
    config: ConfigPath,
    authority: Annotated[Path, typer.Option(exists=True)],
    destination: Annotated[Path, typer.Option()],
) -> None:
    prepared, envelope = load_runtime_config(config), load_authority(authority)
    journal = FinancialSessionJournal(prepared.financial_path, prepared.witness_root, envelope)
    result = prepare_recovery(
        journal.path,
        journal.witness,
        destination,
        now=datetime.now(UTC),
        minimum_free_bytes=prepared.minimum_free_disk_bytes,
    )
    typer.echo(canonical_json(result))


@session_app.command("run")
def run(
    config: ConfigPath,
    authority: Path | None = None,
    trust: Path | None = None,
    mode: TradingMode = TradingMode.DATA_ONLY,
    live_enabled: bool = False,
    ticks: Annotated[int, typer.Option(min=1, max=10000)] = 1,
) -> None:
    prepared = load_runtime_config(config)

    async def bounded() -> Any:
        session = await compose_session(
            prepared,
            authority=None if authority is None else load_authority(authority),
            verifier=None if trust is None else _verifier(trust),
            mode=mode,
            live_enabled=live_enabled,
        )
        if isinstance(session, dict):
            return session
        try:
            await session.start()
            result = None
            for index in range(ticks):
                tick_started = time.monotonic()
                result = await session.tick()
                if index + 1 < ticks:
                    await asyncio.sleep(
                        max(0, prepared.tick_interval_seconds - (time.monotonic() - tick_started))
                    )
            return result
        finally:
            await session.close()

    try:
        typer.echo(canonical_json(asyncio.run(bounded())))
    except Exception as error:
        typer.echo(canonical_json({"status": "BLOCKED", "reason": type(error).__name__}), err=True)
        raise typer.Exit(1) from None


@session_app.command("rehearse")
def rehearse(
    tape: Annotated[Path, typer.Option(exists=True)],
    policies: Annotated[Path, typer.Option(exists=True)],
    output: Annotated[Path, typer.Option()],
) -> None:
    frames = TypeAdapter(tuple[ShadowFrame, ...]).validate_python(
        read_small_json(tape), extra="forbid"
    )
    variants = TypeAdapter(tuple[CopyPolicy, ...]).validate_python(
        read_small_json(policies), extra="forbid"
    )
    result = compare_policy_stream(
        frames, variants, config=ContinuousShadowConfig(), leader_opening={}
    )
    result["operational_acceptance"] = "NOT_PERFORMED"
    publish_redacted(output, result)
    typer.echo(
        canonical_json(
            {
                "status": "SHADOW_REHEARSAL_COMPLETED",
                "frames": len(frames),
                "policies": len(variants),
                "live": False,
            }
        )
    )


@session_app.command("lab-init")
def lab_init(config: ConfigPath, commands: Annotated[Path, typer.Option()]) -> None:
    async def initialize() -> None:
        lab = load_shadow_lab(config, clock=lambda: datetime.now(UTC))
        try:
            lab.initialize()
            ConsoleCommandStore(commands).initialize()
        finally:
            await lab.close()

    asyncio.run(initialize())
    typer.echo("SHADOW_LAB_INITIALIZED_NO_ACQUISITION")


@session_app.command("lab-execute")
def lab_execute(config: ConfigPath, commands: Annotated[Path, typer.Option(exists=True)]) -> None:
    async def execute() -> list[Any]:
        lab = load_shadow_lab(config, clock=lambda: datetime.now(UTC))
        store = ConsoleCommandStore(commands)
        try:
            with ExclusiveWriterLock(lab.store.path.with_suffix(".control")):
                store.retire_scoped_claims(targets=lab.targets)
                return [
                    ControlService.execute_scoped(
                        store, idempotency_key=key, now=datetime.now(UTC), execute=lab.execute
                    )
                    for key in store.pending_scoped(
                        targets=lab.targets,
                        operations=frozenset(
                            {
                                "shadow.create",
                                "shadow.clone",
                                "shadow.start",
                                "shadow.drain",
                                "shadow.resume",
                                "shadow.finalize",
                                "shadow.archive",
                                "shadow.compare",
                                "policy.stage",
                            }
                        ),
                    )
                ]
        finally:
            await lab.close()

    typer.echo(canonical_json(asyncio.run(execute())))


@session_app.command("lab-poll")
def lab_poll(config: ConfigPath, target: str, acquire: bool = False) -> None:
    if not acquire:
        raise typer.BadParameter(
            "--acquire requires separately authorized bounded public-data acquisition"
        )

    async def poll() -> Any:
        lab = load_shadow_lab(config, clock=lambda: datetime.now(UTC))
        try:
            return await lab.poll(target)
        finally:
            await lab.close()

    typer.echo(canonical_json(asyncio.run(poll())))


@session_app.command("lab-publish")
def lab_publish(config: ConfigPath, output: Annotated[Path, typer.Option()]) -> None:
    async def publish() -> None:
        lab = load_shadow_lab(config, clock=lambda: datetime.now(UTC))
        try:
            publish_redacted(
                output,
                lab.console_view(),
            )
        finally:
            await lab.close()

    asyncio.run(publish())
    typer.echo("SHADOW_LAB_PUBLICATION_RETAINED")


@session_app.command("qualify-retained")
def qualify_retained(
    database: Annotated[Path, typer.Option(exists=True)],
    experiment: Annotated[str, typer.Option()],
    selection_start: Annotated[datetime, typer.Option()],
    selection_end: Annotated[datetime, typer.Option()],
    evaluation_start: Annotated[datetime, typer.Option()],
    available_at: Annotated[datetime, typer.Option()],
    horizon_seconds: Annotated[int, typer.Option(min=1, max=86400)],
    tolerance_seconds: Annotated[int, typer.Option(min=1, max=3600)],
    output: Annotated[Path, typer.Option()],
    confidence: str = "0.95",
) -> None:
    from decimal import Decimal

    samples = retained_follower_samples(
        database,
        experiment,
        selection_start=selection_start,
        selection_end=selection_end,
        horizon_seconds=horizon_seconds,
        tolerance_seconds=tolerance_seconds,
    )
    qualifications = [
        produce_qualification(
            samples,
            wallet=wallet,
            selection_start=selection_start,
            selection_end=selection_end,
            available_at=available_at,
            evaluation_start=evaluation_start,
            confidence=Decimal(confidence),
        )
        for wallet in sorted({row.wallet for row in samples})
    ]
    publish_redacted(
        output,
        {
            "method": "retained-point-in-time-follower/v1",
            "samples": [asdict(row) for row in samples],
            "qualifications": [asdict(row) for row in qualifications],
            "execution": "SHADOW_QUOTES_AND_VERIFIED_FEE_MODEL",
            "live_cohort": "NOT_CLAIMED",
        },
    )
