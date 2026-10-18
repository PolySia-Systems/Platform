from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from polysia.cli_commands import platform_worker as worker
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.console_commands import ConsoleCommandStore
from tests.unit.storage.test_acquisition_authority import NOW, policy


@pytest.fixture
def installed_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clock = SimpleNamespace(value=NOW)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.value

    monkeypatch.setattr(worker, "datetime", Clock)
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path.as_posix() == "/opt/polysia/BUILD_COMMIT":
            return "a" * 40
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    manifest = tmp_path / "policy.json"
    manifest.write_text(
        json.dumps(replace(policy(), host=socket.gethostname(), cadence_seconds=300).to_dict())
    )
    value = {
        "database": str(tmp_path / "financial.sqlite3"),
        "release_commit": "a" * 40,
        "manifest": str(manifest),
        "authority": str(tmp_path / "authority.sqlite3"),
        "commands": str(tmp_path / "commands.sqlite3"),
        "status": str(tmp_path / "status.json"),
        "cohort": str(tmp_path / "cohort.json"),
        "acquisition_enabled": False,
        "admission": {"mode": "CONTINUOUS"},
    }
    config = tmp_path / "worker.json"
    config.write_text(json.dumps(value))
    authority = AcquisitionAuthority(Path(value["authority"]), worker.load_policy(manifest))
    authority.initialize()
    commands = ConsoleCommandStore(Path(value["commands"]))
    commands.initialize()
    return config, value, clock, authority, commands


def test_stop_bypasses_long_deferred_queue_and_fences_old_resume(installed_worker):
    config, value, clock, authority, commands = installed_worker
    for revision in range(65):
        commands.submit(
            subject="owner",
            action="drain",
            expected_revision=revision,
            idempotency_key=f"queued-drain-{revision:016d}",
        )
    commands.submit(
        subject="owner",
        action="resume",
        expected_revision=65,
        idempotency_key="stale-resume-before-stop",
    )
    commands.submit(
        subject="owner",
        action="stop",
        expected_revision=66,
        idempotency_key="urgent-stop-after-backlog",
    )
    first = worker.worker_tick(config)
    assert first["status"] == "STOPPED"
    assert authority.status()["stopped"] is True
    for _ in range(3):
        worker.worker_tick(config)
    assert commands.pending() == []
    assert commands.status()["revision"] == 67
    assert authority.status()["requests_charged"] == 0
    assert not Path(value["database"]).exists()


@pytest.mark.parametrize("fault", ["missing", "empty", "missing_authority_row"])
def test_worker_never_reinitializes_lost_or_incomplete_authority(installed_worker, fault):
    import sqlite3

    from polysia.storage.acquisition_authority import AcquisitionBlockedError

    config, value, _, _, _ = installed_worker
    root = config.parent
    path = Path(value["authority"])
    if fault == "missing":
        path.rename(root / "retained-authority.sqlite3")
    elif fault == "empty":
        path.write_bytes(b"")
    else:
        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM authority")
    with pytest.raises(AcquisitionBlockedError, match="do_not_reinitialize"):
        worker.worker_tick(config)
    if fault == "missing":
        assert not path.exists()
    elif fault == "empty":
        assert path.stat().st_size == 0
    else:
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM authority").fetchone() == (0,)


def test_protected_stop_does_not_recreate_missing_authority(installed_worker):
    config, value, _, authority, _ = installed_worker
    retained = authority.status()
    path = Path(value["authority"])
    saved = path.with_name("retained-authority.sqlite3")
    path.rename(saved)
    with pytest.raises(ValueError, match="retained authority is missing"):
        worker.platform_stop(config)
    assert not path.exists()
    assert (
        AcquisitionAuthority(saved, worker.load_policy(Path(value["manifest"]))).status()
        == retained
    )


def test_protected_stop_persists_before_command_store_failure(installed_worker, monkeypatch):
    import sqlite3

    config, _, _, authority, _ = installed_worker
    charged = authority.status()

    def unavailable(store):
        raise sqlite3.OperationalError("fixture command store is read-only")

    monkeypatch.setattr(ConsoleCommandStore, "initialize", unavailable)
    with pytest.raises(sqlite3.OperationalError, match="read-only"):
        worker.platform_stop(config)
    assert authority.status() == {**charged, "stopped": True}


