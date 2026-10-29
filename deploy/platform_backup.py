"""Bounded host backup/isolated restore jobs; run from a verified release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

MAX_GENERATION = 536_870_912
NAME = re.compile(r"platform-\d{8}T\d{6}Z\.tar\.age")
STATE_ROOT = Path("/var/lib/polysia-platform")
CONFIG_ROOT = Path("/etc/polysia-platform")
VAULT_ROOT = Path("/srv/polysia-platform-backups")


def run(args: list[str], *, data: str | None = None, timeout: int = 300) -> str:
    return subprocess.run(
        args, input=data, text=True, capture_output=True, check=True, timeout=timeout
    ).stdout.strip()


def isolated(image: str, *mounts: str, user: str = "10101:10102") -> list[str]:
    if re.fullmatch(r"sha256:[a-f0-9]{64}", image) is None:
        raise ValueError("immutable image ID required")
    args = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--user",
        user,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory",
        "512m",
        "--cpus",
        ".5",
        "--pids-limit",
        "128",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
    ]
    for mount in mounts:
        args += ["--volume", mount]
    return args


def checked_root(path: str, expected: str) -> Path:
    root = Path(path)
    if root != Path(expected) or root.is_symlink() or root.resolve() != root:
        raise ValueError("job root is outside its dedicated allocation")
    return root


def sftp_command(value: dict[str, Any]) -> list[str]:
    if re.fullmatch(r"[a-zA-Z0-9.-]+", value["secondary_host"]) is None:
        raise ValueError("invalid backup destination")
    port = value.get("secondary_port", 22)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid backup SFTP port")
    return [
        "sftp",
        "-P",
        str(port),
        "-oBatchMode=yes",
        "-oStrictHostKeyChecking=yes",
        "-oConnectTimeout=15",
        "-oIdentitiesOnly=yes",
        "-oUserKnownHostsFile=" + value["known_hosts"],
        "-i",
        value["upload_key"],
        "-b",
        "-",
        "polysia-platform-upload@" + value["secondary_host"],
    ]


def backup(value: dict[str, Any]) -> dict[str, Any]:
    try:
        return _backup_generation(value)
    finally:
        subprocess.run(
            ["docker", "stop", "-t", "5", "polysia-platform-backup-stage"],
            capture_output=True,
            timeout=15,
            check=False,
        )


def campaign_mounts(worker: dict[str, Any]) -> list[str]:
    """Expose only the frozen plan, retaining the backup container's narrow mounts."""
    configured = worker.get("campaign")
    if configured is None:
        return []
    if not isinstance(configured, str):
        raise ValueError("invalid campaign plan path")
    path = PurePosixPath(configured)
    if (path.parent != PurePosixPath("/config")
            or re.fullmatch(r"[a-zA-Z0-9_.-]+\.json", path.name) is None):
        raise ValueError("campaign plan must be a dedicated configuration JSON file")
    source = CONFIG_ROOT / path.name
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16_384:
        raise ValueError("campaign plan missing, linked or outside its bound")
    return ["--volume", f"{source}:{path}:ro"]


