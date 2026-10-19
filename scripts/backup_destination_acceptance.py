"""Real encrypted/SFTP destination replacement and nonempty cold recovery on disposable CI."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, check=True, text=True, timeout=300).stdout


async def seed(root: Path, *, commit: str) -> tuple[dict, dict]:
    from polysia.application.services.shadow_reporting import ShadowReportingService
    from polysia.domain.copytrading import LeaderTradeAction
    from polysia.storage.acquisition_authority import AcquisitionAuthority
    from polysia.storage.console_commands import ConsoleCommandStore
    from polysia.storage.dynamic_shadow import DynamicShadowRepository
    from tests.integration.test_continuous_shadow_portfolio import (
        NOW,
        _EventSpec,
        _shadow_database,
        _started_service,
    )
    from tests.unit.storage.test_acquisition_authority import ENDPOINT, policy

    worker, config, publication, control = [
        root / name
        for name in (
            "state/worker",
            "config",
            "state/publication",
            "state/control",
        )
    ]
    for directory in (worker, config, publication, control):
        directory.mkdir(parents=True, mode=0o750, exist_ok=True)
    database, service, clock, scenario = _started_service(worker, name="fixture")
    experiment = service._store.active_experiment("polycop")
    assert experiment is not None
    _, candidates = DynamicShadowRepository(database).current_candidates("polycop")
    scenario.events[candidates[0].wallet_id] = [
        _EventSpec(
            "recovery-fixture-buy",
            LeaderTradeAction.BUY,
            NOW + timedelta(seconds=100),
            Decimal("0.40"),
        ),
    ]
    clock.value = NOW + timedelta(minutes=2)
    assert (await service.poll("polycop")).simulated_count > 0
    clock.value = NOW + timedelta(minutes=4)
    await service.poll("polycop")
    assert service._store.open_position_count(experiment.experiment_id) > 0
    authority = AcquisitionAuthority(worker / "authority.sqlite3", policy())
    authority.initialize()
    authority.reserve(ENDPOINT, now=policy().starts_at, host="host")
    authority.stop()  # An uncertain request remains fully charged.
    commands = ConsoleCommandStore(control / "commands.sqlite3")
    commands.initialize()
    reporting = ShadowReportingService(_shadow_database(database))
    archived = reporting.report(
        experiment.experiment_id, start=NOW, end=NOW + timedelta(seconds=121)
    )
    assert archived["analytical"]["selected_window"]["observation_count"] > 0
    (publication / "reports").mkdir()
    (publication / "reports" / (archived["analytical_digest"] + ".json")).write_text(
        json.dumps(archived)
    )
    commands.submit(
        subject="fixture-owner",
        action="export",
        expected_revision=0,
        idempotency_key="recovery-fixture-selected-report",
    )
    commands.finish(
        1,
        status="APPLIED",
        result={
            "download": "/reports/" + archived["analytical_digest"] + ".json",
            "analytical_digest": archived["analytical_digest"],
        },
    )
    status = {
        "status": "STOPPED",
        "release_commit": commit,
        "last_attempt": datetime.now(UTC).isoformat(),
        "real_orders": False,
        "authority": authority.status(),
        "dataset_role": "ISOLATED_RECOVERY_FIXTURE",
    }
    (worker / "status.json").write_text(json.dumps(status))
    (publication / "publication.json").write_text(
        json.dumps(
            {
                **status,
                "published_at": datetime.now(UTC).isoformat(),
                "report": reporting.report(experiment.experiment_id),
            }
        )
    )
    (config / "manifest.json").write_text(json.dumps(policy().to_dict()))
    value = {
        "source_id": "polycop",
        "database": "/state/" + _shadow_database(database).name,
        "authority": "/state/authority.sqlite3",
        "commands": "/control/commands.sqlite3",
        "release_commit": commit,
        "manifest": "/config/manifest.json",
        "cohort": "/state/cohort.json",
        "acquisition_enabled": False,
        "admission": {},
        "status": "/state/status.json",
        "publication": "/publication/publication.json",
    }
    (config / "worker.json").write_text(json.dumps(value))
    for directory in (worker, publication, control):
        os.chown(directory, 10101, 10102)
        directory.chmod(0o2770 if directory == control else 0o700 if directory == worker else 0o750)
        for path in directory.rglob("*"):
            os.chown(path, 10101, 10102)
            path.chmod(0o750 if path.is_dir() else 0o660 if directory == control else 0o640)
    return archived, authority.status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (
        os.geteuid() != 0
        or os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("RUNNER_ENVIRONMENT") != "github-hosted"
        or Path("/var/lib/polysia-platform/worker/authority.sqlite3").exists()
    ):
        raise ValueError("fresh disposable GitHub-runner installation required")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from deploy import platform_admin as admin
    from deploy import platform_backup as backup
    from deploy import platform_bootstrap as bootstrap

    # GitHub's /opt is writable by its tool-installation identity. Keep SSH's
    # strict ancestor checks and place this chroot under a protected parent.
    root = Path("/srv/polysia-backup-acceptance-" + str(os.getpid()))
    for parent in root.parents:
        stat = parent.stat()
        if stat.st_uid != 0 or stat.st_mode & 0o022:
            raise ValueError("disposable SFTP chroot requires root-owned nonwritable ancestors")
    root.mkdir(mode=0o755)
    primary = root / "primary"
    primary.mkdir(mode=0o755)
    archived, authority_before = asyncio.run(seed(primary, commit=args.commit))
    backup.STATE_ROOT, backup.CONFIG_ROOT = primary / "state", primary / "config"
    bootstrap.STATE_ROOT, bootstrap.CONFIG_ROOT = backup.STATE_ROOT, backup.CONFIG_ROOT
    before = hashlib.sha256((backup.CONFIG_ROOT / "worker.json").read_bytes()).hexdigest()
    try:
        bootstrap.activation_preflight("b" * 40)
    except ValueError as error:
        assert "open inventory" in str(error)
    else:
        raise AssertionError("unsafe active-inventory upgrade was accepted")
    assert hashlib.sha256((backup.CONFIG_ROOT / "worker.json").read_bytes()).hexdigest() == before
    if not Path("/usr/sbin/sshd").exists():
        run("apt-get", "update", "-qq")
        run("apt-get", "install", "-y", "--no-install-recommends", "openssh-server")
    run(
        "useradd",
        "--system",
        "--no-create-home",
        "--shell",
        "/usr/sbin/nologin",
        "polysia-platform-upload",
    )
    # OpenSSH with UsePAM=no rejects locked accounts even for public keys.
    # Assign an undisclosed random hash through stdin, retaining key-only auth.
    password_hash = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=secrets.token_urlsafe(32),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    subprocess.run(
        ["chpasswd", "--encrypted"],
        input="polysia-platform-upload:" + password_hash + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    import pwd

    upload = pwd.getpwnam("polysia-platform-upload")
    (root / "upload-key").touch(mode=0o600)
    (root / "upload-key").unlink()
    run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / "upload-key"))
    (root / "upload-key").chmod(0o600)
    units = []
    destinations = {}
    release = args.artifact_directory.resolve()
    for name, port in (("A", 12222), ("B", 12223)):
        server = root / ("server-" + name)
        server.mkdir(mode=0o755)
        vault = server / "vault"
        vault.mkdir(mode=0o755)
        (vault / "incoming").mkdir(mode=0o750)
        os.chown(vault / "incoming", upload.pw_uid, upload.pw_gid)
        (vault / "status").mkdir(mode=0o755)
        (server / "keys").mkdir(mode=0o700)
        run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0",
            "--read-only",
            "--memory",
            "128m",
            "--cpus",
            ".25",
            "--volume",
            str(server / "keys") + ":/keys:rw",
            "--entrypoint",
            "age-keygen",
            args.image_id,
            "-o",
            "/keys/recovery-key",
        )
        public = run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--volume",
            str(server / "keys") + ":/keys:ro",
            "--user",
            "0",
            "--entrypoint",
            "age-keygen",
            args.image_id,
            "-y",
            "/keys/recovery-key",
        ).strip()
        (server / "recipient").write_text(public)
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(server / "keys/host-key"))
        for key_name in ("recovery-key", "host-key"):
            (server / "keys" / key_name).chmod(0o600)
        (server / "authorized-key").write_bytes((root / "upload-key.pub").read_bytes())
        (server / "authorized-key").chmod(0o644)
        (server / "known-hosts").write_text(
            "[127.0.0.1]:" + str(port) + " " + (server / "keys/host-key.pub").read_text()
        )
        sshd_config = server / "sshd-config"
        sshd_config.write_text(
            "Port "
            + str(port)
            + "\nListenAddress 127.0.0.1\nHostKey "
            + str(server / "keys/host-key")
            + "\nPidFile "
            + str(server / "sshd.pid")
            + "\nPasswordAuthentication no\n"
            "KbdInteractiveAuthentication no\nPermitRootLogin no\nUsePAM no\n"
            "AllowUsers polysia-platform-upload\nAuthorizedKeysFile "
            + str(server / "authorized-key")
            + "\nChrootDirectory "
            + str(vault)
            + "\nForceCommand internal-sftp\n"
            "Subsystem sftp internal-sftp\n"
            "AllowTcpForwarding no\nX11Forwarding no\nPermitTTY no\n"
        )
        Path("/run/sshd").mkdir(exist_ok=True)
        unit = "polysia-acceptance-sftp-" + name.lower()
        run(
            "systemd-run",
            "--unit=" + unit,
            "--service-type=exec",
            "--property=MemoryMax=128M",
            "--property=CPUQuota=25%",
            "--property=TasksMax=64",
            "/usr/sbin/sshd",
            "-D",
            "-e",
            "-f",
            str(sshd_config),
        )
        units.append(unit)
        ready = time.monotonic() + 10
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                if time.monotonic() >= ready:
                    raise ValueError("disposable SFTP listener did not start") from None
                time.sleep(0.1)
        trusted = server / "trusted"
        trusted.mkdir(mode=0o700)
        shutil.copy2(release / "manifest.json", trusted / "manifest.json")
        destinations[name] = {
            "mode": "sftp",
            "secondary_host": "127.0.0.1",
            "secondary_port": port,
            "known_hosts": str(server / "known-hosts"),
            "upload_key": str(root / "upload-key"),
            "recipient_file": str(server / "recipient"),
            "image_id": args.image_id,
            "release": str(release),
            "output": str(backup.STATE_ROOT / "backup-out"),
            "receipt": str(backup.STATE_ROOT / "publication/backup-status.json"),
        }

    def verify_remote(name):
        server = root / ("server-" + name)
        backup.VAULT_ROOT = server / "vault"
        receipt = backup.restore(
            {
                "vault": str(backup.VAULT_ROOT),
                "image_id": args.image_id,
                "recovery_key": str(server / "keys/recovery-key"),
                "release_manifest": str(server / "trusted/manifest.json"),
            }
        )
        receipt["checked_at"] = datetime.now(UTC).isoformat()
        (server / "vault/status/restore-status.json").write_text(json.dumps(receipt))
        (server / "vault/status/restore-status.json").chmod(0o644)
        assert receipt["restored_reports"] == 1
        return receipt

    try:
        assert backup.change_destination({"mode": "none"})["status"] == "UNPROTECTED"
        assert (
            backup.change_destination(destinations["A"])["status"] == "AWAITING_INDEPENDENT_RESTORE"
        )
        verify_remote("A")
        assert backup.change_destination(destinations["A"])["status"] == "DESTINATION_VERIFIED"
        active_a = (backup.CONFIG_ROOT / "backup-job.json").read_bytes()
        bad_b = {**destinations["B"], "secondary_port": 12224}
        try:
            backup.change_destination(bad_b)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError("failed B was accepted")
        assert (backup.CONFIG_ROOT / "backup-job.json").read_bytes() == active_a
        assert (
            backup.change_destination(destinations["B"])["status"] == "AWAITING_INDEPENDENT_RESTORE"
        )
        verify_remote("B")
        assert backup.change_destination(destinations["B"])["status"] == "DESTINATION_VERIFIED"
        retained = sorted((root / "server-B/vault/incoming").iterdir())
        assert backup.change_destination({"mode": "none"})["status"] == "UNPROTECTED"
        assert sorted((root / "server-B/vault/incoming").iterdir()) == retained
        assert backup.change_destination(destinations["B"])["status"] == "DESTINATION_VERIFIED"
        offline = root / "primary-unavailable"
        primary.rename(offline)
        started = time.monotonic()
        proof = verify_remote("B")  # Neither source paths nor primary services are available.
        stage = root / "replacement"
        stage.mkdir(mode=0o700)
        backup.VAULT_ROOT = root / "server-B/vault"
        source = sorted((backup.VAULT_ROOT / "incoming").glob("*.tar.age"))[-1]
        receipt, stopped, metadata = backup.verify_generation(
            source,
            stage,
            image=args.image_id,
            trusted=root / "server-B/trusted/manifest.json",
            recovery_key=root / "server-B/keys/recovery-key",
        )
        assert stopped["status"] == "STOPPED"
        assert stopped["authority"] == authority_before
        assert receipt["analytical_digest"] == metadata["analytical_digest"]
        assert (
            json.loads(
                (stage / "bundle/reports" / (archived["analytical_digest"] + ".json")).read_text()
            )
            == archived
        )
        # Exercise the actual replacement import, not just its decrypt/replay
        # primitive. Primary paths have already been made unavailable.
        replacement = root / "replacement-host"
        for name in ("config", "state/worker", "state/control", "state/publication"):
            target = replacement / name
            target.mkdir(parents=True, mode=0o750, exist_ok=True)
            if name.startswith("state/"):
                os.chown(target, 10101, 10102)
                target.chmod(0o700 if name == "state/worker" else 0o2770)
        bootstrap.CONFIG_ROOT = replacement / "config"
        bootstrap.STATE_ROOT = replacement / "state"
        admin.core = bootstrap
        imported = admin.restore_installation(
            argparse.Namespace(archive=source, recovery_key=root / "server-B/keys/recovery-key"),
            {"commit": args.commit},
            image=args.image_id,
        )
        assert imported["worker"] == "FENCED"
        assert (replacement / "config/restart-fenced").exists()
        retained = json.loads((replacement / "config/worker.json").read_text())
        assert retained["acquisition_enabled"] is False
        assert retained["recovery_requires_authority_reconciliation"] is True
        run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--user",
            "10101:10102",
            "--memory",
            "512m",
            "--cpus",
            ".5",
            "--volume",
            str(replacement / "config/worker.json") + ":/config/worker.json:ro",
            "--volume",
            str(replacement / "config/manifest.json") + ":/config/manifest.json:ro",
            "--volume",
            str(replacement / "state/worker") + ":/state:rw",
            "--volume",
            str(replacement / "state/control") + ":/control:rw",
            "--volume",
            str(replacement / "state/publication") + ":/publication:rw",
            args.image_id,
            "ops",
            "platform-publish",
            "--config",
            "/config/worker.json",
        )
        verify_browser(
            args.image_id, stage / "bundle", archived, root, restored_state=replacement / "state"
        )
        elapsed = time.monotonic() - started
        assert elapsed < 3600 and proof["measured_RPO_seconds"] < 86400
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "source": args.commit,
                    "image_id": args.image_id,
                    "transition": "none/A/failed-B/successful-B/disconnect/reconnect",
                    "crypto": "real age",
                    "transport": "real strict-host-key OpenSSH SFTP",
                    "primary_unavailable": True,
                    "restored_reports": 1,
                    "analytical_digest": receipt["analytical_digest"],
                    "selected_period_digest": archived["analytical_digest"],
                    "authority": authority_before,
                    "measured_RPO_seconds": proof["measured_RPO_seconds"],
                    "measured_RTO_seconds": elapsed,
                    "restored_https_download_and_stop": "PASS",
                    "unsafe_inventory_upgrade": "REFUSED",
                    "provider_requests": 0,
                },
                indent=2,
            )
            + "\n"
        )
    except subprocess.CalledProcessError as error:
        # These are generated disposable identities. Do not print stdin or keys.
        print((error.stderr or "")[-6000:], file=sys.stderr)
        for unit in units:
            subprocess.run(
                ["journalctl", "--no-pager", "-n", "15", "-u", unit],
                check=False,
                timeout=10,
            )
        raise
    finally:
        for unit in units:
            subprocess.run(
                ["systemctl", "stop", unit], capture_output=True, timeout=20, check=False
            )
        subprocess.run(
            ["docker", "stop", "-t", "5", "polysia-acceptance-restored-web"],
            capture_output=True,
            timeout=15,
            check=False,
        )


def verify_browser(
    image: str, bundle: Path, archived: dict, root: Path, *, restored_state: Path
) -> None:
    """Real restored image, private trusted HTTPS, archive download and durable command route."""
    browser = root / "browser"
    browser.mkdir(mode=0o755)
    for name in ("publication", "control"):
        (browser / name).mkdir(mode=0o2770)
        os.chown(browser / name, 10101, 10102)
    shutil.copytree(restored_state / "publication/reports", browser / "publication/reports")
    shutil.copy2(
        restored_state / "publication/publication.json", browser / "publication/publication.json"
    )
    shutil.copy2(restored_state / "control/commands.sqlite3", browser / "control/commands.sqlite3")
    for path in browser.rglob("*"):
        os.chown(path, 10101, 10102)
        path.chmod(0o2770 if path.is_dir() else 0o660)
    web = json.loads(Path("/etc/polysia-platform/web.json").read_text())
    web["unix_socket"] = "/run/polysia-platform/restored.sock"
    (browser / "web.json").write_text(json.dumps(web))
    (browser / "web.json").chmod(0o644)
    run(
        "docker",
        "run",
        "--detach",
        "--rm",
        "--name",
        "polysia-acceptance-restored-web",
        "--user",
        "10102:10102",
        "--network",
        "none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory",
        "128m",
        "--cpus",
        ".25",
        "--volume",
        str(browser / "web.json") + ":/config/web.json:ro",
        "--volume",
        "/etc/polysia-platform/csrf-secret:/config/csrf-secret:ro",
        "--volume",
        str(browser / "publication") + ":/publication:ro",
        "--volume",
        str(browser / "control") + ":/control:rw",
        "--volume",
        "/run/polysia-platform:/run/polysia-platform:rw",
        image,
        "system",
        "console",
        "--config",
        "/config/web.json",
    )
    caddyfile = Path("/etc/polysia-platform/Caddyfile")
    original = caddyfile.read_text()
    caddyfile.write_text(
        original.replace("/run/polysia-platform/web.sock", "/run/polysia-platform/restored.sock")
    )
    run("systemctl", "restart", "polysia-platform-gateway.service")
    context = ssl.create_default_context(
        cafile="/var/lib/polysia-platform/gateway/caddy/pki/authorities/local/root.crt"
    )
    credentials = json.loads(Path("/etc/polysia-platform/gateway-credentials.json").read_text())
    headers = {
        "Authorization": "Basic "
        + base64.b64encode(("owner:" + credentials["owner"]).encode()).decode()
    }
    try:
        ready = time.monotonic() + 60
        while True:
            try:
                with urlopen(
                    Request(
                        "https://localhost:8443/reports/" + archived["analytical_digest"] + ".json",
                        headers=headers,
                    ),
                    context=context,
                    timeout=5,
                ) as response:
                    assert json.load(response) == archived
                break
            except HTTPError as error:
                if error.code not in {502, 503} or time.monotonic() >= ready:
                    raise
            except URLError:
                if time.monotonic() >= ready:
                    raise
            time.sleep(0.2)
        with urlopen(
            Request("https://localhost:8443", headers=headers), context=context, timeout=15
        ) as response:
            assert b"PolySia Console" in response.read()
            cookie = response.headers["Set-Cookie"].split(";", 1)[0]
        with urlopen(
            Request("https://localhost:8443/api/commands", headers=headers),
            context=context,
            timeout=15,
        ) as response:
            revision = json.load(response)["revision"]
        body = {
            "action": "stop",
            "expected_revision": revision,
            "idempotency_key": "restored-browser-stop-fixture",
            "csrf": cookie.split("=", 1)[1],
        }
        with urlopen(
            Request(
                "https://localhost:8443/api/commands",
                data=json.dumps(body).encode(),
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Cookie": cookie,
                    "Origin": "https://localhost:8443",
                },
            ),
            context=context,
            timeout=15,
        ) as response:
            assert response.status == 202
    finally:
        caddyfile.write_text(original)
        run("systemctl", "restart", "polysia-platform-gateway.service")


if __name__ == "__main__":
    main()
