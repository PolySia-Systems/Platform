from __future__ import annotations

import base64
import json
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from polysia.control.service import ControlService
from polysia.deployment.financial_recovery import prepare_recovery
from polysia.deployment.session_supervision import (
    CheckpointPublisher,
    SessionSupervisor,
    SupervisionPolicy,
)
from polysia.domain.financial_session import SessionBlocked
from polysia.security.session_authority import (
    SessionCustody,
    SessionReceiptVerifier,
    receipt_message,
)
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.financial_session import FinancialSessionJournal
from tests.integration.test_financial_session import BINDING, NOW, FakeExecution, authorization


def signed_authority():
    private = Ed25519PrivateKey.generate()
    auth = authorization()
    signature = private.sign(receipt_message(auth, key_id="owner", receipt_id="unique-receipt-001"))
    auth = replace(
        auth,
        owner_receipt=json.dumps(
            {
                "key_id": "owner",
                "receipt_id": "unique-receipt-001",
                "signature": base64.b64encode(signature).decode(),
            }
        ),
    )
    verifier = SessionReceiptVerifier({"owner": private.public_key().public_bytes_raw()})
    return auth, verifier


def test_signature_exact_binding_replay_and_revocation(tmp_path: Path) -> None:
    auth, verifier = signed_authority()
    verified = verifier.verify(auth, BINDING, now=NOW)
    for changed in (
        replace(auth, max_attempts=100),
        replace(auth, granted=False),
        replace(auth, owner_receipt="granted=true"),
    ):
        with pytest.raises(SessionBlocked):
            verifier.verify(changed, BINDING, now=NOW)
    with pytest.raises(SessionBlocked):
        verifier.verify(auth, replace(BINDING, host="other-host"), now=NOW)
    with pytest.raises(SessionBlocked):
        verifier.verify(auth, BINDING, now=NOW + timedelta(hours=2))
    custody = SessionCustody(tmp_path / "control" / "custody.sqlite3")
    custody.initialize()
    custody.claim(verified, auth)
    with pytest.raises(SessionBlocked, match="replayed"):
        custody.claim(verified, auth)
    custody.revoke(key_id="owner")
    assert custody.snapshot(auth.fingerprint)["revoked"] == 1
    with pytest.raises(SessionBlocked, match="revocation"):
        custody.require_current(auth, now=NOW)
    unclaimed = SessionCustody(tmp_path / "unclaimed/custody.sqlite3")
    unclaimed.initialize()
    unclaimed.revoke(receipt_id=verified.receipt_id)
    with pytest.raises(SessionBlocked, match="revoked"):
        unclaimed.claim(verified, auth)


def test_checkpoint_gap_cannot_be_reconstructed_by_worker(tmp_path: Path) -> None:
    auth, verifier = signed_authority()
    current = [NOW]
    custody = SessionCustody(tmp_path / "independent" / "custody.sqlite3")
    custody.initialize()
    custody.claim(verifier.verify(auth, BINDING, now=NOW), auth)
    journal = FinancialSessionJournal(
        tmp_path / "financial" / "session.sqlite3", tmp_path / "witness", auth
    )
    journal.provision(FakeExecution(lambda: NOW).account())
    journal.open()
    outbox = tmp_path / "outbox" / "checkpoint.json"
    prepare_recovery(
        journal.path, journal.witness, tmp_path / "recovery", now=NOW, minimum_free_bytes=1000
    )
    backup = tmp_path / "recovery" / "receipt.json"
    publisher = CheckpointPublisher(auth, custody, outbox, clock=lambda: NOW, timeout_seconds=1)
    supervisor = SessionSupervisor(
        auth,
        custody,
        journal=journal.path,
        witness=journal.witness,
        outbox=outbox,
        backup_receipt=backup,
        policy=SupervisionPolicy(1000, 60, 1),
        clock=lambda: current[0],
        free_bytes=lambda _: 10000,
    )
    publisher.publish(journal.checkpoint(), acknowledge=False)
    retained = supervisor.inspect()
    custody.release_stop(auth.fingerprint, expected=retained)
    custody.require_current(auth, now=NOW, checkpoint=retained)
    journal.mutate("BEFORE_CRASH", {"test": True}, lambda state: state.update(attempts=1))
    committed = journal.checkpoint()
    assert committed.sequence > retained.sequence
    journal.close()
    assert custody.recovery_checkpoint(auth) == retained
    with pytest.raises(SessionBlocked, match="mismatch"):
        journal.open(checkpoint=custody.recovery_checkpoint(auth))
    assert supervisor.inspect() == retained
    current[0] += timedelta(seconds=2)
    with pytest.raises(SessionBlocked, match="supervision_failed"):
        supervisor.inspect()
    assert custody.snapshot(auth.fingerprint)["stopped"] == 1
    # The outbox contains an old proof. The worker cannot promote it to the
    # independent control's current recovery receipt.
    assert json.loads(outbox.read_text())["checkpoint"] == asdict(retained)


