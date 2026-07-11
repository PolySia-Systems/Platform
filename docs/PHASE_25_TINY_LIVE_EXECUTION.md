# Phase 25 Tiny Live Execution

Phase 25 adds one tightly controlled tiny live execution command. It is
restricted to an operator-selected BTC Up/Down 5m token and the token must
already be present in `POLYMARKET_LIVE_TOKEN_ALLOWLIST`.

The command defaults to dry-run. Tests and implementation runs must not place
real live orders.

## Command

Dry-run:

```powershell
python -m pm_trader.cli tiny-live-execute `
  --token-id TOKEN_ID_FROM_ALLOWLIST `
  --side BUY `
  --outcome YES `
  --max-notional 1.00 `
  --order-type FAK `
  --market-slug btc-updown-5m-example `
  --dry-run `
  --output-dir .\release-artifacts
```

Real one-attempt command shape:

```powershell
python -m pm_trader.cli tiny-live-execute `
  --token-id TOKEN_ID_FROM_ALLOWLIST `
  --side BUY `
  --outcome YES `
  --max-notional 1.00 `
  --order-type FOK `
  --market-slug btc-updown-5m-example `
  --no-dry-run `
  --require-clean-git `
  --i-understand-this-places-one-real-order `
  --output-dir .\release-artifacts
```

Do not run the real command unless the operator intentionally approves one
real order attempt with the correct environment and allowlist.

## Hard Gates

Real submit requires all of these:

- `TRADING_MODE=LIVE`
- `LIVE_TRADING_ENABLED=true`
- explicit acknowledgement flag
- clean git when `--require-clean-git` is used
- token in `POLYMARKET_LIVE_TOKEN_ALLOWLIST`
- `max_notional <= 1.00`
- `order_type` is `FAK` or `FOK`
- kill switch inactive
- geoblock returns `blocked=false`
- signer configured
- funder configured
- balance and approval readable
- risk engine approval
- no previous submit attempt in this command run

## Invariants

- Exactly one live submit attempt maximum.
- No retry.
- No order loop.
- No strategy loop.
- No market-making loop.
- No automatic size increase.
- No secret, wallet, funder, API key, or signed payload in reports.

## Reports

The command writes:

- `tiny_live_execution.json`
- `tiny_live_execution.md`
- `tiny_live_execution.html`

Reports include the final result, dry-run status, allowlist status, geoblock
status, kill switch status, risk decision, order parameters, submit/fill
summary, attempt count, blocking reasons, warnings, and operator next steps.
