"""Bounded host backup/isolated restore jobs; run from a verified release."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_GENERATION = 536_870_912
NAME = re.compile(r"platform-\d{8}T\d{6}Z\.tar\.age")


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
    return [
        "sftp",
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


def _backup_generation(value: dict[str, Any]) -> dict[str, Any]:
    output = checked_root(value["output"], "/var/lib/polysia-platform/backup-out")
    output.mkdir(mode=0o700, exist_ok=True)
    os.chown(output, 10101, 10102)
    if shutil.disk_usage(output).free < 8_589_934_592:
        raise OSError("host free-disk reserve unavailable")
    release = Path(value["release"])
    manifest = json.loads((release / "manifest.json").read_text())
    name = datetime.now(UTC).strftime("platform-%Y%m%dT%H%M%SZ.tar.age")
    target = output / name
    recipient = Path(value["recipient_file"]).read_text().strip()
    args = isolated(
        value["image_id"],
        "/etc/polysia-platform/worker.json:/config/worker.json:ro",
        "/etc/polysia-platform/manifest.json:/config/manifest.json:ro",
        "/var/lib/polysia-platform/worker:/state:rw",
        "/var/lib/polysia-platform/control:/control:ro",
        "/var/lib/polysia-platform/publication:/publication:ro",
        f"{release}:/release:ro",
        f"{output}:/out:rw",
    )
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
    ssh = sftp_command(value)
    run(
        ssh,
        data=(
            f'put "{target}" /incoming/{name}.partial\n'
            f"rename /incoming/{name}.partial /incoming/{name}\n"
        ),
    )
    # Prune only this job's named generated ciphertext after confirmed upload.
    generations = sorted((p for p in output.iterdir() if NAME.fullmatch(p.name)), reverse=True)
    for old in generations[2:]:
        if old.is_symlink():
            raise ValueError("backup generation cannot be a symlink")
        old.unlink()
    return {**receipt, "status": "ENCRYPTED_UPLOADED", "filename": name}


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
    vault = checked_root(value["vault"], "/srv/polysia-platform-backups")
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


def _restore_generation(value: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    vault = checked_root(value["vault"], "/srv/polysia-platform-backups")
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
    image = value["image_id"]
    args = isolated(
        image, f"{stage}:/restore:rw", value["recovery_key"] + ":/run/recovery-key:ro", user="0:0"
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
    trusted = Path(value["release_manifest"])
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
    worker = json.loads(
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
    if worker["status"] != "STOPPED" or receipt["acquisition_enabled"] is not False:
        raise ValueError("restored_runtime_not_stopped")
    metadata = json.loads((stage / "bundle/platform-recovery.json").read_text())
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
    tar.unlink()
    if not objectives_met:
        receipt["status"] = "RECOVERY_OBJECTIVES_NOT_MET"
    receipt.update(
        rpo_met=0 <= age <= 86_400,
        rto_met=elapsed <= 3600,
        filename=source.name,
        measured_RPO_seconds=round(age, 3),
        measured_RTO_seconds=round(elapsed, 3),
        network="none",
        runtime_status=worker["status"],
    )
    return receipt


def fetch_restore_status(value: dict[str, Any]) -> dict[str, Any]:
    root = checked_root(value["output"], "/var/lib/polysia-platform/backup-out")
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
        }
        return {key: receipt[key] for key in allowed if key in receipt}
    except OSError, ValueError, subprocess.SubprocessError:
        return {
            "status": "UNKNOWN",
            "checked_at": datetime.now(UTC).isoformat(),
            "next_action": "inspect protected secondary restore journal",
        }
    finally:
        target.unlink(missing_ok=True)


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
