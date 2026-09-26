from __future__ import annotations

import json
from decimal import Decimal
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
    assert payload["orders"][0]["order"]["status"] == "REJECTED"
    assert payload["orders"][0]["order"]["reason"] == "market_specific_fee_provenance_unknown"
    assert payload["orders"][0]["order"]["side"] == "BUY"
    assert payload["positions"] == {}
    assert payload["economics_status"] == "NOT_READY_MISSING_FEE_AND_TERMINAL_EVIDENCE"


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
    assert payload["fills_created"] == 0
    assert payload["orders"][0]["order"]["status"] == "REJECTED"
    assert payload["orders"][0]["order"]["reason"] == "market_specific_fee_provenance_unknown"
    assert payload["positions"] == {}
    assert payload["settlement_status"] == "UNRESOLVED"
    assert payload["economics_status"] == "NOT_READY_MISSING_RECORDED_FEES"


def test_backtest_cli_uses_recorded_fees_and_settles_once(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps({
            "event_type": "book",
            "payload": {
                "asks": [{"price": "0.50", "size": "1"}],
                "bids": [{"price": "0.40", "size": "10"}],
            },
            "raw_payload": {},
            "received_at": "2026-01-01T00:00:00+00:00",
            "source": "polymarket",
            "token_id": "token-1",
        }), encoding="utf-8",
    )
    evidence_path = tmp_path / "evidence.json"
    manifest = {
        "schema_version": "paper-backtest-evidence-v1",
        "market_id": "market-1",
        "token_ids": ["token-1", "token-2"],
        "cutoff_at": "2026-01-02T00:00:00+00:00",
        "fee_snapshots": [{
            "market_id": "market-1", "token_id": "token-1",
            "observed_at": "2025-12-31T23:59:59+00:00",
            "source_id": "fixture-fee", "fee_schedule": {"enabled": False},
        }],
        "terminal": {
            "market_id": "market-1", "observed_at": "2026-01-02T00:00:00+00:00",
            "source_id": "fixture-terminal", "closed": True,
            "outcomes": [
                {"token_id": "token-1", "label": "Yes", "price": "1"},
                {"token_id": "token-2", "label": "No", "price": "0"},
            ],
        },
    }
    evidence_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = runner.invoke(app, [
        "research", "backtest", "--input", str(events_path), "--evidence", str(evidence_path),
        "--initial-cash", "100", "--order-size", "1", "--min-edge", "0.01",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["fills_created"] == 1
    assert payload["orders"][0]["order"]["status"] == "FILLED"
    assert payload["settlement_status"] == "APPLIED"
    assert payload["economics_status"] == "RECORDED_SETTLED"
    assert payload["fees"] == "0"
    assert payload["realized_pnl"] == "0.50"
    assert payload["net_pnl"] == "0.50"
    assert payload["final_cash"] == "100.50"
    assert payload["portfolio"]["total_equity"] == "100.50"
    assert len([row for row in payload["audit_log"] if row["event"] == "settlement"]) == 1

    manifest["fee_snapshots"][0]["fee_schedule"] = {
        "enabled": True, "rate": "0.10", "exponent": "1", "taker_only": True,
    }
    evidence_path.write_text(json.dumps(manifest), encoding="utf-8")
    fee_result = runner.invoke(app, [
        "research", "backtest", "--input", str(events_path), "--evidence", str(evidence_path),
        "--initial-cash", "100", "--order-size", "1", "--min-edge", "0.01",
    ])
    assert fee_result.exit_code == 0
    fee_payload = json.loads(fee_result.stdout)
    assert Decimal(fee_payload["fees"]) == Decimal("0.025")
    assert fee_payload["realized_pnl"] == "0.50"
    assert Decimal(fee_payload["net_pnl"]) == Decimal("0.475")
    assert Decimal(fee_payload["final_cash"]) == Decimal("100.475")

    manifest["terminal"] = None
    evidence_path.write_text(json.dumps(manifest), encoding="utf-8")
    unresolved = runner.invoke(app, [
        "research", "backtest", "--input", str(events_path), "--evidence", str(evidence_path),
        "--initial-cash", "100", "--order-size", "1", "--min-edge", "0.01",
    ])
    assert unresolved.exit_code == 0
    unresolved_payload = json.loads(unresolved.stdout)
    assert unresolved_payload["settlement_status"] == "UNRESOLVED"
    assert unresolved_payload["economics_status"] == "RECORDED_UNRESOLVED_TERMINAL"
    assert Decimal(unresolved_payload["final_cash"]) == Decimal("99.475")


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