def test_due_checkpoint_survives_restart_and_crash_without_delaying_stop(
    installed_worker,
    monkeypatch: pytest.MonkeyPatch,
):
    config, value, clock, authority, commands = installed_worker
    value["acquisition_enabled"] = True
    config.write_text(json.dumps(value))
    # Simulate process failure after durable slot reservation but before cohort
    # loading. The ordinary CLI error path must preserve that timing checkpoint.
    import typer

    with pytest.raises(typer.Exit):
        worker.platform_tick(config)
    receipt = json.loads(Path(value["status"]).read_text())
    assert receipt["next_due_at"] == (NOW + timedelta(seconds=300)).isoformat()
    result = worker.worker_tick(config)
    assert result["status"] == "WAITING_CADENCE"
    assert result["last_poll_started_at"] == NOW.isoformat()
    clock.value = NOW + timedelta(seconds=299)
    assert worker.worker_tick(config)["status"] == "WAITING_CADENCE"
    commands.submit(
        subject="owner",
        action="stop",
        expected_revision=0,
        idempotency_key="stop-during-cadence-wait",
    )
    assert worker.worker_tick(config)["status"] == "STOPPED"
    assert authority.status()["requests_charged"] == 0


def test_clock_regression_blocks_before_source_access(installed_worker):
    config, value, clock, authority, commands = installed_worker
    value["acquisition_enabled"] = True
    config.write_text(json.dumps(value))
    Path(value["status"]).write_text(
        json.dumps(
            {
                "last_poll_started_at": (NOW + timedelta(seconds=10)).isoformat(),
                "next_due_at": (NOW + timedelta(seconds=310)).isoformat(),
            }
        )
    )
    result = worker.worker_tick(config)
    assert result["reason"] == "worker_clock_regressed"
    assert authority.status()["stopped"] is True
    assert authority.status()["requests_charged"] == 0


def test_retry_count_survives_cadence_wait_and_stops_after_three_attempts(
    installed_worker,
    monkeypatch: pytest.MonkeyPatch,
):
    from polysia.storage.acquisition_authority import AcquisitionBlockedError

    config, value, clock, authority, _ = installed_worker
    value["acquisition_enabled"] = True
    config.write_text(json.dumps(value))
    Path(value["cohort"]).write_text(json.dumps({"discovery": {}}))
    attempts = []

    async def unavailable(*args, **kwargs):
        attempts.append(clock.value)
        raise AcquisitionBlockedError("provider_http_503")

    monkeypatch.setattr(worker, "native_lifecycle_poll", unavailable)
    assert worker.worker_tick(config)["transient_failures"] == 1
    clock.value = NOW + timedelta(seconds=60)
    assert worker.worker_tick(config)["status"] == "WAITING_RETRY"
    clock.value = NOW + timedelta(seconds=180)
    assert worker.worker_tick(config)["status"] == "WAITING_CADENCE"
    clock.value = NOW + timedelta(seconds=300)
    assert worker.worker_tick(config)["transient_failures"] == 2
    clock.value = NOW + timedelta(seconds=600)
    assert worker.worker_tick(config)["status"] == "BLOCKED"
    assert attempts == [NOW, NOW + timedelta(seconds=300), NOW + timedelta(seconds=600)]
    assert authority.status()["stopped"] is True


def test_overlapping_tick_does_not_replace_owner_checkpoint(installed_worker, capsys):
    from polysia.cli_support.wallet_intelligence_workflow import workflow_lock

    config, value, _, authority, _ = installed_worker
    status = Path(value["status"])
    checkpoint = '{"status":"POLL_IN_PROGRESS","next_due_at":"retained-owner-slot"}'
    status.write_text(checkpoint)
    with workflow_lock(Path(value["database"]).with_suffix(".worker.lock")):
        worker.platform_tick(config)
    assert json.loads(capsys.readouterr().out)["status"] == "WAITING_WORKER"
    assert status.read_text() == checkpoint
    assert authority.status()["requests_charged"] == 0
