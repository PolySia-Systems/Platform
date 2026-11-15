"""Restricted encrypted financial backup transport. Never starts a financial writer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAXIMUM_ARCHIVE_BYTES = 16 * 1024 * 1024


def generation_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("restricted_backup_generation_required")
    return value


def extract_generation(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, mode="r:") as stream:
        members = stream.getmembers()
        if (
            not 1 <= len(members) <= 32
            or sum(x.size for x in members) > MAXIMUM_ARCHIVE_BYTES
            or any(
                not (x.isfile() or x.isdir())
                or x.name.startswith("/")
                or ".." in Path(x.name).parts
                or Path(x.name).parts[0] != "generation"
                for x in members
            )
            or len({x.name for x in members}) != len(members)
        ):
            raise ValueError("bounded_regular_generation_archive_required")
        stream.extractall(destination, filter="data")


def native(
    profile: dict[str, Any],
    task: str,
    arguments: list[str],
    mounts: list[tuple[str, str, str]],
    *,
    user: str = "0:0",
) -> str:
    task = profile.get("task_prefix", "polysia-op1-backup") + "-" + task
    command = [
        "ctr",
        "-n",
        profile["namespace"],
        "run",
        "--rm",
        "--read-only",
        "--user",
        user,
        "--cpus",
        "0.25",
        "--memory-limit",
        "268435456",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    for source, destination, mode in mounts:
        command += ["--mount", f"type=bind,src={source},dst={destination},options=rbind:{mode}"]
    command += [profile["image"], task, *arguments]
    try:
        return subprocess.check_output(command, text=True, timeout=40)
    except BaseException:
        subprocess.run(
            ["ctr", "-n", profile["namespace"], "tasks", "kill", "--signal", "SIGKILL", task],
            check=False,
            capture_output=True,
            timeout=5,
        )
        raise


def receiver(profile: dict[str, Any]) -> None:
    """Only this forced SSH command is authorized for the backup transport key."""
    import signal

    def expired(*signal_args: object) -> None:
        raise TimeoutError("finite_backup_receive_deadline")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(45)
    import fcntl

    lock = os.open(Path(profile["destination"]) / "receive.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (
        profile["namespace"] != "polysia-op1-recovery"
        or not Path(profile["original_fence"]).is_file()
        or not Path(profile["recovery_fence"]).is_file()
    ):
        raise ValueError("fenced_recovery_destination_required")
    if (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", "polysia-platform-recovery"], check=False
        ).returncode
        == 0
    ):
        raise ValueError("recovery_financial_service_must_remain_inactive")
    header = sys.stdin.buffer.readline(8193)
    if len(header) > 8192:
        raise ValueError("bounded_backup_header_required")
    request = json.loads(header)
    name = generation_name(request["generation"])
    root = Path(profile["destination"]) / name
    if request["operation"] == "QUERY":
        proof = root / "proof.json"
        if proof.is_file():
            value = json.loads(proof.read_text())
            if value["cipher_sha256"] == request["cipher_sha256"]:
                print(json.dumps(value), flush=True)
                return
        print(json.dumps({"status": "NOT_CONFIRMED"}), flush=True)
        return
    if request["operation"] != "UPLOAD" or not 0 < request["bytes"] <= MAXIMUM_ARCHIVE_BYTES:
        raise ValueError("bounded_backup_upload_required")
    if root.exists():
        # Never overwrite an ambiguous earlier upload. The client queries it.
        raise ValueError("existing_generation_requires_query")
    used = sum(p.stat().st_size for p in root.parent.rglob("*") if p.is_file())
    if used + 4 * MAXIMUM_ARCHIVE_BYTES > profile.get("maximum_storage_bytes", 128 * 1024 * 1024):
        raise ValueError("recovery_storage_reserve_exhausted")
    root.mkdir(mode=0o700)
    raw = sys.stdin.buffer.read(request["bytes"])
    if (
        len(raw) != request["bytes"]
        or sys.stdin.buffer.read(1)
        or hashlib.sha256(raw).hexdigest() != request["cipher_sha256"]
    ):
        raise ValueError("complete_cipher_digest_required")
    cipher = root / "generation.age"
    with os.fdopen(os.open(cipher, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        stream.write(raw)
    del raw
    native(
        profile,
        "restore-decrypt-" + name[-24:],
        [
            "age",
            "-d",
            "-i",
            "/keys/age-identity.txt",
            "-o",
            "/transfer/generation.tar",
            "/transfer/generation.age",
        ],
        [(str(root), "/transfer", "rw"), (profile["key_directory"], "/keys", "ro")],
    )
    restored = root / "isolated"
    restored.mkdir(mode=0o700)
    extract_generation(root / "generation.tar", restored)
    record = json.loads((restored / "generation/receipt.json").read_text())
    original = Path(request["source_generation"])
    if not original.is_absolute() or not str(original).startswith("/var/lib/polysia-op1/"):
        raise ValueError("approved_primary_backup_root_required")
    for field in ("artifacts", "restored"):
        if any(".." in Path(x).parts for x in record[field]):
            raise ValueError("contained_recovery_artifact_required")
        record[field] = [
            str(restored / "generation" / Path(x).relative_to(original)) for x in record[field]
        ]
    with (root / "mapped.json").open("x") as stream:
        json.dump(record, stream)
    code = """
