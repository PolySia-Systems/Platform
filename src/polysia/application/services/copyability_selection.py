from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from polysia.application.ports.candidate_intelligence import CandidatePipelineLeaseLostError
from polysia.application.ports.copyability_selection import CopyabilitySelectionStorePort
from polysia.domain.wallet_intelligence import CandidatePipelineLease
from polysia.domain.wallet_intelligence.copyability_selection import (
    DEFAULT_ALPHA_SIZE,
    DEFAULT_STRESS_SIZE,
    FEATURE_SET_VERSION,
    POLICY_ID,
    POLICY_VERSION,
    RANKING_VERSION,
    CopyabilityProcessingKey,
    CopyabilitySelectionRun,
    select_copyability_pools,
)

Clock = Callable[[], datetime]


class CopyabilitySelectionError(RuntimeError):
    """Safe Stage 3 failure that leaves the previous published pools unchanged."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class CopyabilitySelectionOutcome:
    selection: CopyabilitySelectionRun
    idempotent_replay: bool


class CopyabilitySelectionService:
    """Scores Stage 2 evidence and publishes independent copyability pools."""

    def __init__(
        self,
        store: CopyabilitySelectionStorePort,
        *,
        clock: Clock | None = None,
        alpha_size: int = DEFAULT_ALPHA_SIZE,
        stress_size: int = DEFAULT_STRESS_SIZE,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._alpha_size = alpha_size
        self._stress_size = stress_size

    def process_stage2_run(
        self,
        source_id: str,
        stage2_run_id: str,
        *,
        lease: CandidatePipelineLease,
    ) -> CopyabilitySelectionOutcome:
        self._store.initialize()
        key = CopyabilityProcessingKey(
            stage2_run_id=stage2_run_id,
            feature_set_version=FEATURE_SET_VERSION,
            policy_id=POLICY_ID,
            policy_version=POLICY_VERSION,
            ranking_version=RANKING_VERSION,
        )
        existing = self._store.successful_run(key)
        if existing is not None:
            return CopyabilitySelectionOutcome(selection=existing, idempotent_replay=True)
        try:
            evidence = self._store.load_evidence(source_id, stage2_run_id)
        except CandidatePipelineLeaseLostError:
            raise
        except Exception as error:
            raise CopyabilitySelectionError(
                "copyability_selection_failed",
                "Copyability selection failed before atomic publication.",
            ) from error
        source_snapshot_id = evidence[0].source_snapshot_id
        started_at = self._utc_now()
        run_id = self._store.start_run(
            key,
            source_id=source_id,
            source_snapshot_id=source_snapshot_id,
            started_at=started_at,
        )
        try:
            calculated_at = self._utc_now()
            scores, memberships = select_copyability_pools(
                evidence,
                calculated_at=calculated_at,
                alpha_size=self._alpha_size,
                stress_size=self._stress_size,
            )
            published = self._store.publish_run(
                run_id,
                lease=lease,
                scores=scores,
                memberships=memberships,
                published_at=self._utc_now(),
            )
        except Exception as error:
            self._store.fail_run(
                run_id,
                failed_at=self._utc_now(),
                error_code=getattr(error, "error_code", "copyability_selection_failed"),
                error_message="Copyability selection failed before atomic publication.",
            )
            if isinstance(error, (CopyabilitySelectionError, CandidatePipelineLeaseLostError)):
                raise
            raise CopyabilitySelectionError(
                "copyability_selection_failed",
                "Copyability selection failed before atomic publication.",
            ) from error
        return CopyabilitySelectionOutcome(selection=published, idempotent_replay=False)

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must be timezone-aware")
        if value.utcoffset() != timedelta(0):
            raise ValueError("clock must be UTC")
        return value
