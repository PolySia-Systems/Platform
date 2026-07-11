# Phase 30 Tiny Live Read-Only Monitor

Phase 30 adds a read-only monitor for the tiny live account and project state.
It does not submit orders, cancel orders, retry, loop strategy logic, or market
make.

Run one read-only cycle:

```powershell
python -m pm_trader.cli tiny-live-monitor --output-dir .\release-artifacts --redact-secrets
```

Optional scoped checks:

```powershell
python -m pm_trader.cli tiny-live-monitor `
  --auto-btc-5m `
  --max-cycles 1 `
  --interval-seconds 30 `
  --output-dir .\release-artifacts `
  --redact-secrets
```

Generated artifacts:

- `release-artifacts/tiny-live-monitor.json`
- `release-artifacts/tiny-live-monitor.md`

The report includes:

- trading mode and live enabled flag
- kill switch status
- sanitized geoblock status
- signer and funder configured booleans
- balance and approval readability booleans
- open order readability and count only
- account status readability
- latest tiny live execution summary if available
- deployment readiness status if available
- post-live reconciliation status if available
- observability snapshot status if available
- blocking reasons and warnings

Safety rules:

- Read-only only.
- No live submit.
- No live cancel.
- No live strategy loop.
- No live market making.
- No automatic retry.
- Default max cycles is `1`.
- Minimum interval is `30` seconds.
- Reports do not include token IDs, wallet addresses, transaction hashes,
  private keys, API credentials, or signed payloads.
