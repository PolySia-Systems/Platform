from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.domain.copytrading import LeaderTradeEvent
from polysia.domain.copytrading.continuous_shadow import (
    ContinuousEvaluationStatus,
    ContinuousPortfolio,
    ContinuousShadowConfig,
    ContinuousShadowLifecycle,
)
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot


@dataclass(frozen=True, slots=True)
class ContinuousShadowExperiment:
    experiment_id: str
    source_id: str
    selection_run_id: str
    policy_version: str
    cost_model_version: str
    bankroll_version: str
    config: ContinuousShadowConfig
    lifecycle: ContinuousShadowLifecycle
    started_at: datetime
    draining_at: datetime | None
    finalized_at: datetime | None
    last_successful_poll_at: datetime | None
    last_error_code: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "bankroll_version": self.bankroll_version,
            "cost_model_version": self.cost_model_version,
            "config": self.config.to_dict(),
            "draining_at": None if self.draining_at is None else self.draining_at.isoformat(),
            "experiment_id": self.experiment_id,
            "finalized_at": None if self.finalized_at is None else self.finalized_at.isoformat(),
            "last_error_code": self.last_error_code,
            "last_successful_poll_at": (
                None
                if self.last_successful_poll_at is None
                else self.last_successful_poll_at.isoformat()
            ),
            "lifecycle": self.lifecycle.value,
            "policy_version": self.policy_version,
            "selection_run_id": self.selection_run_id,
            "source_id": self.source_id,
            "started_at": self.started_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FollowerAttribution:
    wallet_id: str
    market_reference: str
    outcome_reference: str
    quantity: Decimal
    cost_basis: Decimal


@dataclass(frozen=True, slots=True)
class ContinuousEvaluationRecord:
    event_id: str
    portfolio_id: str
    wallet_id: str
    pool_class: str
    status: ContinuousEvaluationStatus
    reason: str
    requested_size: Decimal
    filled_size: Decimal
    follower_price: Decimal | None
    gross_notional: Decimal | None
    fee: Decimal | None
    fee_status: str
    fee_source: str
    fee_rate: Decimal | None
    fee_exponent: Decimal | None
    realized_pnl: Decimal | None
    source_api_lag_ms: int
    signal_delay_ms: int
    price_movement: Decimal | None
    spread_cost: Decimal | None
    depth_impact: Decimal | None
    liquidity_loss: Decimal | None
    available_liquidity: Decimal | None
    quote_timestamp: datetime | None
    evaluated_at: datetime
    consumed: tuple[tuple[Decimal, Decimal], ...] = ()


@dataclass(frozen=True, slots=True)
class ContinuousLedgerRecord:
    entry_id: str
    portfolio_id: str
    event_id: str | None
    entry_type: str
    market_reference: str | None
    outcome_reference: str | None
    quantity_delta: Decimal
    cash_delta: Decimal
    cost_basis_delta: Decimal
    realized_pnl_delta: Decimal
    fee_delta: Decimal
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ContinuousPositionMark:
    portfolio_id: str
    market_reference: str
    outcome_reference: str
    quantity: Decimal
    mark_price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    mark_status: str
    marked_at: datetime


@dataclass(frozen=True, slots=True)
class ContinuousPollCompletion:
    events: tuple[tuple[LeaderTradeEvent, tuple[str, ...]], ...]
    evaluations: tuple[ContinuousEvaluationRecord, ...]
    portfolios: tuple[ContinuousPortfolio, ...]
    attributions: tuple[FollowerAttribution, ...]
    ledger: tuple[ContinuousLedgerRecord, ...]
    marks: tuple[ContinuousPositionMark, ...]
    raw_event_count: int
    duplicate_count: int
    settlement_count: int
    settlement_backlog_count: int
    request_telemetry: dict[str, object]


