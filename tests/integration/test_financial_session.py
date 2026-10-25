"""Deterministic account lifecycle; no venue clients, credentials, or network."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.application.ports.financial_session import RequestCharge, SessionSubmitReceipt
from polysia.application.services.financial_session import (
    FinancialSessionCoordinator,
    session_ledger,
)
from polysia.config.settings import TradingMode
from polysia.domain.financial_session import (
    AccountObservation,
    ApprovedSessionLimit,
    ConfirmedSessionFill,
    InstrumentScope,
    RuntimeBinding,
    SessionAuthorization,
    SessionBlocked,
    SessionMode,
    SessionOpportunity,
    SourceOccurrence,
)
from polysia.risk.checks import RiskEngine
from polysia.risk.limits import RiskLimits
from polysia.storage.financial_session import FinancialSessionJournal

D = Decimal
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
SCOPE = InstrumentScope("market", "token", "collateral-v2", "route-v2")
BINDING = RuntimeBinding("release-sha", "config-sha", "policy-sha", "fixture-account", "host")


def authorization(**overrides: Any) -> SessionAuthorization:
    values = dict(
        version=1,
        run_id="fixture-run",
        owner_receipt="fictional-test-authority",
        granted=True,
        binding=BINDING,
        starts_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        protective_until=NOW + timedelta(hours=2),
        wallets=frozenset({"wallet"}),
        instruments=(SCOPE,),
        strategy="copy-v1",
        exit_policy="leader-reduction-v1",
        max_order_all_in=D("5"),
        max_open_exposure=D("10"),
        max_turnover=D("30"),
        max_total_loss=D("10"),
        max_daily_loss=D("10"),
        max_market_exposure=D("10"),
        max_wallet_exposure=D("10"),
        max_positions=1,
        max_concurrent_orders=2,
        max_attempts=10,
        fee_rate=D("0.01"),
        max_evidence_age_seconds=30,
        supervision_timeout_seconds=20,
        max_holding_seconds=600,
        dust_shares=D("0.001"),
        max_requests=100,
        protective_request_reserve=10,
        max_response_bytes=1000000,
        max_storage_bytes=10000000,
        max_source_cost=D("0"),
        restart_policy="RECONCILE",
        protective_actions=frozenset({"CANCEL", "REDUCE"}),
    )
    values.update(overrides)
    return SessionAuthorization(**values)


def opportunity(*, occurrence: str = "0", side: str = "BUY", **changes: Any) -> SessionOpportunity:
    event = SourceOccurrence(
        "chain",
        "transaction",
        occurrence,
        "wallet",
        SCOPE,
        side,
        NOW,
        NOW,
        NOW,
        "native",
        "native-event",
        "v2",
        True,
        True,
    )
    values = dict(
        event=event,
        strategy="copy-v1",
        exit_policy="leader-reduction-v1",
        price=D("0.5"),
        shares=D("2"),
        fair_price=D("0.7"),
        uncertainty=D("0.01"),
        cost_per_share=D("0.01"),
        entry_depth=D("10"),
        exit_depth=D("10"),
        market_observed_at=NOW,
        market_expires_at=NOW + timedelta(hours=3),
        venue_eligible=True,
        leader_reduction=side == "SELL",
        reason="fixture only",
        cohort_digest="fictional-fixture-cohort",
        qualification_evidence_id="fictional-fixture-outcomes",
    )
    values.update(changes)
    return SessionOpportunity(**values)


class FakeExecution:
    def __init__(self, now: Callable[[], datetime]) -> None:
        self.now = now
        self.cash = D("100")
        self.positions: dict[str, Decimal] = {}
        self.fees = D("0")
        self.open_orders: set[str] = set()
        self.submissions: list[ApprovedSessionLimit] = []
        self.cancel_calls: list[str] = []
        self.failure: str | None = None
        self.hook: Callable[[], None] | None = None
        self.wait: asyncio.Event | None = None

    def charge_bound(self, action: str) -> RequestCharge:
        return RequestCharge(1, 100, D("0"))

    def account(self) -> AccountObservation:
        return AccountObservation(
            BINDING.account,
            self.now(),
            self.cash,
            tuple(self.positions.items()),
            frozenset(self.open_orders),
            self.fees,
            True,
            "fixture-account-read",
        )

    async def observe_account(self, instrument: InstrumentScope) -> AccountObservation:
        if self.failure == "account":
            raise TimeoutError("fixture source outage")
        return self.account()

    async def submit(
        self,
        approved: ApprovedSessionLimit,
        opportunity: SessionOpportunity,
        snapshot: Any,
        *,
        before_submit: Callable[[], None],
        refresh: Any,
        edge: Decimal,
    ) -> SessionSubmitReceipt:
        if self.failure == "before":
            raise TimeoutError("before possible submit")
        if self.wait is not None:
            await self.wait.wait()
        await refresh()
        if self.hook:
            self.hook()
        before_submit()
        self.submissions.append(approved)
        if self.failure == "after":
            raise TimeoutError("after possible submit")
        if self.failure == "reject":
            return SessionSubmitReceipt(None, True, "definitive-venue-rejection")
        order_id = "order-" + str(len(self.submissions))
        self.open_orders.add(order_id)
        return SessionSubmitReceipt(order_id, False, "fixture-ack")

    async def cancel(self, order_id: str, *, before_cancel: Callable[[], None]) -> None:
        before_cancel()
        self.cancel_calls.append(order_id)


class Harness:
    def __init__(self, root: Path, auth: SessionAuthorization | None = None) -> None:
        self.now = NOW
        self.tick = 0
        self.auth = auth or authorization()
        self.execution = FakeExecution(lambda: self.now)
        self.journal = FinancialSessionJournal(
            root / "financial" / "session.sqlite3", root / "witness", self.auth
        )
        self.journal.provision(self.execution.account())
        self.journal.open()
        self.risk = RiskEngine(
            limits=RiskLimits(
                max_order_notional=D("100"),
                max_position_per_token=D("100"),
                max_position_per_market=D("100"),
                max_open_orders=10,
            )
        )
        self.coordinator = self.new_coordinator()
        self.start()

    def new_coordinator(self) -> FinancialSessionCoordinator:
        return FinancialSessionCoordinator(
            self.journal,
            self.execution,
            self.risk,
            binding=BINDING,
            clock=lambda: self.now,
            monotonic=lambda: self.tick,
            trading_mode=TradingMode.PAPER,
        )

    def start(self) -> None:
        self.coordinator.supervise(evidence_id="fixture-supervisor", healthy=True)
        assert self.coordinator.reconcile(self.execution.account())
        self.coordinator.set_mode(SessionMode.RUNNING)

    def fill(
        self,
        identity: str,
        *,
        size: str = "2",
        side: str = "BUY",
        price: str = "0.5",
        fee: str = "0.01",
        fill_id: str | None = None,
        terminal: bool = True,
    ) -> ConfirmedSessionFill:
        row = self.journal.read()["orders"][identity]
        quantity, value, charged = D(size), D(price), D(fee)
        self.execution.fees += charged
        sign = 1 if side == "BUY" else -1
        self.execution.cash -= sign * quantity * value + charged
        remaining = self.execution.positions.get("token", D("0")) + sign * quantity
        self.execution.positions = {} if remaining == 0 else {"token": remaining}
        if terminal:
            self.execution.open_orders.discard(row["order_id"])
        fill = ConfirmedSessionFill(
            fill_id or "fill-" + identity,
            identity,
            row["order_id"],
            "token",
            side,
            value,
            quantity,
            charged,
            self.now,
        )
        self.coordinator.apply_order_evidence(
            identity,
            order_id=row["order_id"],
            fills=(fill,),
            finality="CONFIRMED_FILL" if terminal else "OPEN",
            evidence_id="fixture-confirmed-trade",
            account=self.execution.account(),
        )
        return fill


@pytest.fixture
def h(tmp_path: Path) -> Iterator[Harness]:
    value = Harness(tmp_path)
    try:
        yield value
    finally:
        value.journal.close()


async def test_complete_entry_exit_with_actual_cashflows_and_fees_once(h: Harness) -> None:
    entry = await h.coordinator.submit(opportunity())
    h.fill(entry)
    exit_id = await h.coordinator.submit(opportunity(occurrence="1", side="SELL"))
    h.fill(exit_id, side="SELL")
    ledger = session_ledger(h.journal.read())
    assert ledger.cash == D("99.98")
    assert ledger.fees == D("0.02")
    assert ledger.realized_pnl == 0
    assert not ledger.positions
    assert h.journal.read()["orders"][exit_id]["state"] == "FINALIZED"
    assert h.journal.read()["attempts"] == 2


async def test_two_sources_one_occurrence_cannot_duplicate_but_distinct_logs_can(
    h: Harness,
) -> None:
    original = opportunity()
    first = await h.coordinator.submit(original)
    overlap = replace(original, event=replace(original.event, source="polycop", source_key="other"))
    assert await h.coordinator.submit(overlap) == first
    assert len(h.execution.submissions) == 1
    assert len(h.journal.read()["decisions"][first]["sources"]) == 2
    assert await h.coordinator.submit(opportunity(occurrence="different-log")) != first
    assert len(h.execution.submissions) == 2


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"fair_price": None}, "edge_or_cost_unknown"),
        ({"fair_price": D("0.4")}, "nonpositive_conservative_edge"),
        ({"cost_per_share": D("0")}, "unpriced_fees"),
        ({"exit_depth": D("1")}, "insufficient_entry_or_exit"),
        ({"venue_eligible": False}, "venue_or_source"),
        ({"market_observed_at": NOW - timedelta(seconds=31)}, "stale_or_future"),
        ({"market_observed_at": NOW + timedelta(seconds=1)}, "stale_or_future"),
        ({"market_expires_at": NOW}, "market_expired"),
        ({"shares": D("0.0001")}, "dust"),
    ],
)
async def test_invalid_evidence_rejected_before_submit(
    h: Harness, change: dict, reason: str
) -> None:
    with pytest.raises(SessionBlocked, match=reason):
        await h.coordinator.submit(opportunity(**change))
    assert not h.execution.submissions
    assert h.journal.read()["attempts"] == 0


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("occurrence", None, "ambiguous_occurrence"),
        ("wallet", "other", "outside_scope"),
        ("instrument", replace(SCOPE, settlement_route="legacy"), "outside_scope"),
        ("complete", False, "source_evidence_ineligible"),
        ("finalized", False, "source_evidence_ineligible"),
    ],
)
async def test_occurrence_mapping_gaps_and_reorg_uncertainty_block(
    h: Harness,
    field: str,
    value: Any,
    reason: str,
) -> None:
    candidate = opportunity()
    candidate = replace(candidate, event=replace(candidate.event, **{field: value}))
    with pytest.raises(SessionBlocked, match=reason):
        await h.coordinator.submit(candidate)
    assert not h.execution.submissions


async def test_unknown_submit_consumes_reservation_across_restart_no_resend(h: Harness) -> None:
    h.execution.failure = "after"
    with pytest.raises(TimeoutError):
        await h.coordinator.submit(opportunity())
    before = h.journal.read()
    identity = next(iter(before["orders"]))
    assert before["orders"][identity]["state"] == "UNCERTAIN_SUBMIT"
    assert before["orders"][identity]["reservation"] == "1.010"
    checkpoint = h.journal.checkpoint()
    h.journal.close()
    h.journal.open(checkpoint=checkpoint)
    h.coordinator = h.new_coordinator()
    assert await h.coordinator.submit(opportunity()) == identity
    assert h.journal.read()["attempts"] == 1
    assert len(h.execution.submissions) == 1
    with pytest.raises(SessionBlocked, match="supervision"):
        h.coordinator.set_mode(SessionMode.RUNNING)


async def test_failure_before_submit_and_definitive_rejection_never_refund_attempts(
    h: Harness,
) -> None:
    h.execution.failure = "before"
    with pytest.raises(TimeoutError):
        await h.coordinator.submit(opportunity())
    assert next(iter(h.journal.read()["orders"].values()))["state"] == "REJECTED"
    h.execution.failure = "reject"
    await h.coordinator.submit(opportunity(occurrence="second"))
    assert h.journal.read()["attempts"] == 2
    assert all(row["state"] == "REJECTED" for row in h.journal.read()["orders"].values())


async def test_partial_fill_cancel_race_keeps_reservation_until_confirmed_account(
    h: Harness,
) -> None:
    identity = await h.coordinator.submit(opportunity())
    first = h.fill(identity, size="1", terminal=False, fill_id="part-1")
    await h.coordinator.cancel(identity)
    assert h.journal.read()["orders"][identity]["state"] == "CANCEL_PENDING"
    assert h.journal.read()["orders"][identity]["reservation"] == "1.010"
    # Cancel ACK lost a race with a confirmed late fill.
    h.fill(identity, size="1", fill_id="part-2")
    h.coordinator.apply_order_evidence(
        identity,
        order_id=first.order_id,
        fills=(first,),
        finality="CONFIRMED_FILL",
        evidence_id="duplicate-confirmation",
        account=h.execution.account(),
    )
    ledger = session_ledger(h.journal.read())
    assert ledger.get("token").size == 2
    assert ledger.fees == D("0.02")
    assert h.journal.read()["reconciliation_ok"]


async def test_manual_account_change_is_visible_and_blocks_entry(h: Harness) -> None:
    h.execution.cash = D("99")
    assert not h.coordinator.reconcile(h.execution.account())
    with pytest.raises(SessionBlocked, match="drained_or_unreconciled"):
        await h.coordinator.submit(opportunity())
    assert h.journal.read()["incidents"][0]["reason"] == "unmatched_external_account_activity"


async def test_final_risk_kill_switch_or_supervision_cannot_be_bypassed(h: Harness) -> None:
    h.execution.hook = lambda: h.risk.kill_switch.activate("fixture emergency")
    with pytest.raises(SessionBlocked, match="final_risk"):
        await h.coordinator.submit(opportunity())
    assert not h.execution.submissions


async def test_supervision_monotonic_timeout_stops_without_wallclock_progress(h: Harness) -> None:
    h.tick = 21_000_000_000
    with pytest.raises(SessionBlocked, match="supervision_expired"):
        await h.coordinator.submit(opportunity())
    assert not h.execution.submissions


async def test_account_queue_rejects_second_financial_task(h: Harness) -> None:
    h.execution.wait = asyncio.Event()
    task = asyncio.create_task(h.coordinator.submit(opportunity()))
    await asyncio.sleep(0)
    with pytest.raises(SessionBlocked, match="operation_busy"):
        await h.coordinator.submit(opportunity(occurrence="other"))
    h.execution.wait.set()
    await task


def test_account_writer_contention_and_wider_binding_are_denied(h: Harness, tmp_path: Path) -> None:
    other = FinancialSessionJournal(
        tmp_path / "other" / "session.sqlite3", tmp_path / "witness", h.auth
    )
    with pytest.raises(RuntimeError, match="writer_busy"):
        other.provision(h.execution.account())
    h.journal.close()
    changed = replace(h.auth, wallets=frozenset({"wallet", "new-wallet"}))
    with pytest.raises(SessionBlocked, match="mismatch"):
        FinancialSessionJournal(h.journal.path, tmp_path / "witness", changed).open()


async def test_old_financial_backup_cannot_refund_consumed_authority(
    h: Harness, tmp_path: Path
) -> None:
    checkpoint = h.journal.checkpoint()
    h.journal.close()
    backup = tmp_path / "old-financial.sqlite3"
    shutil.copyfile(h.journal.path, backup)
    h.journal.open(checkpoint=checkpoint)
    h.coordinator = h.new_coordinator()
    h.start()
    await h.coordinator.submit(opportunity())
    h.journal.close()
    shutil.copyfile(backup, h.journal.path)
    with pytest.raises(SessionBlocked, match="rollback_witness_mismatch"):
        h.journal.open()


def test_lost_state_and_implicit_bootstrap_are_denied(h: Harness) -> None:
    h.journal.close()
    h.journal.path.unlink()
    with pytest.raises(SessionBlocked, match="lost_no_automatic_bootstrap"):
        h.journal.open()
    with pytest.raises(SessionBlocked, match="must_not_be_reinitialized"):
        h.journal.provision(h.execution.account())


async def test_data_only_default_denies_orders(h: Harness) -> None:
    h.coordinator.mode = TradingMode.DATA_ONLY
    with pytest.raises(SessionBlocked, match="DATA_ONLY"):
        await h.coordinator.submit(opportunity())
    assert not h.execution.submissions


@pytest.mark.parametrize("mode", [SessionMode.STOP, SessionMode.DRAIN])
async def test_stop_and_drain_block_entry(h: Harness, mode: SessionMode) -> None:
    h.coordinator.set_mode(mode)
    with pytest.raises(SessionBlocked):
        await h.coordinator.submit(opportunity())
    assert not h.execution.submissions


@pytest.mark.parametrize("missing", ["cash", "positions", "open_order_ids", "cumulative_fees"])
def test_unknown_account_values_never_become_zero(h: Harness, missing: str) -> None:
    with pytest.raises(SessionBlocked, match="incomplete"):
        h.coordinator.reconcile(replace(h.execution.account(), **{missing: None}))


@pytest.mark.parametrize(
    "limit,value,reason",
    [
        ("max_attempts", 1, "attempt_budget"),
        ("max_turnover", D("1.02"), "turnover_limit"),
        ("max_open_exposure", D("1.02"), "aggregate_exposure"),
        ("max_total_loss", D("1.02"), "total_loss_limit"),
        ("max_daily_loss", D("1.02"), "daily_loss_limit"),
        ("max_market_exposure", D("1.02"), "market_concentration"),
        ("max_wallet_exposure", D("1.02"), "wallet_concentration"),
    ],
)
async def test_authority_budgets_are_aggregate_not_per_poll(
    tmp_path: Path,
    limit: str,
    value: Any,
    reason: str,
) -> None:
    local = Harness(tmp_path, authorization(**{limit: value}))
    try:
        await local.coordinator.submit(opportunity())
        with pytest.raises(SessionBlocked, match=reason):
            await local.coordinator.submit(opportunity(occurrence="another"))
        assert len(local.execution.submissions) == 1
        assert local.journal.read()["attempts"] == 1
    finally:
        local.journal.close()


async def test_request_budget_preserves_cancel_and_reconcile_capacity(tmp_path: Path) -> None:
    local = Harness(tmp_path, authorization(max_requests=5, protective_request_reserve=4))
    try:
        for index in range(6):
            with pytest.raises(SessionBlocked, match="request_budget_exhausted"):
                await local.coordinator.submit(opportunity(occurrence=str(index)))
        assert local.journal.read()["requests"] == 1
        assert not local.execution.submissions
    finally:
        local.journal.close()


async def test_expiry_allows_only_explicit_protection_and_stop_still_blocks_it(h: Harness) -> None:
    identity = await h.coordinator.submit(opportunity())
    h.now = h.auth.expires_at
    h.coordinator.supervise(evidence_id="fresh-supervisor", healthy=True)
    await h.coordinator.cancel(identity)
    assert h.execution.cancel_calls == ["order-1"]
    h.coordinator.set_mode(SessionMode.STOP)
    with pytest.raises(SessionBlocked, match="STOP"):
        await h.coordinator.cancel(identity)


async def test_protective_deadline_never_grants_exit_or_cancel(h: Harness) -> None:
    identity = await h.coordinator.submit(opportunity())
    h.now = h.auth.protective_until
    h.coordinator.supervise(evidence_id="fresh", healthy=True)
    with pytest.raises(SessionBlocked, match="not_authorized"):
        await h.coordinator.cancel(identity)
    assert not h.execution.cancel_calls


def test_restart_requires_explicit_external_checkpoint(h: Harness) -> None:
    checkpoint = h.journal.checkpoint()
    h.journal.close()
    with pytest.raises(SessionBlocked, match="explicit_recovery_checkpoint"):
        h.journal.open()
    h.journal.open(checkpoint=checkpoint)
    assert h.journal.read()["supervised_at"] is None
    assert not h.journal.read()["reconciliation_ok"]


async def test_final_supervision_expiry_during_queued_response_blocks_network(h: Harness) -> None:
    h.execution.hook = lambda: setattr(h, "tick", 21_000_000_000)
    with pytest.raises(SessionBlocked, match="supervision_expired"):
        await h.coordinator.submit(opportunity())
    assert not h.execution.submissions


async def test_source_outage_never_leaves_a_submitted_order(h: Harness) -> None:
    h.execution.failure = "account"
    with pytest.raises(TimeoutError):
        await h.coordinator.submit(opportunity())
    assert not h.execution.submissions
    assert not h.journal.read()["orders"]


async def test_financial_store_failure_blocks_possible_submission(
    h: Harness, monkeypatch: Any
) -> None:
    import sqlite3

    original = h.journal.mutate

    def fail_claim(kind: str, payload: Any, change: Any) -> None:
        if kind == "ORDER_STATE":
            raise sqlite3.OperationalError("fixture disk failure")
        original(kind, payload, change)

    monkeypatch.setattr(h.journal, "mutate", fail_claim)
    with pytest.raises(sqlite3.OperationalError):
        await h.coordinator.submit(opportunity())
    assert not h.execution.submissions
    assert h.journal.read()["attempts"] == 1


async def test_optional_telemetry_failure_never_changes_financial_result(h: Harness) -> None:
    class BrokenRecorder:
        def record_measurement(self, **kwargs: Any) -> None:
            raise OSError("fixture telemetry full queue or unavailable store")

    h.coordinator.latency.recorder = BrokenRecorder()
    identity = await h.coordinator.submit(opportunity())
    h.fill(identity)
    assert h.coordinator.latency.errors > 0
    assert h.journal.read()["orders"][identity]["state"] == "FINALIZED"
    assert h.journal.read()["reconciliation_ok"]


async def test_duplicate_open_message_never_reopens_finalized_order(h: Harness) -> None:
    identity = await h.coordinator.submit(opportunity())
    fill = h.fill(identity)
    h.coordinator.apply_order_evidence(
        identity,
        order_id=fill.order_id,
        fills=(fill,),
        finality="OPEN",
        evidence_id="older-duplicate",
        account=h.execution.account(),
    )
    assert h.journal.read()["orders"][identity]["state"] == "FINALIZED"
    assert len(h.journal.read()["fills"]) == 1


async def test_fill_limit_breach_remains_accounted_and_drains(h: Harness) -> None:
    identity = await h.coordinator.submit(opportunity())
    h.fill(identity, price="0.6", fee="0.02")
    state = h.journal.read()
    assert session_ledger(state).cash == D("98.78")
    assert any(i["reason"] == "fill_outside_approved_price" for i in state["incidents"])
    assert state["mode"] == "DRAIN"


async def test_economics_unknown_marks_redaction_and_drawdown(h: Harness) -> None:
    from polysia.monitoring.financial_session import financial_session_view

    empty = financial_session_view(h.journal.read(), h.auth, now=h.now)
    assert empty["economics"]["net_pnl"] is None
    identity = await h.coordinator.submit(opportunity())
    h.fill(identity)
    partial = financial_session_view(h.journal.read(), h.auth, now=h.now)
    assert partial["economics"]["status"] == "PARTIAL_UNKNOWN_MARKS"
    assert partial["economics"]["net_pnl"] is None
    h.coordinator.record_valuation(
        {"token": D("0.4")}, observed_at=h.now, method="conservative_bid"
    )
    measured = financial_session_view(h.journal.read(), h.auth, now=h.now)
    assert measured["economics"]["net_pnl"] == "-0.21"
    assert measured["economics"]["drawdown"] == "0.21"
    assert measured["economics"]["provider_cost"] is None
    assert BINDING.account not in str(measured)
    h.now += timedelta(seconds=31)
    assert (
        financial_session_view(h.journal.read(), h.auth, now=h.now)["economics"]["net_pnl"] is None
    )


def test_ungranted_and_nonfinite_authority_are_default_denied(tmp_path: Path) -> None:
    with pytest.raises(SessionBlocked, match="authority_denied"):
        Harness(tmp_path, authorization(granted=False))
    for value in (D("NaN"), D("Infinity"), D("-1")):
        with pytest.raises(SessionBlocked):
            authorization(max_open_exposure=value)


@pytest.mark.parametrize(
    "held,depth,resolved,age,expected,shares",
    [
        ("2", "10", False, 0, "REDUCE", "1.0"),
        ("2", "0.5", False, 0, "REDUCE", "0.5"),
        ("2", None, False, 0, "ILLIQUID_INCIDENT", "0"),
        ("0.0001", "10", False, 0, "DUST_INCIDENT", "0"),
        ("2", "10", True, 0, "REDEEMABLE_REVIEW", "0"),
        ("2", "10", False, 700, "REDUCE", "2"),
    ],
)
def test_exit_rules_preserve_partial_holdings_and_redeemable_state(
    held: str,
    depth: str | None,
    resolved: bool,
    age: int,
    expected: str,
    shares: str,
) -> None:
    from polysia.domain.financial_session import assess_exit

    plan = assess_exit(
        held_shares=D(held),
        leader_reduction_fraction=D("0.5"),
        available_depth=None if depth is None else D(depth),
        opened_at=NOW - timedelta(seconds=age),
        now=NOW,
        market_expires_at=NOW + timedelta(hours=1),
        resolved=resolved,
        authority=authorization(),
    )
    assert plan.action == expected
    assert plan.shares == D(shares)


async def test_existing_live_broker_bridge_preserves_exact_request_without_real_client(
    h: Harness,
) -> None:
    from polysia.config.settings import AppSettings
    from polysia.execution.financial_session import LiveSessionExecution
    from polysia.execution.live_broker import LiveBroker

    calls = []

    class Adapter:
        is_connected = True

        async def place_limit_order(self, **kwargs: Any) -> dict[str, str]:
            calls.append(kwargs)
            return {"order_id": "broker-order"}

    class Eligibility:
        async def assert_allowed(self) -> object:
            return object()

    async def reader(instrument: InstrumentScope) -> AccountObservation:
        return h.execution.account()

    async def cancellation_eligible(order_id: str) -> bool:
        return False

    risk = RiskEngine(
        limits=replace(h.risk.limits, allow_live_trading=True, min_edge_required=D("0.01"))
    )
    broker = LiveBroker(
        adapter=Adapter(),
        risk_engine=risk,
        settings=AppSettings(TRADING_MODE="LIVE", LIVE_TRADING_ENABLED=True),
        allowed_token_ids=("token",),
        geoblock_check=Eligibility(),
        clock=lambda: h.now,
    )
    execution = LiveSessionExecution(
        broker,
        account_reader=reader,
        charges={
            action: RequestCharge(1, 100, D("0"))
            for action in ("ACCOUNT", "SUBMIT", "CANCEL", "CANCELLATION_READ")
        },
        acknowledgement=True,
        clock=lambda: h.now,
        max_evidence_age_ms=30000,
        protective_eligibility=cancellation_eligible,
    )
    local = FinancialSessionCoordinator(
        h.journal,
        execution,
        risk,
        binding=BINDING,
        clock=lambda: h.now,
        monotonic=lambda: h.tick,
        trading_mode=TradingMode.LIVE,
    )
    local.supervise(evidence_id="fixture", healthy=True)
    identity = await local.submit(opportunity())
    assert calls[0]["size"] == D("2")
    assert calls[0]["price"] == D("0.5")
    assert calls[0]["expiration"] == int(h.auth.expires_at.timestamp())
    assert h.journal.read()["orders"][identity]["order_id"] == "broker-order"
    with pytest.raises(SessionBlocked, match="cancellation_ineligible"):
        await local.cancel(identity)


@pytest.mark.parametrize("prior,late", [("0", "0"), ("1", "0"), ("1", "1"), ("0.5", "0.5")])
async def test_existing_cancellation_finality_gate_reuses_durable_session_checkpoints(
    h: Harness,
    prior: str,
    late: str,
) -> None:
    from polysia.application.ports.cancellation import (
        OpenOrderEvidence,
        OrderDetailEvidence,
        OrderLookupStatus,
        OrderTradeEvidence,
    )
    from polysia.execution.cancellation_finality import (
        CancellationFinalityConfig,
        CancellationFinalityOutcome,
    )

    identity = await h.coordinator.submit(opportunity())
    baseline_fill = None
    if D(prior):
        baseline_fill = h.fill(identity, size=prior, terminal=False, fill_id="baseline")
    await h.coordinator.cancel(identity)
    assert h.journal.read()["orders"][identity]["state"] == "CANCEL_PENDING"

    late_fill = None
    if D(late):
        h.execution.cash -= D(late) * D("0.5") + D("0.01")
        h.execution.fees += D("0.01")
        h.execution.positions["token"] = D(prior) + D(late)
        late_fill = ConfirmedSessionFill(
            "late",
            identity,
            "order-1",
            "token",
            "BUY",
            D("0.5"),
            D(late),
            D("0.01"),
            h.now,
        )

    class NoFillEvidence:
        async def observe_open_orders(self, **kwargs: Any) -> tuple:
            return ()

        async def observe_order_detail(self, **kwargs: Any) -> OrderDetailEvidence:
            h.execution.open_orders.clear()
            return OrderDetailEvidence(
                OrderLookupStatus.FOUND,
                OpenOrderEvidence(
                    "order-1",
                    "token",
                    "BUY",
                    "CANCELED",
                    D("2"),
                    D(prior) + D(late),
                ),
            )

        async def observe_order_trades(self, **kwargs: Any) -> tuple:
            return tuple(
                OrderTradeEvidence(
                    fill.fill_id,
                    "order-1",
                    "token",
                    "CONFIRMED",
                    fill.shares,
                    fill.price,
                )
                for fill in (baseline_fill, late_fill)
                if fill is not None
            )

        async def observe_position_size(self, **kwargs: Any) -> Decimal:
            return D(prior) + D(late)

    async def sleep(seconds: float) -> None:
        pass

    result = await h.coordinator.reconcile_cancellation(
        identity,
        evidence=NoFillEvidence(),
        sleeper=sleep,
        config=CancellationFinalityConfig(
            maximum_observations=2,
            observation_interval_seconds=0,
            timeout_seconds=1,
            required_clean_observations=2,
        ),
        confirmed_fills=() if late_fill is None else (late_fill,),
    )
    expected = (
        CancellationFinalityOutcome.CONFIRMED_NO_FILL
        if not D(late)
        else CancellationFinalityOutcome.FULL_FILL_DETECTED
        if D(prior) + D(late) == 2
        else CancellationFinalityOutcome.PARTIAL_FILL_DETECTED
    )
    assert result.outcome is expected
    state = h.journal.read()
    assert state["orders"][identity]["state"] == (
        "CANCELLED" if D(prior) + D(late) == 0 else "FINALIZED"
    )
    assert state["checkpoints"]
    assert state["reconciliation_ok"]
    assert state["attempts"] == 1
    assert len(h.execution.cancel_calls) == 1


async def test_conflicting_source_mapping_cannot_create_a_second_intent(h: Harness) -> None:
    original = opportunity()
    identity = await h.coordinator.submit(original)
    conflict = replace(original, event=replace(original.event, side="SELL", source="polycop"))
    with pytest.raises(SessionBlocked, match="conflicting_occurrence_evidence"):
        await h.coordinator.submit(conflict)
    assert len(h.execution.submissions) == 1
    state = h.journal.read()
    assert len(state["orders"]) == 1
    assert state["decisions"][identity]["evidence"]["event"]["side"] == "BUY"
    assert state["mode"] == "DRAIN"


async def test_newer_reorg_correction_drains_without_refunding_reserved_exposure(
    h: Harness,
) -> None:
    original = opportunity()
    identity = await h.coordinator.submit(original)
    correction = replace(original, event=replace(original.event, source="polycop", finalized=False))
    with pytest.raises(SessionBlocked, match="conflicting_occurrence_evidence"):
        await h.coordinator.submit(correction)
    state = h.journal.read()
    assert state["mode"] == "DRAIN"
    assert state["orders"][identity]["reservation"] == "1.010"
    assert state["attempts"] == 1
    with pytest.raises(SessionBlocked, match="drained_or_unreconciled"):
        await h.coordinator.submit(opportunity(occurrence="new-event"))


async def test_sell_overfill_is_quarantined_without_inventing_a_short_position(h: Harness) -> None:
    from polysia.monitoring.financial_session import financial_session_view

    entry = await h.coordinator.submit(opportunity())
    h.fill(entry)
    exit_id = await h.coordinator.submit(opportunity(occurrence="exit", side="SELL"))
    h.execution.open_orders.clear()
    h.execution.positions.clear()
    h.execution.cash = D("100.48")
    h.execution.fees = D("0.02")
    fill = ConfirmedSessionFill(
        "overfill",
        exit_id,
        "order-2",
        "token",
        "SELL",
        D("0.5"),
        D("3"),
        D("0.01"),
        h.now,
    )
    h.coordinator.apply_order_evidence(
        exit_id,
        order_id="order-2",
        fills=(fill,),
        finality="CONFIRMED_FILL",
        evidence_id="contradictory-but-confirmed-external-evidence",
        account=h.execution.account(),
    )
    state = h.journal.read()
    assert state["mode"] == "DRAIN"
    assert not state["reconciliation_ok"]
    assert state["quarantined_fills"][0]["fill_id"] == "overfill"
    assert session_ledger(state).get("token").size == 2
    assert state["orders"][exit_id]["state"] == "RECONCILIATION_BLOCKED"
    projection = financial_session_view(state, h.auth, now=h.now)
    assert projection["economics"]["status"] == "UNKNOWN_QUARANTINED_FINANCIAL_EVIDENCE"
    assert projection["economics"]["net_pnl"] is None
    with pytest.raises(SessionBlocked):
        await h.coordinator.submit(opportunity(occurrence="following-entry"))


async def test_better_buy_price_preserves_fixed_share_cap(h: Harness) -> None:
    identity = await h.coordinator.submit(opportunity())
    assert h.execution.submissions[0].request.shares == D("2")
    assert h.execution.submissions[0].request.price == D("0.5")
    h.fill(identity, size="2", price="0.25", fee="0.005")
    state = h.journal.read()
    assert not state["incidents"]
    assert session_ledger(state).get("token").size == 2
    assert session_ledger(state).cash == D("99.495")


async def test_confirmed_fill_survives_missing_account_evidence_in_quarantine(h: Harness) -> None:
    identity = await h.coordinator.submit(opportunity())
    fill = ConfirmedSessionFill(
        "confirmed-unreconciled",
        identity,
        "order-1",
        "token",
        "BUY",
        D("0.5"),
        D("2"),
        D("0.01"),
        h.now,
    )
    with pytest.raises(SessionBlocked, match="account_evidence_incomplete"):
        h.coordinator.apply_order_evidence(
            identity,
            order_id="order-1",
            fills=(fill,),
            finality="CONFIRMED_FILL",
            evidence_id="trade-confirmation",
            account=replace(h.execution.account(), cash=None),
        )
    state = h.journal.read()
    assert state["quarantined_fills"][0]["fill_id"] == "confirmed-unreconciled"
    assert state["mode"] == "DRAIN"
    assert not state["reconciliation_ok"]


@pytest.mark.parametrize(
    "finality,quantity",
    [
        ("CONFIRMED_NO_FILL", "2"),
        ("CONFIRMED_FILL", "1"),
        ("CONFIRMED_PARTIAL", "2"),
    ],
)
async def test_finality_contradiction_preserves_confirmed_fills_and_blocks_accounting(
    h: Harness,
    finality: str,
    quantity: str,
) -> None:
    from polysia.monitoring.financial_session import financial_session_view

    identity = await h.coordinator.submit(opportunity())
    h.execution.open_orders.clear()
    h.execution.positions["token"] = D(quantity)
    h.execution.cash -= D(quantity) * D("0.5") + D("0.01")
    h.execution.fees = D("0.01")
    fill = ConfirmedSessionFill(
        "conflicting-finality-fill",
        identity,
        "order-1",
        "token",
        "BUY",
        D("0.5"),
        D(quantity),
        D("0.01"),
        h.now,
    )
    h.coordinator.apply_order_evidence(
        identity,
        order_id="order-1",
        fills=(fill,),
        finality=finality,
        evidence_id="contradictory-terminal-evidence",
        account=h.execution.account(),
    )
    state = h.journal.read()
    assert state["fills"][0]["fill_id"] == "conflicting-finality-fill"
    assert state["quarantined_finality"][0]["finality"] == finality
    assert state["mode"] == "DRAIN"
    assert not state["reconciliation_ok"]
    view = financial_session_view(state, h.auth, now=h.now)
    assert view["economics"]["fees"] is None
    assert view["economics"]["known_accounted_fees"] == "0.01"
    assert view["economics"]["net_pnl"] is None


async def test_two_source_cohort_to_independent_risk_entry_exit_and_human_view(
    tmp_path: Path,
) -> None:
    from polysia.application.services.cohort_intents import admit_cohort_opportunity
    from polysia.application.services.source_cohort import SourceCohortService
    from polysia.domain.financial_session import digest
    from polysia.domain.wallet_intelligence import (
        CandidateWalletDataset,
        CandidateWalletRecord,
        normalize_evm_wallet,
    )
    from polysia.domain.wallet_intelligence.source_cohort import (
        CohortSelectionPolicy,
        FollowerQualificationEvidence,
        RetainedCandidateSnapshot,
    )
    from polysia.monitoring.financial_session import financial_session_view
    from polysia.storage.candidate_intelligence import CandidateIntelligenceRepository
    from polysia.storage.wallet_intelligence import WalletIntelligenceRepository

    address = "0x0000000000000000000000000000000000000001"
    wallet = normalize_evm_wallet("polygon", address)[0]
    path = tmp_path / "source.sqlite3"
    pipeline = SourceCohortService(
        WalletIntelligenceRepository(path),
        CandidateIntelligenceRepository(path),
        clock=lambda: NOW,
    )
    snapshots = []
    for source in ("polymarket-native", "polycop"):
        dataset = CandidateWalletDataset(
            source,
            "fixture/v2",
            NOW,
            1,
            (CandidateWalletRecord(address, 1, 1, {"score": "999999"}, digest((source, address))),),
            digest((source, "fixture-dataset")),
        )
        snapshots.append(
            await pipeline.ingest(
                RetainedCandidateSnapshot(
                    dataset,
                    "polygon",
                    None,
                    NOW,
                    True,
                    "BOUNDED_FIXTURE",
                    None,
                )
            )
        )
    qualification = FollowerQualificationEvidence(
        wallet,
        "frozen-independent-follower-evidence",
        NOW - timedelta(minutes=30),
        NOW - timedelta(seconds=20),
        NOW + timedelta(minutes=1),
        NOW - timedelta(seconds=10),
        NOW - timedelta(seconds=25),
        40,
        D("0.1"),
        D("0.02"),
        D("0.01"),
        D("10"),
        D("10"),
        D("1"),
        D("0.1"),
        D("0.1"),
        D("0.95"),
        D("0.01"),
        True,
        True,
        (),
    )
    policy = CohortSelectionPolicy(
        "fixture/v1",
        1,
        20,
        timedelta(hours=1),
        D("0.03"),
        D("0.1"),
        D("4"),
        D("0.5"),
        D("0.7"),
        D("0.8"),
        D("2"),
    )
    selection = pipeline.select(tuple(snapshots), {wallet: qualification}, policy)
    assert selection.selected_wallet_ids == (wallet,)
    at = NOW + timedelta(minutes=2)
    raw = opportunity()
    raw = replace(
        raw,
        event=replace(
            raw.event,
            chain="polygon",
            wallet=wallet,
            occurred_at=at,
            observed_at=at,
            ingested_at=at,
        ),
        market_observed_at=at,
    )
    admitted = admit_cohort_opportunity(selection, raw, now=at)
    assert admitted.cohort_digest == selection.digest
    assert admitted.qualification_evidence_id == qualification.evidence_id
    denied = Harness(tmp_path / "denied")
    try:
        denied.now = at
        with pytest.raises(SessionBlocked, match="outside_scope"):
            await denied.coordinator.submit(admitted)
    finally:
        denied.journal.close()
    allowed = Harness(tmp_path / "approved", authorization(wallets=frozenset({wallet})))
    try:
        allowed.now = at
        allowed.start()
        identity = await allowed.coordinator.submit(admitted)
        overlap = replace(admitted, event=replace(admitted.event, source="polycop"))
        assert await allowed.coordinator.submit(overlap) == identity
        allowed.fill(identity)
        exit_event = replace(admitted.event, occurrence="exit-log", side="SELL")
        exit_id = await allowed.coordinator.submit(
            replace(admitted, event=exit_event, leader_reduction=True)
        )
        allowed.fill(exit_id, side="SELL")
        view = financial_session_view(
            allowed.journal.read(),
            allowed.auth,
            now=at,
            discovery_counts={"discovered": 1, "qualified": 1},
        )
        assert view["funnel"]["submitted"] == 2
        assert view["funnel"]["finalized"] == 2
        assert view["economics"]["net_pnl"] == "-0.02"
        assert address not in str(selection.to_console_dict()) + str(view)
    finally:
        allowed.journal.close()


async def test_pending_buy_on_another_token_consumes_position_slot(tmp_path: Path) -> None:
    second_scope = replace(SCOPE, token="token-B", market="market-B")
    local = Harness(tmp_path, authorization(instruments=(SCOPE, second_scope)))
    try:
        await local.coordinator.submit(opportunity())
        other = opportunity(occurrence="other-token")
        other = replace(other, event=replace(other.event, instrument=second_scope))
        with pytest.raises(SessionBlocked, match="position_concurrency_limit"):
            await local.coordinator.submit(other)
        assert len(local.execution.submissions) == 1
        assert local.journal.read()["attempts"] == 1
    finally:
        local.journal.close()


async def test_pending_buy_shares_consume_independent_risk_token_limit(h: Harness) -> None:
    h.risk = RiskEngine(limits=replace(h.risk.limits, max_position_per_token=D("3")))
    h.coordinator.risk = h.risk
    await h.coordinator.submit(opportunity())
    with pytest.raises(SessionBlocked, match="risk_reserved_token_quantity_limit"):
        await h.coordinator.submit(opportunity(occurrence="second"))
    assert len(h.execution.submissions) == 1


async def test_pending_buy_shares_consume_independent_risk_market_limit(tmp_path: Path) -> None:
    second_scope = replace(SCOPE, token="token-B")
    local = Harness(tmp_path, authorization(instruments=(SCOPE, second_scope), max_positions=2))
    try:
        local.risk = RiskEngine(limits=replace(local.risk.limits, max_position_per_market=D("3")))
        local.coordinator.risk = local.risk
        await local.coordinator.submit(opportunity())
        other = opportunity(occurrence="same-market-other-token")
        other = replace(other, event=replace(other.event, instrument=second_scope))
        with pytest.raises(SessionBlocked, match="risk_reserved_market_quantity_limit"):
            await local.coordinator.submit(other)
        assert len(local.execution.submissions) == 1
    finally:
        local.journal.close()


async def test_partial_fill_reduces_pending_quantity_without_double_count(h: Harness) -> None:
    h.risk = RiskEngine(limits=replace(h.risk.limits, max_position_per_token=D("4")))
    h.coordinator.risk = h.risk
    first = await h.coordinator.submit(opportunity())
    h.fill(first, size="1", terminal=False)
    await h.coordinator.submit(opportunity(occurrence="second"))
    assert len(h.execution.submissions) == 2


async def test_pending_sells_do_not_free_future_buy_quantity(tmp_path: Path) -> None:
    local = Harness(tmp_path, authorization(max_concurrent_orders=3))
    try:
        local.risk = RiskEngine(limits=replace(local.risk.limits, max_position_per_token=D("4")))
        local.coordinator.risk = local.risk
        first = await local.coordinator.submit(opportunity())
        local.fill(first)
        await local.coordinator.submit(opportunity(occurrence="pending-buy"))
        await local.coordinator.submit(opportunity(occurrence="pending-sell", side="SELL"))
        with pytest.raises(SessionBlocked, match="risk_reserved_token_quantity_limit"):
            await local.coordinator.submit(opportunity(occurrence="new-entry"))
        assert len(local.execution.submissions) == 3
    finally:
        local.journal.close()


def test_single_cash_ledger_never_aggregates_different_collateral_assets() -> None:
    with pytest.raises(SessionBlocked, match="requires_one_collateral"):
        authorization(
            instruments=(SCOPE, replace(SCOPE, token="another", collateral="other-asset"))
        )
