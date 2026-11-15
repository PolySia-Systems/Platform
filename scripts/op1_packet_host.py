"""Owner-operated OP1 packet bridge. No trading-order signing or venue mutations.

The host launch is one-shot. The container uses the installed release's receipt,
fresh-opening and custody workflow; the external issuer never enters the host.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polysia.deployment.financial_session_runtime import SessionRuntimeConfig
    from polysia.domain.financial_session import SessionAuthorization

BASE = Path("/var/lib/polysia-op1")
INITIAL = BASE / "api-read-20261115-r2-initial"
PROBE = BASE / "api-read-20261115-r2-owner"
TEMPLATE = BASE / "owner-packet-6ab9c089-inputs/read-config.json"
TRUST = Path("/etc/polysia-op1/trust/owner-public-keys.json")
SCRIPT = Path("/etc/polysia-op1/op1_packet_host.py")
READER = Path("/etc/polysia-op1/op1_bounded_read.py")


def write_new(path: Path, body: bytes) -> None:
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())


def launch() -> None:
    import fcntl

    if os.geteuid() != 0:
        raise ValueError("protected_root_operator_required")
    lock = os.open(INITIAL / "packet.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        stop = json.loads(Path("/etc/polysia-op1/commissioning-stop.json").read_text())
        if stop != {"state": "STOP", "authority": "UNISSUED"} or not TRUST.is_file():
            raise ValueError("unissued_STOP_and_enrolled_owner_required")
        if not Path("/etc/polysia-platform/restart-fenced").is_file():
            raise ValueError("original_host_fence_required")
        if (
            len(
                subprocess.check_output(
                    ["ctr", "-n", "polysia-op1", "tasks", "list"], text=True
                ).splitlines()
            )
            != 1
        ):
            raise ValueError("idle_OP1_namespace_required")
        old = json.loads((INITIAL / "receipt.json").read_text())
        if old["status"] != "API_ACCOUNT_OBSERVED" or not old["acquisition"]["stopped"]:
            raise ValueError("completed_initial_read_required")
        grant = old["explicit_read_grant"]
        previous = json.loads(Path(grant["previous_campaign_receipt"]).read_text())
        if (
            not previous["acquisition"]["stopped"]
            or previous["aggregate_campaign"]["requests_charged"] != 32
            or previous["aggregate_campaign"]["bytes_charged"] != 846858
        ):
            raise ValueError("closed_previous_consumption_must_match")
        end = datetime.fromisoformat(grant["starts_at"]) + timedelta(hours=2)
        if datetime.now(UTC) + timedelta(minutes=31) >= end:
            raise ValueError("insufficient_time_for_frozen_packet_and_protection")
        # The existing directory is never reused, including after ambiguity.
        PROBE.mkdir(mode=0o700)
        continuation = dict(old["aggregate_campaign"])
        continuation.update(
            starts_at=grant["starts_at"], parent_receipt=str(INITIAL / "receipt.json")
        )
        write_new(PROBE / "continuation.json", json.dumps(continuation).encode())
        write_new(PROBE / "grant.json", json.dumps(grant).encode())
        write_new(
            PROBE / "capacity-mode.json",
            json.dumps(
                {
                    "initial_clear_baseline_at": old["observed_at"],
                }
            ).encode(),
        )
        write_new(PROBE / "packet-mode", b"OWNER_INTERACTIVE_ONLY\n")
        secret = json.load(sys.stdin)
        if (
            set(secret)
            != {"POLYMARKET_PRIVATE_KEY", "POLYMARKET_FUNDER_ADDRESS", "POLYMARKET_SIGNATURE_TYPE"}
            or secret["POLYMARKET_SIGNATURE_TYPE"] != "3"
        ):
            raise ValueError("existing_type_3_credentials_required")
        write_new(PROBE / "credentials.json", json.dumps(secret).encode())
        del secret
        command = [
            "ctr",
            "-n",
            "polysia-op1",
            "run",
            "--rm",
            "--net-host",
            "--read-only",
            "--hostname",
            "Hetzner-Finland-Helsinki-01",
            "--user",
            "0:0",
            "--cpus",
            "0.25",
            "--memory-limit",
            "536870912",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "POLYSIA_OP1_MARKET=" + old["candidate"]["instrument"]["market"],
            "--env",
            "POLYSIA_OP1_TOKEN=" + old["candidate"]["instrument"]["token"],
        ]
        for source, target, access in (
            (BASE, BASE, "rw"),
            (PROBE, Path("/probe"), "rw"),
            (TEMPLATE, Path("/capacity-config.json"), "ro"),
            (TRUST.parent, TRUST.parent, "ro"),
            (SCRIPT, Path("/packet-host.py"), "ro"),
            (READER, Path("/reader.py"), "ro"),
        ):
            command += ["--mount", f"type=bind,src={source},dst={target},options=rbind:{access}"]
        command += [
            "docker.io/library/polysia:ci",
            "op1-owner-packet-r2",
            "python",
            "/packet-host.py",
            "container",
        ]
        subprocess.run(command, check=True, timeout=200)
    finally:
        (PROBE / "credentials.json").unlink(missing_ok=True)
        # This bridge cannot run financial orders. Do not leave its read/sign
        # waiter alive if the controlling transport failed.
        tasks = subprocess.check_output(["ctr", "-n", "polysia-op1", "tasks", "list"], text=True)
        if any(row.split()[0] == "op1-owner-packet-r2" for row in tasks.splitlines()[1:]):
            subprocess.run(
                [
                    "ctr",
                    "-n",
                    "polysia-op1",
                    "tasks",
                    "kill",
                    "--signal",
                    "SIGKILL",
                    "op1-owner-packet-r2",
                ],
                check=True,
                timeout=10,
            )
        if (PROBE / "owner-signature.bin").exists():
            stop_path = Path("/etc/polysia-op1/commissioning-stop.json")
            pending = stop_path.with_suffix(".pending")
            write_new(
                pending, json.dumps({"state": "STOP", "authority": "PRESENT_NOT_RELEASED"}).encode()
            )
            pending.replace(stop_path)
        os.close(lock)


def build_packet(
    template: SessionRuntimeConfig,
    receipt: dict[str, Any],
    root: Path,
) -> tuple[SessionRuntimeConfig, SessionAuthorization, bytes]:
    from dataclasses import asdict, replace
    from decimal import Decimal

    from pydantic import TypeAdapter

    from polysia.deployment.financial_session_runtime import (
        binding_for,
        validate_capacity_record,
        validate_runtime_binding,
    )
    from polysia.domain.financial_session import (
        AccountObservation,
        ExactSessionEntry,
    )
    from polysia.security.session_authority import receipt_message

    if receipt["status"] != "API_ACCOUNT_OBSERVED" or receipt["scoped_opening"] is None:
        raise ValueError("fresh_scoped_opening_required")
    if receipt["account_mapping"] != asdict(template.account_mapping):
        raise ValueError("observed_account_must_match_signed_config")
    if not receipt["candidate"]["technically_eligible_at_observation"]:
        raise ValueError("eligible_market_required")
    if not 0 < Decimal(receipt["candidate"]["best_ask"]) <= Decimal("0.08"):
        raise ValueError("selected_market_exceeds_frozen_price_ceiling")
    opening = TypeAdapter(AccountObservation).validate_python(receipt["scoped_opening"])
    now = datetime.now(UTC)
    opening.require_complete(
        template.account_mapping.account_id, now=now, max_age=30, scope="ORDER_LIFECYCLE_API"
    )
    at = opening.observed_at
    if at + timedelta(minutes=30) >= datetime.fromisoformat(
        receipt["aggregate_campaign"]["absolute_deadline"]
    ):
        raise ValueError("packet_exceeds_current_finite_window")
    # Only policy-independent paths, actual opening, GTD and the bound capacity
    # record change. Runtime validators retain every composed protective check.
    from polysia.domain.financial_session import canonical_json

    capacity = root / "capacity.json"
    write_new(capacity, canonical_json(receipt["capacity_qualification"]).encode())
    run_id = root.name
    worker, supervisor = BASE / "worker" / run_id, BASE / "supervisor" / run_id
    config = replace(
        template,
        opening=opening,
        financial_path=worker / "financial/session.sqlite3",
        witness_root=worker / "witness",
        custody_path=supervisor / "custody.sqlite3",
        outbox_path=worker / "outbox.json",
        incident_path=worker / "incidents.sqlite3",
        publication_path=worker / "publication/report.json",
        commands_path=BASE / "commands" / run_id / "commands.sqlite3",
        capacity_evidence_path=capacity,
        capacity_evidence_digest=hashlib.sha256(capacity.read_bytes()).hexdigest(),
        exact_entry=ExactSessionEntry(Decimal(5), Decimal("0.08"), at + timedelta(seconds=1335)),
    )
    validate_capacity_record(config, now=now)
    spent = receipt["aggregate_campaign"]
    # Retain the earlier closed campaign as well as every current GET attempt.
    past_attempts, past_bytes = 32 + spent["requests_charged"], 846858 + spent["bytes_charged"]
    from polysia.deployment.financial_session_runtime import load_authority

    inert = load_authority(TEMPLATE.parent / "authority-inert.json")
    if receipt["candidate"]["instrument"] != asdict(inert.instruments[0]):
        raise ValueError("observed_instrument_must_match_signed_config")
    authority = replace(
        inert,
        run_id=run_id,
        owner_receipt="UNSIGNED",
        granted=True,
        binding=binding_for(config),
        starts_at=at,
        expires_at=at + timedelta(minutes=20),
        protective_until=at + timedelta(minutes=30),
        max_requests=1000 - past_attempts,
        max_response_bytes=64 * 1024 * 1024 - past_bytes,
    )
    validate_runtime_binding(config, authority)
    return config, authority, receipt_message(authority, key_id="op1-owner-v1", receipt_id=run_id)


def container() -> None:
    from dataclasses import asdict, replace

    from polysia.deployment.financial_session_runtime import load_runtime_config, provision_session
    from polysia.deployment.session_supervision import CheckpointPublisher
    from polysia.domain.financial_session import canonical_json
    from polysia.security.session_authority import SessionCustody, SessionReceiptVerifier
    from polysia.storage.financial_session import FinancialSessionJournal

    spec = importlib.util.spec_from_file_location("bounded_owner_read", "/reader.py")
    if spec is None or spec.loader is None:
        raise ValueError("installed_read_helper_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import asyncio

    asyncio.run(module.main())
    receipt = json.loads(Path("/probe/receipt.json").read_text())
    root = BASE / "owner-packet-r2-20261115"
    root.mkdir(mode=0o700)
    template = load_runtime_config(Path("/capacity-config.json"))
    config, authority, message = build_packet(template, receipt, root)
    # Serialize Paths exactly as the supported config fingerprint does.
    config_body = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(config).items()
    }
    write_new(root / "config.json", canonical_json(config_body).encode())
    write_new(root / "authority-unsigned.json", canonical_json(asdict(authority)).encode())
    write_new(root / "owner-message.bin", message)
    deadline = config.opening.observed_at + timedelta(seconds=25)
    print(
        canonical_json(
            {
                "stage": "REVIEW",
                "config": config_body,
                "message": base64.b64encode(message).decode(),
                "root": str(root),
                "review_deadline": deadline,
                "read_consumption": receipt["aggregate_campaign"],
            }
        ),
        flush=True,
    )
    signature_path = Path("/probe/owner-signature.bin")
    while not signature_path.exists():
        if datetime.now(UTC) >= deadline:
            raise ValueError("owner_review_window_expired_no_authority_consumed")
        time.sleep(0.05)
    if datetime.now(UTC) >= deadline or signature_path.stat().st_size != 64:
        raise ValueError("fresh_external_signature_required")
    signature = signature_path.read_bytes()
    signed = replace(
        authority,
        owner_receipt=canonical_json(
            {
                "key_id": "op1-owner-v1",
                "receipt_id": authority.run_id,
                "signature": base64.b64encode(signature).decode(),
            }
        ),
    )
    verifier = SessionReceiptVerifier(
        {
            key: base64.b64decode(value, validate=True)
            for key, value in json.loads(TRUST.read_text()).items()
        }
    )
    verifier.verify_signature(signed)
    write_new(root / "authority-signed.json", canonical_json(asdict(signed)).encode())
    custody = SessionCustody(config.custody_path)
    os.umask(0o027)
    custody.initialize()
    provision_session(config, signed, verifier, custody, now=datetime.now(UTC))
    journal = FinancialSessionJournal(config.financial_path, config.witness_root, signed)
    try:
        journal.open()
        CheckpointPublisher(
            signed,
            custody,
            config.outbox_path,
            clock=lambda: datetime.now(UTC),
            timeout_seconds=config.checkpoint_handshake_seconds,
        ).publish(journal.checkpoint(), acknowledge=False)
    finally:
        journal.close()
    for folder, uid in (
        (config.financial_path.parents[1], 999),
        (config.custody_path.parent, 995),
        (config.commands_path.parent, 995),
    ):
        # All three roots were newly created for this exact receipt, never N3.
        if folder.name != signed.run_id or not folder.is_relative_to(BASE):
            raise ValueError("isolated_role_path_required")
        for path in (folder, *folder.rglob("*")):
            if path.is_symlink():
                raise ValueError("role_path_symlink_denied")
            os.chown(path, uid, 981)
            path.chmod(0o2750 if path.is_dir() else 0o640)
    config.commands_path.chmod(0o660)
    # The independent supervisor must still verify recovery and release STOP.
    result = {
        "stage": "PROVISIONED_STOPPED",
        "root": str(root),
        "run_id": signed.run_id,
        "financial_actions": 0,
        "supervision": "NOT_RELEASED",
        "recovery": "NOT_COMMISSIONED",
    }
    write_new(root / "commissioning-receipt.json", canonical_json(result).encode())
    print(canonical_json(result), flush=True)


def accept_signature() -> None:
    signature = base64.b64decode(sys.stdin.read().strip(), validate=True)
    if len(signature) != 64 or not PROBE.is_dir():
        raise ValueError("existing_packet_and_raw_signature_required")
    write_new(PROBE / "owner-signature.bin", signature)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("launch", "container", "accept-signature"))
    mode = parser.parse_args().mode
    try:
        {"launch": launch, "container": container, "accept-signature": accept_signature}[mode]()
    except Exception as error:
        # No credential values, HTTP bodies or arbitrary exception text.
        known = {
            "owner_review_window_expired_no_authority_consumed",
            "eligible_market_required",
            "fresh_scoped_opening_required",
            "selected_market_exceeds_frozen_price_ceiling",
            "insufficient_time_for_frozen_packet_and_protection",
            "idle_OP1_namespace_required",
        }
        print(
            json.dumps(
                {
                    "stage": "BLOCKED",
                    "error_type": type(error).__name__,
                    "reason": str(error) if str(error) in known else "inspect_protected_receipt",
                }
            ),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
