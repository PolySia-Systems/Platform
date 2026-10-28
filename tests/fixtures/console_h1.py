"""Shared real financial producer fixture; scale rows are explicitly synthetic copies."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.config.settings import TradingMode
from polysia.deployment.session_supervision import SessionSupervisor, SupervisionPolicy
from polysia.monitoring.financial_session import financial_session_view
from polysia.security.session_authority import SessionCustody
from polysia.storage.console_commands import ConsoleCommandStore
from tests.integration.test_financial_session import Harness, opportunity
from tests.integration.test_session_custody import signed_authority


def publication(
    root: Path, *, wallets: int = 4, orders: int = 1, now: datetime | None = None
) -> dict[str, Any]:
    harness = Harness(root / "producer")
    try:
        asyncio.run(harness.coordinator.submit(opportunity()))
        view = financial_session_view(
            harness.journal.read(), harness.auth, now=harness.now, trading_mode=TradingMode.PAPER
        )
        now = now or datetime.now(UTC)
        # Rebase only fixture clocks, never financial values or permission.
        view["as_of"] = now.isoformat()
        view["expires_at"] = (now + timedelta(seconds=30)).isoformat()
        view["account_observed_at"] = now.isoformat()
        view["account_valid_until"] = view["expires_at"]
        view["remaining_authority"]["expires_at"] = (now + timedelta(minutes=5)).isoformat()
        view["orders"] = [
            {**view["orders"][0], "intent_id": f"order-{index:05}", "updated_at": now.isoformat()}
            for index in range(orders)
        ]
        if orders > 1:
            view["orders"][-1]["token"] = "synthetic-long-token-" + "abcdef0123456789" * 12
        return {
            "version": "console-producer-fixture/v1",
            "dataset_role": "SYNTHETIC",
            "published_at": now.isoformat(),
            "financial_session": view,
            "diagnostic": {
                "discovery": {
                    "candidates": [
                        {
                            "wallet_id": f"wallet-{index:05}",
                            "state": "ACTIVITY_CONFIRMED",
                            "exclusions": ["eligibility_unknown"],
                            "last_qualifying_activity": now.isoformat(),
                        }
                        for index in range(wallets)
                    ]
                }
            },
        }
    finally:
        harness.journal.close()


def write_publication(
    root: Path, *, wallets: int = 4, orders: int = 1, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    value = publication(root, wallets=wallets, orders=orders, now=now)
    (root / "publication.json").write_text(json.dumps(value), encoding="utf-8")
    (root / "supervisor-status.json").write_text(
        json.dumps(
            {
                "status": "STOP",
                "scope": "fixture-run",
                "reason": "synthetic_protective_stop",
                "observed_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=20)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return value


def protective_owner(
    root: Path, commands: ConsoleCommandStore
) -> tuple[SessionSupervisor, SessionCustody]:
    auth, verifier = signed_authority()
    from tests.integration.test_financial_session import BINDING, NOW

    custody = SessionCustody(root / "independent-fixture/custody.sqlite3")
    custody.initialize()
    custody.claim(verifier.verify(auth, BINDING, now=NOW), auth)
    # Only process_controls is invoked. No account, journal, provider or inspection is opened.
    owner = SessionSupervisor(
        auth,
        custody,
        journal=root / "absent-private-journal",
        witness=root / "absent-witness",
        outbox=root / "absent-outbox",
        backup_receipt=root / "absent-backup",
        policy=SupervisionPolicy(1000, 60, 1),
        clock=lambda: datetime.now(UTC),
        commands=commands,
    )
    return owner, custody
