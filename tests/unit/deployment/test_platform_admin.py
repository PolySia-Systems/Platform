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
