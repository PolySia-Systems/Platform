# Phase 36 Controlled Manual Intervention Live Test

Phase 36 adds a guarded harness for a future manual-intervention live test. The
command defaults to dry-run and must not be run live without a separate operator
approval.

## Goal

The real test, when separately approved, sends exactly one tiny BTC Up/Down 5m
order with a maximum notional of 1 USDC. After that single submit attempt, the
system stops all trading behavior and polls reconciliation read-only. The
operator manually cancels the open order or closes the resulting position from
the Polymarket website. The system then detects the mismatch through Phase 35
reconciliation and reports `MANUAL_INTERVENTION_DETECTED`.

## Command

Dry-run first:

```powershell
python -m pm_trader.cli manual-intervention-live-test --auto-btc-5m --outcome YES --side BUY --max-notional 1.00 --order-type FOK --dry-run --output-dir .\release-artifacts
```

The real path requires `--no-dry-run`,
`--i-understand-this-places-one-real-order`, and
`--i-will-manually-cancel-or-close`, plus existing LIVE mode, live enabled,
allowlist, signer/funder, geoblock, and risk guardrails.

## Safety Rules

- One live order attempt maximum.
- No retry.
- No looped trading.
- No strategy automation.
- No live market making.
- No automatic cancel.
- No automatic repair by trading.
- After submit, only read-only reconciliation polling is allowed.
- Manual intervention detection pauses trading and requires acknowledgement.

## Reports

The command writes:

- `release-artifacts/manual-intervention-live-test.json`
- `release-artifacts/manual-intervention-live-test.md`

Reports are sanitized. They must not contain private keys, wallet addresses,
full token IDs, transaction hashes, raw signed payloads, API credentials,
allowlist values, or environment secrets.

## Current Status

Phase 36 implementation supports dry-run verification. The real 1 USDC
manual-intervention test must only be run after reviewing the dry-run report and
receiving explicit operator approval.