def test_post_commit_publication_failure_retains_money_and_fences_writer(tmp_path: Path) -> None:
    auth, _ = signed_authority()
    journal = FinancialSessionJournal(
        tmp_path / "financial" / "session.sqlite3", tmp_path / "witness", auth
    )
    journal.provision(FakeExecution(lambda: NOW).account())
    journal.open()

    def lost_publication(_checkpoint):
        raise OSError("fixture crash after durable commit")

    journal.after_commit = lost_publication
    with pytest.raises(OSError):
        journal.mutate("CLAIM", {}, lambda state: state.update(attempts=1))
    assert journal.read()["attempts"] == 1
    with pytest.raises(SessionBlocked, match="cold_recovery"):
        journal.mutate("TRY_AGAIN", {}, lambda state: state.update(attempts=0))
    journal.close()


def test_scoped_STOP_is_applied_by_independent_supervisor_and_stays_latched(tmp_path: Path) -> None:
    auth, verifier = signed_authority()
    custody = SessionCustody(tmp_path / "custody/control.sqlite3")
    custody.initialize()
    custody.claim(verifier.verify(auth, BINDING, now=NOW), auth)
    journal = FinancialSessionJournal(
        tmp_path / "financial/session.sqlite3", tmp_path / "witness", auth
    )
    journal.provision(FakeExecution(lambda: NOW).account())
    journal.open()
    try:
        prepare_recovery(
            journal.path, journal.witness, tmp_path / "recovery", now=NOW, minimum_free_bytes=1000
        )
        publisher = CheckpointPublisher(
            auth, custody, tmp_path / "outbox.json", clock=lambda: NOW, timeout_seconds=1
        )
        publisher.publish(journal.checkpoint(), acknowledge=False)
        commands = ConsoleCommandStore(tmp_path / "commands.sqlite3")
        commands.initialize()
        supervisor = SessionSupervisor(
            auth,
            custody,
            journal=journal.path,
            witness=journal.witness,
            outbox=tmp_path / "outbox.json",
            backup_receipt=tmp_path / "recovery/receipt.json",
            policy=SupervisionPolicy(1000, 60, 1),
            clock=lambda: NOW,
            commands=commands,
        )
        checkpoint = supervisor.inspect()
        custody.release_stop(auth.fingerprint, expected=checkpoint)
        target = auth.run_id + ":stop"
        preview = ControlService.preview_scoped(
            commands,
            operation="session.stop",
            target=target,
            actor="operator",
            role="operator",
            allowed_targets=frozenset({target}),
            now=NOW,
        )
        commands.submit_scoped(
            subject="operator",
            role="operator",
            preview_id=preview.fingerprint,
            expected_revision=0,
            idempotency_key="independent-stop-0001",
            now=NOW,
            allowed_targets=frozenset({target}),
        )
        supervisor.inspect()
        assert commands.scoped_status()[0]["status"] == "APPLIED"
        supervisor.inspect()  # healthy ACK cannot clear explicit STOP
        assert custody.snapshot(auth.fingerprint)["stopped"] == 1
        with pytest.raises(SessionBlocked, match="stop_release"):
            custody.release_stop(auth.fingerprint, expected=checkpoint)
        with pytest.raises(SessionBlocked, match="stop"):
            custody.require_current(auth, now=NOW)
    finally:
        journal.close()


def test_idle_supervision_refreshes_health_without_unbounded_duplicate_ack_history(tmp_path):
    import sqlite3

    from polysia.storage.financial_session import SessionRecoveryCheckpoint

    auth, verifier = signed_authority()
    custody = SessionCustody(tmp_path / "custody.sqlite3")
    custody.initialize()
    custody.claim(verifier.verify(auth, BINDING, now=NOW), auth)
    checkpoint = SessionRecoveryCheckpoint(auth.fingerprint, 1, "fixture-exact-checkpoint")
    for seconds in range(5):
        custody.acknowledge(
            checkpoint,
            now=NOW + timedelta(seconds=seconds),
            worker_at=NOW,
            reason="supervisor_checks_passed",
            ready=True,
        )
    with sqlite3.connect(custody.path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM custody_events WHERE kind='CHECKPOINT_ACK'"
            ).fetchone()[0]
            == 1
        )
    assert (
        custody.snapshot(auth.fingerprint)["supervised_at"]
        == (NOW + timedelta(seconds=4)).isoformat()
    )
    assert custody.snapshot(auth.fingerprint)["stopped"] == 1
