from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from polysia.application.ports.candidate_intelligence import (
    CandidateIntelligenceStorePort,
    CandidatePipelineLeaseLostError,
)
from polysia.application.ports.candidate_wallets import (
    CandidateStoredSnapshot,
    CandidateWalletSourcePort,
    CandidateWalletStorePort,
)
from polysia.application.ports.copyability_selection import CopyabilitySelectionStorePort
from polysia.application.services.candidate_wallet_sync import (
    CandidateSyncOutcome,
    CandidateWalletSyncService,
)
from polysia.application.services.copyability_selection import (
    CopyabilitySelectionError,
    CopyabilitySelectionService,
)
from polysia.domain.wallet_intelligence import (
    CandidatePipelineLease,
    CandidatePolicyEvaluation,
    CandidatePoolRun,
    CandidateProcessingKey,
    CandidateSourceHistory,
    CandidateSourceObservation,
    CandidateStatus,
    CandidateWalletFeature,
    DataReadinessStatus,
    normalize_evm_wallet,
)
from polysia.domain.wallet_intelligence.copyability_selection import CopyabilitySelectionRun

Clock = Callable[[], datetime]

FEATURE_SET_VERSION = "snapshot-derived-v1"
CANDIDATE_POLICY_ID = "polycop-discovery"
CANDIDATE_POLICY_VERSION = "v1"
RANKING_VERSION = "source-score-rank-persistence-v1"
PIPELINE_LEASE_RESOURCE = "wallet-intelligence-pipeline"
MAX_CURRENT_WALLETS = 25_000
WALLET_HISTORY_BATCH_SIZE = 32


