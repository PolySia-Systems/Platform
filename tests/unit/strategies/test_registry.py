from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from polysia.domain.strategy import StrategyLifecycleStatus, StrategyRun
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import StrategyRegistryRepository
from polysia.strategies.btc_15m_favorite_take_profit import (
    Btc15mFavoriteTakeProfitStrategy,
)
from polysia.strategies.registry import StrategyRegistry, StrategyRegistryError

NOW = datetime(2026, 7, 11, 12, tzinfo=UTC)


def test_registry_registers_stable_version_with_unrated_performance() -> None:
    registry = StrategyRegistry()
    definition = Btc15mFavoriteTakeProfitStrategy.definition(created_at=NOW)

    registry.register(definition)

    assert registry.get(definition.strategy_id, "0.6.0") == definition
    assert registry.list() == (definition,)
    assert registry.performance(definition.strategy_id, "0.6.0").score_status == "unrated"
    assert (
        registry.performance(definition.strategy_id, "0.6.0").evidence_sufficiency
        == "insufficient"
    )


def test_registry_prevents_duplicate_identity_and_tracks_lifecycle() -> None:
    registry = StrategyRegistry()
    definition = registry.register(
        Btc15mFavoriteTakeProfitStrategy.definition(created_at=NOW)
    )

    with pytest.raises(StrategyRegistryError, match="already registered"):
        registry.register(definition)

    updated = registry.set_lifecycle(
        definition.strategy_id,
        definition.version,
        StrategyLifecycleStatus.LIMITED_LIVE,
    )
    assert updated.lifecycle_status is StrategyLifecycleStatus.LIMITED_LIVE


def test_strategy_metadata_validation_rejects_empty_and_bad_version() -> None:
    definition = Btc15mFavoriteTakeProfitStrategy.definition(created_at=NOW)

    with pytest.raises(ValidationError):
        definition.model_copy(update={"name": ""}).model_validate(
            {**definition.model_dump(), "name": ""}
        )
    with pytest.raises(ValidationError):
        type(definition).model_validate({**definition.model_dump(), "version": "latest"})


def test_sqlite_registry_round_trips_definition_run_and_lifecycle(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"
    definition = Btc15mFavoriteTakeProfitStrategy.definition(created_at=NOW)
    run = StrategyRun(
        strategy_id=definition.strategy_id,
        strategy_version=definition.version,
        run_id="run-1",
        runtime_mode="limited_live",
        venue="polymarket",
        market="market-1",
        started_at=NOW,
        ended_at=NOW,
        fees=Decimal("0"),
        evidence_references=("report.json",),
    )

    with SQLiteDatabase(database_path) as database:
        registry = StrategyRegistry(StrategyRegistryRepository(database.connection))
        registry.register(definition)
        registry.record_run(run)
        registry.set_lifecycle(
            definition.strategy_id,
            definition.version,
            StrategyLifecycleStatus.PAPER,
        )

    with SQLiteDatabase(database_path) as database:
        registry = StrategyRegistry(StrategyRegistryRepository(database.connection))
        restored = registry.require(definition.strategy_id, definition.version)
        assert restored.lifecycle_status is StrategyLifecycleStatus.PAPER
        assert registry.list_runs(definition.strategy_id, definition.version) == (run,)
        assert registry.performance(definition.strategy_id, definition.version).run_count == 1
        performance = registry.performance(definition.strategy_id, definition.version)
        assert performance.score_status == "unrated"


def test_registry_rejects_duplicate_run_id() -> None:
    registry = StrategyRegistry()
    definition = registry.register(
        Btc15mFavoriteTakeProfitStrategy.definition(created_at=NOW)
    )
    run = StrategyRun(
        strategy_id=definition.strategy_id,
        strategy_version=definition.version,
        run_id="same-run",
        runtime_mode="paper",
        venue="polymarket",
        started_at=NOW,
    )
    registry.record_run(run)

    with pytest.raises(StrategyRegistryError, match="already recorded"):
        registry.record_run(run)
