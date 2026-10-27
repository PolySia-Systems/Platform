"""Local real financial/Risk/custody owners under bounded optional-web faults."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from polysia.cli import app as cli
from polysia.deployment.financial_recovery import prepare_recovery
from polysia.deployment.session_supervision import (
    CheckpointPublisher,
    SessionSupervisor,
    SupervisionPolicy,
)
from polysia.domain.financial_session import SessionBlocked
from polysia.monitoring.financial_session import financial_session_view
from polysia.security.session_authority import SessionCustody
from tests.integration.test_financial_session import BINDING, NOW, Harness, opportunity
from tests.integration.test_session_custody import signed_authority
from tests.unit.monitoring.test_console import application
from tests.unit.monitoring.test_console_h1 import call


@pytest.mark.parametrize(
    "fault",
    [
        "browser_gone",
        "api_failure",
        "malformed_publication",
        "command_store_fault",
        "web_pressure",
        "financial_uncertainty",
    ],
)
def test_optional_web_faults_preserve_independent_owners_and_emergency_stop(
    tmp_path, monkeypatch, fault
):
    authority, verifier = signed_authority()
    financial = Harness(tmp_path / "worker", auth=authority)
    web = application(tmp_path / "public", targets=frozenset({authority.run_id + ":stop"}))
    custody = SessionCustody(tmp_path / "independent/control.sqlite3")
    custody.initialize()
    custody.claim(verifier.verify(authority, BINDING, now=NOW), authority)
    prepare_recovery(
        financial.journal.path,
        financial.journal.witness,
        tmp_path / "recovery",
        now=NOW,
        minimum_free_bytes=1000,
    )
    outbox = tmp_path / "outbox/checkpoint.json"
    supervisor = SessionSupervisor(
        authority,
        custody,
        journal=financial.journal.path,
        witness=financial.journal.witness,
        outbox=outbox,
        backup_receipt=tmp_path / "recovery/receipt.json",
        policy=SupervisionPolicy(1000, 60, 1),
        clock=lambda: NOW,
        commands=web._commands,
    )
    publisher = CheckpointPublisher(
        authority,
        custody,
        outbox,
        clock=lambda: NOW,
        timeout_seconds=1,
        wait=lambda _seconds: supervisor.inspect(),
    )
    publisher.publish(financial.journal.checkpoint(), acknowledge=False)
    checkpoint = supervisor.inspect()
    custody.release_stop(authority.fingerprint, expected=checkpoint)
    financial.journal.after_commit = publisher.publish
    view = financial_session_view(financial.journal.read(), authority, now=NOW)
    path = tmp_path / "public/publication.json"
    path.write_text(
        json.dumps({"published_at": datetime.now(UTC).isoformat(), "financial_session": view})
    )
    pool = ThreadPoolExecutor(max_workers=4)
    futures = []
    started = time.perf_counter()
    try:
        if fault == "api_failure":

            def unavailable():
                raise OSError("optional report unavailable")

            monkeypatch.setattr(web, "_read_publication", unavailable)
            assert call(web, "/api/report")[0] == "503 Service Unavailable"
        elif fault == "malformed_publication":
            path.write_text('{"financial_session":')
            assert call(web, "/api/report")[0] == "503 Service Unavailable"
        elif fault == "command_store_fault":
            (tmp_path / "public/commands.sqlite3").write_bytes(
                b"synthetic non-database control fault"
            )
            assert call(web, "/api/commands")[0] == "503 Service Unavailable"
            assert supervisor.inspect() == financial.journal.checkpoint()
            assert (
                custody.snapshot(authority.fingerprint)["stop_reason"]
                == "scoped_control_store_unavailable"
            )
            with pytest.raises(SessionBlocked, match="stop"):
                custody.require_current(authority, now=NOW)
        elif fault == "web_pressure":
            futures = [pool.submit(call, web, "/api/console/v1/snapshot") for _ in range(128)]
        elif fault == "financial_uncertainty":
            with closing(sqlite3.connect(financial.journal.path)) as connection, connection:
                raw = json.loads(connection.execute("SELECT state FROM session").fetchone()[0])
                raw["source_cost"] = (
                    "0.01"  # Deliberate witness mismatch, never repaired by the web.
                )
                connection.execute("UPDATE session SET state=?", (json.dumps(raw),))
            with pytest.raises(SessionBlocked, match="supervision_failed"):
                supervisor.inspect()
            assert custody.snapshot(authority.fingerprint)["stopped"] == 1
        if fault not in {"command_store_fault", "financial_uncertainty"}:
            custody.require_current(authority, now=NOW, checkpoint=financial.journal.checkpoint())
            asyncio.run(financial.coordinator.submit(opportunity()))
            identity = next(iter(financial.journal.read()["orders"]))
            financial.fill(identity, size="1", terminal=False)
            assert financial.journal.read()["orders"][identity]["fill_state"] == "PARTIAL_FILL"
            custody.require_current(authority, now=NOW, checkpoint=financial.journal.checkpoint())
            assert supervisor.inspect() == financial.journal.checkpoint()
        assert all(future.result(timeout=10)[0] == "200 OK" for future in futures)
        assert time.perf_counter() - started < 15
        # The actual OS-protected command works with no browser, report, config
        # activation, optional command queue, provider, signer or notification.
        result = CliRunner().invoke(
            cli,
            [
                "ops",
                "session",
                "emergency-stop",
                "--custody",
                str(tmp_path / "independent/control.sqlite3"),
                authority.fingerprint,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "STOP_RETAINED" in result.output
        if fault == "command_store_fault":
            supervisor.inspect()
        assert (
            custody.snapshot(authority.fingerprint)["stop_reason"]
            == "explicit_local_emergency_STOP"
        )
        with pytest.raises(SessionBlocked, match="stop"):
            custody.require_current(authority, now=NOW)
    finally:
        pool.shutdown(wait=True)
        financial.journal.close()
