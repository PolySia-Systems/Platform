"""Owner-only finite host orchestration for existing Platform entry points.

No financial worker is launched unless the owner explicitly supplies
--execute-owner-test. Other modes only inspect or run independent controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def role_id(profile: dict[str, Any], role: str) -> str:
    if role not in {"backup", "control", "worker", "stop"}:
        raise ValueError("known_OP1_role_required")
    return "polysia-op1-" + hashlib.sha256(profile["run_id"].encode()).hexdigest()[:12] + "-" + role


def container_command(profile: dict[str, Any], role: str) -> list[str]:
    base = Path(profile["base"])
    packet = Path(profile["packet"])
    command = [
        "ctr",
        "-n",
        profile["namespace"],
        "run",
        "--rm",
        "--read-only",
        "--hostname",
        "Hetzner-Finland-Helsinki-01",
        "--user",
        "999:981" if role == "worker" else "995:981",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--mount",
        f"type=bind,src={base},dst={base},options=rbind:ro",
        "--mount",
        f"type=bind,src={profile['trust']},dst=/trust.json,options=rbind:ro",
    ]
    if role == "worker":
        command += [
            "--net-host",
            "--cpus",
            "0.25",
            "--memory-limit",
            "536870912",
            "--mount",
            f"type=bind,src={profile['worker_directory']},dst={profile['worker_directory']},options=rbind:rw",
            "--mount",
            f"type=bind,src={profile['worker_script']},dst=/worker.py,options=rbind:ro",
        ]
        inner = [
            "python",
            "/worker.py",
            "--config",
            str(packet / "config.json"),
            "--authority",
            str(packet / "authority-signed.json"),
            "--trust",
            "/trust.json",
            "--credentials",
            str(Path(profile["worker_directory"]) / "credentials.json"),
            "--execute-owner-test",
        ]
    else:
        for key in ("supervisor_directory", "commands_directory"):
            command += [
                "--mount",
                f"type=bind,src={profile[key]},dst={profile[key]},options=rbind:rw",
            ]
        if role == "stop":
            inner = [
                "polysia",
                "ops",
                "session",
                "stop",
                "--config",
                str(packet / "config.json"),
                "--authority",
                str(packet / "authority-signed.json"),
            ]
        else:
            inner = [
                "polysia",
                "ops",
                "session",
                "control",
                "--config",
                str(packet / "config.json"),
                "--authority",
                str(packet / "authority-signed.json"),
                "--trust",
                "/trust.json",
                "--backup",
                str(Path(profile["publication"]) / "current-backup.json"),
                "--ticks",
                "200000",
                "--release-stop",
            ]
    return command + [profile["image"], role_id(profile, role), *inner]


def run_role(profile: dict[str, Any], role: str) -> None:
    from op1_backup_transport import watch

    until = datetime.fromisoformat(profile["until"])
    duration = math.ceil((until - datetime.now(UTC)).total_seconds())
    if not 0 < duration <= 7200:
        raise ValueError("current_finite_owner_window_required")
    if role == "backup":
        watch(profile, duration=duration, interval=20)
        return
    command = container_command(profile, role)
    process = subprocess.Popen(command)

    def terminate(*signal_args: object) -> None:
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, terminate)
    try:
        result = process.wait(timeout=duration)
        if result:
            raise RuntimeError("bounded_role_failed")
    finally:
        if process.poll() is None:
            subprocess.run(
                [
                    "ctr",
                    "-n",
                    profile["namespace"],
                    "tasks",
                    "kill",
                    "--signal",
                    "SIGINT",
                    role_id(profile, role),
                ],
                check=False,
                capture_output=True,
                timeout=5,
            )
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    [
                        "ctr",
                        "-n",
                        profile["namespace"],
                        "tasks",
                        "kill",
                        "--signal",
                        "SIGKILL",
                        role_id(profile, role),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
                process.wait(timeout=5)


def start_unit(profile: dict[str, Any], profile_path: Path, role: str, duration: int) -> None:
    duration = min(
        duration,
        math.ceil((datetime.fromisoformat(profile["until"]) - datetime.now(UTC)).total_seconds()),
    )
    if duration <= 0:
        raise ValueError("protective_window_expired_before_unit_start")
    command = [
        "systemd-run",
        "--quiet",
        "--collect",
        "--unit",
        role_id(profile, role),
        "--property=RuntimeMaxSec=" + str(duration),
        "--property=Restart=no",
        "--property=KillMode=control-group",
        "--property=ExecStopPost=-/usr/bin/python3 "
        + profile["host_script"]
        + " cleanup --profile "
        + str(profile_path)
        + " --role "
        + role,
        "/usr/bin/python3",
        profile["host_script"],
        "child",
        "--profile",
        str(profile_path),
        "--role",
        role,
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=15)


def cleanup_role(profile: dict[str, Any], role: str) -> None:
    prefix = profile["task_prefix"] + "-" if role == "backup" else role_id(profile, role)
    if not prefix.startswith("polysia-op1-") or len(prefix) < 24:
        raise ValueError("isolated_role_cleanup_prefix_required")
    tasks = subprocess.check_output(["ctr", "-n", profile["namespace"], "tasks", "list"], text=True)
    for row in tasks.splitlines()[1:]:
        task = row.split()[0]
        if task.startswith(prefix) if role == "backup" else task == prefix:
            subprocess.run(
                ["ctr", "-n", profile["namespace"], "tasks", "kill", "--signal", "SIGKILL", task],
                check=False,
                capture_output=True,
                timeout=5,
            )


def service_state(profile: dict[str, Any], role: str) -> str:
    result = subprocess.run(
        ["systemctl", "show", role_id(profile, role), "--property=ActiveState", "--value"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()


def inspect_run(profile: dict[str, Any]) -> dict[str, Any]:
    import sqlite3

    with sqlite3.connect(Path(profile["financial_path"]).as_uri() + "?mode=ro", uri=True) as db:
        state = json.loads(db.execute("SELECT state FROM session").fetchone()[0])
    with sqlite3.connect(Path(profile["custody_path"]).as_uri() + "?mode=ro", uri=True) as db:
        custody = db.execute(
            "SELECT stopped,stop_reason,revoked FROM grants WHERE fingerprint=?",
            (profile["authority_fingerprint"],),
        ).fetchone()
    if custody is None:
        raise ValueError("existing_independent_custody_required")
    return {
        "mode": state["mode"],
        "attempts": state["attempts"],
        "orders": state["orders"],
        "fills": state["fills"],
        "requests": state["requests"],
        "response_bytes": state["response_bytes"],
        "reconciled_at": state["reconciled_at"],
        "reconciliation_ok": state["reconciliation_ok"],
        "equity": state["equity"],
        "quarantined_fills": state["quarantined_fills"],
        "quarantined_finality": state["quarantined_finality"],
        "services": {
            role: service_state(profile, role) for role in ("backup", "control", "worker")
        },
        "financial_state_only": True,
        "external_reconciliation_not_inferred": True,
        "custody_stopped": bool(custody[0]),
        "stop_reason": custody[1],
        "revoked": bool(custody[2]),
    }


def start(profile: dict[str, Any], path: Path, *, execute_owner_test: bool) -> None:
    if not execute_owner_test:
        raise ValueError("explicit_manual_owner_execution_required")
    if os.geteuid() != 0:
        raise ValueError("protected_owner_operator_required")
    if not Path("/etc/polysia-platform/restart-fenced").is_file():
        raise ValueError("original_N3_fence_required")
    if subprocess.run(
        ["systemctl", "is-active", "--quiet", "polysia-platform"], check=False
    ).returncode == 0:
        raise ValueError("original_N3_financial_service_must_remain_inactive")
    ack_path = Path(profile["alert_receipt"])
    ack = json.loads(ack_path.read_text())
    if (
        ack_path.is_symlink()
        or ack_path.stat().st_uid != 0
        or ack_path.stat().st_mode & 0o022
        or ack.get("human_reported_received") is not True
        or ack.get("message_id") != profile["alert_message_id"]
    ):
        raise ValueError("verified_owner_human_alert_receipt_required")
    state = inspect_run(profile)
    if state["attempts"] or state["orders"] or state["fills"]:
        raise ValueError("prior_financial_activity_requires_reconciliation_not_restart")
    if (
        state["mode"] != "STOP"
        or not state["custody_stopped"]
        or state["revoked"]
        or state["stop_reason"] != "commissioning_stop"
    ):
        raise ValueError("initial_commissioning_STOP_required_not_recovery_override")
    if any(x in {"active", "activating"} for x in state["services"].values()):
        raise ValueError("existing_managed_run_must_not_be_restarted")
    now = datetime.now(UTC)
    if now >= datetime.fromisoformat(profile["entry_until"]):
        raise ValueError("signed_entry_window_expired")
    duration = math.ceil((datetime.fromisoformat(profile["until"]) - now).total_seconds())
    if not 0 < duration <= 7200:
        raise ValueError("finite_protective_window_required")
    marker = Path(profile["packet"]) / "owner-start-request.json"
    with os.fdopen(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(
            {"owner_entry_requested": True, "at": now.isoformat(), "run_id": profile["run_id"]},
            stream,
        )
    try:
        start_unit(profile, path, "backup", duration)
        deadline = time.monotonic() + 90
        while True:
            if service_state(profile, "backup") != "active":
                raise RuntimeError("automatic_backup_not_running")
            publication = Path(profile["publication"]) / "current-backup.json"
            completed = list(Path(profile["generations"]).glob("*/publication-input.json"))
            if publication.exists() and len(completed) >= 3:
                observed = json.loads(publication.read_text())["observed_at"]
                if (datetime.now(UTC) - datetime.fromisoformat(observed)).total_seconds() < 30:
                    break
            if time.monotonic() >= deadline:
                raise TimeoutError("offsite_backup_warmup_failed")
            time.sleep(0.25)
        # Qualification and execution share the 60 attempts/minute ceiling.
        wait_until = datetime.fromisoformat(profile["qualification_last_read_at"]).timestamp() + 60
        while time.time() < wait_until:
            time.sleep(min(0.25, wait_until - time.time()))
        if datetime.now(UTC) >= datetime.fromisoformat(profile["entry_until"]):
            raise ValueError("entry_window_expired_during_control_warmup")
        start_unit(profile, path, "control", duration)
        start_unit(profile, path, "worker", duration)
        while service_state(profile, "worker") in {"active", "activating"}:
            if any(service_state(profile, role) != "active" for role in ("backup", "control")):
                raise RuntimeError("independent_control_service_failed")
            if datetime.now(UTC) >= datetime.fromisoformat(profile["until"]):
                break
            time.sleep(0.5)
    finally:
        # Restrictive custody STOP uses the independent role, never the signer.
        try:
            subprocess.run(
                container_command(profile, "stop"), capture_output=True, timeout=20, check=True
            )
        finally:
            for role in ("worker", "control", "backup"):
                subprocess.run(
                    ["systemctl", "stop", role_id(profile, role)],
                    check=False,
                    capture_output=True,
                    timeout=20,
                )
    print(json.dumps(inspect_run(profile)), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("start", "child", "inspect", "cleanup"))
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--role", choices=("backup", "control", "worker"))
    parser.add_argument("--execute-owner-test", action="store_true")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    if profile["namespace"] != "polysia-op1" or profile["base"] != "/var/lib/polysia-op1":
        raise ValueError("existing_isolated_primary_namespace_required")
    if args.mode == "start":
        start(profile, args.profile, execute_owner_test=args.execute_owner_test)
    elif args.mode == "child":
        run_role(profile, args.role)
    elif args.mode == "cleanup":
        cleanup_role(profile, args.role)
    else:
        print(json.dumps(inspect_run(profile)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "HOST_STOP", "error_type": type(error).__name__}), flush=True)
        sys.exit(1)
