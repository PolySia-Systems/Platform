"""Compose native research with the existing single-writer Shadow engine."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.bounded_market import BoundedMarketAdapter
from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.copytrading_source import (
    PolymarketCopyTradingSource,
    PolymarketMarketScope,
)
from polysia.application.ports.continuous_shadow import (
    ContinuousPollOutcome,
    ContinuousSelectionSnapshot,
    ContinuousSelectionUnavailableError,
)
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.application.services.continuous_shadow import ContinuousShadowService
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.wallet_intelligence import normalize_evm_wallet
from polysia.monitoring.latency_intelligence.identity import load_runtime_identity
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.monitoring.process_capacity import ProcessCapacity
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.continuous_shadow import (
    ContinuousShadowLeaseRepository,
    ContinuousShadowRepository,
)
from polysia.storage.latency_telemetry import LatencyTelemetryStore
from polysia.storage.metadata_identity_cache import MetadataIdentityCache


class NativeShadowService(ContinuousShadowService):
    """Own observational persistence for every native poll, including cancellation."""

    async def poll(self, source_id: str) -> ContinuousPollOutcome:
        try:
            capacity = ProcessCapacity()
        except Exception:
            capacity = None
        try:
            return await super().poll(source_id)
        finally:
            publish_native_health(self.latency_recorder, capacity, stage="poll")


def publish_native_health(recorder: Any, capacity: ProcessCapacity | None, *, stage: str) -> None:
    """Publish optional diagnostics for both qualification and admitted polls."""
    if recorder is None:
        return
    try:
        recorder.flush()
        health = recorder.health()
        path = recorder.store.path.with_suffix(".health.json") if isinstance(
            recorder, LatencyRecorder
        ) else None
        if path is not None:
            health["native_stage"] = stage
            health.update(_capacity_health(path, capacity, telemetry_fault=bool(
                health["telemetry_errors"] or health["dropped_measurements"],
            )))
            temporary = path.with_suffix(".partial")
            temporary.write_text(json.dumps(health, sort_keys=True), encoding="utf-8")
            temporary.replace(path)
    except Exception:
        logging.getLogger(__name__).warning("native_telemetry_publication_failed")


def _capacity_health(
    path: Path, observer: ProcessCapacity | None, *, telemetry_fault: bool = False,
) -> dict[str, Any]:
    """Retain bounded process totals across oneshot restarts, outside economic state."""
    previous: dict[str, Any] = {}
    history_gap = False
    errors = 0
    try:
        if path.exists():
            if path.is_symlink() or path.stat().st_size > 4096:
                raise ValueError("invalid optional process observation")
            previous = dict(json.loads(path.read_text(encoding="utf-8")))
            errors = int(previous.get("process_capacity_errors", 0))
            if errors < 0:
                raise ValueError("invalid optional process error count")
    except (OSError, ValueError, TypeError):
        previous = {}
        errors = 0
        history_gap = True
    release = load_runtime_identity().deploy_sha
    old = previous.get("process_capacity_summary", {})
    if not isinstance(old, dict) or old.get("release_commit") != release:
        old = {}
    try:
        for key, value in old.items():
            if key in ("release_commit", "first_observed_at", "last_observed_at", "history_gap"):
                continue
            if value is not None and (
                not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
            ):
                raise ValueError("invalid optional process history")
    except ValueError:
        old = {}
        history_gap = True
    retained_fault = {
        "native_telemetry_fault_observed": telemetry_fault or previous.get(
            "native_telemetry_fault_observed",
        ) is True,
        "native_telemetry_history_gap": history_gap or previous.get(
            "native_telemetry_history_gap",
        ) is True,
    }
    try:
        if observer is None:
            raise ValueError("process observer unavailable")
        sample = observer.observation(path.parent)
        stamp = datetime.now(UTC).isoformat()
        elapsed = sample["sample_seconds"]
        cpu = sample["process_cpu_percent_one_core"]
        rss = sample["peak_process_rss_bytes"]
        free = sample["disk_free_bytes"]
        if (not isinstance(elapsed, (int, float))
                or cpu is not None and not isinstance(cpu, (int, float))
                or rss is not None and not isinstance(rss, int)
                or not isinstance(free, int)):
            raise ValueError("invalid optional process sample")
        if any(value is not None and (not math.isfinite(value) or value < 0)
               for value in (elapsed, cpu, rss, free)):
            raise ValueError("invalid optional process sample")
        summary = {
            "release_commit": release,
            "samples": int(old.get("samples", 0)) + 1,
            "first_observed_at": old.get("first_observed_at", stamp),
            "last_observed_at": stamp,
            "history_gap": history_gap or old.get("history_gap", False),
            "sample_seconds_total": old.get("sample_seconds_total", 0) + elapsed,
            "cpu_seconds_total": old.get("cpu_seconds_total", 0) + (
                0 if cpu is None else float(cpu) * elapsed / 100
            ),
            "cpu_samples": int(old.get("cpu_samples", 0)) + int(cpu is not None),
            "maximum_cpu_percent_one_core": max(
                old.get("maximum_cpu_percent_one_core") or 0, cpu or 0,
            ) if cpu is not None else old.get("maximum_cpu_percent_one_core"),
            "maximum_peak_process_rss_bytes": max(
                old.get("maximum_peak_process_rss_bytes") or 0, rss or 0,
            ) if rss is not None else old.get("maximum_peak_process_rss_bytes"),
            "minimum_free_disk_bytes": min(
                old.get("minimum_free_disk_bytes", free), free,
            ),
        }
        return {**retained_fault, "process_capacity": sample, "process_capacity_summary": summary,
                "process_capacity_errors": errors}
    except Exception:
        return {**retained_fault,
                "process_capacity": {"status": "UNKNOWN", "reason": "probe_failed"},
                "process_capacity_summary": old, "process_capacity_errors": errors + 1}


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
    persistent: bool = False, refreshed_discovery: dict[str, Any] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ContinuousShadowService:
    initial = NativeSnapshotPort(discovery)
    port = initial if refreshed_discovery is None else NativeSnapshotPort(refreshed_discovery)
    if refreshed_discovery is not None and (
        refreshed_discovery.get("original_cohort_digest") != discovery["digest"]
        or {(c.wallet_id, c.address) for c in port.snapshot.candidates}
        != {(c.wallet_id, c.address) for c in initial.snapshot.candidates}
        or port.snapshot.published_at < initial.snapshot.published_at
    ):
        raise ValueError("native revalidation cannot replace admitted identities")
    if len(port.snapshot.candidates) > authority.policy.cohort_limit:
        raise ValueError("native cohort exceeds acquisition policy")
    transport = BoundedPublicTransport(authority, closure=closure)
    config = ContinuousShadowConfig(
        code_sha=code_sha, runtime_version=(
            "continuous-shadow-native-research-v2" if persistent
            else "continuous-shadow-native-research-v1"
        ),
        policy_version="native-research-shadow-policy/v1",
        selection_policy="native-recent-activity-v1",
        wallet_count=len(port.snapshot.candidates),
        selection_observed_at=initial.snapshot.published_at,
        selection_preflight_digest=initial.snapshot.source_snapshot_id,
        capacity_evidence=admission, period_duration_seconds=0 if persistent else 86_400,
        poll_interval_seconds=authority.policy.cadence_seconds, initial_lookback_minutes=1,
        source_max_pages=4, source_max_requests=4,
        maximum_selection_age_hours=4,
        period_max_storage_bytes=67_108_864,
    )
    telemetry = LatencyTelemetryStore(database.with_name("native-latency.sqlite3"))
    identity_cache = MetadataIdentityCache(database.with_name("metadata-identity.sqlite3"))
    return NativeShadowService(
        ContinuousShadowRepository(database), port, ContinuousShadowLeaseRepository(database),
        lambda leaders: PolymarketCopyTradingSource(
            leaders, transport=transport, clock=clock,
            market_scope=PolymarketMarketScope.ALL_VERIFIED,
            max_pages=4, max_requests=4, max_elapsed_seconds=30,
            identity_cache=identity_cache,
        ),
        BoundedMarketAdapter(transport), config=config, concurrency=1,
        maximum_pages_per_wallet=4, maximum_selection_age=timedelta(hours=4),
        automatic_rollover=False,
        clock=clock,
        latency_recorder=LatencyRecorder(telemetry, load_runtime_identity(venue_id="polymarket")),
    )