def _backup_generation(value: dict[str, Any]) -> dict[str, Any]:
    mode = value.get("mode", "sftp")
    if mode not in {"local", "sftp"}:
        raise ValueError("backup mode must be local or sftp")
    if mode == "sftp":
        sftp_command(value)  # Validate before snapshot/encryption work.
    output = checked_root(value["output"], str(STATE_ROOT / "backup-out"))
    output.mkdir(mode=0o700, exist_ok=True)
    if (
        sum(p.stat().st_size for p in output.iterdir() if NAME.fullmatch(p.name)) + MAX_GENERATION
        > 2_147_483_648
    ):
        raise OSError("retained backup allocation is full; preserve generations before cleanup")
    os.chown(output, 10101, 10102)
    if shutil.disk_usage(output).free < 8_589_934_592 + 2 * MAX_GENERATION:
        raise OSError("host free-disk reserve unavailable")
    release = Path(value["release"])
    manifest = json.loads((release / "manifest.json").read_text())
    name = datetime.now(UTC).strftime("platform-%Y%m%dT%H%M%SZ.tar.age")
    target = output / name
    recipient = Path(value["recipient_file"]).read_text().strip()
    args = isolated(
        value["image_id"],
        f"{CONFIG_ROOT}/worker.json:/config/worker.json:ro",
        f"{STATE_ROOT}/worker:/state:rw",
        f"{STATE_ROOT}/control:/control:ro",
        f"{STATE_ROOT}/publication:/publication:ro",
        f"{release}:/release:ro",
        f"{output}:/out:rw",
    )
    if (CONFIG_ROOT / "manifest.json").is_file():
        args += ["--volume", f"{CONFIG_ROOT}/manifest.json:/config/manifest.json:ro"]
    args += campaign_mounts(json.loads((CONFIG_ROOT / "worker.json").read_bytes()))
    args += ["--name", "polysia-platform-backup-stage"]
    receipt = json.loads(
        run(
            args
            + [
                value["image_id"],
                "ops",
                "platform-backup",
                "--config",
                "/config/worker.json",
                "--image-archive",
                "/release/polysia-image.tar.gz",
                "--release-manifest",
                "/release/manifest.json",
                "--recipient",
                recipient,
                "--output",
                "/out/" + name,
            ]
        )
    )
    if target.stat().st_size > MAX_GENERATION or receipt["release_commit"] != manifest["commit"]:
        raise ValueError("backup generation identity or size differs")
    if mode == "sftp":
        run(
            sftp_command(value),
            data=(
                f'put "{target}" /incoming/{name}.partial\n'
                f"rename /incoming/{name}.partial /incoming/{name}\n"
            ),
        )
    # Prune only this job's named generated ciphertext after confirmed upload.
    generations = sorted((p for p in output.iterdir() if NAME.fullmatch(p.name)), reverse=True)
    for old in generations[2:] if value.get("retire_generations", True) else []:
        if old.is_symlink():
            raise ValueError("backup generation cannot be a symlink")
        old.unlink()
    return {
        **receipt,
        "status": "ENCRYPTED_UPLOADED" if mode == "sftp" else "LOCAL_ENCRYPTED",
        "filename": name,
    }


