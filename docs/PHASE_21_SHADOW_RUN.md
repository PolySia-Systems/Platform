# Phase 21 Real-Time Shadow Run Reports

Phase 21 adds repeatable shadow-run reporting for market observation without
live trading. The default implementation uses deterministic mocked public
market events so local tests and operator checks are stable. The path remains
paper-only.

## Command

```powershell
python -m pm_trader.cli shadow-run
```

Useful options:

```powershell
python -m pm_trader.cli shadow-run `
  --duration-minutes 1 `
  --sample-interval-seconds 10 `
  --max-events 6 `
  --strategy stale-price `
  --output-dir release-artifacts
```

## Safety Rules

- No live order is placed.
- No live cancel is sent.
- The live broker is not used.
- `LIVE_TRADING_ENABLED=true` blocks the command.
- Strategy intents go through the risk engine.
- Only the paper broker handles approved intents.
- Reports are sanitized and do not include secrets, wallet addresses, funder
  addresses, API keys, or signed payloads.

## Metrics

The shadow-run report includes:

- start time, end time, and duration
- selected market and selected token status
- event count and event rate
- stream health, reconnect count, and stale event count
- orderbook updates
- best bid/ask, spread, mid, and microprice observation counts
- strategy intent count
- risk approval and rejection counts
- paper order and fill counts
- paper position
- realized, unrealized, and total paper PnL
- max drawdown
- average, p95, and p99 decision latency

## Outputs

The command writes:

- `shadow_run.json`
- `shadow_run.md`
- `shadow_run.html`
- `shadow_run_timeseries.jsonl`

If no format flags are passed, JSON, Markdown, and HTML reports are all
written. If one or more of `--json`, `--markdown`, or `--html` is passed, only
the selected report formats are written. The time-series JSONL file is always
written.

## Classification

The final classification is one of:

- `SHADOW_HEALTHY`
- `SHADOW_DEGRADED`
- `SHADOW_FAILED`

`SHADOW_HEALTHY` means the paper-only path exercised market events, orderbook
updates, strategy, risk evaluation, paper fills, position updates, and PnL. It
does not approve live trading.

