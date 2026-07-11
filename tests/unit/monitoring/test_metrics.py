from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.metrics import (
    build_operator_status,
    build_orderbook_metrics,
    build_portfolio_metrics,
    build_runtime_safety_metrics,
)
from polysia.orderbook.book import LocalOrderBook
from polysia.portfolio.positions import PositionLedger
from polysia.risk.kill_switch import KillSwitch


def test_runtime_safety_metrics_are_sanitized() -> None:
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1,token-2",
        POLYMARKET_LIVE_MAX_ORDER_SIZE="0.5",
        POLYMARKET_LIVE_MAX_ORDER_NOTIONAL="0.25",
        POLYMARKET_LIVE_MAX_OPEN_ORDERS=2,
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )

    payload = build_runtime_safety_metrics(settings).to_dict()

    assert payload["private_key_configured"] is True
    assert payload["funder_address_configured"] is True
    assert payload["wallet_address_configured"] is True
    assert payload["live_token_allowlist_count"] == 2
    assert payload["live_max_order_size"] == "0.5"
    assert "not-for-output" not in str(payload)
    assert "0xwallet" not in str(payload)
    assert "token-1" not in str(payload)


def test_operator_status_blocks_default_settings() -> None:
    status = build_operator_status(
        settings=AppSettings(),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )

    payload = status.to_dict()

    assert payload["status"] == "blocked"
    assert payload["tiny_live_orders_ready"] is False
    assert "TRADING_MODE is not LIVE" in payload["warnings"]
    assert payload["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_operator_status_ready_when_all_live_guards_are_configured() -> None:
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        **{"POLYMARKET_PRIVATE_KEY": "configured"},
    )

    status = build_operator_status(settings=settings)

    assert status.status == "ok"
    assert status.tiny_live_orders_ready is True
    assert status.warnings == ()


def test_operator_status_includes_kill_switch_warning() -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual stop")
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-1",
        **{"POLYMARKET_PRIVATE_KEY": "configured"},
    )

    status = build_operator_status(settings=settings, kill_switch=kill_switch)

    assert status.status == "blocked"
    assert status.kill_switch_active is True
    assert status.kill_switch_reason == "manual stop"
    assert "kill switch is active" in status.warnings


def test_orderbook_metrics_summarize_local_book() -> None:
    book = LocalOrderBook(token_id="token-1")
    book.apply_snapshot(
        bids=((Decimal("0.40"), Decimal("3")), (Decimal("0.39"), Decimal("1"))),
        asks=((Decimal("0.45"), Decimal("2")),),
    )

    metrics = build_orderbook_metrics(book).to_dict()

    assert metrics == {
        "ask_depth": "2",
        "ask_level_count": 1,
        "best_ask": "0.45",
        "best_bid": "0.40",
        "bid_depth": "3",
        "bid_level_count": 2,
        "imbalance": "0.6",
        "microprice": "0.43",
        "mid": "0.425",
        "spread": "0.05",
        "token_id": "token-1",
    }


def test_portfolio_metrics_summarize_pnl() -> None:
    ledger = PositionLedger(cash=Decimal("10"))
    ledger.apply_fill(
        type(
            "Fill",
            (),
            {
                "token_id": "token-1",
                "side": "BUY",
                "price": Decimal("0.40"),
                "size": Decimal("5"),
            },
        )()
    )

    metrics = build_portfolio_metrics(ledger, {"token-1": Decimal("0.50")}).to_dict()

    assert metrics == {
        "cash": "8.00",
        "gross_market_value": "2.50",
        "position_count": 1,
        "realized_pnl": "0",
        "total_equity": "10.50",
        "unrealized_pnl": "0.50",
    }
