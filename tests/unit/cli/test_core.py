from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from polysia.adapters.polymarket.public import PolymarketPublicAdapterError
from polysia.cli import app
from polysia.domain.market import MarketSummary

runner = CliRunner()


def test_health_command_returns_safe_payload(monkeypatch) -> None:
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_WALLET_ADDRESS", raising=False)
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)

    result = runner.invoke(app, ["system", "health"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["trading_mode"] == "DATA_ONLY"
    assert payload["live_trading_enabled"] is False
    assert payload["live_trading_allowed"] is False
    assert "polymarket_private_key" not in payload


def test_discover_markets_command_prints_active_markets(monkeypatch) -> None:
    class FakeAdapter:
        async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]:
            assert page_size == 3
            return [
                MarketSummary(
                    id="123",
                    slug="example-market",
                    question="Will this test pass?",
                    category="Testing",
                )
            ]

    monkeypatch.setattr("polysia.cli_commands.core.PolymarketPublicAdapter", FakeAdapter)

    result = runner.invoke(app, ["market", "discover", "--limit", "3"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["count"] == 1
    assert payload["markets"][0]["slug"] == "example-market"


def test_discover_markets_command_handles_adapter_errors(monkeypatch) -> None:
    class FakeAdapter:
        async def list_active_markets(self, page_size: int = 20) -> list[MarketSummary]:
            raise PolymarketPublicAdapterError("Could not list active Polymarket markets.")

    monkeypatch.setattr("polysia.cli_commands.core.PolymarketPublicAdapter", FakeAdapter)

    result = runner.invoke(app, ["market", "discover", "--limit", "3"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"


def test_stream_market_command_delegates_to_async_runner(monkeypatch) -> None:
    calls = []

    async def fake_stream_market(
        *,
        token_id: str,
        max_events: int | None,
        stale_after_seconds: float,
    ) -> None:
        calls.append(
            {
                "max_events": max_events,
                "stale_after_seconds": stale_after_seconds,
                "token_id": token_id,
            }
        )

    monkeypatch.setattr("polysia.cli_commands.core._stream_market", fake_stream_market)

    result = runner.invoke(
        app,
        [
            "market",
            "stream",
            "--token-id",
            "token-1",
            "--max-events",
            "2",
            "--stale-after-seconds",
            "4",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "max_events": 2,
            "stale_after_seconds": 4.0,
            "token_id": "token-1",
        }
    ]


def test_paper_trade_command_runs_local_simulation() -> None:
    result = runner.invoke(
        app,
        [
            "research",
            "paper-trade",
            "--token-id",
            "token-1",
            "--best-bid",
            "0.49",
            "--bid-size",
            "100",
            "--best-ask",
            "0.52",
            "--ask-size",
            "10",
            "--order-size",
            "1",
            "--initial-cash",
            "100",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["orders"][0]["order"]["status"] == "FILLED"
    assert payload["orders"][0]["order"]["side"] == "BUY"
    assert payload["positions"]["token-1"]["size"] == "1"


def test_paper_trade_command_supports_passive_market_maker() -> None:
    result = runner.invoke(
        app,
        [
            "research",
            "paper-trade",
            "--strategy",
            "passive-market-maker",
            "--token-id",
            "token-1",
            "--best-bid",
            "0.40",
            "--bid-size",
            "100",
            "--best-ask",
            "0.50",
            "--ask-size",
            "10",
            "--order-size",
            "1",
            "--min-edge",
            "0.05",
            "--initial-cash",
            "100",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["orders"][0]["order"]["status"] == "ACCEPTED"
    assert payload["orders"][0]["order"]["side"] == "BUY"
    assert payload["positions"] == {}


def test_backtest_jsonl_command_replays_local_file(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event_type": "book",
                "payload": {
                    "asks": [{"price": "0.50", "size": "1"}],
                    "bids": [{"price": "0.40", "size": "10"}],
                },
                "raw_payload": {},
                "received_at": "2026-01-01T00:00:00+00:00",
                "source": "polymarket",
                "token_id": "token-1",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "research",
            "backtest",
            "--input",
            str(events_path),
            "--initial-cash",
            "100",
            "--order-size",
            "1",
            "--min-edge",
            "0.01",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["events_processed"] == 1
    assert payload["fills_created"] == 1
    assert payload["positions"]["token-1"]["size"] == "1"


def test_backtest_jsonl_command_supports_passive_market_maker(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event_type": "book",
                "payload": {
                    "asks": [{"price": "0.50", "size": "1"}],
                    "bids": [{"price": "0.40", "size": "10"}],
                },
                "raw_payload": {},
                "received_at": "2026-01-01T00:00:00+00:00",
                "source": "polymarket",
                "token_id": "token-1",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "research",
            "backtest",
            "--input",
            str(events_path),
            "--strategy",
            "passive-market-maker",
            "--initial-cash",
            "100",
            "--order-size",
            "1",
            "--min-edge",
            "0.05",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["intents_generated"] == 1
    assert payload["orders"][0]["order"]["status"] == "ACCEPTED"
    assert payload["fills_created"] == 0


def test_backtest_jsonl_command_handles_bad_input(tmp_path: Path) -> None:
    events_path = tmp_path / "bad.jsonl"
    events_path.write_text("{bad", encoding="utf-8")

    result = runner.invoke(app, ["research", "backtest", "--input", str(events_path)])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "invalid JSON" in payload["message"]
