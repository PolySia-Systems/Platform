from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.services.financial_session import session_ledger
from polysia.backtesting.shadow_policy_lab import ShadowFrame, compare_policy_stream
from polysia.control.service import ControlService, ControlValidationError
from polysia.domain.copytrading import LeaderPositionEffect, LeaderTradeAction, LeaderTradeEvent
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowConfig
from polysia.domain.copytrading.copy_policy import CopyPolicy
from polysia.domain.financial_session import ObservedRedemption, SessionBlocked, SessionMode
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    OrderBookLevel,
)
from polysia.monitoring.capabilities import CapabilityEvidence, capability_projection
from polysia.monitoring.session_incidents import SessionIncidents
from polysia.storage.console_commands import ConsoleCommandStore
from tests.integration.test_financial_session import NOW, Harness, authorization, opportunity

D = Decimal


def policy(*, profit: bool = False) -> CopyPolicy:
    return CopyPolicy(
        "profit/v1" if profit else "mirror/v1",
        "FIXED_DEBIT",
        D(1),
        D("0.1"),
        "NET_TAKE_PROFIT" if profit else "MIRROR",
        D("0.2") if profit else None,
    )


def test_policy_available_capital_rounding_fee_and_baseline() -> None:
    fixed = policy()
    shares = fixed.entry_size(
        cash=D(10),
        reserved_debit=D("9.3"),
        price=D("0.3"),
        fee_per_share=D("0.02"),
        share_quantum=D("0.01"),
        minimum_shares=D(1),
        depth=D(100),
        entered_before=False,
    )
    assert shares == D("2.18") and shares * D("0.32") <= D("0.7")
    assert (
        fixed.entry_size(
            cash=D(10),
            reserved_debit=D(0),
            price=D("0.3"),
            fee_per_share=D(0),
            share_quantum=D("0.01"),
            minimum_shares=D(1),
            depth=D(100),
            entered_before=True,
        )
        == 0
    )
    exit_args = dict(
        held=D(4),
        reserved_sell=D(1),
        cost_basis=D(2),
        bid=D("0.6"),
        exit_fee_per_share=D("0.01"),
        entry_fees=D("0.02"),
        opened_at=NOW,
        now=NOW,
        leader_before=D(100),
        leader_reduction=D(25),
        share_quantum=D("0.01"),
    )
    assert fixed.exit_decision(**exit_args) == ("LEADER_REDUCTION", D(1))
    with pytest.raises(SessionBlocked, match="baseline"):
        fixed.exit_decision(**{**exit_args, "leader_before": None})
    with pytest.raises(SessionBlocked, match="hybrid"):
        replace(fixed, stop_loss=D(1))


def frame(at, bid: str, ask: str, event=None) -> ShadowFrame:
    return ShadowFrame(
        at,
        MarketDetails(
            id="market",
            condition_id="condition",
            active=True,
            closed=False,
            fee_schedule=MarketFeeSchedule(enabled=False),
        ),
        MarketOrderBookSnapshot(
            token_id="token",
            market_id="condition",
            timestamp=at,
            bids=(OrderBookLevel(price=D(bid), size=D(100)),),
            asks=(OrderBookLevel(price=D(ask), size=D(100)),),
            minimum_order_size=D(1),
            tick_size=D("0.01"),
        ),
        event,
    )


def test_two_policies_have_stateful_different_exits_on_identical_frozen_stream() -> None:
    buy = LeaderTradeEvent(
        "buy",
        "retained-corroborated",
        "leader",
        "condition",
        "token",
        LeaderTradeAction.BUY,
        LeaderPositionEffect.OPEN,
        D("0.4"),
        D(10),
        NOW,
        NOW,
        "retained-log",
    )
    sell = replace(
        buy,
        event_id="sell",
        trade_action=LeaderTradeAction.SELL,
        executed_size=D(5),
        executed_at=NOW + timedelta(seconds=2),
        observed_at=NOW + timedelta(seconds=2),
    )
    tape = (
        frame(NOW, "0.39", "0.4", buy),
        frame(NOW + timedelta(seconds=1), "0.7", "0.71"),
        frame(NOW + timedelta(seconds=2), "0.8", "0.81", sell),
    )
    config = ContinuousShadowConfig(follower_bankroll=D(10), follower_maximum_exposure=D(10))
    result = compare_policy_stream(
        tape, (policy(), policy(profit=True)), config=config, leader_opening={}
    )
    mirror, profit = result["results"]
    assert mirror["initial_cash"] == profit["initial_cash"] == 10
    assert mirror["open_positions"][0]["quantity"] == D("1.25")
    assert profit["open_positions"] == []
    assert any(
        row["input_kind"] == "POSITION_TRIGGER" and row["side"] == "SELL"
        for row in profit["decisions"]
    )
    assert mirror["cash"] != profit["cash"]
    assert result["frame_count"] == 3 and result["acquisition_copies"] == 1
    assert result["combined_portfolio_return"] is None and result["accuracy_percent"] is None