@dataclass(frozen=True, slots=True)
class ContinuousPollOutcome:
    experiment: ContinuousShadowExperiment
    poll_run_id: str
    window_start: datetime
    window_end: datetime
    candidate_count: int
    raw_event_count: int
    new_event_count: int
    duplicate_count: int
    evaluation_count: int
    simulated_count: int
    unknown_count: int
    rejected_count: int
    settlement_count: int
    settlement_backlog_count: int
    realized_pnl_delta: Decimal
    fee_delta: Decimal
    follower_nav: Decimal
    follower_cash: Decimal
    follower_exposure: Decimal
    request_telemetry: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_count": self.candidate_count,
            "duplicate_count": self.duplicate_count,
            "evaluation_count": self.evaluation_count,
            "experiment": self.experiment.to_dict(),
            "fee_delta": format(self.fee_delta, "f"),
            "follower_cash": format(self.follower_cash, "f"),
            "follower_exposure": format(self.follower_exposure, "f"),
            "follower_nav": format(self.follower_nav, "f"),
            "new_event_count": self.new_event_count,
            "poll_run_id": self.poll_run_id,
            "raw_event_count": self.raw_event_count,
            "realized_pnl_delta": format(self.realized_pnl_delta, "f"),
            "rejected_count": self.rejected_count,
            "request_telemetry": self.request_telemetry,
            "settlement_count": self.settlement_count,
            "settlement_backlog_count": self.settlement_backlog_count,
            "simulated_count": self.simulated_count,
            "status": "succeeded",
            "unknown_count": self.unknown_count,
            "window_end": self.window_end.isoformat(),
            "window_start": self.window_start.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ContinuousShadowHealth:
    level: str
    reasons: tuple[str, ...]
    experiment: ContinuousShadowExperiment | None
    last_poll_status: str | None
    last_poll_at: datetime | None
    poll_interval_seconds: int
    cumulative_events: int
    cumulative_evaluations: int
    duplicate_count: int
    duplicate_processing_count: int
    unknown_ratio: Decimal | None
    ledger_balanced: bool
    unmarked_position_count: int
    unknown_fee_count: int
    open_position_count: int
    settlement_backlog_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "cumulative_evaluations": self.cumulative_evaluations,
            "cumulative_events": self.cumulative_events,
            "duplicate_count": self.duplicate_count,
            "duplicate_events_detected": self.duplicate_count,
            "duplicate_processing_count": self.duplicate_processing_count,
            "experiment": None if self.experiment is None else self.experiment.to_dict(),
            "last_poll_at": None if self.last_poll_at is None else self.last_poll_at.isoformat(),
            "last_poll_status": self.last_poll_status,
            "ledger_balanced": self.ledger_balanced,
            "level": self.level,
            "open_position_count": self.open_position_count,
            "settlement_backlog_count": self.settlement_backlog_count,
            "poll_interval_seconds": self.poll_interval_seconds,
            "reasons": list(self.reasons),
            "unknown_fee_count": self.unknown_fee_count,
            "unknown_ratio": (
                None if self.unknown_ratio is None else format(self.unknown_ratio, "f")
            ),
            "unmarked_position_count": self.unmarked_position_count,
        }


class ContinuousShadowStorePort(Protocol):
    def initialize(self) -> None: ...

    def start_experiment(
        self,
        *,
        source_id: str,
        selection_run_id: str,
        candidates: tuple[ProtectedShadowCandidate, ...],
        config: ContinuousShadowConfig,
        started_at: datetime,
    ) -> ContinuousShadowExperiment: ...

    def active_experiment(self, source_id: str) -> ContinuousShadowExperiment | None: ...

    def transition(
        self,
        experiment_id: str,
        *,
        lifecycle: ContinuousShadowLifecycle,
        transitioned_at: datetime,
    ) -> ContinuousShadowExperiment: ...

    def retained_candidates(
        self,
        experiment_id: str,
    ) -> tuple[ProtectedShadowCandidate, ...]: ...

    def watermark(self, experiment_id: str) -> datetime | None: ...

    def seen_event_ids(self, event_ids: tuple[str, ...]) -> set[str]: ...

    def portfolios(self, experiment_id: str) -> tuple[ContinuousPortfolio, ...]: ...

    def attributions(self, experiment_id: str) -> tuple[FollowerAttribution, ...]: ...

    def start_poll(
        self,
        *,
        experiment_id: str,
        selection_run_id: str,
        window_start: datetime,
        window_end: datetime,
        started_at: datetime,
        candidate_count: int,
    ) -> str: ...

    def complete_poll(
        self,
        poll_run_id: str,
        *,
        experiment: ContinuousShadowExperiment,
        selection_run_id: str,
        current_candidates: tuple[ProtectedShadowCandidate, ...],
        completion: ContinuousPollCompletion,
        completed_at: datetime,
    ) -> ContinuousPollOutcome: ...

    def fail_poll(
        self,
        poll_run_id: str,
        *,
        failed_at: datetime,
        error_code: str,
    ) -> None: ...

    def health(
        self,
        source_id: str,
        *,
        now: datetime,
        poll_interval_seconds: int,
    ) -> ContinuousShadowHealth: ...

    def results(self, experiment_id: str, *, limit: int) -> dict[str, object]: ...


class ContinuousMarketReadPort(Protocol):
    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot: ...

    async def get_market_by_condition_id(self, condition_id: str) -> MarketDetails: ...


class ContinuousCandidatePort(Protocol):
    def current_candidates(
        self,
        source_id: str,
    ) -> tuple[str, tuple[ProtectedShadowCandidate, ...]]: ...


__all__ = [
    "ContinuousCandidatePort",
    "ContinuousEvaluationRecord",
    "ContinuousLedgerRecord",
    "ContinuousMarketReadPort",
    "ContinuousPollCompletion",
    "ContinuousPollOutcome",
    "ContinuousPositionMark",
    "ContinuousShadowExperiment",
    "ContinuousShadowHealth",
    "ContinuousShadowStorePort",
    "FollowerAttribution",
]
