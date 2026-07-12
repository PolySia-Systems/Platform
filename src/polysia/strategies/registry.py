from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from polysia.domain.strategy import (
    StrategyDefinition,
    StrategyLifecycleStatus,
    StrategyPerformanceSummary,
    StrategyRun,
)


class StrategyRegistryError(RuntimeError):
    """Raised when registry identity or lifecycle invariants are violated."""


class StrategyRegistryStore(Protocol):
    def add_definition(self, definition: StrategyDefinition) -> None: ...

    def get_definition(self, strategy_id: str, version: str) -> StrategyDefinition | None: ...

    def list_definitions(self) -> list[StrategyDefinition]: ...

    def update_lifecycle(
        self,
        strategy_id: str,
        version: str,
        status: StrategyLifecycleStatus,
    ) -> StrategyDefinition: ...

    def add_run(self, run: StrategyRun) -> None: ...

    def list_runs(self, strategy_id: str, version: str) -> list[StrategyRun]: ...

    def upsert_performance(self, summary: StrategyPerformanceSummary) -> None: ...

    def get_performance(
        self,
        strategy_id: str,
        version: str,
    ) -> StrategyPerformanceSummary | None: ...


class StrategyRegistry:
    """Small reusable registry; it does not orchestrate or execute strategies."""

    def __init__(self, store: StrategyRegistryStore | None = None) -> None:
        self._store = store
        self._definitions: dict[tuple[str, str], StrategyDefinition] = {}
        self._runs: dict[tuple[str, str], list[StrategyRun]] = {}
        self._performance: dict[tuple[str, str], StrategyPerformanceSummary] = {}

    def register(self, definition: StrategyDefinition) -> StrategyDefinition:
        key = (definition.strategy_id, definition.version)
        if self.get(*key) is not None:
            raise StrategyRegistryError(
                f"strategy {definition.strategy_id}@{definition.version} is already registered"
            )
        if self._store is not None:
            self._store.add_definition(definition)
        self._definitions[key] = definition
        summary = StrategyPerformanceSummary(
            strategy_id=definition.strategy_id,
            strategy_version=definition.version,
        )
        self._performance[key] = summary
        if self._store is not None:
            self._store.upsert_performance(summary)
        return definition

    def get(self, strategy_id: str, version: str) -> StrategyDefinition | None:
        key = (strategy_id, version)
        definition = self._definitions.get(key)
        if definition is None and self._store is not None:
            definition = self._store.get_definition(strategy_id, version)
            if definition is not None:
                self._definitions[key] = definition
        return definition

    def list(self) -> tuple[StrategyDefinition, ...]:
        if self._store is not None:
            for definition in self._store.list_definitions():
                self._definitions[(definition.strategy_id, definition.version)] = definition
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: (item[0], item[1]))
        )

    def set_lifecycle(
        self,
        strategy_id: str,
        version: str,
        status: StrategyLifecycleStatus,
    ) -> StrategyDefinition:
        current = self.require(strategy_id, version)
        updated = current.model_copy(update={"lifecycle_status": status})
        if self._store is not None:
            updated = self._store.update_lifecycle(strategy_id, version, status)
        self._definitions[(strategy_id, version)] = updated
        return updated

    def record_run(self, run: StrategyRun) -> None:
        self.require(run.strategy_id, run.strategy_version)
        key = (run.strategy_id, run.strategy_version)
        if any(existing.run_id == run.run_id for existing in self.list_runs(*key)):
            raise StrategyRegistryError(f"strategy run {run.run_id} is already recorded")
        if self._store is not None:
            self._store.add_run(run)
        self._runs.setdefault(key, []).append(run)
        current = self.performance(*key)
        updated = current.model_copy(
            update={
                "fees": (current.fees or 0) + run.fees,
                "last_evaluation_date": run.ended_at or run.started_at,
                "run_count": current.run_count + 1,
                "trade_count": current.trade_count + len(run.fills),
            }
        )
        self._performance[key] = updated
        if self._store is not None:
            self._store.upsert_performance(updated)

    def list_runs(self, strategy_id: str, version: str) -> tuple[StrategyRun, ...]:
        self.require(strategy_id, version)
        key = (strategy_id, version)
        if self._store is not None:
            persisted = self._store.list_runs(strategy_id, version)
            self._runs[key] = persisted
        return tuple(self._runs.get(key, ()))

    def performance(
        self,
        strategy_id: str,
        version: str,
    ) -> StrategyPerformanceSummary:
        self.require(strategy_id, version)
        key = (strategy_id, version)
        if self._store is not None:
            persisted = self._store.get_performance(strategy_id, version)
            if persisted is not None:
                self._performance[key] = persisted
        return self._performance.setdefault(
            key,
            StrategyPerformanceSummary(
                strategy_id=strategy_id,
                strategy_version=version,
            ),
        )

    def require(self, strategy_id: str, version: str) -> StrategyDefinition:
        definition = self.get(strategy_id, version)
        if definition is None:
            raise StrategyRegistryError(f"strategy {strategy_id}@{version} is not registered")
        return definition

    def load(self, definitions: Iterable[StrategyDefinition]) -> None:
        for definition in definitions:
            self._definitions[(definition.strategy_id, definition.version)] = definition


__all__ = ["StrategyRegistry", "StrategyRegistryError", "StrategyRegistryStore"]
