from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polysia.domain.copytrading.live_experiment import CopyExperimentState
from polysia.storage.copytrading import CopyExperimentRepository
from polysia.storage.db import SQLiteDatabase

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def _repository(tmp_path: object) -> tuple[SQLiteDatabase, CopyExperimentRepository]:
    database = SQLiteDatabase(tmp_path / "copy.sqlite3")  # type: ignore[operator]
    database.initialize()
    repository = CopyExperimentRepository(database.connection)
    repository.create(
        run_id="tiny-live-copy-test",
        authorization_id="authorization",
        started_at=NOW,
        signal_window_end=NOW + timedelta(hours=12),
        payload={},
    )
    repository.set_state(
        "tiny-live-copy-test",
        CopyExperimentState.MONITORING,
        updated_at=NOW,
    )
    return database, repository


def _claim(
    repository: CopyExperimentRepository,
    *,
    index: int,
    leader: str | None = None,
    entry_debit: Decimal = Decimal("2.25"),
) -> int | None:
    return repository.claim_entry_attempt(
        run_id="tiny-live-copy-test",
        leader_alias=leader or f"candidate-{index:03d}",
        event_id=f"event-{index}",
        market_id=f"market-{index}",
        market_slug=f"btc-updown-15m-{index:010d}",
        token_id=f"token-{index}",
        entry_price=Decimal("0.45"),
        entry_quantity=Decimal("5"),
        entry_debit=entry_debit,
        entry_fee=Decimal("0"),
        entry_cancel_at=NOW + timedelta(seconds=90),
        leader_latency_ms=1_000,
        leader_price_difference=Decimal("-0.05"),
        claimed_at=NOW + timedelta(seconds=index),
    )


