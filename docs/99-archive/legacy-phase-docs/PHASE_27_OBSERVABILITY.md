# Phase 27 Observability Hardening

Phase 27 adds a sanitized, dashboard-friendly observability snapshot. It is
read-only and does not place orders, cancel orders, retry, loop, run strategies,
or enable live trading.

Run:

```powershell
python -m pm_trader.cli observability-snapshot --output-dir .\release-artifacts
```

The command writes:

- `release-artifacts/observability-snapshot.json`
- `release-artifacts/observability-snapshot.md`
- `release-artifacts/observability-dashboard.html`

The snapshot includes:

- trading mode
- live enabled flag
- kill switch status
- allowed live path readiness
- public data status
- stream health when available
- orderbook freshness when available
- paper trading status
- backtest or strategy evaluation status
- open order read status when available
- last tiny live result summary
- latency metrics
- health counters
- warning count
- blocking reason count

Safety rules:

- No live submit path.
- No live cancel path.
- No live strategy loop.
- No market making.
- No raw token IDs.
- No wallet addresses.
- No transaction hashes.
- No private keys or API credentials.
- No signed payloads.

