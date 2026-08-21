from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.ports.cancellation import (
    CancellationResponse,
    OpenOrderEvidence,
    OrderDetailEvidence,
    OrderLookupStatus,
    OrderTradeEvidence,
)
from polysia.execution.cancellation_finality import (
    CancellationFinalityConfig,
    CancellationFinalityGate,
    CancellationFinalityOutcome,
    CancellationTarget,
    cancellation_operation_id,
)
from polysia.storage.db import SQLiteDatabase
from polysia.storage.repositories import LiveOrderCheckpointRepository

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)
ORDER_ID = "order-1"
TOKEN_ID = "token-1"
TARGET = CancellationTarget(
    order_id=ORDER_ID,
    token_id=TOKEN_ID,
    side="BUY",
    expected_size=Decimal("5"),
)


@dataclass(frozen=True, slots=True)
class Observation:
    open: bool = False
    detail_status: str | None = "CANCELED"
    matched_size: Decimal = Decimal("0")
    trade_size: Decimal = Decimal("0")
    trade_price: Decimal = Decimal("0.42")
    trade_status: str = "CONFIRMED"
    position: Decimal = Decimal("0")
    failing_endpoint: str | None = None
    side: str = "BUY"
    additional_open_order: bool = False


class EvidencePort:
    def __init__(self, observations: list[Observation]) -> None:
        self.observations = observations
        self.index = 0
        self.read_calls = 0

    @property
    def current(self) -> Observation:
        return self.observations[min(self.index, len(self.observations) - 1)]

    def _fail(self, endpoint: str) -> None:
        self.read_calls += 1
        if self.current.failing_endpoint == endpoint:
            raise RuntimeError(f"{endpoint} unavailable")

    async def observe_open_orders(
        self,
        *,
        order_id: str | None = None,
    ) -> tuple[OpenOrderEvidence, ...]:
        self._fail("open_orders")
        if order_id not in {None, ORDER_ID}:
            return ()
        orders: list[OpenOrderEvidence] = []
        if self.current.open:
            orders.append(
                _order(
                status="LIVE",
                matched_size=self.current.matched_size,
                side=self.current.side,
                )
            )
        if self.current.additional_open_order and order_id is None:
            orders.append(
                OpenOrderEvidence(
                    order_id="unexpected-order",
                    token_id="unexpected-token",
                    side="BUY",
                    status="LIVE",
                    original_size=Decimal("1"),
                    matched_size=Decimal("0"),
                )
            )
        return tuple(orders)

    async def observe_order_detail(self, *, order_id: str) -> OrderDetailEvidence:
        self._fail("order_detail")
        assert order_id == ORDER_ID
        if self.current.detail_status is None:
            return OrderDetailEvidence(status=OrderLookupStatus.NOT_FOUND)
        return OrderDetailEvidence(
            status=OrderLookupStatus.FOUND,
            order=_order(
                status=self.current.detail_status,
                matched_size=self.current.matched_size,
                side=self.current.side,
            ),
        )

    async def observe_order_trades(
        self,
        *,
        order_id: str,
        token_id: str,
    ) -> tuple[OrderTradeEvidence, ...]:
        self._fail("order_trades")
        assert (order_id, token_id) == (ORDER_ID, TOKEN_ID)
        if self.current.trade_size == 0:
            return ()
        return (
            OrderTradeEvidence(
                evidence_id="trade-1:taker",
                order_id=ORDER_ID,
                token_id=TOKEN_ID,
                status=self.current.trade_status,
                size=self.current.trade_size,
                price=self.current.trade_price,
            ),
        )

    async def observe_position_size(self, *, token_id: str) -> Decimal:
        try:
            self._fail("position")
            assert token_id == TOKEN_ID
            return self.current.position
        finally:
            self.index += 1


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class SimulatedCrash(BaseException):
    pass


def _order(*, status: str, matched_size: Decimal, side: str = "BUY") -> OpenOrderEvidence:
    return OpenOrderEvidence(
        order_id=ORDER_ID,
        token_id=TOKEN_ID,
        side=side,  # type: ignore[arg-type]
        status=status,
        original_size=Decimal("5"),
        matched_size=matched_size,
    )


async def _run(
    tmp_path: Path,
    observations: list[Observation],
    *,
    response: CancellationResponse | None = None,
    config: CancellationFinalityConfig | None = None,
    target: CancellationTarget = TARGET,
    position_baseline: Decimal = Decimal("0"),
    account_wide: bool = False,
) -> tuple[object, int, list[dict[str, object]], EvidencePort]:
    mutation_calls = 0
    evidence = EvidencePort(observations)
    clock = MutableClock()

    async def mutate() -> CancellationResponse:
        nonlocal mutation_calls
        mutation_calls += 1
        return response or CancellationResponse((ORDER_ID,), {})

    with SQLiteDatabase(tmp_path / "state.sqlite3") as database:
        checkpoints = LiveOrderCheckpointRepository(database.connection)
        result = await CancellationFinalityGate(
            evidence_port=evidence,
            checkpoints=checkpoints,
            run_id="run-1",
            clock=clock,
            sleeper=clock.sleep,
            config=config,
        ).run(
            operation_id="cancel-operation-1",
            targets=(target,),
            position_baselines={TOKEN_ID: position_baseline},
            mutation=mutate,
            account_wide=account_wide,
        )
        stored = checkpoints.list_for_run("run-1")
    return result, mutation_calls, stored, evidence


