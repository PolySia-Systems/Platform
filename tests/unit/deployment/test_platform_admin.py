from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from deploy import platform_admin as admin
from deploy import platform_bootstrap as core


def configuration():
    return {
        "schema": admin.SCHEMA,
        "commit": "a" * 40,
        "profile": "private",
        "hostname": "localhost",
        "public_opt_in": False,
        "roles": {"owner": "operator", "reader": "reader"},
        "backup": {"mode": "none"},
    }


@pytest.mark.parametrize(
    "change",
    [
        {"commit": "main"},
        {"schema": "future"},
        {"hostname": "localhost\nroot"},
        {"profile": "anonymous"},
        {"roles": {"owner": "root"}},
        {"roles": {"reader": "reader"}},
        {"backup": {"mode": "cloud"}},
        {"hostname": "public.example.com"},
        {"profile": "own-domain", "hostname": "console.example.com"},
    ],
)
def test_configuration_fails_closed_before_mutation(change):
    with pytest.raises(ValueError):
        admin.validate({**configuration(), **change})


def test_private_and_explicit_domain_configuration_are_versioned_and_validated():
    assert admin.validate(configuration())["profile"] == "private"
    value = {
        **configuration(),
        "profile": "own-domain",
        "hostname": "console.example.com",
        "public_opt_in": True,
    }
    assert admin.validate(value) == value


def test_same_release_rerun_cannot_restart_newly_authorized_acquisition(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    (tmp_path / "worker.json").write_text(
        json.dumps(
            {
                "release_commit": "a" * 40,
                "acquisition_enabled": True,
                "admission": {},
            }
        )
    )
    with pytest.raises(ValueError, match="disable acquisition"):
        core.activation_preflight("a" * 40)


def test_gateway_backend_has_no_tcp_or_financial_mount_and_stop_survives_queue_failure():
    args = core.container_command(
        "sha256:" + "a" * 64, role="web", hostname="fixture", gateway=True, configured=False
    )
    assert args[args.index("--network") + 1] == "none"
    assert not any("/state" in value or "docker.sock" in value for value in args)
    assert "/run/polysia-platform:/run/polysia-platform:rw" in args
    worker = core.service_text("sha256:" + "a" * 64, role="worker", hostname="fixture")
    assert "ConditionPathExists=!/etc/polysia-platform/restart-fenced" in worker
    gateway = admin.gateway_unit(Path("/opt/polysia-platform/gateway/caddy"), public=False)
    assert "CPUQuota=25%" in gateway and "MemoryMax=192M" in gateway
    assert "InaccessiblePaths=/var/lib/polysia-platform/worker" in gateway
    assert "CAP_NET_BIND_SERVICE" not in gateway
    web = core.service_text("sha256:" + "a" * 64, role="web", hostname="fixture", gateway=True)
    assert "install -d -o 10102 -g 10102 -m 0750 /run/polysia-platform" in web
    assert "RuntimeDirectory=" not in web


def test_legacy_backup_registration_preserves_destination_and_requires_fresh_proof(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    original = json.dumps({"secondary_host": "retained.invalid", "upload_key": "retained"})
    (tmp_path / "backup.json").write_text(original)
    assert admin.retained_backup() == {
        "mode": "sftp",
        "protection": "RETAINED_REVERIFY_REQUIRED",
    }
    assert (tmp_path / "backup.json").read_text() == original
    assert not (tmp_path / "backup-job.json").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Linux host ownership contract")
def test_rollback_restores_content_permissions_and_fences_without_touching_financial_data(
    tmp_path,
    monkeypatch,
):
    config, services, install, state = [
        tmp_path / name for name in ("config", "units", "install", "state")
    ]
    for root in (config, services, install, state):
        root.mkdir()
    monkeypatch.setattr(core, "CONFIG_ROOT", config)
    monkeypatch.setattr(core, "SERVICE_ROOT", services)
    monkeypatch.setattr(core, "INSTALL_ROOT", install)
    monkeypatch.setattr(core, "STATE_ROOT", state)
    monkeypatch.setattr(core, "activation_preflight", lambda commit: None)
    monkeypatch.setattr(core, "run", lambda *args: "")
    monkeypatch.setattr(admin.subprocess, "run", lambda *args, **kwargs: None)
    (config / "worker.json").write_text(json.dumps({"release_commit": "a" * 40}))
    (config / "web.json").write_text('{"roles":{"retained":"reader"}}')
    (config / "web.json").chmod(0o640)
    financial = state / "financial.sqlite3"
    financial.write_bytes(b"retained-financial-evidence")
    receipt = admin.preserve_rollback()
    assert receipt["files"][str(config / "web.json")]["mode"] == 0o640
    (config / "web.json").write_text("new configuration")
    assert admin.rollback()["worker"] == "FENCED"
    assert json.loads((config / "web.json").read_text())["roles"] == {"retained": "reader"}
    assert (config / "web.json").stat().st_mode & 0o777 == 0o640
    assert financial.read_bytes() == b"retained-financial-evidence"
    assert (config / "restart-fenced").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Linux protected root utility")
def test_independent_container_stop_runs_even_when_supervision_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    monkeypatch.setattr(core, "STATE_ROOT", tmp_path)
    (tmp_path / "worker.json").write_text(
        json.dumps(
            {
                "authority": "/state/authority.sqlite3",
                "installation_state": "UNCONFIGURED",
                "acquisition_enabled": False,
            }
        )
    )
    calls = []

    def run(command, **kwargs):
        assert (tmp_path / "restart-fenced").exists()
        calls.append(command)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(command, 40)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(admin.subprocess, "run", run)
    result = admin.protected_stop()
    assert calls[-1] == ["docker", "stop", "-t", "5", "polysia-platform-worker"]
    assert result["durable_authority_stop"] == "NO_AUTHORITY_CONFIGURED"
    assert result["status"] == "OS_WORKER_FENCED"


@pytest.mark.skipif(sys.platform == "win32", reason="Linux administrative entry")
def test_stage_records_refused_activation_without_changing_active_roots(
    tmp_path,
    monkeypatch,
    capsys,
):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    config = tmp_path / "active-config"
    monkeypatch.setattr(core, "CONFIG_ROOT", config)
    monkeypatch.setattr(admin, "load_core", lambda args: core)
    monkeypatch.setattr(admin.os, "geteuid", lambda: 0)
    monkeypatch.setattr(admin, "preflight", lambda value: None)
    monkeypatch.setattr(
        core,
        "verify_artifact",
        lambda directory, commit: {
            "commit": commit,
            "archive_sha256": "c" * 64,
            "image_id": "sha256:" + "d" * 64,
        },
    )
    monkeypatch.setattr(core, "archive_image_ids", lambda *args: ())

    def refuse(commit):
        raise ValueError("open inventory or pending observations require retained executable")

    def never_activate(*args, **kwargs):
        raise AssertionError("staging may not invoke Docker, services or configuration activation")

    monkeypatch.setattr(core, "activation_preflight", refuse)
    monkeypatch.setattr(core, "run", never_activate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "platform_admin.py",
            "stage",
            "--noninteractive",
            "--profile",
            "private",
            "--commit",
            "b" * 40,
            "--artifact-directory",
            str(artifact),
        ],
    )
    admin.main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["activation"]["status"] == "REFUSED"
    assert receipt["image_loaded"] is False
    assert receipt["status"] == "VERIFIED_DOWNLOAD_ONLY"
    assert json.loads((artifact / "staging-receipt.json").read_text()) == receipt
    assert not config.exists()
