"""Install exact CI assets on a disposable Ubuntu runner and verify trusted HTTPS.

Requires root, systemd and Docker. Never run against an existing installation.
The normal suite does not invoke this explicit acceptance workload.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import socket
import ssl
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def run(*args: str) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=300)
    if result.returncode:
        # Only this disposable fixture's subprocess diagnostics, never credential files.
        print(result.stderr[-12000:], file=sys.stderr)
        result.check_returncode()
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-handoff", type=Path)
    args = parser.parse_args()
    config, state = Path("/etc/polysia-platform"), Path("/var/lib/polysia-platform")
    if os.geteuid() != 0 or config.exists() or state.exists():
        raise ValueError("a clean disposable root-owned destination is required")
    artifact = args.artifact_directory.resolve()
    sys.path.insert(0, str(artifact))
    import platform_admin as admin
    import platform_bootstrap as core

    manifest = core.verify_artifact(artifact, commit=args.commit)
    for name, field in (
        ("platform_admin.py", "admin_sha256"),
        ("platform_bootstrap.py", "bootstrap_sha256"),
    ):
        assert hashlib.sha256((artifact / name).read_bytes()).hexdigest() == manifest[field]
    admin.core = core
    value = {
        "schema": admin.SCHEMA,
        "commit": args.commit,
        "profile": "private",
        "hostname": "localhost",
        "public_opt_in": False,
        "roles": {"owner": "operator", "reader": "reader"},
        "backup": {"mode": "none"},
    }
    admin.preflight(value)
    # A process interruption after staging must be resumable, preserving staged identity.
    staged = core.bootstrap(artifact, commit=args.commit, install_units=False)
    command = (
        sys.executable,
        str(artifact / "platform_admin.py"),
        "install",
        "--noninteractive",
        "--profile",
        "private",
        "--commit",
        args.commit,
        "--artifact-directory",
        str(artifact),
    )
    first = json.loads(run(*command))
    assert first["status"] == "SETUP_COMPLETE"
    credentials = (config / "gateway-credentials.json").read_bytes()
    second = json.loads(run(*command))
    assert second["status"] == "SETUP_COMPLETE"
    assert (config / "gateway-credentials.json").read_bytes() == credentials
    assert (
        staged["image_id"]
        == json.loads((config / "maintenance-receipt.json").read_text())["image_id"]
    )
    for unit in (
        "worker.timer",
        "publisher.timer",
        "web.service",
        "gateway.service",
        "health.timer",
    ):
        assert run("systemctl", "is-active", "polysia-platform-" + unit).strip() == "active"
    run("systemctl", "start", "polysia-platform-health.service")
    ca = state / "gateway/caddy/pki/authorities/local/root.crt"
    deadline = time.monotonic() + 40
    while not ca.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    context = ssl.create_default_context(cafile=str(ca))
    accounts = json.loads(credentials)

    def request(path="/", *, user="owner", password=None, method="GET", body=None, headers=None):
        supplied = dict(headers or {})
        if user is not None:
            raw = (user + ":" + (password or accounts[user])).encode()
            supplied["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        if body is not None:
            supplied["Content-Type"] = "application/json"
        req = Request(
            "https://localhost:8443" + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers=supplied,
        )
        try:
            with urlopen(req, context=context, timeout=15) as reply:
                return reply.status, dict(reply.headers), reply.read()
        except HTTPError as error:
            return error.code, dict(error.headers), error.read()

    # Trust is explicit to this client; no global trust store is changed.
    while time.monotonic() < deadline:
        try:
            status, headers, _ = request()
            if status == 200:
                break
        except URLError:
            time.sleep(0.2)
    assert status == 200
    assert request(user=None)[0] == 401
    assert request(password="incorrect-fixture-password")[0] == 401
    assert request(user=None, headers={"X-Polysia-User": "owner"})[0] == 401
    assert request(headers={"Host": "foreign.invalid"})[0] in {403, 404, 421}
    assert request(headers={"Origin": "https://foreign.invalid"})[0] == 403
    assert request(user="reader", method="POST", path="/api/commands", body={})[0] == 403
    assert (
        request(
            user="reader",
            headers={"X-Polysia-User": "owner"},
            method="POST",
            path="/api/commands",
            body={},
        )[0]
        == 403
    )
    assert (
        request(
            user="reader",
            headers={"X_Polysia_User": "owner"},
            method="POST",
            path="/api/commands",
            body={},
        )[0]
        == 403
    )
    assert oct(Path("/run/polysia-platform/web.sock").stat().st_mode & 0o777) == "0o660"
    with socket.socket() as direct:
        direct.settimeout(1)
        assert direct.connect_ex(("127.0.0.1", 8765)) != 0
    denied = subprocess.run(
        [
            "runuser",
            "-u",
            "nobody",
            "--",
            "python3",
            "-c",
            "import socket; s=socket.socket(socket.AF_UNIX); "
            "s.connect('/run/polysia-platform/web.sock')",
        ],
        capture_output=True,
        timeout=10,
    )
    assert denied.returncode != 0 and b"PermissionError" in denied.stderr
    report = json.loads(request("/api/report")[2])
    assert report["status"] == "UNCONFIGURED" and report["real_orders"] is False
    assert not (state / "worker/authority.sqlite3").exists()
    csrf_cookie = headers["Set-Cookie"].split(";", 1)[0]
    command_body = {
        "action": "stop",
        "expected_revision": 0,
        "idempotency_key": "installation-stop-fixture",
        "csrf": csrf_cookie.split("=", 1)[1],
    }
    assert (
        request(
            "/api/commands",
            method="POST",
            body=command_body,
            headers={"Cookie": csrf_cookie, "Origin": "https://localhost:8443"},
        )[0]
        == 202
    )
    run("systemctl", "start", "polysia-platform-worker.service")
    receipt = json.loads(request("/api/commands")[2])
    assert receipt["receipts"][0]["status"] == "APPLIED"
    publication = state / "publication/publication.json"
    original = publication.read_bytes()
    fixture = {
        **report,
        "dataset_role": "ISOLATED_INSTALLATION_PERFORMANCE_FIXTURE",
        "diagnostic": {
            "discovery": {
                "candidates": [
                    {
                        "wallet_id": "fixture-" + str(i),
                        "execution_eligibility": "FIXTURE_ONLY",
                        "detail": "x" * 1024,
                    }
                    for i in range(512)
                ]
            }
        },
    }
    payload = json.dumps(fixture).encode()
    run("systemctl", "stop", "polysia-platform-publisher.timer")
    try:
        publication.write_bytes(payload)
        timings = []
        for _ in range(100):
            started = time.perf_counter()
            code, _, measured = request("/api/report")
            timings.append(time.perf_counter() - started)
            assert code == 200
            assert len(json.loads(measured)["diagnostic"]["discovery"]["candidates"]) == 512
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            load = [pool.submit(request, password="invalid-load-fixture") for _ in range(32)]
            assert request("/api/report")[0] == 200
            assert all(future.result()[0] == 401 for future in load)
        p95 = sorted(timings)[94]
        assert p95 < 2, p95
    finally:
        publication.write_bytes(original)
        run("systemctl", "start", "polysia-platform-publisher.timer")
    # A revoked credential is rejected on every subsequent request, including cached browsers.
    run(
        sys.executable,
        str(artifact / "platform_admin.py"),
        "configure",
        "--noninteractive",
        "--artifact-directory",
        str(artifact),
        "--remove-user",
        "reader",
    )
    assert request(user="reader")[0] == 401
    run(sys.executable, str(artifact / "platform_admin.py"), "stop", "--noninteractive")
    assert (config / "restart-fenced").exists()
    run("systemctl", "start", "polysia-platform-worker.service")
    assert (
        run(
            "systemctl",
            "show",
            "polysia-platform-worker.service",
            "--property",
            "ConditionResult",
            "--value",
        ).strip()
        == "no"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.browser_handoff:
        args.browser_handoff.write_text(
            json.dumps(
                {
                    "username": "owner",
                    "password": accounts["owner"],
                    "ca_certificate": ca.read_text(),
                    "fixture_only": True,
                }
            )
        )
        args.browser_handoff.chmod(0o600)
        os.chown(args.browser_handoff, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    args.output.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source": args.commit,
                "image_id": staged["image_id"],
                "os_release": Path("/etc/os-release").read_text(),
                "profile": "private",
                "trusted_https": "explicit isolated Caddy CA; no certificate bypass",
                "interrupted_rerun": "PASS",
                "revocation": "PASS",
                "protected_stop": "PASS",
                "sample_count": 100,
                "payload_bytes": len(payload),
                "fixture_wallets": 512,
                "cached_api_p95_seconds": p95,
                "cached_api_median_seconds": statistics.median(timings),
                "provider_requests": 0,
                "checked_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        for unit in ("web", "gateway", "worker", "publisher"):
            subprocess.run(
                ["journalctl", "--no-pager", "-n", "20", "-u", "polysia-platform-" + unit],
                check=False,
                timeout=10,
            )
        raise
