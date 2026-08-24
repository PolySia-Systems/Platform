from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from polysia.application.ports.copytrading import LeaderTradeSourcePort
from polysia.domain.copytrading.dynamic_shadow import (
    DynamicShadowMode,
    ShadowEventEvaluation,
    ShadowWalletSummary,
)
from polysia.domain.market import MarketOrderBookSnapshot
from polysia.domain.wallet_intelligence import CandidatePipelineLease


@dataclass(frozen=True, slots=True)
class ProtectedShadowCandidate:
    wallet_id: str
    address: str = field(repr=False)
    pools: tuple[str, ...] = ()
    alpha_rank: int | None = None
    stress_rank: int | None = None


@dataclass(frozen=True, slots=True)
class DynamicShadowRunRecord:
    run_id: str
    source_id: str
    selection_run_id: str
    mode: DynamicShadowMode
    policy_version: str
    cost_model_version: str
    window_start: datetime
    window_end: datetime
    started_at: datetime
    completed_at: datetime | None
    status: str
    candidate_count: int
    event_count: int
    simulated_count: int
    unknown_count: int
    rejected_count: int
    realized_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    last_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class DynamicShadowHealth:
    current_run: DynamicShadowRunRecord | None
    last_run: DynamicShadowRunRecord | None
    level: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DynamicShadowWalletResult:
    run_id: str
    wallet_id: str
    mode: DynamicShadowMode
    pools: tuple[str, ...]
    alpha_rank: int | None
    stress_rank: int | None
    event_count: int
    simulated_count: int
    unknown_count: int
    rejected_count: int
    buy_count: int
    sell_count: int
    realized_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    open_notional: Decimal
    policy_version: str
    cost_model_version: str
    window_start: datetime
    window_end: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha_rank": self.alpha_rank,
            "buy_count": self.buy_count,
            "cost_model_version": self.cost_model_version,
            "event_count": self.event_count,
            "fees": format(self.fees, "f"),
            "mode": self.mode.value,
            "open_notional": format(self.open_notional, "f"),
            "policy_version": self.policy_version,
            "pools": list(self.pools),
            "realized_pnl": format(self.realized_pnl, "f"),
            "rejected_count": self.rejected_count,
            "run_id": self.run_id,
            "sell_count": self.sell_count,
            "simulated_count": self.simulated_count,
            "slippage": format(self.slippage, "f"),
            "stress_rank": self.stress_rank,
            "unknown_count": self.unknown_count,
            "wallet_id": self.wallet_id,
            "window_end": self.window_end.isoformat(),
            "window_start": self.window_start.isoformat(),
        }


class DynamicShadowStorePort(Protocol):
    def initialize(self) -> None: ...

    def current_candidates(
        self,
        source_id: str,
    ) -> tuple[str, tuple[ProtectedShadowCandidate, ...]]: ...

    def current_run(
        self,
        source_id: str,
        *,
        mode: DynamicShadowMode,
    ) -> DynamicShadowRunRecord | None: ...

    def current_wallet_results(
        self,
        source_id: str,
        *,
        mode: DynamicShadowMode,
        limit: int = 100,
    ) -> tuple[DynamicShadowWalletResult, ...]: ...

    def successful_run(
        self,
        *,
        selection_run_id: str,
        mode: DynamicShadowMode,
        policy_version: str,
        cost_model_version: str,
        window_start: datetime,
        window_end: datetime,
    ) -> DynamicShadowRunRecord | None: ...

    def start_run(
        self,
        *,
        source_id: str,
        selection_run_id: str,
        mode: DynamicShadowMode,
        policy_version: str,
        cost_model_version: str,
        window_start: datetime,
        window_end: datetime,
        started_at: datetime,
        candidate_count: int,
    ) -> str: ...

    def complete_run(
        self,
        run_id: str,
        *,
        candidates: tuple[ProtectedShadowCandidate, ...],
        evaluations: tuple[ShadowEventEvaluation, ...],
        summaries: tuple[ShadowWalletSummary, ...],
        completed_at: datetime,
    ) -> DynamicShadowRunRecord: ...

    def fail_run(
        self,
        run_id: str,
        *,
        failed_at: datetime,
        error_code: str,
    ) -> None: ...

    def health(self, source_id: str, *, now: datetime) -> DynamicShadowHealth: ...


class DynamicShadowLeasePort(Protocol):
    def initialize(self) -> None: ...

    def acquire_lease(
        self,
        resource: str,
        *,
        owner_id: str,
        acquired_at: datetime,
        lease_duration: timedelta,
    ) -> CandidatePipelineLease: ...

    def renew_lease(
        self,
        lease: CandidatePipelineLease,
        *,
        renewed_at: datetime,
        lease_duration: timedelta,
    ) -> CandidatePipelineLease: ...

    def release_lease(self, lease: CandidatePipelineLease) -> None: ...


class ShadowQuotePort(Protocol):
    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot: ...


class LeaderSourceFactory(Protocol):
    def __call__(self, leaders: Mapping[str, str]) -> LeaderTradeSourcePort: ...


class DynamicShadowTelemetryPort(Protocol):
    def request_telemetry(self) -> dict[str, object]: ...

    def trades_circuit(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class DynamicShadowOutcome:
    run: DynamicShadowRunRecord
    idempotent_replay: bool
    candidate_count: int
    alpha_count: int
    stress_count: int
    overlap_count: int
    event_count: int
    simulated_count: int
    unknown_count: int
    rejected_count: int
    realized_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    request_telemetry: dict[str, object]
    trades_circuit: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha_count": self.alpha_count,
            "candidate_count": self.candidate_count,
            "cost_model_version": self.run.cost_model_version,
            "event_count": self.event_count,
            "fees": format(self.fees, "f"),
            "idempotent_replay": self.idempotent_replay,
            "mode": self.run.mode.value,
            "overlap_count": self.overlap_count,
            "policy_version": self.run.policy_version,
            "realized_pnl": format(self.realized_pnl, "f"),
            "rejected_count": self.rejected_count,
            "request_telemetry": self.request_telemetry,
            "run_id": self.run.run_id,
            "selection_run_id": self.run.selection_run_id,
            "simulated_count": self.simulated_count,
            "slippage": format(self.slippage, "f"),
            "status": self.run.status,
            "stress_count": self.stress_count,
            "unknown_count": self.unknown_count,
            "trades_circuit": self.trades_circuit,
            "window_end": self.run.window_end.isoformat(),
            "window_start": self.run.window_start.isoformat(),
        }