def test_local_rejection_before_claim_consumes_no_attempt(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    try:
        assert repository.get("tiny-live-copy-test").total_entry_attempts == 0  # type: ignore[union-attr]
    finally:
        database.close()


def test_every_claim_consumes_once_and_used_leader_cannot_repeat(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    try:
        assert _claim(repository, index=1) == 1
        repository.record_entry_submission(
            run_id="tiny-live-copy-test",
            attempt_number=1,
            venue_order_id=None,
            state="REJECTED",
            updated_at=NOW + timedelta(seconds=2),
        )
        repository.record_no_fill(
            run_id="tiny-live-copy-test",
            attempt_number=1,
            updated_at=NOW + timedelta(seconds=3),
            signal_window_open=True,
        )
        assert _claim(repository, index=2, leader="candidate-001") is None
        assert _claim(repository, index=2) == 2
    finally:
        database.close()


def test_rejected_or_unknown_venue_submission_still_consumes_attempt(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    try:
        assert _claim(repository, index=1) == 1
        repository.record_entry_submission(
            run_id="tiny-live-copy-test",
            attempt_number=1,
            venue_order_id=None,
            state="SUBMISSION_REJECTED_OR_UNKNOWN",
            updated_at=NOW,
        )

        snapshot = repository.get("tiny-live-copy-test")
        assert snapshot is not None
        assert snapshot.total_entry_attempts == 1
        assert repository.attempts("tiny-live-copy-test")[0]["state"] == (
            "SUBMISSION_REJECTED_OR_UNKNOWN"
        )
    finally:
        database.close()


def test_three_unfilled_attempts_finalize_and_fourth_is_impossible(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    try:
        for index in range(1, 4):
            assert _claim(repository, index=index) == index
            repository.record_entry_submission(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                venue_order_id=f"order-{index}",
                state="ENTRY_PENDING",
                updated_at=NOW + timedelta(seconds=index),
            )
            snapshot = repository.record_no_fill(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                updated_at=NOW + timedelta(seconds=index + 10),
                signal_window_open=True,
            )
        assert snapshot.state is CopyExperimentState.FINALIZED
        assert snapshot.total_entry_attempts == 3
        assert snapshot.completed_live_cycles == 0
        assert _claim(repository, index=4) is None
    finally:
        database.close()


def test_cumulative_filled_entry_cost_is_atomic_and_capped_at_ten_usd(
    tmp_path,
) -> None:
    database, repository = _repository(tmp_path)
    try:
        for index in range(1, 3):
            assert _claim(repository, index=index, entry_debit=Decimal("5")) == index
            repository.record_entry_submission(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                venue_order_id=f"order-{index}",
                state="ENTRY_PENDING",
                updated_at=NOW,
            )
            repository.record_fill(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                position_size=Decimal("5"),
                fill_price=Decimal("0.9"),
                entry_fee=Decimal("0"),
                updated_at=NOW,
            )
            repository.complete_cycle(
                run_id="tiny-live-copy-test",
                updated_at=NOW,
                signal_window_open=True,
            )

        assert repository.cumulative_entry_cost("tiny-live-copy-test") == Decimal("9")
        assert _claim(
            repository,
            index=3,
            entry_debit=Decimal("1.01"),
        ) is None
        assert _claim(
            repository,
            index=3,
            entry_debit=Decimal("1"),
        ) == 3
    finally:
        database.close()


def test_active_third_attempt_is_managed_but_cannot_accept_another_signal(
    tmp_path,
) -> None:
    database, repository = _repository(tmp_path)
    try:
        for index in range(1, 3):
            assert _claim(repository, index=index) == index
            repository.record_entry_submission(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                venue_order_id=f"order-{index}",
                state="ENTRY_PENDING",
                updated_at=NOW,
            )
            repository.record_no_fill(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                updated_at=NOW,
                signal_window_open=True,
            )

        assert _claim(repository, index=3) == 3
        repository.record_entry_submission(
            run_id="tiny-live-copy-test",
            attempt_number=3,
            venue_order_id="order-3",
            state="ENTRY_PENDING",
            updated_at=NOW,
        )
        snapshot = repository.get("tiny-live-copy-test")
        assert snapshot is not None
        assert snapshot.state is CopyExperimentState.ENTRY_PENDING
        assert snapshot.entry_order_id == "order-3"
        assert snapshot.signal_acceptance_open is False
        assert _claim(repository, index=4) is None
    finally:
        database.close()


def test_three_filled_cycles_finalize_and_survive_the_cycle_cap(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    try:
        for index in range(1, 4):
            assert _claim(repository, index=index) == index
            repository.record_entry_submission(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                venue_order_id=f"entry-{index}",
                state="ENTRY_PENDING",
                updated_at=NOW,
            )
            repository.record_fill(
                run_id="tiny-live-copy-test",
                attempt_number=index,
                position_size=Decimal("5"),
                fill_price=Decimal("0.47"),
                entry_fee=Decimal("0"),
                updated_at=NOW,
            )
            snapshot = repository.complete_cycle(
                run_id="tiny-live-copy-test",
                updated_at=NOW,
                signal_window_open=True,
            )

        assert snapshot.completed_live_cycles == 3
        assert snapshot.state is CopyExperimentState.FINALIZED
        assert snapshot.signal_acceptance_open is False
    finally:
        database.close()


def test_partial_fill_uses_confirmed_position_and_one_related_exit(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    try:
        assert _claim(repository, index=1) == 1
        repository.record_entry_submission(
            run_id="tiny-live-copy-test",
            attempt_number=1,
            venue_order_id="entry",
            state="ENTRY_PENDING",
            updated_at=NOW,
        )
        snapshot = repository.record_fill(
            run_id="tiny-live-copy-test",
            attempt_number=1,
            position_size=Decimal("2.5"),
            fill_price=Decimal("0.47"),
            entry_fee=Decimal("0"),
            updated_at=NOW,
        )
        assert snapshot.position_size == Decimal("2.5")
        assert snapshot.entry_order_id is None
        repository.record_exit_order(
            run_id="tiny-live-copy-test",
            order_id="exit",
            exit_price=Decimal("0.52"),
            exit_fee=Decimal("0"),
            updated_at=NOW,
        )
        try:
            repository.record_exit_order(
                run_id="tiny-live-copy-test",
                order_id="second-exit",
                exit_price=Decimal("0.52"),
                exit_fee=Decimal("0"),
                updated_at=NOW,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("a second related exit order was accepted")
    finally:
        database.close()


def test_durable_attempt_and_cycle_counters_survive_reopen(tmp_path) -> None:
    path = tmp_path / "copy.sqlite3"
    database = SQLiteDatabase(path)
    database.initialize()
    repository = CopyExperimentRepository(database.connection)
    repository.create(
        run_id="tiny-live-copy-test",
        authorization_id="authorization",
        started_at=NOW,
        signal_window_end=NOW + timedelta(hours=12),
        payload={},
    )
    repository.set_state(
        "tiny-live-copy-test",
        CopyExperimentState.MONITORING,
        updated_at=NOW,
    )
    assert _claim(repository, index=1) == 1
    repository.record_entry_submission(
        run_id="tiny-live-copy-test",
        attempt_number=1,
        venue_order_id="entry",
        state="ENTRY_PENDING",
        updated_at=NOW,
    )
    repository.record_fill(
        run_id="tiny-live-copy-test",
        attempt_number=1,
        position_size=Decimal("5"),
        fill_price=Decimal("0.47"),
        entry_fee=Decimal("0"),
        updated_at=NOW,
    )
    repository.complete_cycle(
        run_id="tiny-live-copy-test",
        updated_at=NOW,
        signal_window_open=True,
    )
    database.close()

    with SQLiteDatabase(path) as reopened:
        snapshot = CopyExperimentRepository(reopened.connection).get(
            "tiny-live-copy-test"
        )
        assert snapshot is not None
        assert snapshot.total_entry_attempts == 1
        assert snapshot.completed_live_cycles == 1
        assert snapshot.state is CopyExperimentState.MONITORING
