# Phase 28 Real Data Shadow Run

Phase 28 adds a public-market-data shadow run that uses real public market
selection and realtime stream events, then routes normalized events through the
local orderbook, research strategy, risk engine, and paper broker only.

Run with an explicit market:

```powershell
python -m pm_trader.cli shadow-run-real-data --market-slug MARKET_SLUG --max-events 100 --output-dir .\release-artifacts
```

Or auto-select the current BTC Up/Down 5m market:

```powershell
python -m pm_trader.cli shadow-run-real-data --auto-btc-5m --max-events 100 --output-dir .\release-artifacts
```

Supported strategies:

- `stale-price`
- `passive-market-maker`

Generated artifacts:

- `release-artifacts/shadow-run-real-data.json`
- `release-artifacts/shadow-run-real-data.md`
- `release-artifacts/shadow-run-real-data-events.jsonl`

The command records:

- public stream health
- event count
- orderbook updates
- orderbook freshness
- strategy intent count
- risk approval and denial counts
- paper order and fill counts
- simulated position and PnL
- latency metrics
- warnings for timeout or stream disconnect

Safety rules:

- No live broker.
- No live order submit.
- No live cancel.
- No retry path that can trade.
- No live strategy loop.
- No market making against live APIs.
- Paper broker only.
- Reports do not include token IDs, wallet addresses, transaction hashes,
  private keys, API credentials, or signed payloads.

