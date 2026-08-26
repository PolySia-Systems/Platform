from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from polysia.domain.copytrading import LeaderTradeAction
from polysia.domain.copytrading.continuous_shadow import (
    calculate_verified_taker_fee,
    verified_settlement_prices,
    walk_order_book,
)
from polysia.domain.market import (
    MarketDetails,
    MarketFeeSchedule,
    MarketOrderBookSnapshot,
    MarketOutcomeSummary,
    OrderBookLevel,
)

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)


def _book() -> MarketOrderBookSnapshot:
    return MarketOrderBookSnapshot(
        token_id="token-yes",
        market_id="condition-1",
        timestamp=NOW,
        bids=(OrderBookLevel(price=Decimal("0.39"), size=Decimal("4")),),
        asks=(
            OrderBookLevel(price=Decimal("0.41"), size=Decimal("2")),
            OrderBookLevel(price=Decimal("0.42"), size=Decimal("3")),
        ),
        minimum_order_size=Decimal("1"),
        tick_size=Decimal("0.01"),
    )


def test_verified_market_fee_uses_official_price_curve_not_flat_percentage() -> None:
    market = MarketDetails(
        id="market-1",
        condition_id="condition-1",
        fee_schedule=MarketFeeSchedule(
            enabled=True,
            rate=Decimal("0.04"),
            exponent=Decimal("1"),
            taker_only=True,
        ),
    )

    evidence = calculate_verified_taker_fee(
        market,
        price=Decimal("0.50"),
        size=Decimal("100"),
    )

    assert evidence.status == "VERIFIED"
    assert evidence.amount == Decimal("1.00000")
    assert evidence.source == "official_sdk_market_feeSchedule"


def test_missing_or_incomplete_fee_provenance_stays_unknown() -> None:
    missing = calculate_verified_taker_fee(
        None,
        price=Decimal("0.50"),
        size=Decimal("10"),
    )
    incomplete = calculate_verified_taker_fee(
        MarketDetails(
            id="market-1",
            fee_schedule=MarketFeeSchedule(enabled=True, rate=Decimal("0.04")),
        ),
        price=Decimal("0.50"),
        size=Decimal("10"),
    )

    assert missing.amount is None and missing.status == "UNKNOWN"
    assert incomplete.amount is None and incomplete.status == "UNKNOWN"


def test_shared_book_walk_never_reuses_consumed_depth_and_allows_partial_fill() -> None:
    consumed: dict[Decimal, Decimal] = {}
    first = walk_order_book(
        _book(),
        action=LeaderTradeAction.BUY,
        requested_size=Decimal("4"),
        already_consumed=consumed,
    )
    for price, size in first.consumed:
        consumed[price] = consumed.get(price, Decimal("0")) + size
    second = walk_order_book(
        _book(),
        action=LeaderTradeAction.BUY,
        requested_size=Decimal("4"),
        already_consumed=consumed,
    )

    assert first.filled_size == Decimal("4")
    assert second.filled_size == Decimal("1")
    assert sum(size for _, size in (*first.consumed, *second.consumed)) == Decimal("5")


def test_settlement_requires_closed_complete_exact_zero_one_outcomes() -> None:
    verified = MarketDetails(
        id="market-1",
        closed=True,
        outcomes=(
            MarketOutcomeSummary(label="Yes", token_id="yes", price=Decimal("1")),
            MarketOutcomeSummary(label="No", token_id="no", price=Decimal("0")),
        ),
    )
    ambiguous = verified.model_copy(
        update={
            "outcomes": (
                MarketOutcomeSummary(label="Yes", token_id="yes", price=Decimal("0.9")),
                MarketOutcomeSummary(label="No", token_id="no", price=Decimal("0.1")),
            )
        }
    )

    assert verified_settlement_prices(verified) == {
        "yes": Decimal("1"),
        "no": Decimal("0"),
    }
    assert verified_settlement_prices(ambiguous) is None


def test_adverse_drift_is_disabled_in_the_baseline_policy() -> None:
    from polysia.domain.copytrading.continuous_shadow import adverse_price_drift_exceeded

    assert (
        adverse_price_drift_exceeded(
            action=LeaderTradeAction.BUY,
            price_movement=Decimal("1"),
            gross_notional=Decimal("10"),
            maximum_ratio=None,
        )
        is False
    )
    assert (
        adverse_price_drift_exceeded(
            action=LeaderTradeAction.BUY,
            price_movement=Decimal("1"),
            gross_notional=Decimal("10"),
            maximum_ratio=Decimal("0.05"),
        )
        is True
    )


def test_walk_forward_does_not_use_future_fills_for_wallet_evidence() -> None:
    from datetime import timedelta

    from polysia.domain.copytrading.continuous_shadow_experiments import (
        RecordedShadowFill,
        walk_forward_policy_report,
    )

    fills = tuple(
        RecordedShadowFill(
            evaluated_at=NOW + timedelta(hours=index),
            wallet_id="wallet-a",
            pool_class="ALPHA",
            action=LeaderTradeAction.BUY,
            leader_price=Decimal("0.40"),
            follower_price=Decimal("0.41"),
            filled_size=Decimal("5"),
            gross_notional=Decimal("2.05"),
            fee=Decimal("0.01"),
            price_movement=Decimal("0.05"),
            spread_cost=Decimal("0.01"),
            depth_impact=Decimal("0"),
            realized_pnl=None,
            status="SIMULATED",
        )
        for index in range(6)
    )
    report = walk_forward_policy_report(fills, split_at=NOW + timedelta(hours=2))
    wallet_policy = next(
        item for item in report["policies"] if item["policy_id"] == "wallet-min-evidence-3"
    )

    assert report["look_ahead"] is False
    assert report["claim"] == "not_a_profitability_or_live_promotion_result"
    assert wallet_policy["in_sample"]["buy_count"] == 0
    assert wallet_policy["out_of_sample"]["buy_count"] == 3
