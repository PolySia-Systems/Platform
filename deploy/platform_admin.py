"""Guided, root-only maintenance of one disabled Platform installation.

Run the manifest-verified script from an exact published release. No provider
credentials, admission or acquisition policy is created by installation.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import tarfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

if __name__.startswith("deploy."):
    from deploy import platform_bootstrap as core

CADDY_VERSION = "2.11.7"
CADDY_SHA512 = (
    "a7a433a1b133efc3c8d10eb0b99d52a24b5ef5c322dc77f5282182b1c0402139ab83f"
    "3a99f0c52409df77d20123fb0b523edad8a66d8f5e49136197bf61ef0e7"
)
SCHEMA = "platform-installation/v1"
MAX_ASSET = 536_870_912


def load_core(args: argparse.Namespace):
    """Load only the bootstrap bytes bound to the same trusted release as this entry."""
    directory = (args.artifact_directory or Path(__file__).resolve().parent).resolve()
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        if (
            not args.tag
            or re.fullmatch(r"v\d+\.\d+\.\d+", args.tag) is None
            or re.fullmatch(r"[a-f0-9]{40}", args.commit or "") is None
        ):
            raise ValueError("first setup requires an exact --tag and --commit")
        origin = "https://github.com/PolySia-Systems/Platform/releases/download/" + args.tag + "/"
        with urlopen(origin + "manifest.json", timeout=30) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("release manifest exceeds size limit")
        manifest = json.loads(raw)
        if manifest.get("commit") != args.commit:
            raise ValueError("release source differs from requested commit")
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != manifest["admin_sha256"]:
            raise ValueError("administrative entry differs from trusted release")
        manifest_path.write_bytes(raw)
        target = directory / "platform_bootstrap.py"
        if not target.exists():
            download(origin + target.name, target)
    manifest = json.loads(manifest_path.read_text())
    for path, key in (
        (Path(__file__), "admin_sha256"),
        (directory / "platform_bootstrap.py", "bootstrap_sha256"),
    ):
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get(key):
            raise ValueError("administrative release bytes differ: " + path.name)
    specification = importlib.util.spec_from_file_location(
        "platform_bootstrap",
        directory / "platform_bootstrap.py",
    )
    if specification is None or specification.loader is None:
        raise ValueError("verified bootstrap cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def atomic(path: Path, value: object, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("configuration path must not traverse symlinks")
    temporary = path.with_suffix(path.suffix + ".partial")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate(value: dict) -> dict:
    if (
        value.get("schema") != SCHEMA
        or re.fullmatch(r"[a-f0-9]{40}", value.get("commit", "")) is None
        or value.get("profile") not in {"private", "own-domain", "cloudflare"}
        or value.get("backup", {}).get("mode") not in {"none", "local", "sftp"}
    ):
        raise ValueError("unsupported installation configuration")
    profile, hostname = value["profile"], value.get("hostname", "")
    if (
        re.fullmatch(r"[a-z0-9.-]+", hostname) is None
        or ".." in hostname
        or hostname.startswith(("-", "."))
        or hostname.endswith(("-", "."))
    ):
        raise ValueError("valid lowercase hostname required")
    if profile == "private" and hostname != "localhost":
        raise ValueError("private access must use localhost")
    if profile == "own-domain" and ("." not in hostname or not value.get("public_opt_in")):
        raise ValueError("own-domain requires an explicit public hostname and opt-in")
    roles = value.get("roles", {})
    if (
        not roles
        or len(roles) > 16
        or any(
            re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user) is None
            or role not in {"reader", "operator"}
            for user, role in roles.items()
        )
    ):
        raise ValueError("explicit reader/operator usernames required")
    if "operator" not in roles.values():
        raise ValueError("at least one protected operator is required")
    return value


def phase(config: dict, stage: str, **fields: object) -> None:
    path = core.CONFIG_ROOT / "maintenance-receipt.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    if previous.get("commit") != config["commit"]:
        previous = {}
    atomic(
        path,
        {
            **previous,
            "schema": "platform-maintenance/v1",
            "commit": config["commit"],
            "phase": stage,
            "checked_at": datetime.now(UTC).isoformat(),
            **fields,
        },
    )


def download(url: str, target: Path) -> None:
    if not url.startswith("https://github.com/") or target.exists() or target.is_symlink():
        raise ValueError("unused asset path and trusted HTTPS release origin required")
    temporary = target.with_suffix(target.suffix + ".partial")
    if temporary.is_symlink():
        raise ValueError("download staging must not be a symlink")
    if temporary.exists():
        temporary.unlink()  # Only this known incomplete, unverified asset; never retained evidence.
    with urlopen(url, timeout=30) as source, temporary.open("xb") as output:
        size = 0
        while chunk := source.read(1_048_576):
            size += len(chunk)
            if size > MAX_ASSET:
                raise ValueError("release download exceeds capacity bound")
            output.write(chunk)
    temporary.replace(target)


def fetch_release(tag: str, commit: str) -> Path:
    if re.fullmatch(r"v\d+\.\d+\.\d+", tag) is None:
        raise ValueError("exact immutable release tag required")
    if re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise ValueError("exact trusted release source commit required")
    root = core.INSTALL_ROOT / "downloads" / commit
    if root.is_symlink() or not root.resolve().is_relative_to(core.INSTALL_ROOT):
        raise ValueError("download root escapes installation")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    origin = "https://github.com/PolySia-Systems/Platform/releases/download/" + tag + "/"
    if not (root / "manifest.json").exists():
        download(origin + "manifest.json", root / "manifest.json")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("commit") != commit:
        raise ValueError("published release differs from requested source")
    assets = {
        "polysia-image.tar.gz": "archive_sha256",
        "os-packages.txt": "os_packages_sha256",
        "platform_bootstrap.py": "bootstrap_sha256",
        "platform_backup.py": "backup_job_sha256",
        "platform_admin.py": "admin_sha256",
    }
    for name, key in assets.items():
        if not (root / name).exists():
            download(origin + name, root / name)
        with (root / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest.get(key):
                raise ValueError("published asset digest mismatch: " + name)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != manifest["admin_sha256"]:
        raise ValueError("run the administrative entry from this exact tested release")
    core.verify_artifact(root, commit=commit)
    return root


def preflight(value: dict) -> None:
    import grp
    import platform
    import pwd

    validate(value)
    if os.geteuid() != 0 or platform.machine() not in {"x86_64", "amd64"}:
        raise ValueError("Ubuntu LTS amd64 and administrative SSH/root access are required")
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    if release.get("ID", "").strip('"') != "ubuntu":
        raise ValueError("supported server profile requires Ubuntu LTS")
    if release.get("VERSION_ID", "").strip('"') not in {"24.04", "26.04"}:
        raise ValueError("supported Ubuntu LTS releases: 24.04, 26.04")
    for root in (core.INSTALL_ROOT, core.CONFIG_ROOT, core.STATE_ROOT, core.SERVICE_ROOT):
        if root.is_symlink() or root.resolve() != root:
            raise ValueError("installation roots must not traverse symlinks")
    if shutil.disk_usage("/var/lib").free < 8_589_934_592:
        raise ValueError("at least 8 GiB free is required for staging, rollback and host reserve")
    memory = int(Path("/proc/meminfo").read_text().split("MemAvailable:", 1)[1].split()[0])
    if memory < 1_048_576:
        raise ValueError("at least 1 GiB available memory is required")
    core.run("docker", "info", "--format", "{{.ServerVersion}}")
    core.run("systemctl", "--version")
    for name, uid in (("polysia-platform-worker", 10101), ("polysia-platform-web", 10102)):
        for lookup, expected, field in (
            (pwd.getpwuid, uid, "pw_name"),
            (grp.getgrgid, uid, "gr_name"),
        ):
            try:
                if getattr(lookup(expected), field) != name:
                    raise ValueError("dedicated identity number is already occupied")
            except KeyError:
                pass
        try:
            if pwd.getpwnam(name).pw_uid != uid or grp.getgrnam(name).gr_gid != uid:
                raise ValueError("dedicated identity name is already occupied")
        except KeyError:
            pass
    # An existing installation owns its bound listeners. Its activation path
    # validates/stops only dedicated units; a fresh install may not claim a port.
    retained_web = (
        (core.CONFIG_ROOT / "worker.json").is_file()
        and (core.CONFIG_ROOT / "web.json").is_file()
        and (core.SERVICE_ROOT / "polysia-platform-web.service").is_file()
    )
    if not (core.CONFIG_ROOT / "installation.json").exists() and not retained_web:
        ports = (
            (8443,)
            if value["profile"] == "private"
            else ((80, 443) if value["profile"] == "own-domain" else (8765,))
        )
        for port in ports:
            with socket.socket() as listener:
                listener.bind(
                    ("127.0.0.1" if value["profile"] != "own-domain" else "0.0.0.0", port)
                )


def install_gateway() -> Path:
    root = core.INSTALL_ROOT / "gateway" / CADDY_VERSION
    if root.resolve() != root:
        raise ValueError("gateway installation must not traverse symlinks")
    root.mkdir(parents=True, exist_ok=True, mode=0o755)
    archive = root / "caddy.tar.gz"
    if not archive.exists():
        download(
            "https://github.com/caddyserver/caddy/releases/download/v"
            + CADDY_VERSION
            + "/caddy_"
            + CADDY_VERSION
            + "_linux_amd64.tar.gz",
            archive,
        )
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha512").hexdigest() != CADDY_SHA512:
            raise ValueError("pinned gateway archive checksum differs")
    binary = root / "caddy"
    with tarfile.open(archive, "r:gz") as bundle:
        for name in ("caddy", "LICENSE"):
            member = bundle.getmember(name)
            if not member.isfile() or member.size > 100_000_000:
                raise ValueError("invalid pinned gateway member")
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError("gateway member missing")
            incoming = stream.read()
            target = root / name
            if target.is_symlink() or target.exists() and target.read_bytes() != incoming:
                raise ValueError("existing immutable gateway differs")
            if not target.exists():
                target.write_bytes(incoming)
        binary.chmod(0o755)
    return binary


def image_json(image: str, code: str, value: dict) -> str:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--memory",
            "128m",
            "--cpus",
            ".25",
            "--pids-limit",
            "64",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--entrypoint",
            "python",
            image,
            "-c",
            code,
        ],
        input=json.dumps(value),
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    )
    return result.stdout


def configure(
    value: dict, *, image: str, allow_change: bool = False, cloudflare: dict | None = None
) -> dict:
    """Stage validated access/configuration before any activation."""
    validate(value)
    current = core.CONFIG_ROOT / "installation.json"
    if current.exists() and validate(json.loads(current.read_text())) != value and not allow_change:
        raise ValueError("existing configuration differs; use an explicit maintenance change")
    if value["profile"] == "cloudflare":
        if cloudflare:
            if (core.CONFIG_ROOT / "web.json").exists():
                raise ValueError(
                    "existing Cloudflare identity is preserved; no identity replacement"
                )
            issuer = cloudflare["issuer"]
            if (
                re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", issuer) is None
                or re.fullmatch(r"[a-f0-9]{64}", cloudflare["audience"]) is None
                or re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", cloudflare["owner"]) is None
            ):
                raise ValueError(
                    "valid Access issuer, application audience and owner email required"
                )
            atomic(core.CONFIG_ROOT / "csrf-secret", secrets.token_hex(32), mode=0o640)
            os.chown(core.CONFIG_ROOT / "csrf-secret", 0, 10102)
            atomic(
                core.CONFIG_ROOT / "web.json",
                {
                    "issuer": issuer,
                    "audience": cloudflare["audience"],
                    "roles": {cloudflare["owner"]: "operator"},
                    "origin": "https://" + value["hostname"],
                    "port": 8765,
                    "commands": "/control/commands.sqlite3",
                    "publication": "/publication/publication.json",
                    "csrf_secret_file": "/config/csrf-secret",
                },
                mode=0o640,
            )
            os.chown(core.CONFIG_ROOT / "web.json", 0, 10102)
        if not (core.CONFIG_ROOT / "web.json").exists():
            return {
                "status": "ACCESS_CONFIGURATION_REQUIRED",
                "next_action": "Provide your Access issuer, audience and owner identity "
                "through the guided administrative entry.",
            }
        existing_web = json.loads((core.CONFIG_ROOT / "web.json").read_text())
        if existing_web["origin"] != "https://" + value["hostname"]:
            raise ValueError(
                "existing Cloudflare origin is preserved; commission an authorized route "
                "before changing its hostname",
            )
        atomic(current, value)
        return {
            "status": "EXISTING_CLOUDFLARE_PRESERVED"
            if not cloudflare
            else "CLOUDFLARE_BACKEND_CONFIGURED",
            "origin": "https://" + value["hostname"],
            "route": "EXTERNAL_OWNER_COMMISSIONING_REQUIRED" if cloudflare else "PRESERVED",
        }
    caddy = install_gateway()
    access = core.CONFIG_ROOT / "gateway-credentials.json"
    if access.exists():
        credentials = json.loads(access.read_text())
    else:
        credentials = {name: secrets.token_urlsafe(32) for name in value["roles"]}
        atomic(access, credentials)
    passwords = {}
    for name in value["roles"]:
        if name not in credentials:
            credentials[name] = secrets.token_urlsafe(32)
        password = credentials[name]
        passwords[name] = subprocess.run(
            [str(caddy), "hash-password", "--algorithm", "bcrypt", "--bcrypt-cost", "10"],
            input=password + "\n",
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
    origin = (
        "https://localhost:8443"
        if value["profile"] == "private"
        else ("https://" + value["hostname"])
    )
    gateway = image_json(
        image,
        "import json,sys; from polysia.deployment.gateway import gateway_config; "
        "print(gateway_config(**json.load(sys.stdin)))",
        {
            "profile": value["profile"],
            "origin": origin,
            "socket_path": "/run/polysia-platform/web.sock",
            "passwords": passwords,
        },
    )
    staged = core.CONFIG_ROOT / "Caddyfile.staged"
    atomic(staged, gateway, mode=0o640)
    core.run(str(caddy), "adapt", "--config", str(staged), "--adapter", "caddyfile")
    if not (core.CONFIG_ROOT / "csrf-secret").exists():
        atomic(core.CONFIG_ROOT / "csrf-secret", secrets.token_hex(32), mode=0o640)
    os.chown(core.CONFIG_ROOT / "csrf-secret", 0, 10102)
    web = {
        "profile": value["profile"],
        "origin": origin,
        "roles": value["roles"],
        "unix_socket": "/run/polysia-platform/web.sock",
        "commands": "/control/commands.sqlite3",
        "publication": "/publication/publication.json",
        "csrf_secret_file": "/config/csrf-secret",
    }
    atomic(core.CONFIG_ROOT / "web.json", web, mode=0o640)
    os.chown(core.CONFIG_ROOT / "web.json", 0, 10102)
    staged.replace(core.CONFIG_ROOT / "Caddyfile")
    os.chown(core.CONFIG_ROOT / "Caddyfile", 0, 10102)
    atomic(current, value)
    atomic(access, {name: credentials[name] for name in value["roles"]})
    return {
        "status": "ACCESS_CONFIGURED",
        "origin": origin,
        "credentials_file": str(access),
        "profile": value["profile"],
    }


def gateway_unit(caddy: Path, *, public: bool) -> str:
    return (
        "[Unit]\nDescription=PolySia authenticated HTTPS gateway\n"
        "After=polysia-platform-web.service\nRequires=polysia-platform-web.service\n\n"
        "[Service]\nUser=10102\nGroup=10102\nUMask=0077\n"
        "Environment=XDG_DATA_HOME=/var/lib/polysia-platform/gateway\n"
        "ExecStart=" + str(caddy) + " run --config /etc/polysia-platform/Caddyfile\n"
        "Restart=on-failure\nRestartSec=5\nNoNewPrivileges=true\nProtectSystem=strict\n"
        "ProtectHome=true\nPrivateTmp=true\nRestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n"
        "ReadWritePaths=/var/lib/polysia-platform/gateway\n"
        "InaccessiblePaths=/var/lib/polysia-platform/worker /var/lib/polysia-platform/control\n"
        "CapabilityBoundingSet="
        + ("CAP_NET_BIND_SERVICE" if public else "")
        + "\n"
        + ("AmbientCapabilities=CAP_NET_BIND_SERVICE\n" if public else "")
        + "MemoryMax=192M\nCPUQuota=25%\nTasksMax=64\nLimitNOFILE=256\n"
        "LogRateLimitIntervalSec=60s\nLogRateLimitBurst=20\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )


def activate(value: dict, *, image: str) -> None:
    gateway_state = core.STATE_ROOT / "gateway"
    gateway_state.mkdir(exist_ok=True, mode=0o700)
    os.chown(gateway_state, 10102, 10102)
    worker = core.CONFIG_ROOT / "worker.json"
    if not worker.exists():
        atomic(
            worker,
            {
                "installation_state": "UNCONFIGURED",
                "release_commit": value["commit"],
                "database": "/state/financial.sqlite3",
                "manifest": "/config/manifest.json",
                "authority": "/state/authority.sqlite3",
                "commands": "/control/commands.sqlite3",
                "status": "/state/status.json",
                "publication": "/publication/publication.json",
                "cohort": "/state/cohort.json",
                "acquisition_enabled": False,
                "admission": {},
                "backup_mode": "none",
            },
            mode=0o640,
        )
        os.chown(worker, 0, 10102)
    else:
        previous = json.loads(worker.read_text())
        previous["backup_mode"] = value["backup"]["mode"]
        if previous["release_commit"] != value["commit"]:
            # The bootstrap's activation preflight already refused incompatible
            # inventory, pinned sessions, admission and active acquisition.
            previous["release_commit"] = value["commit"]
        atomic(worker, previous, mode=0o640)
        os.chown(worker, 0, 10102)
    for role in ("worker", "publisher", "web"):
        text = core.service_text(
            image,
            role=role,
            hostname=socket.gethostname(),
            gateway=value["profile"] != "cloudflare",
            configured=(core.CONFIG_ROOT / "manifest.json").is_file(),
        )
        atomic(core.SERVICE_ROOT / ("polysia-platform-" + role + ".service"), text, mode=0o644)
    if value["profile"] == "cloudflare":
        core.run("systemctl", "daemon-reload")
        core.run("systemctl", "restart", "polysia-platform-web.service")
        core.run(
            "systemctl",
            "start",
            "polysia-platform-worker.service",
            "polysia-platform-publisher.service",
        )
        core.run(
            "systemctl",
            "enable",
            "--now",
            "polysia-platform-worker.timer",
            "polysia-platform-publisher.timer",
        )
        return
    atomic(
        core.SERVICE_ROOT / "polysia-platform-gateway.service",
        gateway_unit(
            core.INSTALL_ROOT / "gateway" / CADDY_VERSION / "caddy",
            public=value["profile"] == "own-domain",
        ),
        mode=0o644,
    )
    core.run("systemctl", "daemon-reload")
    # Atomic config replacement changes the host inode. Recreate the container
    # bind mount before enabling the gateway so revocations take effect.
    core.run("systemctl", "restart", "polysia-platform-web.service")
    core.run("systemctl", "restart", "polysia-platform-gateway.service")
    core.run("systemctl", "start", "polysia-platform-worker.service")
    core.run("systemctl", "start", "polysia-platform-publisher.service")
    core.run(
        "systemctl",
        "enable",
        "--now",
        "polysia-platform-worker.timer",
        "polysia-platform-publisher.timer",
        "polysia-platform-gateway.service",
    )


def verify_access(value: dict) -> None:
    """Confirm the actual gateway/certificate/application boundary before claiming setup."""
    if value["profile"] == "cloudflare":
        return
    deadline = time.monotonic() + 60
    certificate = core.STATE_ROOT / "gateway/caddy/pki/authorities/local/root.crt"
    if value["profile"] == "private":
        while not certificate.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        context = ssl.create_default_context(cafile=str(certificate))
        origin = "https://localhost:8443"
    else:
        context, origin = ssl.create_default_context(), "https://" + value["hostname"]
    credentials = json.loads((core.CONFIG_ROOT / "gateway-credentials.json").read_text())
    name = next(name for name, role in value["roles"].items() if role == "operator")
    authorization = base64.b64encode((name + ":" + credentials[name]).encode()).decode()
    request = Request(origin, headers={"Authorization": "Basic " + authorization})
    while time.monotonic() < deadline:
        try:
            with urlopen(request, context=context, timeout=5) as response:
                if response.status == 200 and b"PolySia Console" in response.read(65536):
                    return
        except OSError:
            time.sleep(0.5)
    raise ValueError("trusted HTTPS is not ready; inspect the gateway/certificate receipt")


def publish_health() -> dict:
    value = json.loads((core.CONFIG_ROOT / "health.json").read_text())
    if value.get("schema") != "platform-health/v1":
        raise ValueError("validated health configuration required")
    receipt = {
        "status": "UNKNOWN",
        "component": "gateway",
        "version": value["version"],
        "release_commit": value["commit"],
        "profile": value["profile"],
        "checked_at": datetime.now(UTC).isoformat(),
        "backup_mode": value["backup_mode"],
    }
    if value["profile"] == "cloudflare":
        receipt.update(
            status="EXTERNAL_IDENTITY_CONFIGURED",
            certificate_trust="CLOUDFLARE",
            next_action="Use the existing protected route; observation has separate gates.",
        )
    else:
        try:
            private = value["profile"] == "private"
            context = ssl.create_default_context(
                cafile=str(core.CONFIG_ROOT / "gateway-ca.crt") if private else None,
            )
            with (
                socket.create_connection(("127.0.0.1", 8443 if private else 443), timeout=3) as raw,
                context.wrap_socket(raw, server_hostname=value["hostname"]) as protected,
            ):
                peer = protected.getpeercert()
            expires = ssl.cert_time_to_seconds(peer["notAfter"])
            remaining = expires - time.time()
            warning = 3600 if private else 172800
            receipt.update(
                status="CERTIFICATE_CURRENT" if remaining > warning else "CERTIFICATE_NEAR_EXPIRY",
                certificate_trust="PRIVATE_CA" if private else "PUBLIC_CA",
                expires_at=datetime.fromtimestamp(expires, UTC).isoformat(),
                last_success=receipt["checked_at"],
                next_action="No action required."
                if remaining > warning
                else "Inspect renewal, domain reachability and dedicated gateway logs.",
            )
        except (OSError, ValueError, KeyError):
            receipt.update(
                status="FAILED",
                reason="gateway_tls_unavailable",
                impact="Browser TLS is unavailable or untrusted; acquisition remains separate.",
                next_action="Inspect gateway, certificate and hostname; use protected SSH STOP.",
            )
    atomic(core.STATE_ROOT / "publication/installation-status.json", receipt, mode=0o640)
    if os.geteuid() == 0:
        os.chown(core.STATE_ROOT / "publication/installation-status.json", 10101, 10102)
    return receipt


def install_health(value: dict) -> None:
    release = core.INSTALL_ROOT / "releases" / value["commit"]
    manifest = json.loads((release / "manifest.json").read_text())
    if value["profile"] == "private":
        ca = core.STATE_ROOT / "gateway/caddy/pki/authorities/local/root.crt"
        atomic(core.CONFIG_ROOT / "gateway-ca.crt", ca.read_text(), mode=0o640)
        os.chown(core.CONFIG_ROOT / "gateway-ca.crt", 0, 10102)
    atomic(
        core.CONFIG_ROOT / "health.json",
        {
            "schema": "platform-health/v1",
            "commit": value["commit"],
            "version": manifest.get("version", "UNKNOWN"),
            "profile": value["profile"],
            "hostname": value["hostname"],
            "backup_mode": value["backup"]["mode"],
        },
        mode=0o640,
    )
    os.chown(core.CONFIG_ROOT / "health.json", 0, 10102)
    executable = release / "platform_admin.py"
    atomic(
        core.SERVICE_ROOT / "polysia-platform-health.service",
        "[Unit]\nDescription=PolySia local certificate and installation health\n[Service]\n"
        "Type=oneshot\nUser=10101\nGroup=10102\nExecStart=/usr/bin/python3 "
        + str(executable)
        + " health\nNoNewPrivileges=true\nProtectSystem=strict\nProtectHome=true\n"
        "ReadWritePaths=/var/lib/polysia-platform/publication\n"
        "InaccessiblePaths=/var/lib/polysia-platform/worker /var/lib/polysia-platform/control\n"
        "MemoryMax=64M\nCPUQuota=10%\nTasksMax=16\nTimeoutStartSec=15\n",
        mode=0o644,
    )
    atomic(
        core.SERVICE_ROOT / "polysia-platform-health.timer",
        "[Unit]\nDescription=PolySia local health schedule\n[Timer]\nOnCalendar=*-*-* *:*:15 UTC\n"
        "Persistent=true\n[Install]\nWantedBy=timers.target\n",
        mode=0o644,
    )
    publish_health()
    core.run("systemctl", "daemon-reload")
    core.run("systemctl", "enable", "--now", "polysia-platform-health.timer")


def load_backup(commit: str):
    directory = core.INSTALL_ROOT / "releases" / commit
    manifest = json.loads((directory / "manifest.json").read_text())
    path = directory / "platform_backup.py"
    if (
        path.is_symlink()
        or manifest.get("commit") != commit
        or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["backup_job_sha256"]
    ):
        raise ValueError("verified release backup job required")
    specification = importlib.util.spec_from_file_location("platform_backup", path)
    if specification is None or specification.loader is None:
        raise ValueError("verified backup implementation cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def preserve_rollback() -> dict | None:
    worker = core.CONFIG_ROOT / "worker.json"
    if not worker.exists():
        return None
    old_commit = json.loads(worker.read_text())["release_commit"]
    files = [
        core.CONFIG_ROOT / name
        for name in (
            "installation.json",
            "worker.json",
            "web.json",
            "csrf-secret",
            "Caddyfile",
            "gateway-credentials.json",
            "backup-job.json",
            "backup.json",
            "backup-status-fetch.json",
            "health.json",
            "gateway-ca.crt",
        )
    ]
    files += [
        core.SERVICE_ROOT / ("polysia-platform-" + name)
        for name in (
            "worker.service",
            "worker.timer",
            "publisher.service",
            "publisher.timer",
            "web.service",
            "gateway.service",
            "backup.service",
            "backup.timer",
            "recovery-status.service",
            "recovery-status.timer",
            "health.service",
            "health.timer",
        )
    ]
    existing = {}
    for path in files:
        if path.is_symlink():
            raise ValueError("rollback inputs must not be symlinks")
        if path.exists():
            stat = path.stat()
            existing[str(path)] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mode": stat.st_mode & 0o777,
                "uid": stat.st_uid,
                "gid": stat.st_gid,
            }
    identity = hashlib.sha256(json.dumps(existing, sort_keys=True).encode()).hexdigest()
    root = core.INSTALL_ROOT / "checkpoints" / identity
    if root.resolve() != root:
        raise ValueError("rollback checkpoint must not traverse symlinks")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for source, metadata in existing.items():
        digest = metadata["sha256"]
        target = root / digest
        if not target.exists():
            shutil.copy2(source, target)
            target.chmod(0o600)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("existing rollback checkpoint differs")
    receipt = {
        "schema": "platform-rollback/v1",
        "commit": old_commit,
        "root": str(root),
        "files": existing,
    }
    atomic(root / "checkpoint.json", receipt)
    atomic(core.CONFIG_ROOT / "rollback-checkpoint.json", receipt)
    return receipt


def rollback() -> dict:
    receipt = json.loads((core.CONFIG_ROOT / "rollback-checkpoint.json").read_text())
    if (
        receipt.get("schema") != "platform-rollback/v1"
        or re.fullmatch(r"[a-f0-9]{40}", receipt.get("commit", "")) is None
    ):
        raise ValueError("verified compatible rollback checkpoint required")
    core.activation_preflight(receipt["commit"])
    root = Path(receipt["root"])
    if root.resolve() != root or not root.is_relative_to(core.INSTALL_ROOT / "checkpoints"):
        raise ValueError("rollback checkpoint outside installation")
    restored = []
    for target, metadata in receipt["files"].items():
        digest = metadata["sha256"]
        path = Path(target)
        if path.parent not in {core.CONFIG_ROOT, core.SERVICE_ROOT} or path.is_symlink():
            raise ValueError("rollback destination outside protected configuration")
        if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ValueError("rollback file identity is invalid")
        saved = root / digest
        if saved.is_symlink() or hashlib.sha256(saved.read_bytes()).hexdigest() != digest:
            raise ValueError("rollback configuration identity differs")
        restored.append((path, saved, metadata))
    for unit in (
        "worker.timer",
        "worker.service",
        "publisher.timer",
        "web.service",
        "gateway.service",
    ):
        subprocess.run(
            ["systemctl", "stop", "polysia-platform-" + unit],
            capture_output=True,
            check=False,
            timeout=40,
        )
    for path, saved, metadata in restored:
        shutil.copy2(saved, path)
        path.chmod(metadata["mode"])
        os.chown(path, metadata["uid"], metadata["gid"])
    core.run("systemctl", "daemon-reload")
    # Leave workers stopped/fenced for protected inspection; do not downgrade any database.
    atomic(core.CONFIG_ROOT / "restart-fenced", {"reason": "rollback_requires_review"})
    return {
        "status": "COMPATIBLE_CONFIGURATION_RESTORED",
        "commit": receipt["commit"],
        "financial_data": "UNCHANGED",
        "worker": "FENCED",
        "next_action": "Inspect protected configuration and retained reports before restart.",
    }


def backup_schedule(commit: str, *, enabled: bool) -> None:
    if not enabled:
        subprocess.run(
            ["systemctl", "disable", "--now", "polysia-platform-backup.timer"],
            capture_output=True,
            check=False,
            timeout=30,
        )
        return
    executable = core.INSTALL_ROOT / "releases" / commit / "platform_backup.py"
    unit = (
        "[Unit]\nDescription=PolySia encrypted backup\nAfter=docker.service\n\n[Service]\n"
        "Type=oneshot\nExecStart=/usr/bin/python3 "
        + str(executable)
        + " backup --config /etc/polysia-platform/backup-job.json\n"
        "CPUQuota=50%\nMemoryMax=640M\nTasksMax=256\nTimeoutStartSec=600\n"
        "LogRateLimitIntervalSec=60s\nLogRateLimitBurst=20\n"
    )
    atomic(core.SERVICE_ROOT / "polysia-platform-backup.service", unit, mode=0o644)
    atomic(
        core.SERVICE_ROOT / "polysia-platform-backup.timer",
        "[Unit]\nDescription=PolySia daily backup\n[Timer]\nOnCalendar=*-*-* 00:15:00 UTC\n"
        "Persistent=true\n[Install]\nWantedBy=timers.target\n",
        mode=0o644,
    )
    core.run("systemctl", "daemon-reload")
    core.run("systemctl", "enable", "--now", "polysia-platform-backup.timer")


def configure_backup(args: argparse.Namespace) -> dict:
    current = validate(json.loads((core.CONFIG_ROOT / "installation.json").read_text()))
    module = load_backup(current["commit"])
    mode = args.backup_mode
    if mode is None:
        if args.noninteractive:
            raise ValueError("--backup-mode none/local/sftp is required")
        choices = {"": "none", "1": "none", "2": "local", "3": "sftp"}
        print("Backup: 1 none (UNPROTECTED), 2 encrypted local checkpoint, 3 independent SFTP")
        mode = choices.get(input("Backup choice [1]: ").strip())
    if mode not in {"none", "local", "sftp"}:
        raise ValueError("choose none, local or sftp")
    candidate = {"mode": mode}
    if mode != "none":
        if not args.noninteractive:
            print("Keep the recovery private key outside this installation and its archive.")
            if args.recipient_file is None:
                args.recipient_file = Path(
                    input("Public age recipient file (absolute path): ").strip()
                )
            if mode == "local" and args.recovery_key is None:
                args.recovery_key = Path(
                    input("Separately held recovery key for verification: ").strip()
                )
            if mode == "sftp":
                print("SFTP needs restricted upload and protected independent restore receipts.")
                args.secondary_host = (
                    args.secondary_host or input("Independent SFTP hostname: ").strip()
                )
                if args.known_hosts_file is None:
                    args.known_hosts_file = Path(input("Verified SSH host keys file: ").strip())
                if args.upload_key_file is None:
                    args.upload_key_file = Path(input("Root-only SFTP upload key file: ").strip())
        if args.recipient_file is None:
            raise ValueError("a separately held recovery key's public --recipient-file is required")
        for path in (args.recipient_file, args.known_hosts_file, args.upload_key_file):
            if path is not None and (
                not path.is_absolute() or path.is_symlink() or not path.is_file()
            ):
                raise ValueError("existing absolute protected backup input files required")
        release = core.INSTALL_ROOT / "releases" / current["commit"]
        installed = json.loads((release / "installation-receipt.json").read_text())
        candidate.update(
            image_id=installed["image_id"],
            release=str(release),
            output=str(core.STATE_ROOT / "backup-out"),
            recipient_file=str(args.recipient_file),
            receipt=str(core.STATE_ROOT / "publication/backup-status.json"),
        )
        if mode == "sftp":
            if not args.secondary_host or not args.known_hosts_file or not args.upload_key_file:
                raise ValueError(
                    "SFTP host, pinned known-hosts file and root-only upload key required"
                )
            if args.upload_key_file.stat().st_mode & 0o077:
                raise ValueError("upload key must be root-only")
            candidate.update(
                secondary_host=args.secondary_host,
                secondary_port=args.secondary_port,
                known_hosts=str(args.known_hosts_file),
                upload_key=str(args.upload_key_file),
            )
    outcome = module.change_destination(candidate, recovery_key=args.recovery_key)
    if outcome["status"] in {"DESTINATION_VERIFIED", "UNPROTECTED"}:
        backup_schedule(current["commit"], enabled=mode != "none")
        current["backup"] = {"mode": mode, "protection": outcome.get("protection", "UNPROTECTED")}
        atomic(core.CONFIG_ROOT / "installation.json", current)
        worker_file = core.CONFIG_ROOT / "worker.json"
        worker = json.loads(worker_file.read_text())
        worker["backup_mode"] = mode
        atomic(worker_file, worker, mode=0o640)
        os.chown(worker_file, 0, 10102)
        receipt = {**outcome, "checked_at": datetime.now(UTC).isoformat()}
        atomic(core.STATE_ROOT / "publication/backup-status.json", receipt, mode=0o640)
        os.chown(core.STATE_ROOT / "publication/backup-status.json", 0, 10102)
        install_health(current)
    return outcome


def retained_backup() -> dict:
    """Recognize an existing destination without inventing a new restore proof."""
    for name in ("backup-job.json", "backup.json"):
        path = core.CONFIG_ROOT / name
        if path.is_symlink():
            raise ValueError("retained backup configuration must not be a symlink")
        if path.exists():
            candidate = json.loads(path.read_text())
            mode = candidate.get("mode", "sftp")
            if mode not in {"none", "local", "sftp"}:
                raise ValueError("retained backup mode is unsupported")
            return {"mode": mode, "protection": "RETAINED_REVERIFY_REQUIRED"}
    return {"mode": "none", "protection": "UNPROTECTED"}


def promote_retained_backup(value: dict, *, image: str) -> None:
    """Keep destination, keys and generations; change only the verified executable."""
    if value["backup"]["mode"] == "none":
        return
    active = core.CONFIG_ROOT / "backup-job.json"
    source = active if active.exists() else core.CONFIG_ROOT / "backup.json"
    job = json.loads(source.read_text())
    job.update(image_id=image, release=str(core.INSTALL_ROOT / "releases" / value["commit"]))
    atomic(active, job)
    backup_schedule(value["commit"], enabled=True)
    # Older installations already fetch the independent restore receipt. Preserve
    # that configuration and timer, replacing only its manifest-verified script.
    status_unit = core.SERVICE_ROOT / "polysia-platform-recovery-status.service"
    if (core.CONFIG_ROOT / "backup-status-fetch.json").is_file() and status_unit.exists():
        original = status_unit.read_text()
        updated, count = re.subn(
            r"/opt/polysia-platform/releases/[a-f0-9]{40}/platform_backup\.py",
            str(core.INSTALL_ROOT / "releases" / value["commit"] / "platform_backup.py"),
            original,
        )
        if count != 1:
            raise ValueError("retained recovery-status executable needs explicit inspection")
        atomic(status_unit, updated, mode=0o644)
        core.run("systemctl", "daemon-reload")


def protected_stop() -> dict:
    """Fence OS restart, then confirm authority independently of the command store."""

    def attempt(command: list[str], *, timeout: int):
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return subprocess.CompletedProcess(command, 124, stdout="", stderr="unconfirmed")

    atomic(
        core.CONFIG_ROOT / "restart-fenced",
        {
            "reason": "protected_administrative_stop",
            "checked_at": datetime.now(UTC).isoformat(),
        },
    )
    # Missing/broken units during interrupted setup cannot prevent the separate
    # container stop attempt. The restart fence was durable before either call.
    for unit in ("worker.timer", "worker.service"):
        attempt(["systemctl", "stop", "polysia-platform-" + unit], timeout=40)
    stopped_container = attempt(
        ["docker", "stop", "-t", "5", "polysia-platform-worker"],
        timeout=15,
    )
    result = {
        "status": "OS_WORKER_FENCED"
        if stopped_container.returncode == 0
        else "OS_RESTART_FENCED_RUNTIME_UNCONFIRMED",
        "data_retained": True,
        "durable_authority_stop": "NOT_CONFIRMED",
        "command_receipt": "UNKNOWN",
        "next_action": "Confirm durable STOP before any restart.",
    }
    worker_file = core.CONFIG_ROOT / "worker.json"
    if not worker_file.is_file():
        return result
    worker = json.loads(worker_file.read_text())
    authority = core.STATE_ROOT / "worker" / Path(worker["authority"]).name
    if not authority.exists():
        if (
            worker.get("installation_state") == "UNCONFIGURED"
            and worker.get("acquisition_enabled") is False
        ):
            result.update(
                durable_authority_stop="NO_AUTHORITY_CONFIGURED",
                next_action="No acquisition is authorized; the OS restart fence remains.",
            )
        return result
    try:
        if authority.is_symlink():
            raise ValueError("retained authority cannot be a symlink")
        with closing(sqlite3.connect(authority.as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute("SELECT policy_digest,stopped FROM authority").fetchall()
            connection.execute(
                "SELECT COUNT(*),SUM(COALESCE(actual_bytes,reserved_bytes)) FROM reservations",
            ).fetchone()
        if (
            len(rows) != 1
            or re.fullmatch(r"[a-f0-9]{64}", rows[0][0]) is None
            or rows[0][1] not in {0, 1}
        ):
            raise ValueError("retained authority identity is invalid")
    except (sqlite3.DatabaseError, ValueError, TypeError):
        # Older retained executables initialize authority before STOP. Never
        # delegate damaged/missing state to that initializer or replenish it.
        result["reason"] = "retained_authority_invalid_do_not_reinitialize"
        return result
    release = core.INSTALL_ROOT / "releases" / worker["release_commit"]
    image = json.loads((release / "installation-receipt.json").read_text())["image_id"]
    module = load_backup(worker["release_commit"])
    command = module.isolated(
        image,
        f"{core.CONFIG_ROOT}/worker.json:/config/worker.json:ro",
        f"{core.CONFIG_ROOT}/manifest.json:/config/manifest.json:ro",
        f"{core.STATE_ROOT}/worker:/state:rw",
        f"{core.STATE_ROOT}/control:/control:rw",
    )
    applied = attempt(
        command
        + [
            "--name",
            "polysia-platform-protected-stop",
            image,
            "ops",
            "platform-stop",
            "--config",
            "/config/worker.json",
        ],
        timeout=60,
    )
    if applied.returncode == 0:
        try:
            receipt = json.loads(applied.stdout)["receipt"]
            result["command_receipt"] = "RECORDED" if "revision" in receipt else "NOT_CONFIRMED"
        except (ValueError, KeyError, TypeError):
            result["command_receipt"] = "NOT_CONFIRMED"
    try:
        with closing(sqlite3.connect(authority.as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("SELECT stopped FROM authority").fetchone() == (1,):
                result.update(
                    status="STOPPED"
                    if stopped_container.returncode == 0
                    else "AUTHORITY_STOPPED_RUNTIME_UNCONFIRMED",
                    durable_authority_stop="CONFIRMED",
                    next_action="Inspect retained evidence; restart remains fenced.",
                )
    except sqlite3.DatabaseError:
        pass
    return result


def restore_installation(args: argparse.Namespace, value: dict, *, image: str) -> dict:
    """Populate only a fresh replacement through the shared verified crypto/replay path."""
    if not args.archive or not args.recovery_key:
        raise ValueError("--archive and separately held --recovery-key are required")
    worker_root = core.STATE_ROOT / "worker"
    if any(worker_root.glob("*.sqlite3*")):
        raise ValueError("replacement restore requires empty financial/authority state")
    reports = core.STATE_ROOT / "publication/reports"
    commands = core.STATE_ROOT / "control/commands.sqlite3"
    if (
        reports.is_symlink()
        or (reports.exists() and any(reports.iterdir()))
        or commands.exists()
        or commands.is_symlink()
    ):
        raise ValueError("replacement reports and command state must be empty before restore")
    if (
        args.recovery_key.is_symlink()
        or not args.recovery_key.is_file()
        or args.recovery_key.stat().st_mode & 0o077
        or args.recovery_key.resolve().is_relative_to(core.STATE_ROOT)
        or args.recovery_key.resolve().is_relative_to(core.CONFIG_ROOT)
    ):
        raise ValueError("separately held root-only recovery key required")
    module = load_backup(value["commit"])
    stage = core.STATE_ROOT / "replacement-restore"
    if stage.exists():
        raise ValueError("prior replacement staging is retained; inspect before another restore")
    stage.mkdir(mode=0o700)
    release = core.INSTALL_ROOT / "releases" / value["commit"]
    proof, stopped, metadata = module.verify_generation(
        args.archive.resolve(),
        stage,
        image=image,
        trusted=release / "manifest.json",
        recovery_key=args.recovery_key.resolve(),
    )
    bundle = stage / "bundle"
    # Fence before the first replacement write. An interruption retains this
    # explicit stopped state and the verified staging evidence for inspection.
    atomic(core.CONFIG_ROOT / "restart-fenced", {"reason": "replacement_restore_in_progress"})
    safe = json.loads((bundle / "recovery-runtime.json").read_text())
    for field, target in (
        ("database", worker_root / "financial.sqlite3"),
        ("authority", worker_root / "authority.sqlite3"),
        ("commands", core.STATE_ROOT / "control/commands.sqlite3"),
    ):
        source = bundle / Path(safe[field]).name
        if source.exists():
            if target.exists() and field != "commands":
                raise ValueError("restore cannot replace existing financial evidence")
            with (
                closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
                closing(sqlite3.connect(target)) as restored,
            ):
                original.backup(restored)
                if restored.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("replacement SQLite integrity differs")
            os.chown(target, 10101, 10102)
            target.chmod(0o660 if field == "commands" else 0o640)
        safe[field] = (
            "/control/commands.sqlite3" if field == "commands" else "/state/" + target.name
        )
    for name, target in (
        ("policy.json", core.CONFIG_ROOT / "manifest.json"),
        ("cohort.json", worker_root / "cohort.json"),
        ("financial-session.json", worker_root / "financial.sqlite3.session.json"),
    ):
        source = bundle / name
        if source.exists():
            shutil.copy2(source, target)
            target.chmod(0o640)
            os.chown(target, 0 if name == "policy.json" else 10101, 10102)
    safe.update(
        manifest="/config/manifest.json",
        cohort="/state/cohort.json",
        status="/state/status.json",
        publication="/publication/publication.json",
        backup_mode="none",
        acquisition_enabled=False,
        recovery_requires_authority_reconciliation=True,
    )
    atomic(core.CONFIG_ROOT / "worker.json", safe, mode=0o640)
    os.chown(core.CONFIG_ROOT / "worker.json", 0, 10102)
    atomic(
        worker_root / "status.json",
        {
            **stopped,
            "last_attempt": datetime.now(UTC).isoformat(),
            "reason": "recovery_authority_reconciliation_required",
            "next_action": "Fence the old primary and reconcile newest consumed authority "
            "before any separately authorized observation.",
        },
        mode=0o640,
    )
    os.chown(worker_root / "status.json", 10101, 10102)
    reports.mkdir(exist_ok=True)
    for source in (bundle / "reports").glob("*.json"):
        shutil.copy2(source, reports / source.name)
        os.chown(reports / source.name, 10101, 10102)
        (reports / source.name).chmod(0o640)
    os.chown(reports, 10101, 10102)
    reports.chmod(0o750)
    atomic(
        core.CONFIG_ROOT / "restart-fenced",
        {"reason": "recovery_requires_authority_reconciliation"},
    )
    return {
        **proof,
        "financial_data": "RESTORED_WITHOUT_REIDENTIFICATION",
        "original_created_at": metadata["created_at"],
        "worker": "FENCED",
    }


def main() -> None:
    global core
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "install",
            "configure",
            "update",
            "stage",
            "rollback",
            "restore",
            "preflight",
            "status",
            "stop",
            "uninstall",
            "backup",
            "health",
        ),
    )
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    parser.add_argument("--artifact-directory", type=Path)
    parser.add_argument("--profile", choices=("private", "own-domain", "cloudflare"))
    parser.add_argument("--hostname")
    parser.add_argument("--public-opt-in", action="store_true")
    parser.add_argument("--access-issuer")
    parser.add_argument("--access-audience")
    parser.add_argument("--access-owner")
    parser.add_argument("--operator", action="append", default=[])
    parser.add_argument("--reader", action="append", default=[])
    parser.add_argument("--remove-user", action="append", default=[])
    parser.add_argument("--noninteractive", action="store_true")
    parser.add_argument("--backup-mode", choices=("none", "local", "sftp"))
    parser.add_argument("--recipient-file", type=Path)
    parser.add_argument("--secondary-host")
    parser.add_argument("--secondary-port", type=int, default=22)
    parser.add_argument("--known-hosts-file", type=Path)
    parser.add_argument("--upload-key-file", type=Path)
    parser.add_argument("--recovery-key", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0 and not (args.action == "health" and os.geteuid() == 10101):
        parser.error("administrative SSH/root access required")
    core = load_core(args)
    if args.action == "health":
        print(json.dumps(publish_health(), sort_keys=True))
        return
    if args.action == "rollback":
        print(json.dumps(rollback(), sort_keys=True))
        return
    if args.action == "backup":
        print(json.dumps(configure_backup(args), sort_keys=True))
        return
    if args.action == "status":
        for name in ("installation.json", "maintenance-receipt.json"):
            path = core.CONFIG_ROOT / name
            print(path.read_text() if path.exists() else name + ": UNCONFIGURED")
        return
    if args.action in {"stop", "uninstall"}:
        result = protected_stop()
        if args.action == "uninstall":
            for name in (
                "worker.timer",
                "publisher.timer",
                "gateway.service",
                "health.timer",
                "backup.timer",
                "recovery-status.timer",
            ):
                if (core.SERVICE_ROOT / ("polysia-platform-" + name)).exists():
                    core.run("systemctl", "disable", "--now", "polysia-platform-" + name)
            core.run("systemctl", "stop", "polysia-platform-web.service")
        print(json.dumps(result))
        return
    prior_file = core.CONFIG_ROOT / "installation.json"
    prior = validate(json.loads(prior_file.read_text())) if prior_file.exists() else {}
    if (
        not prior
        and (core.CONFIG_ROOT / "worker.json").is_file()
        and (core.CONFIG_ROOT / "web.json").is_file()
    ):
        # Register the existing protected deployment without changing its access
        # mechanism or treating its listener as an unrelated fresh-port conflict.
        web = json.loads((core.CONFIG_ROOT / "web.json").read_text())
        worker = json.loads((core.CONFIG_ROOT / "worker.json").read_text())
        prior = validate(
            {
                "schema": SCHEMA,
                "commit": worker["release_commit"],
                "profile": web.get("profile", "cloudflare"),
                "hostname": urlsplit(web["origin"]).hostname,
                "public_opt_in": web.get("profile") == "own-domain",
                "roles": {"owner": "operator", "reader": "reader"},
                "backup": retained_backup(),
            }
        )
    profile = args.profile or prior.get("profile")
    if profile is None:
        if args.noninteractive:
            parser.error("--profile is required in noninteractive mode")
        print(
            "Access: 1 private through SSH (default), 2 your public domain, 3 existing Cloudflare"
        )
        profile = {"": "private", "1": "private", "2": "own-domain", "3": "cloudflare"}.get(
            input("Access choice [1]: ").strip()
        )
        if profile is None:
            parser.error("choose 1, 2 or 3")
    hostname = "localhost" if profile == "private" else args.hostname or prior.get("hostname")
    if not hostname and not args.noninteractive:
        hostname = input(
            "Your hostname (DNS/ingress commissioning requires your authorization): "
        ).strip()
    roles = dict(prior.get("roles", {"owner": "operator", "reader": "reader"}))
    if (args.operator or args.reader or args.remove_user) and args.action != "configure":
        parser.error("identity changes require the configure action")
    if profile == "cloudflare" and (args.operator or args.reader or args.remove_user):
        parser.error(
            "local user options apply only to the gateway; existing Cloudflare stays preserved"
        )
    for name in args.remove_user:
        if name not in roles:
            parser.error("cannot remove an unconfigured local user")
        del roles[name]
    roles.update(dict.fromkeys(args.reader, "reader"))
    roles.update(dict.fromkeys(args.operator, "operator"))
    value = validate(
        {
            "schema": SCHEMA,
            "commit": args.commit or prior.get("commit"),
            "profile": profile,
            "hostname": hostname,
            "public_opt_in": args.public_opt_in or prior.get("public_opt_in", False),
            "roles": roles,
            "backup": prior.get("backup", retained_backup()),
        }
    )
    preflight(value)
    if args.action == "preflight":
        try:
            core.activation_preflight(value["commit"])
        except ValueError as error:
            print(
                json.dumps(
                    {
                        "status": "ACTIVATION_REFUSED",
                        "reason": str(error),
                        "active_data": "UNCHANGED",
                        "next_action": "Stage the exact release; retain the active executable "
                        "and reconcile.",
                    }
                )
            )
            raise SystemExit(1) from None
        print(json.dumps({"status": "PREFLIGHT_PASSED", "configuration": value}))
        return
    local = Path(__file__).resolve().parent
    directory = args.artifact_directory or (
        local
        if (local / "polysia-image.tar.gz").is_file()
        else fetch_release(args.tag, value["commit"])
    )
    if args.action == "stage":
        manifest = core.verify_artifact(directory, commit=value["commit"])
        core.archive_image_ids(directory, manifest)
        try:
            core.activation_preflight(value["commit"])
            activation = {"status": "PREFLIGHT_PASSED"}
        except ValueError as error:
            activation = {"status": "REFUSED", "reason": str(error)}
        receipt = {
            "status": "VERIFIED_DOWNLOAD_ONLY",
            "commit": value["commit"],
            "archive_sha256": manifest["archive_sha256"],
            "image_id": manifest["image_id"],
            "activation": activation,
            "active_configuration_and_data": "UNCHANGED",
            "image_loaded": False,
            "starts_acquisition": False,
        }
        atomic(directory / "staging-receipt.json", receipt)
        print(json.dumps(receipt, sort_keys=True))
        return
    core.activation_preflight(value["commit"])
    checkpoint_file = core.CONFIG_ROOT / "rollback-checkpoint.json"
    checkpoint = (
        preserve_rollback()
        if prior != value
        else json.loads(checkpoint_file.read_text())
        if checkpoint_file.exists()
        else None
    )
    phase(value, "PREFLIGHT_PASSED")
    receipt = core.bootstrap(directory, commit=value["commit"], install_units=False)
    phase(value, "ARTIFACT_VERIFIED", image_id=receipt["image_id"])
    if args.action == "restore":
        proof = restore_installation(args, value, image=receipt["image_id"])
        phase(value, "RESTORE_VERIFIED", restore=proof)
    cf = None
    if profile == "cloudflare" and not (core.CONFIG_ROOT / "web.json").exists():
        supplied = (args.access_issuer, args.access_audience, args.access_owner)
        if not all(supplied) and not args.noninteractive:
            print("Create your owner-only Access application and Tunnel to 127.0.0.1:8765.")
            print(
                "This configures the verifier; DNS, ingress and account setup remain owner actions."
            )
            supplied = (
                args.access_issuer
                or input("Access issuer https://TEAM.cloudflareaccess.com: ").strip(),
                args.access_audience or input("Access application audience: ").strip(),
                args.access_owner or input("Authorized operator email: ").strip(),
            )
        if any(supplied) and not all(supplied):
            parser.error("provide all three --access-issuer, --access-audience and --access-owner")
        if all(supplied):
            cf = dict(zip(("issuer", "audience", "owner"), supplied, strict=True))
    access = configure(
        value,
        image=receipt["image_id"],
        allow_change=args.action in {"configure", "update"},
        cloudflare=cf,
    )
    phase(value, "CONFIGURATION_STAGED", access=access)
    if access["status"] == "ACCESS_CONFIGURATION_REQUIRED":
        print(
            json.dumps(
                {
                    "status": "ACCESS_CONFIGURATION_REQUIRED",
                    "access": access,
                    "acquisition_enabled": False,
                }
            )
        )
        return
    try:
        activate(value, image=receipt["image_id"])
        verify_access(value)
        promote_retained_backup(value, image=receipt["image_id"])
        install_health(value)
    except (OSError, ValueError, subprocess.SubprocessError):
        atomic(core.CONFIG_ROOT / "restart-fenced", {"reason": "activation_incomplete"})
        subprocess.run(
            [
                "systemctl",
                "stop",
                "polysia-platform-worker.timer",
                "polysia-platform-worker.service",
            ],
            capture_output=True,
            check=False,
            timeout=40,
        )
        phase(
            value,
            "ACTIVATION_INCOMPLETE",
            worker="FENCED",
            next_action="Inspect dedicated service logs; rerun this exact release or rollback.",
        )
        raise ValueError(
            "activation incomplete; worker restart is fenced; inspect maintenance receipt"
        ) from None
    phase(
        value,
        "ACTIVATED",
        access=access,
        backup=value["backup"],
        acquisition_enabled=False,
        rollback_checkpoint=checkpoint,
    )
    print(
        json.dumps(
            {
                "status": "SETUP_COMPLETE",
                "access": access,
                "backup": value["backup"].get("protection", "UNPROTECTED"),
                "acquisition_enabled": False,
                "next_action": "Read the Console. Observation needs separate approved authority.",
            }
        )
    )


if __name__ == "__main__":
    main()
