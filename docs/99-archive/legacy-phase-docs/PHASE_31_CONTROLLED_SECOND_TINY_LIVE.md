# Phase 31 Controlled Second Tiny Live

Phase 31 adds a stricter dry-run-first command for a possible second tiny live
test. It defaults to dry-run and allows at most one real order attempt only when
the operator supplies every required live gate and both acknowledgement flags.

Dry-run example:

```powershell
python -m pm_trader.cli controlled-second-tiny-live `
  --auto-btc-5m `
  --side BUY `
  --outcome YES `
  --max-notional 1.00 `
  --order-type FOK `
  --dry-run `
  --output-dir .\release-artifacts
```

Generated artifacts:

- `release-artifacts/controlled-second-tiny-live.json`
- `release-artifacts/controlled-second-tiny-live.md`

Real submit remains blocked unless all gates are true:

- `TRADING_MODE=LIVE`
- `LIVE_TRADING_ENABLED=true`
- explicit `--submit`
- `--i-understand-this-places-real-orders`
- `--i-confirm-this-is-the-second-controlled-tiny-live-test`
- kill switch inactive
- official geoblock check allowed
- signer configured
- funder configured
- balance readable
- approval readable
- selected token allowlisted
- selected market is BTC Up/Down 5m
- risk approval passes
- max notional is at most `1.00`
- order type is `FOK` or `FAK`

Safety rules:

- Dry-run by default.
- Exactly one live order attempt maximum.
- No retry.
- No loop.
- No strategy automation.
- No market making.
- No automatic size increase.
- No fallback order.
- Reports do not include token IDs, wallet addresses, transaction hashes,
  private keys, API credentials, signed payloads, or raw secrets.
