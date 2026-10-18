from __future__ import annotations

import json
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


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Linux host ownership contract")
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