import json
from pathlib import Path
from polysia.deployment.financial_recovery import verify_recovery
verify_recovery(json.loads(Path('/transfer/mapped.json').read_text()))
print('RESTORE_VERIFIED')
"""
    checked = native(
        profile,
        "restore-verify-" + name[-24:],
        ["python", "-c", code],
        [(str(root), "/transfer", "ro"), (str(root), str(root), "ro")],
    )
    if checked.strip() != "RESTORE_VERIFIED":
        raise ValueError("actual_isolated_restore_required")
    proof = {
        key: record[key]
        for key in (
            "authority_fingerprint",
            "checkpoint",
            "artifact_sha256",
            "authority_reissued",
            "custody_included",
        )
    }
    proof.update(
        version="session-offsite-backup/v1",
        restore_verified=True,
        financial_writer="FORBIDDEN",
        observed_at=datetime.now(UTC).isoformat(),
        cipher_sha256=request["cipher_sha256"],
        generation=name,
    )
    with os.fdopen(
        os.open(root / "proof.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
    ) as f:
        json.dump(proof, f)
    (root / "generation.tar").unlink()
    print(json.dumps(proof), flush=True)


def ssh_exchange(
    profile: dict[str, Any], header: dict[str, Any], data: bytes = b""
) -> dict[str, Any]:
    command = [
        "ssh",
        "-T",
        "-oBatchMode=yes",
        "-oStrictHostKeyChecking=yes",
        "-oIdentitiesOnly=yes",
        "-oConnectTimeout=5",
        "-oServerAliveInterval=3",
        "-oServerAliveCountMax=2",
        "-oUserKnownHostsFile=" + profile["known_hosts"],
        "-i",
        profile["identity"],
        profile["target"],
    ]
    result = subprocess.run(
        command,
        input=json.dumps(header).encode() + b"\n" + data,
        capture_output=True,
        timeout=35,
        check=True,
    )
    if len(result.stdout) > 8192:
        raise ValueError("bounded_offsite_proof_required")
    return json.loads(result.stdout)


def transfer_budget(profile: dict[str, Any], generation: str, *, charge: int = 0) -> None:
    path = Path(profile["budget_path"])
    total = 0
    pending = None
    if path.exists():
        if path.stat().st_size > 256 * 1024:
            raise ValueError("bounded_backup_budget_history_required")
        for line in path.read_text().splitlines():
            item = json.loads(line)
            if item["kind"] == "RESERVED":
                total += item["bytes"]
                pending = item["generation"]
            elif item["kind"] == "CONFIRMED" and item["generation"] == pending:
                pending = None
    if charge:
        if pending is not None:
            raise ValueError("unconfirmed_backup_requires_inspection_not_new_upload")
        limit = profile.get("maximum_transport_bytes", 64 * 1024 * 1024)
        if not 0 < limit <= 64 * 1024 * 1024 or total + charge > limit:
            raise ValueError("finite_backup_transport_budget_exhausted")
        item = {"kind": "RESERVED", "generation": generation, "bytes": charge}
    else:
        if pending != generation:
            raise ValueError("matching_backup_reservation_required")
        item = {"kind": "CONFIRMED", "generation": generation}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def transmit(
    profile: dict[str, Any], record: dict[str, Any], cipher: Path, source: Path
) -> dict[str, Any]:
    if cipher.stat().st_size > MAXIMUM_ARCHIVE_BYTES:
        raise ValueError("bounded_cipher_required")
    raw = cipher.read_bytes()
    header = {
        "operation": "UPLOAD",
        "generation": generation_name(source.name),
        "bytes": len(raw),
        "cipher_sha256": hashlib.sha256(raw).hexdigest(),
        "source_generation": str(source),
    }
    transfer_budget(profile, header["generation"], charge=len(raw) + 16384)
    try:
        proof = ssh_exchange(profile, header, raw)
    except OSError, subprocess.SubprocessError, ValueError:
        # A lost upload response is never blindly resent. QUERY is read-only.
        proof = ssh_exchange(profile, {**header, "operation": "QUERY"})
    if (
        proof.get("checkpoint") != record["checkpoint"]
        or proof.get("artifact_sha256") != record["artifact_sha256"]
        or proof.get("cipher_sha256") != header["cipher_sha256"]
    ):
        raise ValueError("matching_confirmed_offsite_generation_required")
    transfer_budget(profile, header["generation"])
    return proof


def inner_capture(config: Path, authority: Path, destination: Path, recipient: Path) -> None:
    from polysia.deployment.financial_recovery import prepare_recovery
    from polysia.deployment.financial_session_runtime import load_authority, load_runtime_config
    from polysia.storage.financial_session import FinancialSessionJournal

    c, a = load_runtime_config(config), load_authority(authority)
    journal = FinancialSessionJournal(c.financial_path, c.witness_root, a)
    record = prepare_recovery(
        journal.path,
        journal.witness,
        destination,
        now=datetime.now(UTC),
        minimum_free_bytes=c.minimum_free_disk_bytes,
    )
    plaintext = destination / "generation.tar"
    # Include only the immutable snapshot/restore generation, never custody or keys.
    with (
        os.fdopen(os.open(plaintext, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream,
        tarfile.open(fileobj=stream, mode="w") as archive,
    ):
        for name in ("receipt.json", "snapshots", "restore"):
            archive.add(destination / name, arcname="generation/" + name)
    if plaintext.stat().st_size > MAXIMUM_ARCHIVE_BYTES - 1024:
        raise ValueError("bounded_financial_archive_required")
    subprocess.run(
        [
            "age",
            "-r",
            recipient.read_text().strip(),
            "-o",
            str(destination / "generation.age"),
            str(plaintext),
        ],
        check=True,
        timeout=15,
        capture_output=True,
    )
    plaintext.unlink()
    print(json.dumps(record), flush=True)


def watch(profile: dict[str, Any], *, duration: int, interval: int) -> None:
    """Finite backup-only commissioning or runtime maintenance; no worker heartbeat."""
    if not 1 <= duration <= 7200 or not 5 <= interval <= 30:
        raise ValueError("finite_backup_watch_required")
    started = time.monotonic()
    sequence = 0
    while time.monotonic() - started < duration:
        cycle_started = time.monotonic()
        at = datetime.now(UTC)
        if profile.get("until") and at >= datetime.fromisoformat(profile["until"]):
            break
        sequence += 1
        used = sum(p.stat().st_size for p in Path(profile["generations"]).rglob("*") if p.is_file())
        if used + 4 * MAXIMUM_ARCHIVE_BYTES > profile.get(
            "maximum_storage_bytes", 128 * 1024 * 1024
        ):
            raise ValueError("finite_backup_storage_reserve_exhausted")
        destination = Path(profile["generations"]) / at.strftime("%Y%m%dT%H%M%S%fZ")
        command = [
            "python",
            "/backup-tool.py",
            "inner-capture",
            "--config",
            profile["config"],
            "--authority",
            profile["authority"],
            "--destination",
            str(destination),
            "--recipient",
            "/recipient.txt",
        ]
        mounts = [
            (profile["base"], profile["base"], "ro"),
            (profile["generations"], profile["generations"], "rw"),
            (profile["script"], "/backup-tool.py", "ro"),
            (profile["recipient"], "/recipient.txt", "ro"),
        ]
        record = json.loads(
            native(profile, "backup-capture-" + str(sequence), command, mounts, user="995:981")
        )
        proof = transmit(profile, record, destination / "generation.age", destination)
        record["offsite"] = proof
        # Validation uses the installed package, not a claimed editable PASS.
        code = """