class CandidateIntelligenceError(RuntimeError):
    """Safe Stage 2 failure with the current healthy pool preserved."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class CandidateIntelligenceOutcome:
    pool: CandidatePoolRun
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class WalletIntelligencePipelineOutcome:
    snapshot: CandidateStoredSnapshot
    pool: CandidatePoolRun
    source_refreshed: bool
    source_idempotent_replay: bool
    intelligence_idempotent_replay: bool
    selection: CopyabilitySelectionRun | None = None
    selection_idempotent_replay: bool = False

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate_pool": {
                "evaluated_count": self.pool.evaluated_count,
                "feature_set_version": self.pool.key.feature_set_version,
                "ineligible_count": self.pool.ineligible_count,
                "invalid_count": self.pool.invalid_count,
                "partial_count": self.pool.partial_count,
                "policy_id": self.pool.key.policy_id,
                "policy_version": self.pool.key.policy_version,
                "published_at": self.pool.published_at.isoformat(),
                "ranking_version": self.pool.key.ranking_version,
                "ready_count": self.pool.ready_count,
                "run_id": self.pool.run_id,
                "selected_count": self.pool.selected_count,
                "stale_count": self.pool.stale_count,
                "unknown_count": self.pool.unknown_count,
                "watchlist_count": self.pool.watchlist_count,
            },
            "intelligence_idempotent_replay": self.intelligence_idempotent_replay,
            "source": {
                "idempotent_replay": self.source_idempotent_replay,
                "record_count": self.snapshot.record_count,
                "refreshed": self.source_refreshed,
                "run_id": self.snapshot.run_id,
                "snapshot_id": self.snapshot.snapshot_id,
                "source_id": self.snapshot.source_id,
                "source_total_pages": self.snapshot.source_total_pages,
            },
            "status": "succeeded",
        }
        if self.selection is not None:
            payload["copyability_selection"] = {
                "alpha_count": self.selection.alpha_count,
                "evaluated_count": self.selection.evaluated_count,
                "feature_set_version": self.selection.key.feature_set_version,
                "live_review_count": self.selection.live_review_count,
                "overlap_count": self.selection.overlap_count,
                "policy_id": self.selection.key.policy_id,
                "policy_version": self.selection.key.policy_version,
                "published_at": self.selection.published_at.isoformat(),
                "ranking_version": self.selection.key.ranking_version,
                "rejected_count": self.selection.rejected_count,
                "run_id": self.selection.run_id,
                "stage2_run_id": self.selection.key.stage2_run_id,
                "stress_count": self.selection.stress_count,
                "watchlist_count": self.selection.watchlist_count,
            }
            payload["selection_idempotent_replay"] = self.selection_idempotent_replay
        return payload


class CandidateIntelligenceService:
    """Builds point-in-time-safe Stage 2 features and publishes one complete pool."""

    def __init__(
        self,
        store: CandidateIntelligenceStorePort,
        *,
        chain_by_source: dict[str, str],
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._chain_by_source = dict(chain_by_source)
        self._clock = clock or (lambda: datetime.now(UTC))

    def process_snapshot(
        self,
        source_id: str,
        source_snapshot_id: str,
        *,
        lease: CandidatePipelineLease,
        stale_after: timedelta = timedelta(hours=36),
    ) -> CandidateIntelligenceOutcome:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        chain = self._chain_by_source.get(source_id)
        if chain is None:
            raise CandidateIntelligenceError(
                "source_chain_unknown",
                "Candidate source has no reviewed chain mapping.",
            )
        self._store.initialize()
        key = CandidateProcessingKey(
            source_snapshot_id=source_snapshot_id,
            feature_set_version=FEATURE_SET_VERSION,
            policy_id=CANDIDATE_POLICY_ID,
            policy_version=CANDIDATE_POLICY_VERSION,
            ranking_version=RANKING_VERSION,
        )
        existing = self._store.successful_run(key)
        if existing is not None:
            return CandidateIntelligenceOutcome(pool=existing, idempotent_replay=True)
        started_at = self._utc_now()
        run_id = self._store.start_run(key, source_id=source_id, started_at=started_at)
        try:
            history = self._store.load_source_history(source_id, source_snapshot_id)
            calculated_at = self._utc_now()
            features = _calculate_features(
                history,
                chain=chain,
                calculated_at=calculated_at,
                stale_after=stale_after,
                history_loader=lambda wallet_keys: self._store.load_wallet_histories(
                    source_id,
                    source_snapshot_id,
                    wallet_keys,
                ),
            )
            evaluations = _evaluate_and_rank(features)
            published = self._store.publish_run(
                run_id,
                lease=lease,
                features=features,
                evaluations=evaluations,
                published_at=self._utc_now(),
            )
        except Exception as error:
            self._store.fail_run(
                run_id,
                failed_at=self._utc_now(),
                error_code=getattr(error, "error_code", "candidate_intelligence_failed"),
                error_message="Candidate Intelligence failed before atomic publication.",
            )
            if isinstance(error, (CandidateIntelligenceError, CandidatePipelineLeaseLostError)):
                raise
            raise CandidateIntelligenceError(
                "candidate_intelligence_failed",
                "Candidate Intelligence failed before atomic publication.",
            ) from error
        return CandidateIntelligenceOutcome(pool=published, idempotent_replay=False)

    def _utc_now(self) -> datetime:
        return _require_utc(self._clock(), field_name="clock")


class WalletIntelligencePipelineService:
    """Serializes source freshness and Candidate Intelligence under one fenced lease."""

    def __init__(
        self,
        source: CandidateWalletSourcePort,
        source_store: CandidateWalletStorePort,
        intelligence_store: CandidateIntelligenceStorePort,
        *,
        chain: str,
        clock: Clock | None = None,
        selection_store: CopyabilitySelectionStorePort | None = None,
    ) -> None:
        self._source = source
        self._source_store = source_store
        self._intelligence_store = intelligence_store
        self._selection_store = selection_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._source_sync = CandidateWalletSyncService(source, source_store, clock=self._clock)
        self._intelligence = CandidateIntelligenceService(
            intelligence_store,
            chain_by_source={source.source_id: chain},
            clock=self._clock,
        )
        self._selection = (
            None
            if selection_store is None
            else CopyabilitySelectionService(selection_store, clock=self._clock)
        )

    async def ensure(
        self,
        *,
        scheduled_for: date,
        fresh_after: timedelta = timedelta(hours=24),
        stale_after: timedelta = timedelta(hours=36),
        lease_duration: timedelta = timedelta(minutes=30),
        history_days: int = 365,
        quarantine_days: int = 30,
        intelligence_history_days: int = 365,
    ) -> WalletIntelligencePipelineOutcome:
        if fresh_after <= timedelta(0) or stale_after <= fresh_after:
            raise ValueError("freshness thresholds must be positive and increasing")
        if intelligence_history_days < 365:
            raise ValueError("intelligence_history_days must be at least 365")
        lease = self._acquire(lease_duration)
        try:
            checked_at = self._utc_now()
            state = self._source_store.source_state(self._source.source_id)
            source_refreshed = (
                state.current_snapshot_id is None
                or state.last_success_at is None
                or checked_at - state.last_success_at > fresh_after
            )
            if source_refreshed:
                source_outcome = await self._source_sync.sync(
                    scheduled_for=scheduled_for,
                    history_days=history_days,
                    quarantine_days=quarantine_days,
                )
            else:
                if state.current_run_id is None:
                    raise CandidateIntelligenceError(
                        "source_state_incomplete",
                        "Healthy source state is missing its accepted run identity.",
                    )
                source_outcome = CandidateSyncOutcome(
                    snapshot=self._source_store.stored_snapshot(state.current_run_id),
                    idempotent_replay=True,
                )
            lease = self._intelligence_store.renew_lease(
                lease,
                renewed_at=self._utc_now(),
                lease_duration=lease_duration,
            )
            intelligence_outcome = self._intelligence.process_snapshot(
                self._source.source_id,
                source_outcome.snapshot.snapshot_id,
                lease=lease,
                stale_after=stale_after,
            )
            self._intelligence_store.prune_history(
                cutoff=self._utc_now() - timedelta(days=intelligence_history_days)
            )
            selection = None
            selection_replay = False
            if self._selection is not None and self._selection_store is not None:
                lease = self._intelligence_store.renew_lease(
                    lease,
                    renewed_at=self._utc_now(),
                    lease_duration=lease_duration,
                )
                try:
                    selection_outcome = self._selection.process_stage2_run(
                        self._source.source_id,
                        intelligence_outcome.pool.run_id,
                        lease=lease,
                    )
                except CopyabilitySelectionError:
                    raise
                self._selection_store.prune_history(
                    cutoff=self._utc_now() - timedelta(days=intelligence_history_days)
                )
                selection = selection_outcome.selection
                selection_replay = selection_outcome.idempotent_replay
            return WalletIntelligencePipelineOutcome(
                snapshot=source_outcome.snapshot,
                pool=intelligence_outcome.pool,
                source_refreshed=source_refreshed,
                source_idempotent_replay=source_outcome.idempotent_replay,
                intelligence_idempotent_replay=intelligence_outcome.idempotent_replay,
                selection=selection,
                selection_idempotent_replay=selection_replay,
            )
        finally:
            self._intelligence_store.release_lease(lease)

    async def sync_source_only(
        self,
        *,
        scheduled_for: date,
        force_new: bool = False,
        lease_duration: timedelta = timedelta(minutes=30),
        history_days: int = 365,
        quarantine_days: int = 30,
    ) -> CandidateSyncOutcome:
        lease = self._acquire(lease_duration)
        try:
            return await self._source_sync.sync(
                scheduled_for=scheduled_for,
                force_new=force_new,
                history_days=history_days,
                quarantine_days=quarantine_days,
            )
        finally:
            self._intelligence_store.release_lease(lease)

    def _acquire(self, lease_duration: timedelta) -> CandidatePipelineLease:
        self._source_store.initialize()
        self._intelligence_store.initialize()
        if self._selection_store is not None:
            self._selection_store.initialize()
        return self._intelligence_store.acquire_lease(
            PIPELINE_LEASE_RESOURCE,
            owner_id=str(uuid.uuid4()),
            acquired_at=self._utc_now(),
            lease_duration=lease_duration,
        )

    def _utc_now(self) -> datetime:
        return _require_utc(self._clock(), field_name="clock")


def _calculate_features(
    history: CandidateSourceHistory,
    *,
    chain: str,
    calculated_at: datetime,
    stale_after: timedelta,
    history_loader: Callable[
        [tuple[str, ...]], dict[str, tuple[CandidateSourceObservation, ...]]
    ],
) -> tuple[CandidateWalletFeature, ...]:
    snapshots_by_id = {snapshot.snapshot_id: snapshot for snapshot in history.snapshots}
    if history.current_snapshot_id not in snapshots_by_id:
        raise CandidateIntelligenceError(
            "source_history_incomplete",
            "Current source snapshot is missing from accepted history.",
        )
    current_observations = history.current_observations
    if len(current_observations) > MAX_CURRENT_WALLETS:
        raise CandidateIntelligenceError(
            "current_wallet_limit_exceeded",
            "Current source snapshot exceeds the reviewed Stage 2 wallet limit.",
        )
    current_wallet_keys = tuple(item.wallet_key for item in current_observations)
    if len(set(current_wallet_keys)) != len(current_wallet_keys):
        raise CandidateIntelligenceError(
            "current_wallet_duplicate",
            "Current source snapshot contains duplicate wallet identities.",
        )
    features: list[CandidateWalletFeature] = []
    for offset in range(0, len(current_observations), WALLET_HISTORY_BATCH_SIZE):
        current_batch = current_observations[offset : offset + WALLET_HISTORY_BATCH_SIZE]
        wallet_keys = tuple(item.wallet_key for item in current_batch)
        histories = history_loader(wallet_keys)
        if set(histories) != set(wallet_keys):
            raise CandidateIntelligenceError(
                "wallet_history_incomplete",
                "Current wallet history did not reconcile with the source snapshot.",
            )
        for current in current_batch:
            wallet_id, normalized_chain, normalized_address = normalize_evm_wallet(
                chain, current.external_wallet_id
            )
            observations = sorted(
                histories[current.wallet_key],
                key=lambda item: (item.accepted_at, item.snapshot_id),
            )
            if not observations or observations[-1].snapshot_id != history.current_snapshot_id:
                raise CandidateIntelligenceError(
                    "wallet_history_incomplete",
                    "Current wallet observation is not the latest accepted evidence.",
                )
            prior = observations[:-1]
            first_seen_at = observations[0].accepted_at
            eligible_snapshot_count = sum(
                first_seen_at <= snapshot.accepted_at <= current.accepted_at
                for snapshot in history.snapshots
            )
            if eligible_snapshot_count < len(observations):
                raise CandidateIntelligenceError(
                    "presence_denominator_invalid",
                    "Wallet presence denominator did not reconcile.",
                )
            presence_ratio = Decimal(len(observations)) / Decimal(eligible_snapshot_count)
            data_age = max(timedelta(0), calculated_at - current.accepted_at)
            previous = prior[-1] if prior else None
            at_1d = _point_at_or_before(prior, current.captured_at - timedelta(days=1))
            at_7d = _point_at_or_before(prior, current.captured_at - timedelta(days=7))
            at_30d = _point_at_or_before(prior, current.captured_at - timedelta(days=30))
            ranks = tuple(Decimal(item.source_rank) for item in observations)
            scores = tuple(
                item.source_score for item in observations if item.source_score is not None
            )
            rank_volatility, rank_stability = _volatility_and_stability(ranks)
            score_volatility, score_stability = _volatility_and_stability(scores)
            is_stale = data_age > stale_after
            readiness_reasons: tuple[str, ...]
            if is_stale:
                readiness = DataReadinessStatus.STALE
                readiness_reasons = ("source_snapshot_stale",)
            elif current.source_score is None:
                readiness = DataReadinessStatus.PARTIAL
                readiness_reasons = ("source_score_missing",)
            else:
                readiness = DataReadinessStatus.READY
                readiness_reasons = ("current_source_evidence_valid",)
                if any(point is None for point in (at_1d, at_7d, at_30d)):
                    readiness_reasons += ("historical_windows_incomplete",)
            features.append(
                CandidateWalletFeature(
                    wallet_id=wallet_id,
                    chain=normalized_chain,
                    normalized_address=normalized_address,
                    source_wallet_key=current.wallet_key,
                    source_rank=current.source_rank,
                    source_score=current.source_score,
                    source_metrics_json=current.source_metrics_json,
                    effective_at=current.captured_at,
                    observed_at=current.captured_at,
                    ingested_at=current.accepted_at,
                    calculated_at=calculated_at,
                    first_seen_at=first_seen_at,
                    last_seen_at=current.accepted_at,
                    observation_count=len(observations),
                    observed_days=len({item.captured_at.date() for item in observations}),
                    eligible_snapshot_count=eligible_snapshot_count,
                    presence_ratio=presence_ratio,
                    data_age_seconds=int(data_age.total_seconds()),
                    stale_after_seconds=int(stale_after.total_seconds()),
                    is_stale=is_stale,
                    previous_rank=None if previous is None else previous.source_rank,
                    rank_delta_previous=_rank_delta(current, previous),
                    rank_delta_1d=_rank_delta(current, at_1d),
                    rank_delta_7d=_rank_delta(current, at_7d),
                    rank_delta_30d=_rank_delta(current, at_30d),
                    best_rank=min(item.source_rank for item in observations),
                    worst_rank=max(item.source_rank for item in observations),
                    rank_volatility=rank_volatility,
                    rank_stability=rank_stability,
                    score_delta_previous=_score_delta(current, previous),
                    score_delta_1d=_score_delta(current, at_1d),
                    score_delta_7d=_score_delta(current, at_7d),
                    score_delta_30d=_score_delta(current, at_30d),
                    score_volatility=score_volatility,
                    score_stability=score_stability,
                    data_readiness_status=readiness,
                    readiness_reasons=readiness_reasons,
                )
            )
    if len(features) != len(current_observations) or not features:
        raise CandidateIntelligenceError(
            "feature_count_mismatch",
            "Candidate feature count did not reconcile with the source snapshot.",
        )
    if len({feature.wallet_id for feature in features}) != len(features):
        raise CandidateIntelligenceError(
            "canonical_identity_collision",
            "Multiple source identities resolved to one canonical wallet in one snapshot.",
        )
    return tuple(features)


def _evaluate_and_rank(
    features: tuple[CandidateWalletFeature, ...],
) -> tuple[CandidatePolicyEvaluation, ...]:
    status_by_wallet: dict[str, tuple[CandidateStatus, tuple[str, ...]]] = {}
    selected: list[CandidateWalletFeature] = []
    for feature in features:
        readiness = feature.data_readiness_status
        if readiness is DataReadinessStatus.READY:
            status = CandidateStatus.SELECTED
            reasons = ("ready_discovery_candidate",)
            selected.append(feature)
        elif readiness is DataReadinessStatus.INVALID:
            status = CandidateStatus.INELIGIBLE
            reasons = ("invalid_current_evidence",)
        else:
            status = CandidateStatus.WATCHLIST
            reasons = (f"readiness_{readiness.value.lower()}",)
        status_by_wallet[feature.wallet_id] = (status, reasons)
    selected.sort(
        key=lambda feature: (
            -feature.source_score
            if feature.source_score is not None
            else Decimal("Infinity"),
            feature.source_rank,
            -feature.presence_ratio,
            feature.wallet_id,
        )
    )
    selected_rank = {feature.wallet_id: index for index, feature in enumerate(selected, 1)}
    evaluations = tuple(
        CandidatePolicyEvaluation(
            wallet_id=feature.wallet_id,
            candidate_status=status_by_wallet[feature.wallet_id][0],
            candidate_rank=selected_rank.get(feature.wallet_id),
            policy_reasons=status_by_wallet[feature.wallet_id][1],
        )
        for feature in features
    )
    return evaluations


def _point_at_or_before(
    observations: list[CandidateSourceObservation],
    threshold: datetime,
) -> CandidateSourceObservation | None:
    eligible = [item for item in observations if item.captured_at <= threshold]
    return (
        None
        if not eligible
        else max(eligible, key=lambda item: (item.captured_at, item.snapshot_id))
    )


def _rank_delta(
    current: CandidateSourceObservation,
    historical: CandidateSourceObservation | None,
) -> int | None:
    return None if historical is None else historical.source_rank - current.source_rank


def _score_delta(
    current: CandidateSourceObservation,
    historical: CandidateSourceObservation | None,
) -> Decimal | None:
    if historical is None or current.source_score is None or historical.source_score is None:
        return None
    return current.source_score - historical.source_score


def _volatility_and_stability(
    values: tuple[Decimal, ...],
) -> tuple[Decimal | None, Decimal | None]:
    if len(values) < 2:
        return None, None
    with localcontext() as context:
        context.prec = 28
        mean = sum(values, Decimal(0)) / Decimal(len(values))
        variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(
            len(values)
        )
        volatility = variance.sqrt()
        stability = Decimal(1) / (Decimal(1) + volatility)
    return volatility, stability


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return value.astimezone(UTC)
