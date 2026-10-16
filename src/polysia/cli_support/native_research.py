"""Compose native research with the existing single-writer Shadow engine."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.bounded_market import BoundedMarketAdapter
from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.copytrading_source import (
    PolymarketCopyTradingSource,
    PolymarketMarketScope,
)
from polysia.application.ports.continuous_shadow import (
    ContinuousSelectionSnapshot,
    ContinuousSelectionUnavailableError,
)
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.application.services.continuous_shadow import ContinuousShadowService
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.wallet_intelligence import normalize_evm_wallet
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.continuous_shadow import (
    ContinuousShadowLeaseRepository,
    ContinuousShadowRepository,
)


class NativeSnapshotPort:
    def __init__(self, discovery: dict[str, Any]) -> None:
        unsigned = {key: value for key, value in discovery.items() if key != "digest"}
        digest = hashlib.sha256(json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        if (discovery.get("digest") != digest
                or discovery.get("profile") != "native-recent-activity/v1"):
            raise ValueError("native discovery digest or profile mismatch")
        candidates: list[ProtectedShadowCandidate] = []
        for item in discovery["candidates"]:
            if item["execution_eligibility"] != "ELIGIBLE_FOR_RESEARCH":
                continue
            wallet_id, _, address = normalize_evm_wallet("polygon", item["address"])
            if wallet_id != item["wallet_id"] or item["state"] != "ACTIVITY_CONFIRMED":
                raise ValueError("native candidate identity or evidence mismatch")
            candidates.append(ProtectedShadowCandidate(wallet_id, address, ("NATIVE_RESEARCH",)))
        if not candidates or len(candidates) > 10 or len({c.wallet_id for c in candidates}) != len(
            candidates
        ):
            raise ContinuousSelectionUnavailableError("no valid unique native research cohort")
        self.snapshot = ContinuousSelectionSnapshot.create(
            source_id="polymarket-native", selection_run_id="native-" + digest[:32],
            source_snapshot_id=digest, feature_set_version="complete-native-activity/v1",
            policy_id="native-recent-activity", policy_version="v1",
            ranking_version="activity-recency-identity/v1",
            published_at=datetime.fromisoformat(discovery["frozen_at"]),
            candidates=tuple(candidates),
        )

    def current_snapshot(
        self, source_id: str, **_kwargs: Any,
    ) -> ContinuousSelectionSnapshot:
        if source_id != self.snapshot.source_id:
            raise ContinuousSelectionUnavailableError("native source identity mismatch")
        return self.snapshot


def native_shadow_service(
    database: Path, discovery: dict[str, Any], *, authority: AcquisitionAuthority,
    code_sha: str, admission: dict[str, Any], closure: bool = False,
) -> ContinuousShadowService:
    port = NativeSnapshotPort(discovery)
    if len(port.snapshot.candidates) > authority.policy.cohort_limit:
        raise ValueError("native cohort exceeds acquisition policy")
    transport = BoundedPublicTransport(authority, closure=closure)
    config = ContinuousShadowConfig(
        code_sha=code_sha, runtime_version="continuous-shadow-native-research-v1",
        policy_version="native-research-shadow-policy/v1",
        selection_policy="native-recent-activity-v1",
        wallet_count=len(port.snapshot.candidates),
        selection_observed_at=port.snapshot.published_at,
        selection_preflight_digest=port.snapshot.source_snapshot_id,
        capacity_evidence=admission, period_duration_seconds=86_400,
        poll_interval_seconds=authority.policy.cadence_seconds, initial_lookback_minutes=1,
        source_max_pages=4, source_max_requests=4,
    )
    return ContinuousShadowService(
        ContinuousShadowRepository(database), port, ContinuousShadowLeaseRepository(database),
        lambda leaders: PolymarketCopyTradingSource(
            leaders, transport=transport, market_scope=PolymarketMarketScope.ALL_VERIFIED,
            max_pages=4, max_requests=4, max_elapsed_seconds=30,
        ),
        BoundedMarketAdapter(transport), config=config, concurrency=1,
        maximum_pages_per_wallet=4, maximum_selection_age=timedelta(hours=4),
        automatic_rollover=False,
    )
