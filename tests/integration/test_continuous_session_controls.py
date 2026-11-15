"""Deterministic independent controls and offsite failure cases; no external account."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import timedelta
from pathlib import Path

import pytest

from polysia.deployment.continuous_session_controls import (
    ContinuousSessionSupervisor,
)
from polysia.deployment.financial_recovery import prepare_recovery
from polysia.deployment.session_supervision import (
    CheckpointPublisher,
    SessionSupervisor,
    SupervisionPolicy,
)
from polysia.domain.financial_session import SessionBlocked
from polysia.security.session_authority import SessionCustody
from polysia.storage.financial_session import FinancialSessionJournal
from scripts import op1_backup_transport as transport
from scripts import op1_session_host as host
from scripts.op1_bounded_read import credential_json
from tests.integration.test_financial_session import BINDING, NOW, FakeExecution
from tests.integration.test_session_custody import signed_authority


@pytest.fixture
def controls(tmp_path):
    authority, verifier = signed_authority()
    at = [NOW]
    custody = SessionCustody(tmp_path / "control/custody.sqlite3")
    custody.initialize()
    custody.claim(verifier.verify(authority, BINDING, now=NOW), authority)
    journal = FinancialSessionJournal(
        tmp_path / "financial/session.sqlite3", tmp_path / "witness", authority
    )
    journal.provision(FakeExecution(lambda: NOW).account())
    journal.open()
    record = prepare_recovery(
        journal.path, journal.witness, tmp_path / "backup", now=NOW, minimum_free_bytes=1000
    )
    proof = {
        key: record[key]
        for key in (
            "authority_fingerprint",
            "checkpoint",
            "artifact_sha256",
            "authority_reissued",
            "custody_included",
        )
    }
    proof.update(
        version="session-offsite-backup/v1",
        restore_verified=True,
        financial_writer="FORBIDDEN",
        observed_at=NOW.isoformat(),
    )
    record["offsite"] = proof
    backup = tmp_path / "backup/receipt.json"
    backup.write_text(json.dumps(record))
    outbox = tmp_path / "outbox.json"
    publisher = CheckpointPublisher(
        authority, custody, outbox, clock=lambda: at[0], timeout_seconds=1
    )
    supervisor = SessionSupervisor(
        authority,
        custody,
        journal=journal.path,
        witness=journal.witness,
        outbox=outbox,
        backup_receipt=backup,
        policy=SupervisionPolicy(1000, 60, 1),
        clock=lambda: at[0],
    )

    def wait(seconds):
        at[0] += timedelta(seconds=seconds)

    yield authority, custody, journal, publisher, supervisor, at, wait, record
    journal.close()


def test_armed_control_keeps_STOP_and_never_fakes_worker_health(controls):
    a, c, j, p, s, at, wait, _ = controls
    original = c.snapshot(a.fingerprint)
    result = ContinuousSessionSupervisor(a, c, s, clock=lambda: at[0], wait=wait).run(
        maximum_ticks=3
    )
    assert result["checks"] == 0
    assert not p.outbox.exists()
    current = c.snapshot(a.fingerprint)
    assert current["stopped"] == 1
    assert current["supervised_at"] == original["supervised_at"] is None
    assert j.read()["attempts"] == 0


def test_real_worker_publication_and_offsite_ACK_allow_only_bounded_start(controls):
    a, c, j, p, s, at, wait, _ = controls
    p.publish(j.checkpoint(), acknowledge=False)
    results = []

    def advancing(seconds):
        results.append(c.snapshot(a.fingerprint)["stopped"])
        wait(seconds)

    result = ContinuousSessionSupervisor(
        a, c, s, clock=lambda: at[0], wait=advancing, release_stop=True
    ).run(maximum_ticks=3)
    assert result["checks"] == 3 and results == [0, 0, 0]
    assert c.snapshot(a.fingerprint)["stopped"] == 1
    assert j.read()["attempts"] == 0


@pytest.mark.parametrize("change", ["wrong_checkpoint", "stale", "future", "custody", "missing"])
def test_bad_offsite_proof_cannot_release_STOP(controls, change):
    a, c, j, p, s, at, wait, record = controls
    p.publish(j.checkpoint(), acknowledge=False)
    if change == "wrong_checkpoint":
        record["offsite"]["checkpoint"] = {}
    if change == "stale":
        record["offsite"]["observed_at"] = (NOW - timedelta(seconds=61)).isoformat()
    if change == "future":
        record["offsite"]["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if change == "custody":
        record["offsite"]["custody_included"] = True
    if change == "missing":
        del record["offsite"]
    s.backup_receipt.write_text(json.dumps(record))
    with pytest.raises(SessionBlocked):
        ContinuousSessionSupervisor(a, c, s, clock=lambda: at[0], wait=wait, release_stop=True).run(
            maximum_ticks=1
        )
    assert c.snapshot(a.fingerprint)["stopped"] == 1
    assert j.read()["attempts"] == 0


def test_explicit_stop_and_elapsed_authority_are_never_cleared(controls):
    a, c, j, p, s, at, wait, _ = controls
    p.publish(j.checkpoint(), acknowledge=False)
    c.stop(a.fingerprint, reason="explicit_operator_STOP")
    result = ContinuousSessionSupervisor(
        a, c, s, clock=lambda: at[0], wait=wait, release_stop=True
    ).run(maximum_ticks=1)
    assert result["status"] == "LATCHED_STOP"
    at[0] = a.protective_until
    result = ContinuousSessionSupervisor(
        a, c, s, clock=lambda: at[0], wait=wait, release_stop=True
    ).run(maximum_ticks=1)
    assert result["status"] == "DEADLINE_STOP"
    assert c.snapshot(a.fingerprint)["stopped"] == 1


def test_old_worker_heartbeat_is_not_startup_admission(controls):
    a, c, j, p, s, at, wait, _ = controls
    p.publish(j.checkpoint(), acknowledge=False)
    at[0] += timedelta(seconds=1)
    with pytest.raises(SessionBlocked, match="startup_not_observed"):
        ContinuousSessionSupervisor(
            a, c, s, clock=lambda: at[0], wait=wait, release_stop=True, startup_timeout_seconds=1
        ).run(maximum_ticks=30)
    assert c.snapshot(a.fingerprint)["stopped"] == 1


def test_cached_ACK_cannot_release_commissioning_STOP(controls, monkeypatch):
    a, c, j, p, s, at, wait, _ = controls
    p.publish(j.checkpoint(), acknowledge=False)
    s.inspect()
    at[0] += timedelta(seconds=1)
    p.publish(j.checkpoint(), acknowledge=False)
    monkeypatch.setattr(s, "inspect", lambda: j.checkpoint())
    with pytest.raises(SessionBlocked, match="fresh_startup_ACK"):
        ContinuousSessionSupervisor(
            a, c, s, clock=lambda: at[0], wait=wait, release_stop=True, startup_timeout_seconds=1
        ).run(maximum_ticks=30)
    assert c.snapshot(a.fingerprint)["stopped"] == 1


@pytest.mark.parametrize("fault", ["worker_lost", "clock_regression", "artifact_corrupt"])
def test_runtime_fault_latches_STOP_without_financial_mutation(controls, fault):
    a, c, j, p, s, at, wait, record = controls
    p.publish(j.checkpoint(), acknowledge=False)

    def fail_after_admission(seconds):
        assert c.snapshot(a.fingerprint)["stopped"] == 0
        if fault == "worker_lost":
            at[0] += timedelta(seconds=a.supervision_timeout_seconds + 1)
        elif fault == "clock_regression":
            at[0] -= timedelta(seconds=1)
        else:
            Path(record["artifacts"][0]).write_bytes(b"corrupt")
        wait(seconds)

    with pytest.raises(SessionBlocked):
        ContinuousSessionSupervisor(
            a, c, s, clock=lambda: at[0], wait=fail_after_admission, release_stop=True
        ).run(maximum_ticks=2)
    assert c.snapshot(a.fingerprint)["stopped"] == 1
    assert j.read()["attempts"] == 0


def test_transient_units_have_deadline_no_restart_and_exact_cleanup(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    calls = []
    p = {
        "run_id": "fixture-only",
        "until": (datetime.now(UTC) + timedelta(seconds=10)).isoformat(),
        "host_script": "/etc/polysia-op1/op1_session_host.py",
    }
    monkeypatch.setattr(host.subprocess, "run", lambda command, **kw: calls.append(command))
    host.start_unit(p, tmp_path / "profile.json", "control", 999)
    command = calls[0]
    ttl = next(x for x in command if x.startswith("--property=RuntimeMaxSec="))
    assert 0 < int(ttl.split("=")[-1]) <= 10
    assert "--property=Restart=no" in command
    cleanup = next(x for x in command if x.startswith("--property=ExecStopPost="))
    assert "cleanup --profile" in cleanup and cleanup.endswith("--role control")
    assert command[-1] == "control"


def test_cleanup_targets_only_owned_tasks(monkeypatch):
    calls = []
    p = {
        "run_id": "fixture",
        "task_prefix": "polysia-op1-long-fixture-backup",
        "namespace": "polysia-op1",
    }
    own = host.role_id(p, "worker")
    monkeypatch.setattr(
        host.subprocess,
        "check_output",
        lambda *a, **kw: "TASK PID STATUS\n" + own + " 1 RUNNING\nunrelated 2 RUNNING\n",
    )
    monkeypatch.setattr(host.subprocess, "run", lambda command, **kw: calls.append(command))
    host.cleanup_role(p, "worker")
    assert len(calls) == 1 and calls[0][-1] == own


def test_ambiguous_upload_uses_query_and_never_resends(controls, tmp_path, monkeypatch):
    *_, record = controls
    cipher = tmp_path / "generation.age"
    cipher.write_bytes(b"encrypted-fixture")
    calls = []

    def exchange(profile, header, data=b""):
        calls.append(header["operation"])
        if header["operation"] == "UPLOAD":
            raise TimeoutError()
        return {**record["offsite"], "cipher_sha256": header["cipher_sha256"]}

    monkeypatch.setattr(transport, "ssh_exchange", exchange)
    assert transport.transmit(
        {"budget_path": str(tmp_path / "budget.jsonl")}, record, cipher, tmp_path / "generation01"
    )["restore_verified"]
    assert calls == ["UPLOAD", "QUERY"]


@pytest.mark.parametrize("name", ["../escape", "/absolute", "generation/../escape"])
def test_receiver_refuses_unsafe_generations_and_archives(tmp_path, name):
    with pytest.raises(ValueError):
        transport.generation_name(name)
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as stream:
        item = tarfile.TarInfo(name)
        item.size = 1
        stream.addfile(item, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        transport.extract_generation(archive, tmp_path / "output")


def test_budget_is_durable_and_ambiguous_transfer_cannot_be_repeated(tmp_path):
    p = {"budget_path": str(tmp_path / "transport.jsonl"), "maximum_transport_bytes": 20000}
    transport.transfer_budget(p, "generation1", charge=17000)
    with pytest.raises(ValueError, match="unconfirmed"):
        transport.transfer_budget(p, "generation2", charge=1000)
    transport.transfer_budget(p, "generation1")
    with pytest.raises(ValueError, match="exhausted"):
        transport.transfer_budget(p, "generation2", charge=4000)
    rows = [json.loads(line) for line in Path(p["budget_path"]).read_text().splitlines()]
    assert rows[0]["bytes"] == 17000 and [x["kind"] for x in rows] == ["RESERVED", "CONFIRMED"]


def test_authentication_credentials_round_trip_supported_SDK_alias():
    from polymarket import ApiKeyCreds

    creds = ApiKeyCreds(apiKey="fixture-key", passphrase="fixture-pass", secret="fixture-secret")
    assert ApiKeyCreds.model_validate_json(credential_json(creds)) == creds


def test_owner_execution_default_is_disabled_before_any_host_access(tmp_path):
    with pytest.raises(ValueError, match="explicit_manual_owner"):
        host.start({}, tmp_path / "missing", execute_owner_test=False)


def test_role_container_mounts_protect_independent_custody():
    p = {
        "base": "/var/lib/polysia-op1",
        "packet": "/var/lib/polysia-op1/packet",
        "namespace": "polysia-op1",
        "trust": "/etc/polysia-op1/trust/public.json",
        "worker_directory": "/var/lib/polysia-op1/worker/run",
        "supervisor_directory": "/var/lib/polysia-op1/supervisor/run",
        "commands_directory": "/var/lib/polysia-op1/commands/run",
        "publication": "/var/lib/polysia-op1/supervisor/run/backup",
        "worker_script": "/etc/polysia-op1/op1_owner_worker.py",
        "run_id": "fixture-run",
        "image": "fixture-image",
    }
    worker = host.container_command(p, "worker")
    control = host.container_command(p, "control")
    assert worker[worker.index("--user") + 1] == "999:981"
    assert control[control.index("--user") + 1] == "995:981"
    assert not any("supervisor/run" in x and "rbind:rw" in x for x in worker)
    assert not any("worker/run" in x and "rbind:rw" in x for x in control)
    assert "--net-host" in worker and "--net-host" not in control
    assert "--execute-owner-test" in worker and "--release-stop" in control
