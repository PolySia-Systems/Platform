from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polysia.backtesting.shadow_opportunity_replay import replay_shadow_opportunities

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _row(
    event_id: str, *, book_hash: str, book_at: datetime = NOW,
    side: str = "BUY", fee_enabled: bool = False,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "poll_run_id": "poll-1",
        "source_id": "polymarket:data-api-v2:trades",
        "wallet_id": "wallet-1",
        "market_reference": "condition-1",
        "outcome_reference": "token-1",
        "side": side,
        "price": "0.4" if side == "BUY" else "0.6",
        "size": "10",
        "source_at": (NOW - timedelta(seconds=5)).isoformat(),
        "first_observed_at": (NOW - timedelta(seconds=3)).isoformat(),
        "admission_at": (NOW - timedelta(seconds=1)).isoformat(),
        "decision_at": NOW.isoformat(),
        "selection_digest": "a" * 64,
        "config_digest": "b" * 64,
        "policy_version": "continuous-shadow-policy-v0.2",
        "cost_model_version": "polymarket-fee-depth-delay-v0.2",
        "maximum_quote_age_ms": 30_000,
        "book_at": book_at.isoformat(),
        "book_hash": book_hash,
        "market_token_binding": "VERIFIED",
        "book_levels": [{"price": "0.41" if side == "BUY" else "0.59", "size": "20"}],
        "book_bids": [{"price": "0.39", "size": "20"}],
        "fee_enabled": fee_enabled,
        "fee_rate": "0.02" if fee_enabled else None,
        "fee_exponent": "1" if fee_enabled else None,
        "fee_taker_only": True if fee_enabled else None,
    }


def test_all_opportunities_enter_both_policies_but_shared_depth_is_not_reused() -> None:
    report = replay_shadow_opportunities(
        (_row("first", book_hash="same"), _row("second", book_hash="same")),
        experiment_id="period-1",
    )
    economic = report["report"]
    assert isinstance(economic, dict)
    assert report["opportunity_count"] == 2
    assert economic["eligible_observations"] == 2
    assert economic["evaluated_observations"] == 1
    assert report["excluded_execution_evidence"] == {
        "shared_book_depth_unallocated": 1
    }


def test_future_book_is_unknown_without_lookahead() -> None:
    report = replay_shadow_opportunities(
        (_row("future", book_hash="future", book_at=NOW + timedelta(seconds=1)),),
        experiment_id="period-1",
    )
    economic = report["report"]
    assert isinstance(economic, dict)
    assert economic["eligible_observations"] == 1
    assert economic["evaluated_observations"] == 0
    assert report["excluded_execution_evidence"] == {"future_book": 1}


def test_round_trip_uses_fee_once_for_each_execution() -> None:
    buy = _row("buy", book_hash="buy-book", fee_enabled=True)
    sell = _row("sell", book_hash="sell-book", side="SELL", fee_enabled=True)
    sell["source_at"] = (NOW - timedelta(seconds=1)).isoformat()
    sell["first_observed_at"] = NOW.isoformat()
    sell["admission_at"] = (NOW + timedelta(seconds=1)).isoformat()
    sell["decision_at"] = (NOW + timedelta(seconds=2)).isoformat()
    sell["book_at"] = (NOW + timedelta(seconds=2)).isoformat()
    report = replay_shadow_opportunities((buy, sell), experiment_id="period-1")
    economic = report["report"]
    assert isinstance(economic, dict)
    control = economic["control"]
    assert isinstance(control, dict)
    assert economic["eligible_observations"] == 2
    assert control["remaining_positions"] == []
    gross = Decimal(str(control["gross_pnl"]))
    fees = Decimal(str(control["fees"]))
    slippage = Decimal(str(control["slippage"]))
    net = Decimal(str(control["net_pnl"]))
    assert fees > 0
    assert gross - fees - slippage == net


def test_partial_depth_is_reported_without_inventing_full_fill() -> None:
    row = _row("partial", book_hash="partial-book")
    row["book_levels"] = [{"price": "0.41", "size": "2"}]
    report = replay_shadow_opportunities((row,), experiment_id="period-1")
    economic = report["report"]
    assert isinstance(economic, dict)
    assert economic["evaluated_observations"] == 1
    control = economic["control"]
    assert isinstance(control, dict)
    assert control["partially_filled"] == 1


def test_verified_terminal_settlement_values_inventory_once() -> None:
    row = _row("buy", book_hash="buy-book")
    terminal = {
        "market_reference": "condition-1",
        "outcome_reference": "token-1",
        "price": "1",
        "observed_at": (NOW + timedelta(minutes=1)).isoformat(),
        "poll_run_id": "settlement-poll",
    }
    report = replay_shadow_opportunities(
        (row,), experiment_id="period-1", settlements=(terminal, terminal)
    )["report"]
    assert isinstance(report, dict)
    control = report["control"]
    assert isinstance(control, dict)
    assert control["valuation_status"] == "MEASURED"
    once = replay_shadow_opportunities(
        (row,), experiment_id="period-1", settlements=(terminal,)
    )["report"]
    assert isinstance(once, dict)
    assert control["net_pnl"] == once["control"]["net_pnl"]
    assert Decimal(str(control["net_pnl"])) > 0