@pytest.mark.asyncio
async def test_two_leaders_cannot_liquidate_each_others_quantity(tmp_path: Path) -> None:
    harness = Harness(tmp_path, authorization(wallets=frozenset({"wallet", "second"})))
    try:
        first = await harness.coordinator.submit(opportunity(occurrence="first"))
        harness.fill(first)
        second_event = replace(opportunity(occurrence="second").event, wallet="second")
        second = await harness.coordinator.submit(opportunity(event=second_event))
        harness.fill(second)
        owned = harness.coordinator.allocation_view()
        assert sum(row["quantity"] for row in owned.values()) == 4
        with pytest.raises(SessionBlocked, match="leader_policy_allocation"):
            await harness.coordinator.submit(
                opportunity(occurrence="oversell", side="SELL", shares=D(3))
            )
        assert harness.journal.read()["attempts"] == 2
    finally:
        harness.journal.close()


@pytest.mark.asyncio
async def test_redemption_allocation_is_chronological_and_does_not_grant_mutation(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, authorization(wallets=frozenset({"wallet", "second"})))
    try:
        for alias in ("wallet", "second"):
            event = replace(opportunity(occurrence=alias).event, wallet=alias)
            identity = await harness.coordinator.submit(opportunity(event=event))
            harness.fill(identity)
        harness.now += timedelta(seconds=1)
        harness.execution.cash += D(2)
        harness.execution.positions["token"] -= D(2)
        event = ObservedRedemption(
            "redeem-001",
            harness.auth.binding.account,
            "collateral-v2",
            (("token", D(2)),),
            D(2),
            harness.now,
            "confirmed-receipt-digest",
        )
        harness.coordinator.observe_redemption(event, harness.execution.account())
        owned = harness.coordinator.allocation_view()
        assert sorted(row["quantity"] for row in owned.values()) == [D(1), D(1)]
        assert sum(row["fees"] for row in owned.values()) == D("0.01")
        harness.coordinator.observe_redemption(event, harness.execution.account())
        assert len(harness.journal.read()["cash_events"]) == 1
        harness.now += timedelta(seconds=1)
        identity = await harness.coordinator.submit(opportunity(occurrence="later-buy"))
        harness.fill(identity)
        owned = harness.coordinator.allocation_view()
        assert {row["wallet"]: row["quantity"] for row in owned.values()} == {
            "wallet": D(3),
            "second": D(1),
        }
        ledger = session_ledger(harness.journal.read())
        assert (
            sum(row["cost_basis"] for row in owned.values())
            == ledger.get("token").size * ledger.get("token").avg_price
        )
        assert harness.execution.cancel_calls == []  # observation has no mutation capability
    finally:
        harness.journal.close()


