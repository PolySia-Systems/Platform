from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polysia.application.ports.copytrading import LeaderMarketMetadata
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    LeaderTradeEvent,
)
from polysia.execution.tiny_live_copy import (
    _event_from_pending_payload,
    _event_to_pending_payload,
    _ObservedLeaderEvent,
    _ordered_discovery_aliases,
)
from polysia.storage.copytrading import CopyExperimentRepository
from polysia.storage.db import SQLiteDatabase

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def _aliases() -> tuple[str, ...]:
    return tuple(f"candidate-{index:03d}" for index in range(1, 103))


def _create_run(repository: CopyExperimentRepository, run_id: str) -> None:
    repository.create(
        run_id=run_id,
        authorization_id=f"authorization-{run_id}",
        started_at=NOW,
        signal_window_end=NOW + timedelta(hours=12),
        payload={},
    )


def test_priority_order_and_rotations_cover_all_102_with_exact_active_window(
    tmp_path: Path,
) -> None:
    aliases = _aliases()
    ordered = _ordered_discovery_aliases(
        aliases,
        priority_aliases=("candidate-098", "candidate-027", "candidate-043"),
    )
    assert ordered[:3] == (
        "candidate-027",
        "candidate-043",
        "candidate-098",
    )
    database_path = tmp_path / "state.sqlite3"

    with SQLiteDatabase(database_path) as database:
        repository = CopyExperimentRepository(database.connection)
        _create_run(repository, "run-rotation")
        initial = repository.initialize_discovery(
            run_id="run-rotation",
            ordered_aliases=ordered,
            initialized_at=NOW,
        )
        first = repository.rotate_discovery(
            run_id="run-rotation",
            rotated_at=NOW + timedelta(minutes=30),
        )
        second = repository.rotate_discovery(
            run_id="run-rotation",
            rotated_at=NOW + timedelta(minutes=60),
        )

        assert [initial.cursor, first.cursor, second.cursor] == [0, 34, 68]
        assert all(len(state.active_aliases) == 48 for state in (initial, first, second))
        assert (
            len(
                set(initial.active_aliases) | set(first.active_aliases) | set(second.active_aliases)
            )
            == 102
        )
        assert (
            len(
                {
                    initial.subset_digest,
                    first.subset_digest,
                    second.subset_digest,
                }
            )
            == 3
        )

    with SQLiteDatabase(database_path) as database:
        restored = CopyExperimentRepository(database.connection).discovery_state("run-rotation")
        assert restored.cursor == 68
        assert restored.active_aliases == second.active_aliases


def test_cooldown_and_per_alias_checkpoint_survive_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    aliases = _aliases()
    next_probe = NOW + timedelta(seconds=12)

    with SQLiteDatabase(database_path) as database:
        repository = CopyExperimentRepository(database.connection)
        _create_run(repository, "run-checkpoint")
        repository.initialize_discovery(
            run_id="run-checkpoint",
            ordered_aliases=aliases,
            initialized_at=NOW,
        )
        repository.set_discovery_cooldown(
            run_id="run-checkpoint",
            outage_started_at=NOW,
            next_probe_at=next_probe,
            cooldown_attempt=2,
            updated_at=NOW,
        )
        repository.save_read_checkpoint(
            run_id="run-checkpoint",
            leader_alias="candidate-001",
            window_start=NOW - timedelta(seconds=20),
            window_end=NOW,
            checkpoint_value="v1:checkpoint",
            last_successful_at=NOW - timedelta(seconds=6),
            updated_at=NOW,
        )
        repository.stage_read_page(
            run_id="run-checkpoint",
            leader_alias="candidate-001",
            window_start=NOW - timedelta(seconds=20),
            window_end=NOW,
            checkpoint_value="v1:checkpoint",
            last_successful_at=NOW - timedelta(seconds=6),
            event_payloads=(
                {
                    "event_id": "event-1",
                    "leader_id": "candidate-001",
                },
            ),
            staged_at=NOW,
        )

    with SQLiteDatabase(database_path) as database:
        repository = CopyExperimentRepository(database.connection)
        discovery = repository.discovery_state("run-checkpoint")
        checkpoint = repository.read_checkpoint(
            run_id="run-checkpoint",
            leader_alias="candidate-001",
        )
        assert discovery.outage_started_at == NOW
        assert discovery.next_probe_at == next_probe
        assert discovery.cooldown_attempt == 2
        assert checkpoint is not None
        assert checkpoint.checkpoint_value == "v1:checkpoint"
        assert checkpoint.last_successful_at == NOW - timedelta(seconds=6)
        assert repository.pending_read_events(
            run_id="run-checkpoint",
            leader_alias="candidate-001",
        ) == (
            {
                "event_id": "event-1",
                "leader_id": "candidate-001",
            },
        )
        assert repository.apply_event_if_unseen(
            run_id="run-checkpoint",
            event_id="event-1",
            leader_alias="candidate-001",
            observed_at=NOW,
            market_reference="market-1",
            outcome_reference="token-1",
            next_size=Decimal("5"),
        )
        assert not repository.apply_event_if_unseen(
            run_id="run-checkpoint",
            event_id="event-1",
            leader_alias="candidate-001",
            observed_at=NOW,
            market_reference="market-1",
            outcome_reference="token-1",
            next_size=Decimal("10"),
        )
        assert repository.inventory(
            run_id="run-checkpoint",
            leader_alias="candidate-001",
            market_reference="market-1",
            outcome_reference="token-1",
        ) == Decimal("5")
        repository.clear_pending_read_events(
            run_id="run-checkpoint",
            event_ids=("event-1",),
        )
        assert (
            repository.pending_read_events(
                run_id="run-checkpoint",
                leader_alias="candidate-001",
            )
            == ()
        )


def test_pending_event_preserves_verified_market_metadata_across_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    event = LeaderTradeEvent(
        event_id="event-safe-digest",
        source_id="polymarket:data-api",
        leader_id="candidate-001",
        market_reference="market-1",
        outcome_reference="token-1",
        trade_action=LeaderTradeAction.BUY,
        position_effect=LeaderPositionEffect.UNKNOWN,
        executed_price=Decimal("0.51"),
        executed_size=Decimal("2"),
        executed_at=NOW - timedelta(seconds=2),
        observed_at=NOW,
        external_evidence_reference="sha256:safe-evidence-digest",
    )
    observed = _ObservedLeaderEvent(
        event=event,
        metadata=LeaderMarketMetadata(
            market_reference="market-1",
            outcome_reference="token-1",
            external_slug="btc-updown-15m-1785326400",
            outcome_label="Up",
            starts_at=NOW,
            ends_at=NOW + timedelta(minutes=15),
        ),
    )

    with SQLiteDatabase(database_path) as database:
        repository = CopyExperimentRepository(database.connection)
        _create_run(repository, "run-pending-metadata")
        repository.stage_read_page(
            run_id="run-pending-metadata",
            leader_alias="candidate-001",
            window_start=NOW - timedelta(seconds=20),
            window_end=NOW,
            checkpoint_value="v1:checkpoint",
            last_successful_at=None,
            event_payloads=(_event_to_pending_payload(observed),),
            staged_at=NOW,
        )

    with SQLiteDatabase(database_path) as database:
        payload = CopyExperimentRepository(database.connection).pending_read_events(
            run_id="run-pending-metadata",
            leader_alias="candidate-001",
        )[0]
        restored = _event_from_pending_payload(payload)

    assert restored == observed
    serialized = json.dumps(payload, sort_keys=True)
    assert "proxyWallet" not in serialized
    assert "transactionHash" not in serialized
