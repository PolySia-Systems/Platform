"""Real pure producers and command owners; explicitly synthetic scale and host gaps."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.application.services.source_cohort import SharedCohortSelection
from polysia.config.settings import TradingMode
from polysia.deployment.shadow_lab import ShadowLab, ShadowSourcePlan
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.financial_session import digest
from polysia.domain.wallet_intelligence.source_cohort import CohortCandidate
from polysia.monitoring.capabilities import CapabilityEvidence, capability_projection
from polysia.monitoring.financial_session import financial_session_view
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from tests.integration.test_financial_session import Harness, opportunity
from tests.integration.test_session_policy_controls import policy
from tests.integration.test_session_sources_and_resources import CASH, CTF, EXCHANGE, SCOPE, WALLET
from tests.unit.storage.test_acquisition_authority import policy as acquisition_policy


def lab(root: Path) -> ShadowLab:
    root.mkdir(parents=True, exist_ok=True)
    mirror, profit = policy(), policy(profit=True)
    config = ContinuousShadowConfig(
        copy_policy=mirror, policy_version=mirror.version, code_sha="a" * 40
    )
    selection = ContinuousSelectionSnapshot.create(
        source_id="fixture",
        selection_run_id="selection",
        source_snapshot_id="retained",
        feature_set_version="features",
        policy_id="policy",
        policy_version="1",
        ranking_version="1",
        published_at=datetime.now(UTC),
        candidates=(ProtectedShadowCandidate("leader", WALLET, ("SHADOW_ALPHA",), 1, None),),
    )
    owner = ShadowLab(
        ContinuousShadowRepository(root / "shadow.sqlite3"),
        AcquisitionAuthority(
            root / "acquisition.sqlite3",
            replace(acquisition_policy(), endpoints=("https://rpc.fixture/",)),
        ),
        selection=selection,
        templates={
            mirror.fingerprint: config,
            profit.fingerprint: replace(config, copy_policy=profit, policy_version=profit.version),
        },
        allowed_targets=frozenset({"fixture-lab", "fixture-lab-two"}),
        clock=lambda: datetime.now(UTC),
        source_plan=ShadowSourcePlan(
            "https://rpc.fixture/", EXCHANGE, CTF, CASH, (SCOPE,), (("leader", WALLET),)
        ),
    )
    owner.initialize()
    return owner


def write(
    root: Path, *, wallets: int = 10_000, orders: int = 200, lab_view: dict[str, Any] | None = None
) -> dict[str, Any]:
    path = root / "publication.json"
    retained = json.loads(path.read_text()) if path.is_file() else {}
    harness = Harness(root / "h2-financial")
    try:
        asyncio.run(harness.coordinator.submit(opportunity()))
        identity = next(iter(harness.journal.read()["orders"]))
        harness.fill(identity, size="1", terminal=False)
        view = financial_session_view(
            harness.journal.read(), harness.auth, now=harness.now, trading_mode=TradingMode.PAPER
        )
    finally:
        harness.journal.close()
    now = datetime.now(UTC)
    view["as_of"], view["expires_at"] = now.isoformat(), (now + timedelta(seconds=60)).isoformat()
    view["account_observed_at"], view["account_valid_until"] = now.isoformat(), view["expires_at"]
    view["remaining_authority"]["expires_at"] = (now + timedelta(minutes=5)).isoformat()
    original = view["orders"][0]
    view["orders"] = [
        {**original, "intent_id": f"order-{index:05}", "updated_at": now.isoformat()}
        for index in range(orders)
    ]
    view["positions"][0]["orders"] = ["order-00000"]
    view["positions"][0]["updated_at"] = now.isoformat()
    selection = SharedCohortSelection(
        policy_version="synthetic-selection-v1",
        selected_at=now,
        candidates=tuple(
            CohortCandidate(
                wallet_id="wallet" if index == 0 else f"wallet-{index:05}",
                sources=("native", "polycop"),
                current_sources=("native",),
                state="SELECTED" if index == 0 else "DISCOVERED",
                reasons=() if index == 0 else ("unpriced_fees",),
                rank=index + 1,
                evidence_id="fictional-qualification",
                evaluation_start=now + timedelta(minutes=1),
                ranking_explanation=(
                    "Follower samples, confidence and exit depth; provider score excluded."
                ),
            )
            for index in range(wallets)
        ),
        sources=(),
        qualification_evidence=(),
        digest=digest(("synthetic-cohort", wallets)),
    )
    capability = CapabilityEvidence(
        "backup",
        "MISSING",
        "synthetic-protection-gap",
        now,
        now + timedelta(seconds=60),
        "Financial backup is unprotected",
        "fixture-run",
        "Verify isolated restore",
    )
    retained.update(
        {
            "version": "console-h2-synthetic-producers/v1",
            "dataset_role": "SYNTHETIC",
            "published_at": now.isoformat(),
            "last_attempt": now.isoformat(),
            "status": "OBSERVING",
            "financial_session": view,
            "selection": selection.to_console_dict(),
            "capabilities": capability_projection(
                {"backup": capability}, now=now, enabled={"new_entries": True}
            ),
            "active_account": {
                "identity": "fixture-account-fingerprint",
                "status": "UNKNOWN",
                "observed_at": now.isoformat(),
            },
            "copy_policy": {
                "effective": {
                    "version": "frozen-v1",
                    "sizing": "FIXED_DEBIT",
                    "exit_preset": "HYBRID",
                    "reentry": False,
                },
                "staged": None,
                "digest": "fixture-frozen-policy",
            },
            "capacity": {
                "allocation": "FIXED",
                "actual_requests": 12,
                "measured_response_bytes": 4000,
                "queue_depth": 1,
                "queue_limit": 2,
                "external_shared_egress_utilization": None,
            },
            "backup": {"mode": "UNPROTECTED", "independent_restore": "UNKNOWN"},
            "incidents": [
                {
                    "kind": "backup_unprotected",
                    "scope": "fixture-run",
                    "reason": "separate protection missing",
                    "next_action": "Verify isolated restore",
                    "delivery_state": "NOT_CONFIGURED",
                }
            ],
            "shadow_lab": lab_view or {},
        }
    )
    path.write_text(json.dumps(retained, default=str), encoding="utf-8")
    (root / "supervisor-status.json").write_text(
        json.dumps(
            {
                "status": "STOP",
                "scope": "fixture-run",
                "observed_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=20)).isoformat(),
                "reason": "synthetic_protective_stop",
            }
        ),
        encoding="utf-8",
    )
    return retained