import json,sys
from pathlib import Path
from datetime import UTC,datetime
from polysia.deployment.continuous_session_controls import (
    require_offsite_proof,publish_control_file,
)
v=json.loads(Path('/input.json').read_text())
require_offsite_proof(v,now=datetime.now(UTC),maximum_age=60)
publish_control_file(Path('/publication/current-backup.json'),v)
print('VERIFIED_BACKUP_PUBLISHED')
"""
        input_path = destination / "publication-input.json"
        with input_path.open("x") as stream:
            json.dump(record, stream)
        publication = Path(profile["publication"])
        native(
            profile,
            "backup-publish-" + str(sequence),
            ["python", "-c", code],
            [(str(input_path), "/input.json", "ro"), (str(publication), "/publication", "rw")],
            user="995:981",
        )
        print(
            json.dumps(
                {
                    "status": "OFFSITE_BACKUP_VERIFIED",
                    "sequence": sequence,
                    "checkpoint": record["checkpoint"],
                    "observed_at": proof["observed_at"],
                }
            ),
            flush=True,
        )
        remaining = duration - (time.monotonic() - started)
        delay = max(0, interval - (time.monotonic() - cycle_started))
        if remaining > 0 and delay:
            time.sleep(min(delay, remaining))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("receive", "watch", "inner-capture"))
    for name in ("profile", "config", "authority", "destination", "recipient"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--interval", type=int, default=20)
    args = parser.parse_args()
    if args.mode == "inner-capture":
        inner_capture(args.config, args.authority, args.destination, args.recipient)
    else:
        profile = json.loads(args.profile.read_text())
        if args.mode == "receive":
            receiver(profile)
        else:
            watch(profile, duration=args.duration, interval=args.interval)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "BACKUP_STOP", "error_type": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
