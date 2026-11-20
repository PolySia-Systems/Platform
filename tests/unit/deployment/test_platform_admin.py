from __future__ import annotations

import json
import sqlite3
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


def test_automatic_update_defers_before_downloading_when_activation_is_refused(
    tmp_path, monkeypatch,
):
    (tmp_path / "publication").mkdir()
    (tmp_path / "installation.json").write_text(json.dumps({
        **configuration(), "release_tag": "v0.4.1",
    }))
    (tmp_path / "update-policy.json").write_text('{"auto":true}')
    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    monkeypatch.setattr(core, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(admin.os, "chown", lambda *args: None, raising=False)
    monkeypatch.setattr(admin, "atomic", lambda path, value, **kw: path.write_text(
        json.dumps(value)
    ))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://github.com/PolySia-Systems/Platform/releases/tag/v0.4.2"

        def read(self, limit):
            return json.dumps({"commit": "b" * 40}).encode()

    monkeypatch.setattr(admin, "urlopen", lambda *args, **kwargs: Response())

    def refuse(commit):
        assert commit == "b" * 40
        raise ValueError("pinned active session")

    def unexpected(*args):
        pytest.fail("a blocked upgrade attempted to fetch or apply the candidate")

    monkeypatch.setattr(core, "activation_preflight", refuse)
    monkeypatch.setattr(core, "run", unexpected)
    monkeypatch.setattr(admin, "download", unexpected)
    receipt = admin.release_update("auto-update", None)
    assert receipt["state"] == "UPDATE_REQUIRES_REVIEW"
    assert receipt["installed"] == "v0.4.1"
    assert receipt["available"] == "v0.4.2"


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


def test_managed_leaderboard_has_independent_data_only_container():
    image = "sha256:" + "a" * 64
    collector = core.container_command(image, role="leaderboard", hostname="")
    console = core.container_command(image, role="web", hostname="", leaderboard=True)
    state = core.STATE_ROOT.as_posix() + "/leaderboard"
    assert f"{state}:/leaderboard:rw" in collector
    assert f"{state}:/leaderboard:ro" in console
    assert collector[-5:] == [
        image, "leaderboard", "refresh", "--database", core.LEADERBOARD_DATABASE,
    ]
    assert "TRADING_MODE=DATA_ONLY" in collector and "LIVE_TRADING_ENABLED=false" in collector
    assert not any("/config" in value or "/control" in value for value in collector)


def test_adoption_refuses_unrecognized_overrides_without_changing_them(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    monkeypatch.setattr(core, "CONFIG_ROOT", root)
    monkeypatch.setattr(core, "STATE_ROOT", root)
    monkeypatch.setattr(core, "SERVICE_ROOT", root)
    image = "sha256:" + "a" * 64
    base = core.service_text(image, role="web", hostname="test")
    (root / "polysia-platform-web.service").write_text(base)
    path = admin.leaderboard_override()
    path.parent.mkdir()
    start = next(line for line in base.splitlines() if line.startswith("ExecStart="))
    mount = f"--volume {(root / 'leaderboard').as_posix()}:/leaderboard:ro "
    expected = start.replace("/usr/bin/docker run ", "/usr/bin/docker run " + mount, 1)
    path.write_text("[Service]\nExecStart=\n" + expected + "\n")
    admin.leaderboard_preflight()
    custom = path.read_text() + "Environment=CUSTOM=1\n"
    path.write_text(custom)
    with pytest.raises(ValueError, match="override differs"):
        admin.leaderboard_preflight()
    assert path.read_text() == custom


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


def test_existing_cloudflare_hostname_change_is_refused_without_a_false_setup_receipt(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    original = '{"origin":"https://retained.example.com"}'
    (tmp_path / "web.json").write_text(original)
    value = {**configuration(), "profile": "cloudflare", "hostname": "new.example.com"}
    with pytest.raises(ValueError, match="existing Cloudflare origin is preserved"):
        admin.configure(value, image="sha256:" + "a" * 64, allow_change=True)
    assert (tmp_path / "web.json").read_text() == original
    assert not (tmp_path / "installation.json").exists()


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
    assert receipt["starts_acquisition"] is False
    assert receipt["status"] == "VERIFIED_DOWNLOAD_ONLY"
    assert json.loads((artifact / "staging-receipt.json").read_text()) == receipt
    assert not config.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Linux protected administrative utility")
def test_stop_never_delegates_damaged_authority_to_a_legacy_initializer(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    monkeypatch.setattr(core, "STATE_ROOT", tmp_path)
    (tmp_path / "worker").mkdir()
    authority = tmp_path / "worker/authority.sqlite3"
    authority.write_bytes(b"")
    (tmp_path / "worker.json").write_text(json.dumps({"authority": "/state/authority.sqlite3"}))
    monkeypatch.setattr(
        admin.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )

    def legacy_must_not_load(commit):
        raise AssertionError("damaged authority cannot reach legacy initialization")

    monkeypatch.setattr(admin, "load_backup", legacy_must_not_load)
    assert admin.protected_stop()["reason"] == "retained_authority_invalid_do_not_reinitialize"
    assert authority.stat().st_size == 0
    assert (tmp_path / "restart-fenced").exists()
    with sqlite3.connect(authority.as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []

@pytest.mark.parametrize("configured", [False, True])
def test_status_default_output_and_explicit_human_summary(
    configured, tmp_path, monkeypatch, capsys,
):
    config, receipt = configuration(), {
        "schema": "platform-maintenance/v1",
        "commit": "a" * 40,
        "phase": "ACTIVATED",
        "checked_at": "2026-11-20T18:20:00+03:30",
        "backup": {"protection": "UNPROTECTED", "credential": "secret-sentinel"},
        "acquisition_enabled": False,
        "next_action": "secret-sentinel",
    }
    monkeypatch.setattr(core, "CONFIG_ROOT", tmp_path)
    monkeypatch.setattr(admin, "load_core", lambda _: core)
    monkeypatch.setattr(admin.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(admin, "leaderboard_status", lambda: {"status": "UNKNOWN"})
    monkeypatch.setenv("COLUMNS", "40")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    installation_file = tmp_path / "installation.json"
    maintenance_file = tmp_path / "maintenance-receipt.json"
    if configured:
        installation_file.write_text(json.dumps(config), encoding="utf-8")
        maintenance_file.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["platform_admin.py", "status"])
    admin.main()
    out, err = capsys.readouterr()
    assert not err
    assert out.splitlines() == [
        json.dumps(config) if configured else "installation.json: UNCONFIGURED",
        json.dumps(receipt) if configured else "maintenance-receipt.json: UNCONFIGURED",
        '{"leaderboard": {"status": "UNKNOWN"}}',
    ]
    monkeypatch.setattr(sys, "argv", ["platform_admin.py", "status", "--human"])
    admin.main()
    out, err = capsys.readouterr()
    assert not err
    assert out.isascii() and max(map(len, out.splitlines())) <= 40
    assert "secret-sentinel" not in out and "\x1b" not in out
    if configured:
        assert "Setup completed at the recorded time." in out
        assert "2026-11-20T14:50:00+00:00" in out
        assert "Recorded backup: UNPROTECTED" in out
        (tmp_path / "restart-fenced").write_text("{}", encoding="utf-8")
        admin.main()
        fenced = capsys.readouterr().out
        assert "Worker restart is fenced." in fenced
        assert "Setup completed" not in fenced
        (tmp_path / "restart-fenced").unlink()
        receipt["commit"] = "b" * 40
        maintenance_file.write_text(json.dumps(receipt), encoding="utf-8")
        admin.main()
        stale = capsys.readouterr().out
        assert "No matching maintenance phase" in stale
        assert "Setup completed" not in stale
    else:
        assert "No matching maintenance phase" in out


def test_health_keeps_publisher_output_and_rejects_human_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(admin.os, "geteuid", lambda: 10101, raising=False)
    monkeypatch.setattr(admin, "load_core", lambda _: core)
    calls = []

    def publish():
        calls.append(True)
        return {"status": "SYNTHETIC"}

    monkeypatch.setattr(admin, "publish_health", publish)
    monkeypatch.setattr(sys, "argv", ["platform_admin.py", "health"])
    admin.main()
    assert capsys.readouterr() == ('{"status": "SYNTHETIC"}\n', "")
    monkeypatch.setattr(sys, "argv", ["platform_admin.py", "health", "--human"])
    with pytest.raises(SystemExit, match="2"):
        admin.main()
    assert calls == [True]
    assert "--human is available only for status" in capsys.readouterr().err


@pytest.mark.parametrize("outcome", ["success", "access-required", "fenced", "interrupted"])
@pytest.mark.parametrize("tty", [True, False])
def test_guided_install_reports_actual_phase(outcome, tty, tmp_path, monkeypatch, capsys):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(admin.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(core, "CONFIG_ROOT", config)
    monkeypatch.setattr(admin, "load_core", lambda _: core)
    if tty:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            monkeypatch.setattr(stream, "isatty", lambda: True)
    else:
        # Input may still be a TTY when output is redirected.
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(admin, "preflight", lambda _: None)
    monkeypatch.setattr(core, "activation_preflight", lambda _: None)
    monkeypatch.setattr(admin, "leaderboard_preflight", lambda: None)
    monkeypatch.setattr(admin, "preserve_rollback", lambda: None)
    monkeypatch.setattr(core, "bootstrap", lambda *a, **kw: {"image_id": "synthetic"})
    monkeypatch.setattr(
        admin, "atomic", lambda path, value: path.write_text(json.dumps(value), encoding="utf-8"),
    )
    if outcome == "access-required":
        monkeypatch.setattr("builtins.input", lambda: "")
        profile = ["--profile", "cloudflare", "--hostname", "console.example.test"]
    else:
        profile = ["--profile", "private"]
        monkeypatch.setattr(admin, "configure", lambda *a, **kw: {
            "status": "ACCESS_CONFIGURED", "credentials_file": "secret-sentinel",
        })

    def activate(*a, **kw):
        if outcome == "fenced":
            raise ValueError("synthetic activation failure")
        if outcome == "interrupted":
            raise KeyboardInterrupt

    monkeypatch.setattr(admin, "activate", activate)
    monkeypatch.setattr(admin.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(admin, "verify_access", lambda _: None)
    monkeypatch.setattr(admin, "start_leaderboard", lambda *a: None)
    monkeypatch.setattr(core, "run", lambda *a: None)
    monkeypatch.setattr(admin, "promote_retained_backup", lambda *a, **kw: None)
    monkeypatch.setattr(admin, "install_health", lambda _: None)
    monkeypatch.setattr(admin, "install_admin_entry", lambda: None)
    monkeypatch.setattr(admin, "leaderboard_status", lambda: {"status": "UNKNOWN"})
    monkeypatch.setattr(
        sys, "argv", [
            "platform_admin.py", "install", *profile, "--tag", "v1.2.3",
            "--commit", "a" * 40, "--artifact-directory", str(tmp_path),
        ],
    )
    if not tty and outcome == "access-required":
        sys.argv.append("--noninteractive")
    if outcome == "fenced":
        with pytest.raises(ValueError, match="worker restart is fenced"):
            admin.main()
    elif outcome == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            admin.main()
    else:
        admin.main()

    out, err = capsys.readouterr()
    receipt = json.loads((config / "maintenance-receipt.json").read_text())
    expected_phase, expected_status, expected_copy = {
        "success": ("ACTIVATED", "SETUP_COMPLETE", "Setup completed"),
        "access-required": (
            "CONFIGURATION_STAGED", "ACCESS_CONFIGURATION_REQUIRED",
            "Access configuration required",
        ),
        "fenced": ("ACTIVATION_INCOMPLETE", None, "Worker restart is fenced"),
        "interrupted": ("CONFIGURATION_STAGED", None, "Release artifact verified"),
    }[outcome]
    if outcome == "access-required":
        assert not (config / "installation.json").exists()
        assert "maintenance-receipt.json" in json.loads(out)["access"]["next_action"]
        if tty:
            assert "Access profile: cloudflare" in err
    assert receipt["phase"] == expected_phase
    assert (json.loads(out)["status"] if out else None) == expected_status
    if tty:
        assert "PolySia setup" in err and expected_copy in err
        assert "secret-sentinel" not in err
        assert ("Setup completed" in err) == (outcome == "success")
    else:
        assert not err
    if outcome == "access-required" and not tty:
        monkeypatch.setattr(admin.os, "chown", lambda *_: None, raising=False)
        monkeypatch.setattr(
            admin, "atomic",
            lambda path, value, **_: path.write_text(json.dumps(value), encoding="utf-8"),
        )
        sys.argv.extend(["--access-issuer", "https://fixture.cloudflareaccess.com",
                         "--access-audience", "b" * 64, "--access-owner", "owner@example.test"])
        admin.main()
        resumed = json.loads(capsys.readouterr().out)
        assert resumed["status"] == "SETUP_COMPLETE"
        assert resumed["access"]["route"] == "EXTERNAL_OWNER_COMMISSIONING_REQUIRED"
        assert resumed["acquisition_enabled"] is False
        assert json.loads((config / "installation.json").read_text())["commit"] == "a" * 40
