from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.domain.copytrading.signal_arbiter import (
    ClosedSignalOutcome,
    ConcentrationCause,
    ConcentrationEvent,
    FollowerExecutionOutcome,
    SignalContext,
)
from polysia.storage.copy_signal_arbiter import CopySignalArbiterRepository
from polysia.storage.db import SQLiteDatabase

NOW = datetime(2026, 8, 1, 10, tzinfo=UTC)
CONTEXT = SignalContext(market_type="btc-updown", timeframe_seconds=900)


def _wallet_outcome() -> ClosedSignalOutcome:
    return ClosedSignalOutcome(
        outcome_id="outcome-001",
        leader_key="candidate-001",
        context=CONTEXT,
        opened_at=NOW - timedelta(minutes=20),
        closed_at=NOW - timedelta(minutes=5),
        net_return=Decimal("0.10"),
        maximum_drawdown=Decimal("0.02"),
    )


def test_arbiter_evidence_is_idempotent_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "arbiter.sqlite3"
    database = SQLiteDatabase(path)
    database.initialize()
    repository = CopySignalArbiterRepository(database.connection)
    follower = FollowerExecutionOutcome(
        execution_id="execution-001",
        leader_key="candidate-001",
        context=CONTEXT,
        closed_at=NOW - timedelta(minutes=2),
        filled=True,
        net_pnl=Decimal("0.20"),
        execution_cost=Decimal("0.03"),
        slippage=Decimal("0.01"),
        completed_cycle=True,
    )
    concentration = ConcentrationEvent(
        event_id="cycle-001",
        leader_key="candidate-001",
        cause=ConcentrationCause.COMPLETED_CYCLE,
        occurred_at=NOW - timedelta(minutes=1),
    )

    assert repository.record_wallet_outcome_if_new(
        _wallet_outcome(), labeling_version="fixed-exit-v1", created_at=NOW
    )
    assert not repository.record_wallet_outcome_if_new(
        _wallet_outcome(), labeling_version="fixed-exit-v1", created_at=NOW
    )
    assert repository.record_follower_outcome_if_new(follower, created_at=NOW)
    assert not repository.record_follower_outcome_if_new(follower, created_at=NOW)
    assert repository.record_concentration_event_if_new(concentration, created_at=NOW)
    assert not repository.record_concentration_event_if_new(concentration, created_at=NOW)
    database.close()

    reopened = SQLiteDatabase(path)
    reopened.initialize()
    restored = CopySignalArbiterRepository(reopened.connection)
    try:
        assert restored.wallet_outcomes(labeling_version="fixed-exit-v1") == (
            _wallet_outcome(),
        )
        assert restored.follower_outcomes() == (follower,)
        assert restored.concentration_events() == (concentration,)
    finally:
        reopened.close()


def test_walk_forward_reads_exclude_future_closures(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "walk-forward.sqlite3")
    database.initialize()
    repository = CopySignalArbiterRepository(database.connection)
    future = ClosedSignalOutcome(
        outcome_id="outcome-future",
        leader_key="candidate-001",
        context=CONTEXT,
        opened_at=NOW,
        closed_at=NOW + timedelta(minutes=10),
        net_return=Decimal("1"),
        maximum_drawdown=Decimal("0"),
    )
    repository.record_wallet_outcome_if_new(
        _wallet_outcome(), labeling_version="fixed-exit-v1", created_at=NOW
    )
    repository.record_wallet_outcome_if_new(
        future, labeling_version="fixed-exit-v1", created_at=NOW
    )
    assert repository.record_wallet_outcome_if_new(
        _wallet_outcome(),
        labeling_version="different-label-v1",
        created_at=NOW,
    )
    try:
        assert repository.wallet_outcomes(
            labeling_version="fixed-exit-v1",
            closed_at_or_before=NOW,
        ) == (_wallet_outcome(),)
        assert repository.wallet_outcomes(
            labeling_version="different-label-v1",
            closed_at_or_before=NOW,
        ) == (_wallet_outcome(),)
    finally:
        database.close()


def test_labeling_version_rejects_wallet_like_values(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "protected-label.sqlite3")
    database.initialize()
    repository = CopySignalArbiterRepository(database.connection)
    try:
        with pytest.raises(ValueError, match="wallet address"):
            repository.record_wallet_outcome_if_new(
                _wallet_outcome(),
                labeling_version="0x1111111111111111111111111111111111111111",
                created_at=NOW,
            )
    finally:
        database.close()
