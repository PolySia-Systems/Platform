from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from polysia.bus.events import MarketDataEvent
from polysia.control.models import (
    DesiredStateRevision,
    ObservedOperationalState,
    OperationalState,
    ReconciliationStatus,
    RuntimeObservation,
    StrategyControlKey,
)
from polysia.execution.intents import OrderIntent
from polysia.strategies.base import BaseStrategy, StrategyContext
from polysia.strategies.stale_price import StalePriceStrategy

Clock = Callable[[], datetime]
IdentifierFactory = Callable[[], str]

STALE_PRICE_SHADOW_TARGET = StrategyControlKey(
    strategy_id=StalePriceStrategy.strategy_id,
    strategy_version=StalePriceStrategy.strategy_version,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_identifier() -> str:
    return str(uuid4())


class ShadowIntentBoundary:
    """In-process gate immediately before a Shadow strategy can emit new intents."""

    def __init__(
        self,
        key: StrategyControlKey,
        *,
        clock: Clock = utc_now,
        identifier_factory: IdentifierFactory = new_identifier,
    ) -> None:
        if key != STALE_PRICE_SHADOW_TARGET:
            raise ValueError(f"unsupported Shadow control target: {key.scope}")
        self._key = key
        self._state = OperationalState.RUNNING
        self._revision = 0
        self._clock = clock
        self._identifier_factory = identifier_factory

    @property
    def state(self) -> OperationalState:
        return self._state

    @property
    def revision(self) -> int:
        return self._revision

    def reconcile(self, revision: DesiredStateRevision) -> RuntimeObservation:
        if revision.key != self._key:
            raise ValueError("desired state targets a different Shadow strategy")
        self._state = revision.desired_state
        self._revision = revision.revision
        return self.observe()

    def observe(self) -> RuntimeObservation:
        return RuntimeObservation(
            observation_id=self._identifier_factory(),
            key=self._key,
            desired_revision=self._revision,
            observed_state=ObservedOperationalState(self._state.value),
            reconciliation_status=ReconciliationStatus.SUCCESS,
            observed_at=self._clock(),
        )

    async def on_market_event(
        self,
        strategy: BaseStrategy,
        event: MarketDataEvent,
        context: StrategyContext,
    ) -> list[OrderIntent]:
        if strategy.strategy_id != self._key.strategy_id:
            raise ValueError("Shadow strategy does not match the controlled target")
        if getattr(strategy, "strategy_version", None) != self._key.strategy_version:
            raise ValueError("Shadow strategy version does not match the controlled target")
        if self._state is OperationalState.PAUSED:
            return []
        return await strategy.on_market_event(event, context)


__all__ = ["STALE_PRICE_SHADOW_TARGET", "ShadowIntentBoundary"]