def test_operator_drain_survives_coordinator_restart(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    try:
        harness.coordinator.drain_entries(receipt="immutable-scoped-preview")
        restarted = harness.new_coordinator()
        restarted.supervise(evidence_id="independent-new-observation", healthy=True)
        with pytest.raises(SessionBlocked, match="entry_stop_latched"):
            restarted.set_mode(SessionMode.RUNNING)
        assert harness.journal.read()["mode"] == "DRAIN"
    finally:
        harness.journal.close()


def test_same_block_fill_order_preserves_basis_and_exact_gross_cash() -> None:
    # Incoming order histories may be grouped differently by the venue. Canonical
    # block/log ordering, rather than response insertion order, owns accounting.
    rows = []
    for identity, side, price, gross, log in (
        ("first", "BUY", "0.5", "1", 1),
        ("sale", "SELL", "0.6", "1.2", 2),
        ("later", "BUY", "0.8", "1.6", 3),
    ):
        rows.append(
            {
                "fill_id": identity,
                "order_id": identity,
                "intent_id": identity,
                "token": "token",
                "side": side,
                "price": price,
                "shares": "2",
                "fee": "0",
                "gross_notional": gross,
                "confirmed_at": NOW.isoformat(),
                "chain_order": (100, log),
            }
        )
    state = {"opening": {"cash": "100"}, "fills": [rows[2], rows[0], rows[1]]}
    ledger = session_ledger(state)
    assert ledger.cash == D("98.6") and ledger.get("token").avg_price == D("0.8")
    assert ledger.realized_pnl == D("0.2")


def test_scoped_preview_actor_target_revision_and_idempotent_execution(tmp_path: Path) -> None:
    store = ConsoleCommandStore(tmp_path / "commands.sqlite3")
    store.initialize()
    targets = frozenset({"experiment-one"})
    with pytest.raises(ControlValidationError):
        ControlService.preview_scoped(
            store,
            operation="shadow.drain",
            target="experiment-one",
            actor="reader",
            role="reader",
            allowed_targets=targets,
            now=NOW,
        )
    plan = ControlService.preview_scoped(
        store,
        operation="shadow.drain",
        target="experiment-one",
        actor="operator",
        role="operator",
        allowed_targets=targets,
        now=NOW,
    )
    arguments = dict(
        subject="operator",
        role="operator",
        preview_id=plan.fingerprint,
        expected_revision=0,
        idempotency_key="scoped-command-000001",
        now=NOW,
        allowed_targets=targets,
    )
    with pytest.raises(ValueError, match="actor"):
        store.submit_scoped(**{**arguments, "subject": "someone-else"})
    receipt = store.submit_scoped(**arguments)
    assert receipt["status"] == "REQUESTED" and receipt["effect"] == "NOT_OBSERVED"
    following = ControlService.preview_scoped(
        store,
        operation="shadow.archive",
        target="experiment-one",
        actor="operator",
        role="operator",
        allowed_targets=targets,
        now=NOW,
    )
    store.submit_scoped(
        **{
            **arguments,
            "preview_id": following.fingerprint,
            "expected_revision": 1,
            "idempotency_key": "scoped-command-000002",
        }
    )
    assert store.claim_scoped("scoped-command-000002", now=NOW) is None
    effects = []

    def execute(preview):
        effects.append(preview.target)
        return {"effect": "OBSERVED", "state": "DRAINING"}

    ControlService.execute_scoped(
        store, idempotency_key=arguments["idempotency_key"], now=NOW, execute=execute
    )
    ControlService.execute_scoped(
        store, idempotency_key=arguments["idempotency_key"], now=NOW, execute=execute
    )
    assert effects == ["experiment-one"]
    assert store.submit_scoped(**arguments)["status"] == "APPLIED"
    with pytest.raises(ValueError, match="idempotency"):
        store.submit_scoped(**{**arguments, "idempotency_key": "scoped-command-000002"})
    with pytest.raises(ValueError, match="revision"):
        store.submit_scoped(**{**arguments, "idempotency_key": "scoped-command-000003"})
    assert store.claim_scoped("scoped-command-000002", now=NOW) is not None
    store.retire_scoped_claims(targets=targets)
    assert store.scoped_status()[0]["status"] == "FAILED"


def test_capability_missing_and_expired_are_not_ready() -> None:
    item = CapabilityEvidence(
        "configuration",
        "CONFIGURED",
        "fixture",
        NOW,
        NOW + timedelta(minutes=1),
        "not verified",
        "startup",
        "Validate exact configuration",
    )
    projection = capability_projection(
        {"configuration": item}, now=NOW, enabled={"startup": True, "new_entries": True}
    )
    rows = {row["capability"]: row for row in projection["capabilities"]}
    assert rows["startup"]["status"] == "BLOCKED" and rows["new_entries"]["status"] == "BLOCKED"
    assert replace(item, state="VERIFIED").current_state(NOW + timedelta(minutes=2)) == "EXPIRED"


def test_incident_dedup_failed_delivery_and_rate_limit_with_fake_sink(tmp_path: Path) -> None:
    current = [NOW]
    incidents = SessionIncidents(tmp_path / "incidents.sqlite3", clock=lambda: current[0])
    incidents.initialize()
    key = incidents.record(
        "financial_ambiguity",
        scope="run",
        reason_code="unknown_fill",
        next_action="Reconcile exact account",
    )
    assert key == incidents.record(
        "financial_ambiguity",
        scope="run",
        reason_code="unknown_fill",
        next_action="Reconcile exact account",
    )
    assert incidents.projection()[0]["count"] == 2

    class FakeSink:
        calls = 0

        def deliver(self, payload):
            self.calls += 1
            if self.calls == 1:
                raise OSError("fixture sink unavailable")
            return "fake-delivery-receipt"

    sink = FakeSink()
    with pytest.raises(SessionBlocked, match="delivery_authority"):
        incidents.deliver(key, sink)
    assert incidents.deliver(key, sink, destination_authorized=True) == "FAILED"
    assert incidents.deliver(key, sink, destination_authorized=True) == "RATE_LIMITED"
    current[0] += timedelta(minutes=6)
    assert incidents.deliver(key, sink, destination_authorized=True) == "DELIVERED"
    assert sink.calls == 2


@pytest.mark.parametrize(
    "operation,target",
    [
        ("session.stop", "run:drain"),
        ("session.drain", "run:stop"),
        ("shadow.drain", "run:stop"),
        ("shadow.archive", "run:drain"),
    ],
)
def test_reserved_financial_control_target_rejects_unrelated_operation(operation, target):
    from polysia.control.scoped_operations import ScopedPreview

    with pytest.raises(ValueError, match="target_kind"):
        ScopedPreview(operation, target, 0, "operator", NOW, NOW + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_cash_sizing_releases_only_terminal_buy_reservations(tmp_path):
    from polysia.domain.copytrading.financial_allocation import pending_entry_debit

    harness = Harness(tmp_path)
    try:
        identity = await harness.coordinator.submit(opportunity())
        assert pending_entry_debit(harness.journal.read()) == D("1.01")
        harness.fill(identity)
        assert pending_entry_debit(harness.journal.read()) == 0
        # A confirmed fill spends actual cash; it does not retain the old cash
        # hold after finality. This is separate from unchanged lifetime turnover.
        assert session_ledger(harness.journal.read()).cash < 100
        assert D(harness.journal.read()["turnover"]) == D("1.01")
    finally:
        harness.journal.close()
