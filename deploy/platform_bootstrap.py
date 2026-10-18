"""Promote a hosted immutable artifact into isolated Platform service roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

INSTALL_ROOT = Path("/opt/polysia-platform")
STATE_ROOT = Path("/var/lib/polysia-platform")
CONFIG_ROOT = Path("/etc/polysia-platform")
SERVICE_ROOT = Path("/etc/systemd/system")


def verify_artifact(directory: Path, *, commit: str) -> dict[str, Any]:
    if re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise ValueError("exact source commit required")
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        manifest.get("schema_version") != "platform-release/v1"
        or manifest.get("commit") != commit
        or manifest.get("financial_schema") != 9
        or manifest.get("archive_name") != "polysia-image.tar.gz"
        or re.fullmatch(r"sha256:[a-f0-9]{64}", manifest.get("image_id", "")) is None
    ):
        raise ValueError("unsupported or mismatched release identity")
    image = directory / "polysia-image.tar.gz"
    if image.is_symlink() or not image.is_file() or image.stat().st_size > 536_870_912:
        raise ValueError("archive path or size invalid")
    with image.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != manifest.get("archive_sha256"):
        raise ValueError("release archive digest mismatch")
    if manifest.get("os_packages_sha256"):
        with (directory / "os-packages.txt").open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["os_packages_sha256"]:
                raise ValueError("release system-package inventory differs")
    for name, key in (
        ("platform_bootstrap.py", "bootstrap_sha256"),
        ("platform_backup.py", "backup_job_sha256"),
        ("platform_admin.py", "admin_sha256"),
    ):
        if manifest.get(key):
            path = directory / name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > 1_048_576
                or hashlib.sha256(path.read_bytes()).hexdigest() != manifest[key]
            ):
                raise ValueError("release administrative asset differs: " + name)
    return manifest


def container_command(
    image: str,
    *,
    role: str,
    hostname: str,
    gateway: bool = False,
    configured: bool = True,
) -> list[str]:
    if role not in {"worker", "publisher", "web"}:
        raise ValueError("unsupported process role")
    config_root, state_root = CONFIG_ROOT.as_posix(), STATE_ROOT.as_posix()
    args = [
        "/usr/bin/docker",
        "run",
        "--rm",
        "--name",
        "polysia-platform-" + role,
        "--log-driver=local",
        "--log-opt=max-size=5m",
        "--log-opt=max-file=2",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
        "--env",
        "TRADING_MODE=DATA_ONLY",
        "--env",
        "LIVE_TRADING_ENABLED=false",
    ]
    if role == "web":
        args += [
            "--user",
            "10102:10102",
            "--network",
            "host",
            "--memory",
            "128m",
            "--cpus",
            ".25",
            "--volume",
            f"{config_root}/web.json:/config/web.json:ro",
            "--volume",
            f"{config_root}/csrf-secret:/config/csrf-secret:ro",
        ]
        if gateway:
            args[args.index("host")] = "none"
            args += ["--volume", "/run/polysia-platform:/run/polysia-platform:rw"]
    else:
        args += [
            "--user",
            "10101:10102",
            "--network",
            "none" if role == "publisher" else "bridge",
            "--hostname",
            hostname,
            "--memory",
            "512m",
            "--cpus",
            ".5",
            "--volume",
            f"{config_root}/worker.json:/config/worker.json:ro",
            "--volume",
            f"{state_root}/worker:/state:rw",
        ]
        if configured:
            args += ["--volume", f"{config_root}/manifest.json:/config/manifest.json:ro"]
    args += [
        "--volume",
        f"{state_root}/publication:/publication:{'ro' if role == 'web' else 'rw'}",
        "--volume",
        f"{state_root}/control:/control:rw",
        image,
    ]
    args += {
        "worker": ["research", "platform-tick", "--config", "/config/worker.json"],
        "publisher": ["ops", "platform-publish", "--config", "/config/worker.json"],
        "web": ["system", "console", "--config", "/config/web.json"],
    }[role]
    return args


def archive_image_ids(directory: Path, manifest: dict[str, Any]) -> tuple[str, ...]:
    """Docker stores may address the same archive by config or OCI manifest ID."""
    with tarfile.open(directory / "polysia-image.tar.gz", "r:gz") as archive:

        def read_json(name: str) -> Any:
            member = archive.getmember(name)
            if not member.isfile() or member.size > 1_048_576:
                raise ValueError("invalid image metadata member")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("missing image metadata")
            return json.load(stream)

        docker_manifest = read_json("manifest.json")
        if not isinstance(docker_manifest, list) or len(docker_manifest) != 1:
            raise ValueError("release archive must contain one image")
        config_path = docker_manifest[0]["Config"]
        match = re.fullmatch(r"(?:blobs/sha256/)?([a-f0-9]{64})(?:\.json)?", config_path)
        if match is None:
            raise ValueError("invalid image config identity")
        config_digest = "sha256:" + match[1]
        identities = [config_digest]
        if "index.json" in archive.getnames():
            index = read_json("index.json")
            descriptors = index.get("manifests", [])
            if len(descriptors) != 1:
                raise ValueError("release archive must have one platform descriptor")
            descriptor = descriptors[0]["digest"]
            if re.fullmatch(r"sha256:[a-f0-9]{64}", descriptor) is None:
                raise ValueError("invalid OCI manifest identity")
            blob = read_json("blobs/sha256/" + descriptor.removeprefix("sha256:"))
            if blob.get("config", {}).get("digest") != config_digest:
                raise ValueError("OCI and Docker image config identities differ")
            identities.append(descriptor)
        if manifest["image_id"] not in identities:
            raise ValueError("source runner image ID is not bound by the archive")
        return tuple(identities)


def service_text(
    image: str,
    *,
    role: str,
    hostname: str,
    gateway: bool = False,
    configured: bool = True,
) -> str:
    command = container_command(
        image, role=role, hostname=hostname, gateway=gateway, configured=configured
    )
    if any(re.search(r"[\s%\n]", argument) for argument in command):
        raise ValueError("unsafe systemd argument")
    return (
        "[Unit]\nDescription=PolySia Platform " + role + "\nAfter=docker.service\n"
        "Requires=docker.service\n"
        + (
            "ConditionPathExists=!/etc/polysia-platform/restart-fenced\n"
            if role == "worker"
            else ""
        )
        + "\n[Service]\nType="
        + ("simple" if role == "web" else "oneshot")
        + "\nExecStart="
        + " ".join(command)
        + ("\nExecStop=/usr/bin/docker stop -t 25 polysia-platform-web" if role == "web" else "")
        + "\nTimeoutStartSec=180\nTimeoutStopSec=35\nKillMode=control-group\n"
        + (
            "RuntimeDirectory=polysia-platform\nRuntimeDirectoryMode=0750\n"
            "ExecStartPre=/usr/bin/chown 10102:10102 /run/polysia-platform\n"
            if role == "web" and gateway
            else ""
        )
        + "CPUQuota=50%\nMemoryMax=640M\nTasksMax=256\n"
        "StandardOutput=journal\nStandardError=journal\n"
        "LogRateLimitIntervalSec=60s\nLogRateLimitBurst=10\n"
        + ("Restart=on-failure\nRestartSec=10\n" if role == "web" else "")
    )


def run(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def activation_preflight(commit: str) -> None:
    """Refuse code/schema changes around active financial identities; never downgrade data."""
    config = CONFIG_ROOT / "worker.json"
    if not config.exists():
        return
    value = json.loads(config.read_text())
    if value.get("acquisition_enabled") is not False or value.get("admission"):
        raise ValueError("disable acquisition and reconcile admission before release activation")
    if value.get("release_commit") == commit:
        return
    authority = STATE_ROOT / "worker" / "authority.sqlite3"
    if authority.exists():
        with closing(sqlite3.connect(authority.as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("SELECT stopped FROM authority").fetchone() != (1,):
                raise ValueError("durable authority STOP required before activation")
    database = STATE_ROOT / "worker" / "financial.sqlite3"
    if not database.exists():
        return
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchall() != [
            (9,),
        ]:
            raise ValueError("incompatible financial schema; retain old executable and data")
        for experiment, config_json in connection.execute(
            "SELECT experiment_id,config_json FROM continuous_shadow_experiments "
            "WHERE lifecycle!='FINALIZED'",
        ):
            config_value = json.loads(config_json)
            if config_value.get("runtime_version") == "continuous-shadow-native-research-v2":
                raise ValueError(
                    "active pinned continuous session requires controlled finalization"
                )
            positions = connection.execute(
                "SELECT quantity FROM continuous_shadow_positions WHERE experiment_id=?",
                (experiment,),
            ).fetchall()
            pending = connection.execute(
                "SELECT COUNT(*) FROM continuous_shadow_pending_observations "
                "WHERE experiment_id=? AND admission_state='PENDING'",
                (experiment,),
            ).fetchone()[0]
            if any(Decimal(row[0]) != 0 for row in positions) or pending:
                raise ValueError(
                    "open inventory or pending observations require retained executable"
                )


def bootstrap(directory: Path, *, commit: str, install_units: bool = True) -> dict[str, Any]:
    import grp
    import pwd
    import socket

    manifest = verify_artifact(directory, commit=commit)
    if os.geteuid() != 0:
        raise PermissionError("administrative bootstrap is required")
    activation_preflight(commit)
    for root in (INSTALL_ROOT, STATE_ROOT, CONFIG_ROOT):
        if root.is_symlink() or root.resolve() != root:
            raise ValueError("deployment root must be an isolated absolute directory")
    if shutil.disk_usage("/var/lib").free < 8_589_934_592:
        raise OSError("Platform bootstrap cannot preserve the host disk reserve")
    for name, number in (("polysia-platform-worker", 10101), ("polysia-platform-web", 10102)):
        try:
            if grp.getgrgid(number).gr_name != name:
                raise ValueError("dedicated Platform group ID is already occupied")
        except KeyError:
            run("groupadd", "--system", "--gid", str(number), name)
        try:
            if pwd.getpwuid(number).pw_name != name:
                raise ValueError("dedicated Platform user ID is already occupied")
        except KeyError:
            run(
                "useradd",
                "--system",
                "--uid",
                str(number),
                "--gid",
                str(number),
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
                name,
            )
    for root in (INSTALL_ROOT, STATE_ROOT, CONFIG_ROOT):
        root.mkdir(mode=0o750, parents=True, exist_ok=True)
    for root in (INSTALL_ROOT, CONFIG_ROOT, STATE_ROOT):
        os.chown(root, 0, 10102)
        root.chmod(0o750)
    for name in ("worker", "publication", "control"):
        root = STATE_ROOT / name
        if root.is_symlink():
            raise ValueError("state subdirectory cannot be a symlink")
        root.mkdir(exist_ok=True)
        os.chown(root, 10101, 10102)
        root.chmod(0o700 if name == "worker" else 0o2770 if name == "control" else 0o2750)
    release = INSTALL_ROOT / "releases" / commit
    if release.is_symlink() or not release.resolve().is_relative_to(INSTALL_ROOT):
        raise ValueError("release root escapes isolated installation")
    release.mkdir(parents=True, exist_ok=True)
    assets = ["manifest.json", "polysia-image.tar.gz"]
    for name, key in (
        ("platform_bootstrap.py", "bootstrap_sha256"),
        ("platform_admin.py", "admin_sha256"),
    ):
        if manifest.get(key):
            assets.append(name)
    if manifest.get("os_packages_sha256"):
        assets.append("os-packages.txt")
    if manifest.get("backup_job_sha256"):
        if (
            hashlib.sha256((directory / "platform_backup.py").read_bytes()).hexdigest()
            != manifest["backup_job_sha256"]
        ):
            raise ValueError("backup job differs from tested release")
        assets.append("platform_backup.py")
    for name in assets:
        target = release / name
        if target.is_symlink():
            raise ValueError("immutable release asset cannot be a symlink")
        if target.exists():
            with target.open("rb") as existing, (directory / name).open("rb") as incoming:
                matches = (
                    hashlib.file_digest(existing, "sha256").digest()
                    == hashlib.file_digest(incoming, "sha256").digest()
                )
            if not matches:
                raise ValueError("existing immutable release differs")
        else:
            shutil.copy2(directory / name, target)
    run("docker", "load", "--input", str(release / "polysia-image.tar.gz"))
    image = None
    for identity in archive_image_ids(directory, manifest):
        try:
            loaded = run("docker", "image", "inspect", identity, "--format", "{{.Id}}")
            if loaded == identity:
                image = identity
                break
        except subprocess.CalledProcessError:
            continue
    if image is None:
        raise ValueError("no archive-bound image identity is available after load")
    installed = run(
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "cat",
        image,
        "/opt/polysia/BUILD_COMMIT",
    )
    if installed != commit:
        raise ValueError("installed artifact source mismatch")
    run("docker", "run", "--rm", "--network", "none", image, "system", "health")
    rollback = release / "units-before"
    rollback.mkdir(mode=0o700, exist_ok=True)
    for role in ("worker", "publisher", "web"):
        target = SERVICE_ROOT / f"polysia-platform-{role}.service"
        if target.is_symlink():
            raise ValueError("dedicated service must not be a symlink")
        if target.exists() and not (rollback / target.name).exists():
            shutil.copy2(target, rollback / target.name)
        if install_units:
            target.write_text(service_text(image, role=role, hostname=socket.gethostname()))
    for role in ("worker", "publisher"):
        (SERVICE_ROOT / f"polysia-platform-{role}.timer").write_text(
            "[Unit]\nDescription=PolySia Platform " + role + " schedule\n\n[Timer]\n"
            "OnCalendar=*-*-* *:*:00 UTC\nPersistent=true\nAccuracySec=1s\n\n"
            "[Install]\nWantedBy=timers.target\n",
        )
    run("systemctl", "daemon-reload")
    # Promotion installs supervision but never enables acquisition or fabricates
    # an identity/manifest. Configuration and admission are separate verified steps.
    receipt = {
        "status": "ARTIFACT_INSTALLED",
        "commit": commit,
        "image_id": image,
        "acquisition_enabled": False,
        "web_started": False,
    }
    (release / "installation-receipt.json").write_text(json.dumps(receipt, sort_keys=True))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        verify_artifact(args.artifact_directory, commit=args.commit)
        if args.verify_only
        else bootstrap(args.artifact_directory, commit=args.commit)
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