def decrypt_bounded(command: list[str], source: Path) -> None:
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        if process.stdin is None:
            raise OSError("decryption_input_unavailable")
        total = 0
        with source.open("rb") as stream:
            while chunk := stream.read(1_048_576):
                total += len(chunk)
                if total > MAX_GENERATION:
                    raise ValueError("encrypted_generation_limit_exceeded")
                process.stdin.write(chunk)
        process.stdin.close()
        if process.wait(timeout=120):
            raise ValueError("authenticated_decryption_failed")
    except BaseException:
        process.kill()
        process.wait()
        subprocess.run(
            ["docker", "stop", "-t", "5", "polysia-platform-restore-decrypt"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        raise


def restore(value: dict[str, Any]) -> dict[str, Any]:
    # Drill plaintext is disposable. Only the two encrypted generations and
    # independently retained release assets are the durable recovery source.
    vault = checked_root(value["vault"], str(VAULT_ROOT))
    stage_root = vault / "restore"
    try:
        return _restore_generation(value)
    finally:
        subprocess.run(
            ["docker", "stop", "-t", "5", "polysia-platform-restore-stage"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if stage_root.exists():
            for stage in stage_root.iterdir():
                if re.fullmatch(r"drill-\d{8}T\d{6}Z", stage.name):
                    if stage.is_symlink() or not stage.resolve().is_relative_to(
                        stage_root.resolve()
                    ):
                        raise ValueError("restore_cleanup_path_escaped")
                    shutil.rmtree(stage)


def verify_generation(
    source: Path,
    stage: Path,
    *,
    image: str,
    trusted: Path,
    recovery_key: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Shared real decryption, inventory/replay and fenced startup path."""
    if (
        source.is_symlink()
        or not 0 < source.stat().st_size <= MAX_GENERATION
        or stage.resolve() != stage
        or any(stage.iterdir())
    ):
        raise ValueError("unused protected restore staging and bounded ciphertext required")
    if shutil.disk_usage(stage).free < 8_589_934_592 + 2 * MAX_GENERATION:
        raise OSError("restore staging cannot preserve the host free-disk reserve")
    args = isolated(
        image, f"{stage}:/restore:rw", str(recovery_key) + ":/run/recovery-key:ro", user="0:0"
    )
    decrypt_bounded(
        args
        + [
            "--interactive",
            "--name",
            "polysia-platform-restore-decrypt",
            "--entrypoint",
            "age",
            image,
            "--decrypt",
            "--identity",
            "/run/recovery-key",
            "--output",
            "/restore/bundle.tar",
        ],
        source,
    )
    tar = stage / "bundle.tar"
    if tar.stat().st_size > MAX_GENERATION:
        raise ValueError("plaintext_generation_limit_exceeded")
    verify = isolated(image, f"{stage}:/restore:rw", f"{trusted}:/release.json:ro", user="0:0")
    verify += ["--name", "polysia-platform-restore-stage"]
    receipt = json.loads(
        run(
            verify
            + [
                image,
                "ops",
                "platform-restore-verify",
                "--archive",
                "/restore/bundle.tar",
                "--destination",
                "/restore/bundle",
                "--trusted-release-manifest",
                "/release.json",
            ],
            timeout=300,
        )
    )
    run(
        isolated(image) + ["--name", "polysia-platform-restore-stage", image, "system", "health"],
        timeout=60,
    )
    # Restore startup stays network-isolated and uses rewritten isolated paths.
    command_receipt = json.loads(
        run(
            verify
            + [
                image,
                "research",
                "platform-tick",
                "--config",
                "/restore/bundle/recovery-runtime.json",
            ],
            timeout=60,
        )
    )
    # The CLI intentionally prints a compact status/reason. The durable worker
    # record owns the restored authority counters and financial identity.
    status_path = stage / "bundle/restored-status.json"
    if status_path.is_symlink() or not 0 < status_path.stat().st_size <= 65_536:
        raise ValueError("restored worker status is missing or outside its bound")
    worker = json.loads(status_path.read_text())
    if worker["status"] != command_receipt["status"]:
        raise ValueError("restored worker status differs from its command receipt")
    allowed = (
        {"UNCONFIGURED"} if receipt.get("installation_state") == "UNCONFIGURED" else {"STOPPED"}
    )
    if worker["status"] not in allowed or receipt["acquisition_enabled"] is not False:
        raise ValueError("restored_runtime_not_stopped")
    metadata = json.loads((stage / "bundle/platform-recovery.json").read_text())
    tar.unlink()
    return receipt, worker, metadata


def _restore_generation(value: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    vault = checked_root(value["vault"], str(VAULT_ROOT))
    incoming = vault / "incoming"
    generations = sorted((p for p in incoming.iterdir() if NAME.fullmatch(p.name)), reverse=True)
    if not generations:
        raise ValueError("no_complete_generation")
    selected = value.get("generation")
    if selected and (not isinstance(selected, str) or NAME.fullmatch(selected) is None):
        raise ValueError("invalid_selected_generation")
    source = incoming / selected if selected and NAME.fullmatch(selected) else generations[0]
    if selected and source not in generations:
        raise ValueError("selected_complete_generation_unavailable")
    if source.is_symlink() or not 0 < source.stat().st_size <= MAX_GENERATION:
        raise ValueError("invalid_generation")
    stage_root = vault / "restore"
    stage_root.mkdir(mode=0o700, exist_ok=True)
    stage = stage_root / datetime.now(UTC).strftime("drill-%Y%m%dT%H%M%SZ")
    stage.mkdir(mode=0o700)
    receipt, worker, metadata = verify_generation(
        source,
        stage,
        image=value["image_id"],
        trusted=Path(value["release_manifest"]),
        recovery_key=Path(value["recovery_key"]),
    )
    age = (datetime.now(UTC) - datetime.fromisoformat(metadata["created_at"])).total_seconds()
    elapsed = time.monotonic() - started
    objectives_met = 0 <= age <= 86_400 and elapsed <= 3600
    for old in generations[2:]:
        if old.is_symlink():
            raise ValueError("backup generation cannot be a symlink")
        old.unlink()
    for old in stage_root.iterdir():
        if old != stage and re.fullmatch(r"drill-\d{8}T\d{6}Z", old.name):
            if old.is_symlink() or not old.resolve().is_relative_to(stage_root.resolve()):
                raise ValueError("restore cleanup path escaped")
            shutil.rmtree(old)
    # Ciphertext remains authoritative; remove only this freshly verified staging tar.
    if not objectives_met:
        receipt["status"] = "RECOVERY_OBJECTIVES_NOT_MET"
    with source.open("rb") as encrypted:
        ciphertext_digest = hashlib.file_digest(encrypted, "sha256").hexdigest()
    receipt.update(
        rpo_met=0 <= age <= 86_400,
        rto_met=elapsed <= 3600,
        filename=source.name,
        measured_RPO_seconds=round(age, 3),
        measured_RTO_seconds=round(elapsed, 3),
        network="none",
        runtime_status=worker["status"],
        ciphertext_sha256=ciphertext_digest,
    )
    return receipt


def fetch_restore_status(value: dict[str, Any]) -> dict[str, Any]:
    root = checked_root(value["output"], str(STATE_ROOT / "backup-out"))
    target = root / "restore-status.partial"
    try:
        run(sftp_command(value), data=f'get /status/restore-status.json "{target}"\n', timeout=30)
        if target.is_symlink() or target.stat().st_size > 4096:
            raise ValueError("secondary_status_size_invalid")
        receipt = json.loads(target.read_text())
        allowed = {
            "status",
            "release_commit",
            "checked_at",
            "measured_RPO_seconds",
            "measured_RTO_seconds",
            "acquisition_enabled",
            "runtime_status",
            "network",
            "filename",
            "ciphertext_sha256",
            "analytical_digest",
            "restored_reports",
        }
        return {key: receipt[key] for key in allowed if key in receipt}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {
            "status": "UNKNOWN",
            "checked_at": datetime.now(UTC).isoformat(),
            "next_action": "inspect protected secondary restore journal",
        }
    finally:
        target.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("backup configuration must remain inside its protected root")
    temporary = path.with_suffix(".partial")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def change_destination(
    candidate: dict[str, Any],
    *,
    recovery_key: Path | None = None,
) -> dict[str, Any]:
    """Commit a destination only after an exact-generation real restore proof.

    Failed upload/decryption/verification leaves the active configuration intact.
    Disconnect changes scheduling/protection; it never deletes retained ciphertext.
    """
    current = CONFIG_ROOT / "backup-job.json"
    if CONFIG_ROOT.resolve() != CONFIG_ROOT or current.is_symlink():
        raise ValueError("protected backup configuration required")
    mode = candidate.get("mode")
    if mode not in {"none", "local", "sftp"}:
        raise ValueError("explicit backup mode required")
    history = CONFIG_ROOT / "backup-history"
    if history.resolve() != history:
        raise ValueError("backup history cannot traverse a symlink")
    history.mkdir(mode=0o700, exist_ok=True)
    if current.exists():
        raw = current.read_bytes()
        saved = history / (hashlib.sha256(raw).hexdigest() + ".json")
        if not saved.exists():
            if len(list(history.glob("*.json"))) >= 64:
                raise OSError("retained destination history is full; inspect protected checkpoints")
            _atomic_json(saved, json.loads(raw))
    if mode == "none":
        _atomic_json(current, {"schema": "platform-backup-destination/v1", "mode": "none"})
        return {"status": "UNPROTECTED", "retained_generations": "PRESERVED"}
    checked_root(candidate["output"], str(STATE_ROOT / "backup-out"))
    if mode == "sftp":
        sftp_command(candidate)
    request = {key: value for key, value in candidate.items() if key != "retire_generations"}
    staging = CONFIG_ROOT / "backup-candidate.json"
    prior = json.loads(staging.read_text()) if staging.exists() else {}
    if prior.get("request") == request:
        encrypted = prior["encrypted"]
    else:
        encrypted = backup({**candidate, "retire_generations": False})
        _atomic_json(staging, {"request": request, "encrypted": encrypted})
    source = Path(candidate["output"]) / encrypted["filename"]
    if source.is_symlink() or not source.is_file():
        raise ValueError("staged complete generation is unavailable")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != encrypted["sha256"]:
            raise ValueError("staged generation changed")
    if mode == "local":
        if recovery_key is None:
            return {
                "status": "AWAITING_KEY_VERIFICATION",
                "filename": source.name,
                "next_action": "Verify using the separately held recovery key; "
                "the current destination remains active.",
            }
        if (
            recovery_key.is_symlink()
            or recovery_key.resolve().is_relative_to(STATE_ROOT)
            or recovery_key.resolve().is_relative_to(CONFIG_ROOT)
            or recovery_key.stat().st_mode & 0o077
        ):
            raise ValueError("separately held, root-only recovery key required")
        scratch = STATE_ROOT / "backup-verification"
        scratch.mkdir(mode=0o700, exist_ok=True)
        if scratch.resolve() != scratch:
            raise ValueError("verification root must not traverse symlinks")
        from tempfile import TemporaryDirectory

        with TemporaryDirectory(prefix="candidate-", dir=scratch) as temporary:
            proof, worker, _ = verify_generation(
                source,
                Path(temporary),
                image=candidate["image_id"],
                trusted=Path(candidate["release"]) / "manifest.json",
                recovery_key=recovery_key,
            )
            proof.update(
                filename=source.name,
                ciphertext_sha256=encrypted["sha256"],
                network="none",
                runtime_status=worker["status"],
            )
    else:
        proof = fetch_restore_status(candidate)
    if not (
        proof.get("status") == "VERIFIED_ISOLATED_RESTORE"
        and proof.get("filename") == encrypted["filename"]
        and proof.get("ciphertext_sha256") == encrypted["sha256"]
        and proof.get("release_commit") == encrypted["release_commit"]
        and proof.get("acquisition_enabled") is False
        and proof.get("network") == "none"
        and proof.get("runtime_status") in {"STOPPED", "UNCONFIGURED"}
    ):
        return {
            "status": "AWAITING_INDEPENDENT_RESTORE",
            "filename": source.name,
            "sha256": encrypted["sha256"],
            "release_commit": encrypted["release_commit"],
            "next_action": "Run the fenced restore on the candidate destination, "
            "then repeat this command. The current destination remains active.",
        }
    selected = {
        **request,
        "schema": "platform-backup-destination/v1",
        "verified_generation": {
            "filename": encrypted["filename"],
            "sha256": encrypted["sha256"],
            "release_commit": encrypted["release_commit"],
        },
    }
    _atomic_json(current, selected)
    return {
        "status": "DESTINATION_VERIFIED",
        "mode": mode,
        "protection": "INDEPENDENT_SFTP" if mode == "sftp" else "LOCAL_ENCRYPTED_CHECKPOINT",
        "verified_generation": selected["verified_generation"],
        "prior_destination_and_generations": "RETAINED",
    }


def main() -> None:
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("backup", "restore", "status"))
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.config.read_text())
        with Path("/run/lock/polysia-platform-" + args.mode + ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            operation = {"backup": backup, "restore": restore, "status": fetch_restore_status}[
                args.mode
            ]
            receipt = operation(value)
            if args.mode != "status":
                receipt["checked_at"] = datetime.now(UTC).isoformat()
        output = Path(value["receipt"])
        output.write_text(json.dumps(receipt, sort_keys=True) + "\n")
        if args.mode == "restore":
            output.chmod(0o644)  # Root-owned read-only status directory in SFTP chroot.
        else:
            os.chown(output, 0, 10102)
            output.chmod(0o640)
        print(json.dumps(receipt, sort_keys=True))
        if receipt["status"] == "RECOVERY_OBJECTIVES_NOT_MET":
            raise SystemExit(1)
    except Exception as error:
        failure = {
            "status": "FAILED",
            "error_type": type(error).__name__,
            "checked_at": datetime.now(UTC).isoformat(),
            "next_action": "inspect private job configuration and retained generations",
        }
        if "value" in locals() and value.get("receipt"):
            Path(value["receipt"]).write_text(json.dumps(failure, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error_type": type(error).__name__,
                    "next_action": "inspect private job configuration and retained generations",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
