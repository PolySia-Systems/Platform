# Recorded Paper Backtest Economics

**CURRENT.** The generic `polysia research backtest` command accepts local
JSONL market events and an optional versioned JSON evidence file. It runs a
strategy through Risk and the Paper broker. It does not use the prospective
Research/Runner evidence pipeline, authorize an experiment, or call Live APIs.

Run a local replay with recorded fee and terminal evidence:

```powershell
polysia research backtest --input EVENTS.jsonl --evidence EVIDENCE.json
```

The minimal `paper-backtest-evidence-v1` file is:

```json
{
  "schema_version": "paper-backtest-evidence-v1",
  "market_id": "market-1",
  "token_ids": ["yes-token", "no-token"],
  "cutoff_at": "2026-01-02T00:00:00+00:00",
  "fee_snapshots": [
    {
      "market_id": "market-1",
      "token_id": "yes-token",
      "observed_at": "2025-12-31T23:59:59+00:00",
      "source_id": "recorded-fee-1",
      "fee_schedule": {"enabled": false}
    }
  ],
  "terminal": {
    "market_id": "market-1",
    "observed_at": "2026-01-02T00:00:00+00:00",
    "source_id": "recorded-terminal-1",
    "closed": true,
    "outcomes": [
      {"token_id": "yes-token", "label": "Yes", "price": "1"},
      {"token_id": "no-token", "label": "No", "price": "0"}
    ]
  }
}
```

For a fee-enabled market, replace `fee_schedule` with
`{"enabled": true, "rate": "0.10", "exponent": "1", "taker_only": true}`
using the values recorded for that market and token. A verified fee-free
schedule needs explicit `enabled: false`. Unknown, partial, or ambiguous fee
evidence is rejected. Each token with market events needs a fee snapshot at or
before its first event; later snapshots apply only to later events. Event rows
must be ordered by their timezone-aware replay clock. All event tokens and fee
snapshots must match the declared market/token set and cutoff. The operator
must retain the source records named by `source_id`; the JSON alone does not
authenticate them.

Set `terminal` to `null` when verified terminal evidence is unavailable. The
result then has `settlement_status: UNRESOLVED` and
`economics_status: RECORDED_UNRESOLVED_TERMINAL`. A terminal observation must
fall after the last event and no later than the cutoff, identify the same
market and complete token set, and contain a verified closed binary 0/1
outcome. Invalid terminal evidence is rejected. With no `--evidence`, fills
requiring unknown fees remain rejected and the command marks economics
`NOT_READY_MISSING_RECORDED_FEES`. Recorded evidence cannot be paired with
`--max-events`, which would truncate the validated interval.

Paper `realized_pnl` and `unrealized_pnl` are gross. `fees` are charged once
per fill. `net_pnl = realized_pnl + unrealized_pnl - fees`; `cash` includes
fill and settlement cash flows, and `total_equity = cash + gross_market_value`.
`valuation_complete` states whether every open token has a mark. Risk's
`daily_pnl` is that UTC day's realized gross P&L less that day's fees, using
the execution/replay clock; unrealized marks do not enter its existing daily
loss comparison. A terminal outcome is applied once per open position. The
standalone `research paper-trade` demo has no evidence interface and always
marks its output `NOT_READY_MISSING_FEE_AND_TERMINAL_EVIDENCE`.
