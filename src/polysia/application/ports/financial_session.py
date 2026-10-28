"""Trusted execution boundary; implementations retain venue eligibility gates."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from polysia.application.ports.cancellation import (
    CancellationEvidencePort,
    OpenOrderEvidence,
    OrderDetailEvidence,
    OrderTradeEvidence,
)
from polysia.domain.financial_session import (
    AccountObservation,
    ApprovedSessionLimit,
    InstrumentScope,
    SessionOpportunity,
)
from polysia.risk.evidence import VerifiedLiveRiskSnapshot


@dataclass(frozen=True, slots=True)
class RequestCharge:
    requests: int
    response_bytes: int
    source_cost: Decimal


@dataclass(frozen=True, slots=True)
class SessionSubmitReceipt:
    order_id: str | None
    definitively_rejected: bool
    evidence_id: str


class SessionExecutionPort(Protocol):
    def charge_bound(self, action: str) -> RequestCharge: ...

    async def observe_account(self, instrument: InstrumentScope) -> AccountObservation: ...

    async def submit(
        self,
        approved: ApprovedSessionLimit,
        opportunity: SessionOpportunity,
        snapshot: VerifiedLiveRiskSnapshot,
        *,
        before_submit: Callable[[], None],
        refresh: Callable[[], Awaitable[VerifiedLiveRiskSnapshot]],
        edge: Decimal,
    ) -> SessionSubmitReceipt: ...

    async def cancel(self, order_id: str, *, before_cancel: Callable[[], None]) -> None: ...


class BudgetedCancellationEvidence:
    """Reserve every finality read against the account-wide durable request budget."""

    def __init__(self, source: CancellationEvidencePort, reserve: Callable[[], None]) -> None:
        self.source, self.reserve = source, reserve

    async def observe_open_orders(
        self, *, order_id: str | None = None
    ) -> tuple[OpenOrderEvidence, ...]:
        self.reserve()
        return await self.source.observe_open_orders(order_id=order_id)

    async def observe_order_detail(self, *, order_id: str) -> OrderDetailEvidence:
        self.reserve()
        return await self.source.observe_order_detail(order_id=order_id)

    async def observe_order_trades(
        self,
        *,
        order_id: str,
        token_id: str,
    ) -> tuple[OrderTradeEvidence, ...]:
        self.reserve()
        return await self.source.observe_order_trades(order_id=order_id, token_id=token_id)

    async def observe_position_size(self, *, token_id: str) -> Decimal:
        self.reserve()
        return await self.source.observe_position_size(token_id=token_id)
