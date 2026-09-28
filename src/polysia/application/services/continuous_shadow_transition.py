"""Apply a prepared Shadow period at a safe boundary using existing receipts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from polysia.application.ports.continuous_shadow import (
    ContinuousCandidatePort,
    ContinuousSelectionUnavailableError,
    ContinuousShadowStorePort,
)
from polysia.application.services.continuous_shadow import (
    ContinuousShadowError,
    ContinuousShadowService,
)
from polysia.domain.copytrading.continuous_shadow import (
    ContinuousShadowConfig,
    ContinuousShadowLifecycle,
)


@dataclass(frozen=True, slots=True)
class PreparedShadowPeriod:
    command_id: str
    expected_latest_experiment_id: str
    snapshot_digest: str
    expires_at: datetime
    config: ContinuousShadowConfig


class ContinuousShadowTransition:
    def __init__(
        self,
        store: ContinuousShadowStorePort,
        candidates: ContinuousCandidatePort,
        service_factory: Callable[[ContinuousShadowConfig], ContinuousShadowService],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._candidates = candidates
        self._service_factory = service_factory
        self._clock = clock

    async def tick(
        self, source_id: str, plan: PreparedShadowPeriod | None
    ) -> dict[str, object]:
        """Poll the frozen period, or consume one prepared command when flat."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("Shadow transition clock must be UTC")
        self._store.initialize()
        active = self._store.active_experiment(source_id)
        latest = self._store.latest_experiment(source_id)
        latest_id = "none" if latest is None else latest.experiment_id
        if active is not None:
            if plan is not None and active.config.to_dict() == plan.config.to_dict():
                receipt = self._store.config_receipt(plan.command_id)
                if receipt is not None and receipt["disposition"] == "PENDING_APPLY":
                    self._service_factory(plan.config).apply_configuration(
                        source_id, command_id=plan.command_id,
                        expected_latest_experiment_id=plan.expected_latest_experiment_id,
                    )
            age = now - active.started_at
            event_count, _storage_bytes = self._store.period_usage(active.experiment_id)
            expired = age >= timedelta(seconds=active.config.period_duration_seconds) or (
                event_count >= active.config.period_max_events
            )
            service = self._service_factory(active.config)
            if not expired:
                outcome = await service.poll(source_id)
                return {"status": "POLL_COMPLETED", "experiment_id": active.experiment_id,
                        "poll": outcome.to_dict()}
            if active.lifecycle is ContinuousShadowLifecycle.RUNNING:
                service.drain(source_id)
            open_count = self._store.open_position_count(active.experiment_id)
            pending_count = self._store.pending_observation_count(active.experiment_id)
            if open_count or pending_count:
                try:
                    outcome = await service.poll(source_id)
                except ContinuousShadowError as error:
                    if "period limit reached with open positions" not in str(error):
                        raise
                    return {
                        "status": "BLOCKED_INVENTORY", "reason": str(error),
                        "experiment_id": active.experiment_id,
                        "open_positions": open_count,
                        "pending_observations": pending_count,
                        "next_action": "resolve_existing_inventory_without_reset",
                    }
                return {
                    "status": "PENDING_DRAIN", "experiment_id": active.experiment_id,
                    "open_positions": open_count, "pending_observations": pending_count,
                    "poll": outcome.to_dict(),
                }
        blocker = self._plan_blocker(source_id, plan, now, latest_id)
        if blocker is not None:
            return {
                "status": "WAITING_PREPARATION", "reason": blocker,
                "experiment_id": None if active is None else active.experiment_id,
                "next_action": "refresh_or_replan_prepared_cohort",
            }
        assert plan is not None
        next_service = self._service_factory(plan.config)
        preview = next_service.preview_configuration(source_id)
        if preview["status"] in {"BLOCKED_CAPACITY", "BLOCKED_SELECTION"}:
            return {
                "status": "WAITING_PREPARATION", "reason": preview["reason"],
                "experiment_id": None if active is None else active.experiment_id,
                "next_action": "refresh_or_replan_prepared_cohort",
            }
        if active is not None:
            self._service_factory(active.config).finalize(source_id)
        receipt = next_service.apply_configuration(
            source_id, command_id=plan.command_id,
            expected_latest_experiment_id=plan.expected_latest_experiment_id,
        )
        if receipt["disposition"] != "APPLIED":
            return {
                "status": "WAITING_PREPARATION", "reason": receipt["reason"],
                "receipt": receipt, "next_action": "inspect_configuration_receipt",
            }
        outcome = await next_service.poll(source_id)
        return {
            "status": "PERIOD_APPLIED", "experiment_id": receipt["experiment_id"],
            "receipt": receipt, "poll": outcome.to_dict(),
        }

    def _plan_blocker(
        self, source_id: str, plan: PreparedShadowPeriod | None,
        now: datetime, latest_id: str,
    ) -> str | None:
        if plan is None:
            return "prepared_cohort_unavailable"
        if plan.expires_at.tzinfo is None or plan.expires_at.utcoffset() != timedelta(0):
            return "prepared_cohort_time_invalid"
        if plan.expires_at <= now:
            return "prepared_cohort_expired"
        if plan.expected_latest_experiment_id != latest_id:
            return "prepared_cohort_revision_changed"
        try:
            current = self._candidates.current_snapshot(source_id)
        except (ContinuousSelectionUnavailableError, OSError):
            return "candidate_snapshot_unavailable"
        if current.digest != plan.snapshot_digest:
            return "candidate_snapshot_changed"
        return None
