"""Real stock-Caddy issuance/renewal/failure/recovery against an isolated Pebble CA.

Explicit disposable GitHub-runner acceptance only. All certificate/DNS endpoints
and challenge listeners are loopback fixtures. No public CA or provider is used.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import socket
import ssl
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

PEBBLE = "v2.10.1"
PEBBLE_SOURCE = "97b2dfade8306ab00f13904b70b0b48753cccdbd"
ARCHIVES = {
    "pebble": "4f2fcb5bca8c85c9cf73ad140fccfc0d2be40bd81ab99879c79b7b8a0b4f70ed",
    "pebble-challtestsrv": "e93a5aa25ecdf3af2f9fbb2de32b0173e64a2eae81002a4ccfe35fa6f4f60b92",
}
HOST = "console.polysia.example.com"


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120).stdout


def fetch(url: str, target: Path) -> None:
    with urlopen(url, timeout=30) as reply:
        data = reply.read(100_000_001)
    if len(data) > 100_000_000:
        raise ValueError("fixture asset exceeds size bound")
    target.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (
        os.geteuid() != 0
        or os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("RUNNER_ENVIRONMENT") != "github-hosted"
        or Path("/var/lib/polysia-platform/worker/authority.sqlite3").exists()
    ):
        raise ValueError("fresh disposable GitHub-runner installation required")
    units = []
    root = Path(tempfile.mkdtemp(prefix="polysia-acme-", dir="/var/tmp"))
    root.chmod(0o750)
    os.chown(root, 0, 10102)
    caddy = Path("/opt/polysia-platform/gateway/2.11.7/caddy")
    ca_state = root / "state"
    control = root / "control"
    for directory in (ca_state, control):
        directory.mkdir(mode=0o700)
        os.chown(directory, 10102, 10102)
    try:
        for name, digest in ARCHIVES.items():
            archive = root / (name + ".tar.gz")
            fetch(
                "https://github.com/letsencrypt/pebble/releases/download/"
                + PEBBLE
                + "/"
                + name
                + "-linux-amd64.tar.gz",
                archive,
            )
            assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
            with tarfile.open(archive) as bundle:
                members = [
                    member
                    for member in bundle.getmembers()
                    if Path(member.name).name == name and member.isfile()
                ]
                assert len(members) == 1 and members[0].size < 100_000_000
                stream = bundle.extractfile(members[0])
                assert stream is not None
                (root / name).write_bytes(stream.read())
                (root / name).chmod(0o755)
        for source, name in (
            ("localhost/cert.pem", "api-cert.pem"),
            ("localhost/key.pem", "api-key.pem"),
            ("pebble.minica.pem", "api-root.pem"),
        ):
            fetch(
                "https://raw.githubusercontent.com/letsencrypt/pebble/"
                + PEBBLE_SOURCE
                + "/test/certs/"
                + source,
                root / name,
            )
            os.chown(root / name, 0, 10102)
            (root / name).chmod(0o640)
        configuration = {
            "pebble": {
                "listenAddress": "127.0.0.1:14000",
                "managementListenAddress": "127.0.0.1:15000",
                "certificate": str(root / "api-cert.pem"),
                "privateKey": str(root / "api-key.pem"),
                "httpPort": 80,
                "tlsPort": 443,
                "externalAccountBindingRequired": False,
                "retryAfter": {"authz": 1, "order": 1},
                "keyAlgorithm": "ecdsa",
                "profiles": {
                    "default": {
                        "description": "isolated short-lived fixture",
                        "validityPeriod": 120,
                    }
                },
            }
        }
        (root / "pebble.json").write_text(json.dumps(configuration))

        def start(name, command, *, public_ports=False, environment=()):
            unit = "polysia-acceptance-" + name
            units.append(unit)
            run(
                "systemd-run",
                "--unit=" + unit,
                "--service-type=exec",
                "--property=User=10102",
                "--property=Group=10102",
                "--property=MemoryMax=256M",
                "--property=CPUQuota=50%",
                "--property=TasksMax=64",
                "--property=NoNewPrivileges=true",
                "--property=ProtectSystem=strict",
                "--property=ProtectHome=true",
                "--property=ReadWritePaths=" + str(ca_state),
                "--property=StandardOutput=append:" + str(root / (name + ".log")),
                "--property=StandardError=append:" + str(root / (name + ".log")),
                "--property=AmbientCapabilities="
                + ("CAP_NET_BIND_SERVICE" if public_ports else ""),
                *["--setenv=" + item for item in environment],
                *command,
            )
            return unit

        start(
            "dns",
            [
                str(root / "pebble-challtestsrv"),
                "-http01=",
                "-https01=",
                "-doh=",
                "-tlsalpn01=",
                "-dnsserver=127.0.0.1:18053",
                "-management=127.0.0.1:18055",
                "-defaultIPv4=127.0.0.1",
                "-defaultIPv6=",
            ],
        )
        start(
            "ca",
            [
                str(root / "pebble"),
                "-config=" + str(root / "pebble.json"),
                "-dnsserver=127.0.0.1:18053",
            ],
            environment=("PEBBLE_VA_NOSLEEP=1", "PEBBLE_AUTHZREUSE=0", "PEBBLE_WFE_NONCEREJECT=0"),
        )
        api_context = ssl.create_default_context(cafile=str(root / "api-root.pem"))
        deadline = time.monotonic() + 30
        while True:
            try:
                with urlopen(
                    "https://localhost:15000/roots/0", context=api_context, timeout=3
                ) as response:
                    issued_root = response.read(65536)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        (root / "issued-root.pem").write_bytes(issued_root)
        context = ssl.create_default_context(cafile=str(root / "issued-root.pem"))
        passwords = json.loads(Path("/etc/polysia-platform/gateway-credentials.json").read_text())
        hashes = {
            name: subprocess.run(
                [str(caddy), "hash-password", "--bcrypt-cost", "10"],
                input=password + "\n",
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout.strip()
            for name, password in passwords.items()
        }
        data = {
            "profile": "own-domain",
            "origin": "https://" + HOST,
            "socket_path": "/run/polysia-platform/acme.sock",
            "passwords": hashes,
        }
        rendered = subprocess.run(
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
                "--entrypoint",
                "python",
                args.image_id,
                "-c",
                "import json,sys; from polysia.deployment.gateway import gateway_config; "
                "print(gateway_config(**json.load(sys.stdin)))",
            ],
            input=json.dumps(data),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        # Only test CA, loopback bind and short timing differ from the product configuration.
        rendered = rendered.replace(
            "{\n",
            "{\n    acme_ca https://localhost:14000/dir\n"
            "    default_bind 127.0.0.1\n"
            "    acme_ca_root "
            + str(root / "api-root.pem")
            + "\n    renew_interval 1s\n    cert_lifetime 2m\n"
            "    renewal_window_ratio 0.9\n",
            1,
        )
        rendered = rendered.replace(
            "https://" + HOST + " {", "https://" + HOST + " {\n    bind 127.0.0.1"
        )
        (root / "Caddyfile").write_text(rendered)
        os.chown(root / "Caddyfile", 0, 10102)
        (root / "Caddyfile").chmod(0o640)
        web = {
            "profile": "own-domain",
            "origin": "https://" + HOST,
            "unix_socket": "/run/polysia-platform/acme.sock",
            "roles": {"owner": "operator", "reader": "reader"},
            "commands": "/control/commands.sqlite3",
            "csrf_secret_file": "/config/csrf-secret",
            "publication": "/publication/publication.json",
        }
        (root / "web.json").write_text(json.dumps(web))
        (root / "web.json").chmod(0o644)
        run(
            "docker",
            "run",
            "--detach",
            "--name",
            "polysia-acceptance-acme-web",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--user",
            "10102:10102",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory",
            "128m",
            "--cpus",
            ".25",
            "--volume",
            str(root / "web.json") + ":/config/web.json:ro",
            "--volume",
            "/etc/polysia-platform/csrf-secret:/config/csrf-secret:ro",
            "--volume",
            "/var/lib/polysia-platform/publication:/publication:ro",
            "--volume",
            str(control) + ":/control:rw",
            "--volume",
            "/run/polysia-platform:/run/polysia-platform:rw",
            args.image_id,
            "system",
            "console",
            "--config",
            "/config/web.json",
        )
        gateway_unit = start(
            "acme-gateway",
            [str(caddy), "run", "--config", str(root / "Caddyfile")],
            public_ports=True,
            environment=("XDG_DATA_HOME=" + str(ca_state),),
        )

        def request(*, user="owner", path="/", headers=None, method="GET", body=None):
            supplied = {"Host": HOST, "Connection": "close", **(headers or {})}
            if user is not None:
                supplied["Authorization"] = (
                    "Basic " + base64.b64encode((user + ":" + passwords[user]).encode()).decode()
                )
            raw = json.dumps(body).encode() if body is not None else b""
            supplied["Content-Length"] = str(len(raw))
            if body is not None:
                supplied["Content-Type"] = "application/json"
            with (
                socket.create_connection(("127.0.0.1", 443), timeout=5) as connection,
                context.wrap_socket(connection, server_hostname=HOST) as protected,
            ):
                peer = protected.getpeercert()
                protected.sendall(
                    (
                        method
                        + " "
                        + path
                        + " HTTP/1.1\r\n"
                        + "\r\n".join(key + ": " + value for key, value in supplied.items())
                        + "\r\n\r\n"
                    ).encode()
                    + raw
                )
                reply = http.client.HTTPResponse(protected)
                reply.begin()
                return reply.status, reply.read(), peer

        def wait_certificate(different=None, *, timeout=100):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    status, _, peer = request()
                    if status == 200 and peer["serialNumber"] != different:
                        return peer
                except OSError:
                    pass
                time.sleep(0.5)
            raise AssertionError("trusted certificate issuance/renewal did not complete")

        initial = wait_certificate()
        assert request(user=None, headers={"X-Polysia-User": "owner"})[0] == 401
        assert request(user="reader", path="/api/commands", method="POST", body={})[0] == 403
        assert (
            request(
                user="reader",
                headers={"X_Polysia_User": "owner"},
                path="/api/commands",
                method="POST",
                body={},
            )[0]
            == 403
        )
        assert request(headers={"Origin": "https://foreign.invalid"})[0] == 403
        assert request(headers={"Host": "foreign.invalid"})[0] in {403, 404, 421}
        renewed = wait_certificate(initial["serialNumber"])
        # Controlled fixture DNS failure; Caddy cannot reach its HTTP/TLS challenge.
        change_dns = Request(
            "http://127.0.0.1:18055/set-default-ipv4",
            method="POST",
            data=b'{"ip":"127.0.0.2"}',
            headers={"Content-Type": "application/json"},
        )
        with urlopen(change_dns, timeout=5):
            pass
        failure_deadline = time.monotonic() + 110
        while time.monotonic() < failure_deadline:
            log = (root / "acme-gateway.log").read_text()
            if any('"level":"error"' in line and "tls.renew" in line for line in log.splitlines()):
                break
            time.sleep(0.5)
        else:
            raise AssertionError("actual ACME renewal failure was not observed")
        failed_status, _, failed_peer = request()
        assert failed_status == 200  # Existing certificate still works while valid.
        change_dns.data = b'{"ip":"127.0.0.1"}'
        with urlopen(change_dns, timeout=5):
            pass
        run("systemctl", "restart", gateway_unit)
        recovered = wait_certificate(failed_peer["serialNumber"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "profile": "own-domain",
                    "trust": "ISOLATED_TEST_CA",
                    "publicly_trusted_commissioning": "EXTERNAL_NOT_VERIFIED",
                    "issuance": "PASS",
                    "renewal": "PASS",
                    "renewal_failure": "PASS",
                    "recovery": "PASS",
                    "initial_serial": initial["serialNumber"],
                    "renewed_serial": renewed["serialNumber"],
                    "recovered_serial": recovered["serialNumber"],
                    "public_provider_requests": 0,
                    "pebble_release": PEBBLE,
                    "pebble_source": PEBBLE_SOURCE,
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        subprocess.run(
            ["docker", "stop", "-t", "5", "polysia-acceptance-acme-web"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        for unit in reversed(units):
            subprocess.run(
                ["systemctl", "stop", unit], capture_output=True, timeout=15, check=False
            )
        # Plaintext fixture keys remain only in this disposable runner until teardown.


if __name__ == "__main__":
    main()
