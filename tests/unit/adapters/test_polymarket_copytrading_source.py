from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polysia.adapters.polymarket.copytrading_source import (
    DATA_API_BASE_URL,
    GAMMA_API_BASE_URL,
    PolymarketCopyTradingSource,
)
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeAction,
    classify_position_effects,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "copytrading"
WALLET = "0x1111111111111111111111111111111111111111"
OBSERVED_AT = datetime(2026, 7, 28, 16, 31, tzinfo=UTC)
START_AT = datetime(2026, 7, 28, 16, 15, tzinfo=UTC)
END_AT = datetime(2026, 7, 28, 16, 31, tzinfo=UTC)


class FakeTransport:
    def __init__(
        self,
        trades: list[dict[str, Any]],
        event: list[dict[str, Any]],
    ) -> None:
        self.trades = trades
        self.event = event
        self.calls: list[tuple[str, str, dict[str, str | int | bool]]] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> Any:
        del purpose
        self.calls.append((base_url, path, dict(params)))
        if base_url == GAMMA_API_BASE_URL and path == "/events":
            return deepcopy(self.event)
        if base_url != DATA_API_BASE_URL:
            raise AssertionError("unexpected base URL")
        if path == "/trades":
            if params.get("takerOnly") is True:
                return deepcopy(self.trades[:2])
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", len(self.trades)))
            return deepcopy(self.trades[offset : offset + limit])
        if path == "/activity":
            return deepcopy(self.trades[:4])
        if path == "/positions":
            return [
                {
                    "asset": "111111",
                    "conditionId": (
                        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    ),
                    "size": 0.25,
                },
                {
                    "asset": "222222",
                    "conditionId": (
                        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    ),
                    "size": 2,
                },
            ]
        if path == "/closed-positions":
            return [{"totalBought": 5}]
        raise AssertionError(f"unexpected path: {path}")


@pytest.fixture
def trades() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "polymarket_trades_page.json").read_text(encoding="utf-8"))


@pytest.fixture
def event() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "polymarket_btc15_event.json").read_text(encoding="utf-8"))


@pytest.fixture
def rejected_signal_fixtures() -> list[dict[str, Any]]:
    return json.loads(
        (FIXTURES / "polymarket_btc15_rejected_signals.json").read_text(encoding="utf-8")
    )


@pytest.mark.asyncio
async def test_normalizes_realistic_response_with_stable_identity_and_no_wallet_leak(
    trades: list[dict[str, Any]],
    event: list[dict[str, Any]],
) -> None:
    transport = FakeTransport(trades, event)
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=transport,
        clock=lambda: OBSERVED_AT,
    )

    first = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=10,
    )
    repeated = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=10,
    )

    assert first.raw_count == 6
    assert first.filtered_count == 0
    assert len(first.events) == 5
    assert first.duplicate_count == 1
    assert [item.event_id for item in first.events] == [item.event_id for item in repeated.events]
    assert first.events[0].executed_price == Decimal("0.52")
    assert first.events[0].trade_action is LeaderTradeAction.SELL
    serialized = repr(first.events)
    assert WALLET not in serialized
    assert trades[0]["transactionHash"] not in serialized
    trade_calls = [call for call in transport.calls if call[1] == "/trades"]
    assert all(call[2]["takerOnly"] is False for call in trade_calls)


@pytest.mark.asyncio
async def test_checkpoint_freezes_window_and_advances_bounded_offset(
    trades: list[dict[str, Any]],
    event: list[dict[str, Any]],
) -> None:
    transport = FakeTransport(trades, event)
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=transport,
        clock=lambda: OBSERVED_AT,
    )
    first = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=2,
    )
    assert first.next_checkpoint is not None

    second = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=2,
        checkpoint=first.next_checkpoint,
    )

    trade_calls = [call for call in transport.calls if call[1] == "/trades"]
    assert trade_calls[-1][2]["offset"] == 2
    assert trade_calls[-1][2]["start"] == int(START_AT.timestamp())
    assert trade_calls[-1][2]["end"] == int(END_AT.timestamp())
    assert {item.event_id for item in first.events}.isdisjoint(
        item.event_id for item in second.events
    )


@pytest.mark.asyncio
async def test_invalid_or_ambiguous_rows_fail_closed(
    trades: list[dict[str, Any]],
    event: list[dict[str, Any]],
) -> None:
    invalid = deepcopy(trades[:2])
    invalid[0].pop("transactionHash")
    invalid[1]["eventSlug"] = "bitcoin-15-minute-by-title-only"
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=FakeTransport(invalid, event),
        clock=lambda: OBSERVED_AT,
    )

    page = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=10,
    )

    assert page.events == ()
    assert page.filtered_count == 1
    assert page.rejected_count == 1


@pytest.mark.asyncio
async def test_market_and_outcome_mapping_uses_condition_and_token_metadata(
    trades: list[dict[str, Any]],
    event: list[dict[str, Any]],
) -> None:
    mismatched = deepcopy(trades[:1])
    mismatched[0]["asset"] = "unverified-token"
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=FakeTransport(mismatched, event),
        clock=lambda: OBSERVED_AT,
    )

    page = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=10,
    )

    assert page.events == ()
    assert page.rejected_count == 1


@pytest.mark.asyncio
async def test_classifies_open_increase_reduce_close_and_unknown(
    trades: list[dict[str, Any]],
    event: list[dict[str, Any]],
) -> None:
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=FakeTransport(trades, event),
        clock=lambda: OBSERVED_AT,
    )
    page = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=10,
    )

    effects = [
        item.position_effect
        for item in classify_position_effects(
            page.events,
            opening_inventory={
                (
                    "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "111111",
                ): Decimal("0")
            },
        )
    ]

    assert effects == [
        LeaderPositionEffect.UNKNOWN,
        LeaderPositionEffect.OPEN,
        LeaderPositionEffect.INCREASE,
        LeaderPositionEffect.REDUCE,
        LeaderPositionEffect.CLOSE,
    ]


