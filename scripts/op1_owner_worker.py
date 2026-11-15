"""Owner-invoked worker bootstrap. No financial execution without the explicit flag."""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "authority", "trust", "credentials"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--execute-owner-test", action="store_true")
    args = parser.parse_args()
    if not args.execute_owner_test:
        parser.error("Explicit owner execution action required. No worker was started.")
    if os.geteuid() != 999:
        raise ValueError("isolated_financial_worker_identity_required")
    from polysia.config.settings import TradingMode
    from polysia.deployment.financial_session_runtime import (
        binding_for,
        load_authority,
        load_runtime_config,
        validate_runtime_binding,
    )
    from polysia.deployment.session_supervision import CheckpointPublisher, committed_checkpoint
    from polysia.security.session_authority import SessionCustody, SessionReceiptVerifier
    from polysia.storage.financial_session import FinancialSessionJournal

    c, a = load_runtime_config(args.config), load_authority(args.authority)
    validate_runtime_binding(c, a)
    verifier = SessionReceiptVerifier(
        {
            key: base64.b64decode(value, validate=True)
            for key, value in json.loads(args.trust.read_text()).items()
        }
    )
    verifier.verify(a, binding_for(c), now=datetime.now(UTC))
    custody = SessionCustody(c.custody_path)
    journal = FinancialSessionJournal(c.financial_path, c.witness_root, a)
    publisher = CheckpointPublisher(
        a,
        custody,
        c.outbox_path,
        clock=lambda: datetime.now(UTC),
        timeout_seconds=c.checkpoint_handshake_seconds,
    )
    deadline = time.monotonic() + 30
    while True:
        a.assert_action(a.binding, datetime.now(UTC), "ENTRY")
        snapshot = custody.snapshot(a.fingerprint)
        if snapshot["revoked"] or (
            snapshot["stopped"] and snapshot["stop_reason"] != "commissioning_stop"
        ):
            raise ValueError("independent_STOP_latched")
        # This is the genuine worker process waiting for independent startup
        # admission. There is no separate surrogate heartbeat process.
        publisher.publish(committed_checkpoint(journal.path, journal.witness), acknowledge=False)
        if not snapshot["stopped"]:
            custody.require_current(a, now=datetime.now(UTC))
            break
        if time.monotonic() >= deadline:
            raise ValueError("independent_control_startup_timeout")
        time.sleep(0.5)
    stat = args.credentials.stat()
    if args.credentials.is_symlink() or stat.st_uid != 999 or stat.st_mode & 0o077:
        raise ValueError("worker_private_credentials_required")
    credentials = json.loads(args.credentials.read_text())
    required = {c.private_key_reference, c.api_credentials_reference}
    if set(credentials) != required or any(not name.startswith("POLYSIA_") for name in required):
        raise ValueError("exact_protected_credential_references_required")
    os.environ.update(credentials)
    from polysia.cli_commands.session import run

    run(
        args.config,
        args.authority,
        args.trust,
        mode=TradingMode.LIVE,
        live_enabled=True,
        owner_entry=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "WORKER_STOP", "error_type": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
