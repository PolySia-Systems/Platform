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
import ssl
import subprocess
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

if __name__ != "__main__":
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
    if not (core.CONFIG_ROOT / "installation.json").exists():
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


def configure(value: dict, *, image: str) -> dict:
    """Stage validated access/configuration before any activation."""
    validate(value)
    current = core.CONFIG_ROOT / "installation.json"
    if current.exists() and validate(json.loads(current.read_text())) != value:
        raise ValueError("existing configuration differs; use an explicit maintenance change")
    if value["profile"] == "cloudflare":
        if not (core.CONFIG_ROOT / "web.json").exists():
            return {
                "status": "ACCESS_CONFIGURATION_REQUIRED",
                "next_action": "Provide your Access issuer, audience and owner identity "
                "through the guided administrative entry.",
            }
        return {"status": "EXISTING_CLOUDFLARE_PRESERVED"}
    caddy = install_gateway()
    access = core.CONFIG_ROOT / "gateway-credentials.json"
    if access.exists():
        credentials = json.loads(access.read_text())
    else:
        credentials = {name: secrets.token_urlsafe(32) for name in value["roles"]}
        atomic(access, credentials)
    passwords = {}
    for name, password in credentials.items():
        passwords[name] = subprocess.run(
            [str(caddy), "hash-password", "--algorithm", "bcrypt", "--bcrypt-cost", "10"],
            input=password,
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
    if value["profile"] == "cloudflare":
        return  # Existing protected route is commissioned separately.
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
    for role in ("worker", "publisher", "web"):
        text = core.service_text(
            image,
            role=role,
            hostname=socket.gethostname(),
            gateway=True,
            configured=(core.CONFIG_ROOT / "manifest.json").is_file(),
        )
        atomic(core.SERVICE_ROOT / ("polysia-platform-" + role + ".service"), text, mode=0o644)
    atomic(
        core.SERVICE_ROOT / "polysia-platform-gateway.service",
        gateway_unit(
            core.INSTALL_ROOT / "gateway" / CADDY_VERSION / "caddy",
            public=value["profile"] == "own-domain",
        ),
        mode=0o644,
    )
    core.run("systemctl", "daemon-reload")
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


def main() -> None:
    global core
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "preflight", "status", "stop", "uninstall"))
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    parser.add_argument("--artifact-directory", type=Path)
    parser.add_argument("--profile", choices=("private", "own-domain", "cloudflare"))
    parser.add_argument("--hostname")
    parser.add_argument("--public-opt-in", action="store_true")
    parser.add_argument("--noninteractive", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("administrative SSH/root access required")
    core = load_core(args)
    if args.action == "status":
        for name in ("installation.json", "maintenance-receipt.json"):
            path = core.CONFIG_ROOT / name
            print(path.read_text() if path.exists() else name + ": UNCONFIGURED")
        return
    if args.action in {"stop", "uninstall"}:
        # OS supervision remains independent of browser, identity and command DB.
        atomic(
            core.CONFIG_ROOT / "restart-fenced",
            {
                "reason": "protected_administrative_stop",
                "checked_at": datetime.now(UTC).isoformat(),
            },
        )
        core.run("systemctl", "stop", "polysia-platform-worker.timer")
        core.run("systemctl", "stop", "polysia-platform-worker.service")
        if args.action == "uninstall":
            core.run(
                "systemctl",
                "disable",
                "--now",
                "polysia-platform-worker.timer",
                "polysia-platform-publisher.timer",
                "polysia-platform-gateway.service",
            )
            core.run("systemctl", "stop", "polysia-platform-web.service")
        print(
            json.dumps(
                {
                    "status": "OS_WORKER_FENCED",
                    "data_retained": True,
                    "durable_authority_stop": "NOT_CONFIRMED",
                    "next_action": "Confirm durable STOP before any restart.",
                }
            )
        )
        return
    profile = args.profile
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
    hostname = "localhost" if profile == "private" else args.hostname
    if not hostname and not args.noninteractive:
        hostname = input(
            "Your hostname (DNS/ingress commissioning requires your authorization): "
        ).strip()
    value = validate(
        {
            "schema": SCHEMA,
            "commit": args.commit,
            "profile": profile,
            "hostname": hostname,
            "public_opt_in": args.public_opt_in,
            "roles": {"owner": "operator", "reader": "reader"},
            "backup": {"mode": "none"},
        }
    )
    preflight(value)
    if args.action == "preflight":
        print(json.dumps({"status": "PREFLIGHT_PASSED", "configuration": value}))
        return
    directory = args.artifact_directory or fetch_release(args.tag, args.commit)
    phase(value, "PREFLIGHT_PASSED")
    receipt = core.bootstrap(directory, commit=args.commit, install_units=False)
    phase(value, "ARTIFACT_VERIFIED", image_id=receipt["image_id"])
    access = configure(value, image=receipt["image_id"])
    phase(value, "CONFIGURATION_STAGED", access=access)
    activate(value, image=receipt["image_id"])
    verify_access(value)
    phase(value, "ACTIVATED", access=access, backup="UNPROTECTED", acquisition_enabled=False)
    print(
        json.dumps(
            {
                "status": "SETUP_COMPLETE",
                "access": access,
                "backup": "UNPROTECTED",
                "acquisition_enabled": False,
                "next_action": "Read the Console. Observation needs separate approved authority.",
            }
        )
    )


if __name__ == "__main__":
    main()
