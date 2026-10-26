from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.control.scoped_operations import ScopedPreview
from polysia.deployment.shadow_lab import ShadowLab, ShadowSourcePlan
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.financial_session import SessionBlocked
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from tests.integration.test_financial_session import NOW
from tests.integration.test_session_policy_controls import policy
from tests.integration.test_session_sources_and_resources import CASH, CTF, EXCHANGE, SCOPE, WALLET
from tests.unit.storage.test_acquisition_authority import policy as acquisition_policy


@pytest.mark.asyncio
async def test_real_shadow_lifecycle_capital_history_and_archive_are_isolated(
    tmp_path: Path,
) -> None:
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
        published_at=NOW,
        candidates=(ProtectedShadowCandidate("leader", WALLET, ("SHADOW_ALPHA",), 1, None),),
    )
    authority = AcquisitionAuthority(
        tmp_path / "acquisition.sqlite3",
        replace(acquisition_policy(), endpoints=("https://rpc.fixture/",)),
    )
    lab = ShadowLab(
        ContinuousShadowRepository(tmp_path / "shadow.sqlite3"),
        authority,
        selection=selection,
        templates={
            mirror.fingerprint: config,
            profit.fingerprint: replace(config, copy_policy=profit, policy_version=profit.version),
        },
        allowed_targets=frozenset({"one", "two", "three"}),
        clock=lambda: NOW,
        maximum_experiments=3,
        source_plan=ShadowSourcePlan(
            "https://rpc.fixture/", EXCHANGE, CTF, CASH, (SCOPE,), (("leader", WALLET),)
        ),
    )

    def run(operation, target="one", arguments=()):
        return lab.execute(
            ScopedPreview(
                operation, target, 0, "operator", NOW, NOW + timedelta(minutes=1), arguments
            )
        )

    try:
        lab.initialize()
        run("shadow.create", arguments=(("policy_digest", mirror.fingerprint),))
        run("shadow.clone", "two", (("source", "one"),))
        run("policy.stage", "two", (("policy_digest", profit.fingerprint),))
        run("shadow.start")
        run("shadow.start", "two")
        first, second = lab.slot("one"), lab.slot("two")
        assert first["experiment_id"] != second["experiment_id"]
        assert (
            lab.store.selection_snapshot(
                lab.store.latest_experiment("shadow-lab:one").selection_run_id
            ).candidates
            == selection.candidates
        )
        with pytest.raises(SessionBlocked, match="immutable"):
            run("policy.stage", arguments=(("policy_digest", profit.fingerprint),))
        run("shadow.drain")
        run("shadow.resume")
        run("shadow.drain")
        run("shadow.archive")
        with pytest.raises(SessionBlocked, match="unarchived"):
            run("shadow.resume")
        run("shadow.drain", "two")
        run("shadow.finalize", "two")
        comparison = lab.compare("one", "two")
        assert comparison["sum_of_returns"] is None
        assert comparison["acquisition_budget"]["requests_charged"] == 0
        assert lab.slot("one")["phase"] == "ARCHIVED"
        assert lab.slot("two")["phase"] == "FINALIZED"
    finally:
        await lab.close()