@pytest.mark.asyncio
async def test_immediate_cancellation_requires_two_clean_observations(tmp_path: Path) -> None:
    result, mutation_calls, stored, _ = await _run(
        tmp_path,
        [Observation(), Observation()],
    )

    assert result.outcome is CancellationFinalityOutcome.CONFIRMED_NO_FILL
    assert result.observation_count == 2
    assert mutation_calls == 1
    payload = stored[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["send_attempt_state"] == "RESPONSE_RECEIVED"
    assert payload["outcome"] == "CONFIRMED_NO_FILL"
    assert len(payload["observation_attempts"]) == 2


@pytest.mark.asyncio
async def test_propagation_delay_must_clear_before_two_clean_observations(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [Observation(open=True, detail_status="LIVE"), Observation(), Observation()],
    )

    assert result.outcome is CancellationFinalityOutcome.CONFIRMED_NO_FILL
    assert result.observation_count == 3


@pytest.mark.asyncio
async def test_persistently_open_order_remains_fail_safe(tmp_path: Path) -> None:
    result, mutation_calls, _, _ = await _run(
        tmp_path,
        [Observation(open=True, detail_status="LIVE")],
    )

    assert result.outcome is CancellationFinalityOutcome.STILL_OPEN
    assert mutation_calls == 1


@pytest.mark.asyncio
async def test_account_wide_finality_detects_a_new_unexpected_open_order(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [Observation(additional_open_order=True)],
        account_wide=True,
    )

    assert result.outcome is CancellationFinalityOutcome.STILL_OPEN


@pytest.mark.asyncio
async def test_not_canceled_response_cannot_confirm_no_fill(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [Observation(), Observation()],
        response=CancellationResponse((), {ORDER_ID: "not canceled"}),
    )

    assert result.outcome is CancellationFinalityOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_delayed_full_fill_wins_over_prior_clean_observation(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [
            Observation(detail_status=None),
            Observation(
                detail_status="MATCHED",
                matched_size=Decimal("5"),
                trade_size=Decimal("5"),
                position=Decimal("5"),
            ),
        ],
    )

    assert result.outcome is CancellationFinalityOutcome.FULL_FILL_DETECTED
    assert result.fill_size == Decimal("5")
    assert result.fill_price == Decimal("0.42")


@pytest.mark.asyncio
async def test_partial_fill_with_canceled_remainder_is_detected(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [
            Observation(
                matched_size=Decimal("2"),
                trade_size=Decimal("2"),
                position=Decimal("2"),
            )
        ],
    )

    assert result.outcome is CancellationFinalityOutcome.PARTIAL_FILL_DETECTED
    assert result.fill_size == Decimal("2")


@pytest.mark.asyncio
async def test_full_sell_fill_uses_decreasing_position_evidence(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [
            Observation(
                detail_status="MATCHED",
                matched_size=Decimal("5"),
                trade_size=Decimal("5"),
                position=Decimal("0"),
                side="SELL",
            )
        ],
        target=CancellationTarget(
            order_id=ORDER_ID,
            token_id=TOKEN_ID,
            side="SELL",
            expected_size=Decimal("5"),
        ),
        position_baseline=Decimal("5"),
    )

    assert result.outcome is CancellationFinalityOutcome.FULL_FILL_DETECTED


@pytest.mark.asyncio
async def test_nonterminal_mined_trade_remains_unknown(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [
            Observation(
                matched_size=Decimal("2"),
                trade_size=Decimal("2"),
                trade_status="MINED",
                position=Decimal("2"),
            )
        ],
    )

    assert result.outcome is CancellationFinalityOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_verified_404_with_independent_clean_evidence_is_confirmed(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [Observation(detail_status=None), Observation(detail_status=None)],
    )

    assert result.outcome is CancellationFinalityOutcome.CONFIRMED_NO_FILL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failing_endpoint",
    ["open_orders", "order_detail", "order_trades", "position"],
)
async def test_required_evidence_endpoint_failure_is_unknown(
    tmp_path: Path,
    failing_endpoint: str,
) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [Observation(failing_endpoint=failing_endpoint)],
    )

    assert result.outcome is CancellationFinalityOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_contradictory_trade_and_position_evidence_is_unknown(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [
            Observation(
                matched_size=Decimal("2"),
                trade_size=Decimal("1"),
                position=Decimal("2"),
            )
        ],
    )

    assert result.outcome is CancellationFinalityOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_unknown(tmp_path: Path) -> None:
    result, _, _, _ = await _run(
        tmp_path,
        [Observation()],
        config=CancellationFinalityConfig(
            maximum_observations=4,
            observation_interval_seconds=1,
            timeout_seconds=0.5,
            required_clean_observations=2,
        ),
    )

    assert result.outcome is CancellationFinalityOutcome.UNKNOWN
    assert result.observation_count == 1
    assert "timeout" in result.reason


