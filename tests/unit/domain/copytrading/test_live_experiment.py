from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polysia.domain.copytrading.live_experiment import (
    CopyExperimentSnapshot,
    CopyExperimentState,
    calculate_entry_quote,
    calculate_realized_pnl,
    calculate_take_profit_price,
    load_candidate_bank,
    signal_is_fresh,
)

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def _addresses(count: int = 102) -> list[str]:
    return [f"0x{index:040x}" for index in range(1, count + 1)]


def test_candidate_bank_requires_exactly_102_unique_valid_addresses() -> None:
    with pytest.raises(ValueError, match="exactly 102"):
        load_candidate_bank("\n".join(_addresses(101)))

    bank = load_candidate_bank("\n".join(_addresses()))

    assert len(bank.aliases_and_addresses) == 102
    assert bank.aliases[0] == "candidate-001"
    assert bank.aliases[-1] == "candidate-102"


def test_candidate_deduplication_preserves_first_seen_order_and_safe_repr() -> None:
    addresses = _addresses()
    text = "\n".join([addresses[0], *addresses, addresses[10]])

    bank = load_candidate_bank(text)

    assert bank.raw_address_count == 104
    assert bank.as_protected_mapping()["candidate-001"] == addresses[0]
    assert addresses[0] not in repr(bank)
    assert addresses[0] not in str(bank.to_safe_dict())


def test_entry_quote_uses_minimum_size_five_percent_offset_and_dynamic_gtd() -> None:
    quote = calculate_entry_quote(
        leader_fill_price=Decimal("0.537"),
        minimum_order_size=Decimal("5"),
        tick_size=Decimal("0.01"),
        best_ask=Decimal("0.53"),
        expected_fee=Decimal("0.01"),
        now=NOW,
        market_end=NOW + timedelta(minutes=10),
    )

    assert quote.raw_price == Decimal("0.51015")
    assert quote.price == Decimal("0.51")
    assert quote.quantity == Decimal("5")
    assert quote.maximum_debit == Decimal("2.56")
    assert quote.cancel_at == NOW + timedelta(seconds=90)
    assert quote.venue_expiration == int((NOW + timedelta(seconds=185)).timestamp())
    assert quote.cancel_at <= NOW + timedelta(minutes=10, seconds=-315)


def test_entry_quote_rejects_late_crossing_and_over_cap_orders() -> None:
    common = {
        "leader_fill_price": Decimal("0.60"),
        "minimum_order_size": Decimal("5"),
        "tick_size": Decimal("0.01"),
        "expected_fee": Decimal("0"),
        "now": NOW,
        "market_end": NOW + timedelta(minutes=8),
    }
    with pytest.raises(ValueError, match="cross"):
        calculate_entry_quote(best_ask=Decimal("0.55"), **common)
    with pytest.raises(ValueError, match="seven minutes"):
        calculate_entry_quote(
            best_ask=Decimal("0.70"),
            **{**common, "market_end": NOW + timedelta(seconds=419)},
        )
    with pytest.raises(ValueError, match="SDK GTD backstop"):
        calculate_entry_quote(
            best_ask=Decimal("0.70"),
            **{**common, "market_end": NOW + timedelta(minutes=8)},
        )
    with pytest.raises(ValueError, match="5.00"):
        calculate_entry_quote(
            best_ask=Decimal("0.99"),
            **{**common, "minimum_order_size": Decimal("10")},
        )


def test_take_profit_rounds_up_and_rejects_impossible_target() -> None:
    assert calculate_take_profit_price(
        Decimal("0.537"),
        tick_size=Decimal("0.01"),
    ) == Decimal("0.60")
    with pytest.raises(ValueError, match="highest valid"):
        calculate_take_profit_price(
            Decimal("0.95"),
            tick_size=Decimal("0.01"),
        )


def test_signal_freshness_enforces_ten_seconds_and_seven_minutes() -> None:
    assert signal_is_fresh(
        executed_at=NOW,
        observed_at=NOW + timedelta(seconds=10),
        market_end=NOW + timedelta(minutes=8),
    )
    assert not signal_is_fresh(
        executed_at=NOW,
        observed_at=NOW + timedelta(seconds=11),
        market_end=NOW + timedelta(minutes=8),
    )
    assert not signal_is_fresh(
        executed_at=NOW,
        observed_at=NOW,
        market_end=NOW + timedelta(seconds=419),
    )


def test_signal_freshness_allows_scoped_four_minute_override() -> None:
    assert signal_is_fresh(
        executed_at=NOW,
        observed_at=NOW + timedelta(seconds=10),
        market_end=NOW + timedelta(seconds=250),
        minimum_seconds_to_end=240,
    )
    assert not signal_is_fresh(
        executed_at=NOW,
        observed_at=NOW,
        market_end=NOW + timedelta(seconds=239),
        minimum_seconds_to_end=240,
    )
    assert not signal_is_fresh(
        executed_at=NOW,
        observed_at=NOW,
        market_end=NOW + timedelta(seconds=240),
    )


def test_concurrency_snapshot_enforces_one_pending_or_one_position_and_exit() -> None:
    CopyExperimentSnapshot(
        state=CopyExperimentState.ENTRY_PENDING,
        total_entry_attempts=1,
        completed_live_cycles=0,
        signal_acceptance_open=True,
        entry_order_id="entry",
    )
    CopyExperimentSnapshot(
        state=CopyExperimentState.EXIT_PENDING,
        total_entry_attempts=1,
        completed_live_cycles=0,
        signal_acceptance_open=True,
        exit_order_id="exit",
        position_size=Decimal("5"),
    )
    with pytest.raises(ValueError, match="cannot coexist"):
        CopyExperimentSnapshot(
            state=CopyExperimentState.EXIT_PENDING,
            total_entry_attempts=1,
            completed_live_cycles=0,
            signal_acceptance_open=True,
            entry_order_id="entry",
            exit_order_id="exit",
            position_size=Decimal("5"),
        )


def test_third_attempt_or_cycle_must_close_signal_acceptance() -> None:
    with pytest.raises(ValueError, match="must close"):
        CopyExperimentSnapshot(
            state=CopyExperimentState.MONITORING,
            total_entry_attempts=3,
            completed_live_cycles=0,
            signal_acceptance_open=True,
        )


@pytest.mark.parametrize(
    ("exit_price", "entry_fee", "exit_fee", "expected_net"),
    [
        (Decimal("0.60"), Decimal("0.01"), Decimal("0.01"), Decimal("0.48")),
        (Decimal("0.50"), Decimal("0"), Decimal("0"), Decimal("0")),
        (Decimal("0.40"), Decimal("0.01"), Decimal("0.01"), Decimal("-0.52")),
        (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("-2.50")),
        (Decimal("1"), Decimal("0"), Decimal("0"), Decimal("2.50")),
    ],
)
def test_fee_adjusted_profit_breakeven_loss_and_resolution(
    exit_price: Decimal,
    entry_fee: Decimal,
    exit_fee: Decimal,
    expected_net: Decimal,
) -> None:
    _gross, net = calculate_realized_pnl(
        entry_price=Decimal("0.50"),
        exit_price=exit_price,
        quantity=Decimal("5"),
        entry_fee=entry_fee,
        exit_fee=exit_fee,
    )

    assert net == expected_net
    with pytest.raises(ValueError, match="must close"):
        CopyExperimentSnapshot(
            state=CopyExperimentState.CLOSED,
            total_entry_attempts=2,
            completed_live_cycles=3,
            signal_acceptance_open=True,
        )