@pytest.mark.asyncio
async def test_coverage_probe_includes_maker_delta_and_small_positions(
    trades: list[dict[str, Any]],
    event: list[dict[str, Any]],
) -> None:
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=FakeTransport(trades, event),
        clock=lambda: OBSERVED_AT,
    )

    coverage = await source.probe_source_coverage(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
    )

    assert coverage.all_trade_count == 6
    assert coverage.taker_trade_count == 2
    assert coverage.maker_coverage_delta == 4
    assert coverage.activity_trade_count == 4
    assert coverage.smallest_visible_position == Decimal("0.25")


@pytest.mark.asyncio
async def test_complete_position_baseline_and_verified_market_metadata_are_sanitized(
    trades: list[dict[str, Any]],
    event: list[dict[str, Any]],
) -> None:
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=FakeTransport(trades, event),
        clock=lambda: OBSERVED_AT,
    )
    baseline = await source.read_inventory("leader-001")
    page = await source.read_page(
        "leader-001",
        start_at=START_AT,
        end_at=END_AT,
        page_size=10,
    )
    metadata = source.market_metadata(
        page.events[0].market_reference,
        page.events[0].outcome_reference,
    )

    assert baseline.positions[
        (
            "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "111111",
        )
    ] == Decimal("0.25")
    assert metadata.external_slug == "btc-updown-15m-1785255300"
    assert metadata.outcome_label in {"Up", "Down"}
    assert WALLET not in repr(baseline)


@pytest.mark.asyncio
async def test_four_sanitized_real_signals_pass_corrected_interval_time_mapping(
    rejected_signal_fixtures: list[dict[str, Any]],
) -> None:
    for fixture in rejected_signal_fixtures:
        observed_at = datetime.fromisoformat(str(fixture["observedAt"]).replace("Z", "+00:00"))
        source = PolymarketCopyTradingSource(
            {"leader-001": WALLET},
            transport=FakeTransport([fixture["trade"]], [fixture["event"]]),
            clock=lambda observed_at=observed_at: observed_at,
        )

        page = await source.read_page(
            "leader-001",
            start_at=observed_at - timedelta(hours=1),
            end_at=observed_at + timedelta(seconds=1),
        )

        assert len(page.events) == 1
        metadata = source.market_metadata(
            page.events[0].market_reference,
            page.events[0].outcome_reference,
        )
        child = fixture["event"]["markets"][0]
        assert metadata.starts_at == datetime.fromisoformat(
            child["eventStartTime"].replace("Z", "+00:00")
        )
        assert metadata.ends_at - metadata.starts_at == timedelta(minutes=15)
        assert child["startDate"] != child["eventStartTime"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate_event", "mutate_trade"),
    [
        (lambda child: child.update(eventStartTime="2026-07-29T06:45:00Z"), None),
        (lambda child: child.update(endDate="2026-07-29T07:00:00Z"), None),
        (None, lambda trade: trade.update(conditionId="0x" + ("f" * 64))),
        (None, lambda trade: trade.update(asset="wrong-token")),
        (None, lambda trade: trade.update(outcome="Down")),
        (
            None,
            lambda trade: trade.update(eventSlug="btc-updown-15m-1785307500"),
        ),
    ],
)
async def test_strict_interval_identity_rejects_adjacent_or_mismatched_evidence(
    rejected_signal_fixtures: list[dict[str, Any]],
    mutate_event: Any,
    mutate_trade: Any,
) -> None:
    fixture = deepcopy(rejected_signal_fixtures[0])
    if mutate_event is not None:
        mutate_event(fixture["event"]["markets"][0])
    if mutate_trade is not None:
        mutate_trade(fixture["trade"])
    observed_at = datetime.fromisoformat(fixture["observedAt"].replace("Z", "+00:00"))
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=FakeTransport([fixture["trade"]], [fixture["event"]]),
        clock=lambda: observed_at,
    )

    page = await source.read_page(
        "leader-001",
        start_at=observed_at - timedelta(hours=1),
        end_at=observed_at + timedelta(seconds=1),
    )

    assert page.events == ()
    assert page.rejected_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_start_time", "accepted"),
    [
        ("2026-07-29T06:30:01Z", True),
        ("2026-07-29T06:30:01.001Z", False),
    ],
)
async def test_interval_time_mapping_uses_at_most_one_second_tolerance(
    rejected_signal_fixtures: list[dict[str, Any]],
    event_start_time: str,
    accepted: bool,
) -> None:
    fixture = deepcopy(rejected_signal_fixtures[0])
    fixture["event"]["markets"][0]["eventStartTime"] = event_start_time
    observed_at = datetime.fromisoformat(fixture["observedAt"].replace("Z", "+00:00"))
    source = PolymarketCopyTradingSource(
        {"leader-001": WALLET},
        transport=FakeTransport([fixture["trade"]], [fixture["event"]]),
        clock=lambda: observed_at,
    )

    page = await source.read_page(
        "leader-001",
        start_at=observed_at - timedelta(hours=1),
        end_at=observed_at + timedelta(seconds=1),
    )

    assert bool(page.events) is accepted


def test_source_module_contains_only_get_transport_and_no_mutation_methods() -> None:
    source = (
        PROJECT_ROOT / "src" / "polysia" / "adapters" / "polymarket" / "copytrading_source.py"
    ).read_text(encoding="utf-8")

    assert 'method="GET"' in source
    assert 'method="POST"' not in source
    assert "place_order" not in source
    assert "cancel_order" not in source