@pytest.mark.asyncio
async def test_restart_before_external_call_never_resends(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    operation_id = cancellation_operation_id("run-1", "entry", (ORDER_ID,))
    first_evidence = EvidencePort([Observation(open=True, detail_status="LIVE")])
    clock = MutableClock()

    async def crash_before_external_call() -> CancellationResponse:
        raise SimulatedCrash

    with SQLiteDatabase(database_path) as database:
        checkpoints = LiveOrderCheckpointRepository(database.connection)
        gate = CancellationFinalityGate(
            evidence_port=first_evidence,
            checkpoints=checkpoints,
            run_id="run-1",
            clock=clock,
            sleeper=clock.sleep,
        )
        with pytest.raises(SimulatedCrash):
            await gate.run(
                operation_id=operation_id,
                targets=(TARGET,),
                position_baselines={TOKEN_ID: Decimal("0")},
                mutation=crash_before_external_call,
            )

    resend_calls = 0

    async def resend() -> CancellationResponse:
        nonlocal resend_calls
        resend_calls += 1
        return CancellationResponse((ORDER_ID,), {})

    with SQLiteDatabase(database_path) as database:
        result = await CancellationFinalityGate(
            evidence_port=EvidencePort([Observation(open=True, detail_status="LIVE")]),
            checkpoints=LiveOrderCheckpointRepository(database.connection),
            run_id="run-1",
            clock=clock,
            sleeper=clock.sleep,
        ).run(
            operation_id=operation_id,
            targets=(TARGET,),
            position_baselines={TOKEN_ID: Decimal("0")},
            mutation=resend,
        )

    assert resend_calls == 0
    assert result.outcome is CancellationFinalityOutcome.STILL_OPEN


@pytest.mark.asyncio
async def test_restart_after_cancellation_may_have_been_sent_stays_read_only_and_unknown(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    operation_id = "cancel-operation-restart"
    clock = MutableClock()
    external_calls = 0

    async def mutate_then_crash() -> CancellationResponse:
        nonlocal external_calls
        external_calls += 1
        raise SimulatedCrash

    with SQLiteDatabase(database_path) as database, pytest.raises(SimulatedCrash):
        await CancellationFinalityGate(
            evidence_port=EvidencePort([Observation()]),
            checkpoints=LiveOrderCheckpointRepository(database.connection),
            run_id="run-1",
            clock=clock,
            sleeper=clock.sleep,
        ).run(
            operation_id=operation_id,
            targets=(TARGET,),
            position_baselines={TOKEN_ID: Decimal("0")},
            mutation=mutate_then_crash,
        )

    async def forbidden_resend() -> CancellationResponse:
        nonlocal external_calls
        external_calls += 1
        return CancellationResponse((ORDER_ID,), {})

    evidence = EvidencePort([Observation(), Observation()])
    with SQLiteDatabase(database_path) as database:
        checkpoints = LiveOrderCheckpointRepository(database.connection)
        gate = CancellationFinalityGate(
            evidence_port=evidence,
            checkpoints=checkpoints,
            run_id="run-1",
            clock=clock,
            sleeper=clock.sleep,
        )
        first = await gate.run(
            operation_id=operation_id,
            targets=(TARGET,),
            position_baselines={TOKEN_ID: Decimal("0")},
            mutation=forbidden_resend,
        )
        reads_after_first = evidence.read_calls
        second = await gate.run(
            operation_id=operation_id,
            targets=(TARGET,),
            position_baselines={TOKEN_ID: Decimal("0")},
            mutation=forbidden_resend,
        )

    assert external_calls == 1
    assert first.outcome is CancellationFinalityOutcome.UNKNOWN
    assert second.outcome is CancellationFinalityOutcome.UNKNOWN
    assert evidence.read_calls > reads_after_first


@pytest.mark.asyncio
async def test_terminal_retry_reuses_evidence_without_reads_or_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    clock = MutableClock()
    evidence = EvidencePort([Observation(), Observation()])
    mutation_calls = 0

    async def mutate() -> CancellationResponse:
        nonlocal mutation_calls
        mutation_calls += 1
        return CancellationResponse((ORDER_ID,), {})

    with SQLiteDatabase(database_path) as database:
        gate = CancellationFinalityGate(
            evidence_port=evidence,
            checkpoints=LiveOrderCheckpointRepository(database.connection),
            run_id="run-1",
            clock=clock,
            sleeper=clock.sleep,
        )
        first = await gate.run(
            operation_id="terminal-retry",
            targets=(TARGET,),
            position_baselines={TOKEN_ID: Decimal("0")},
            mutation=mutate,
        )
        reads_after_first = evidence.read_calls
        second = await gate.run(
            operation_id="terminal-retry",
            targets=(TARGET,),
            position_baselines={TOKEN_ID: Decimal("0")},
            mutation=mutate,
        )

    assert first.outcome is CancellationFinalityOutcome.CONFIRMED_NO_FILL
    assert second == first
    assert mutation_calls == 1
    assert evidence.read_calls == reads_after_first
