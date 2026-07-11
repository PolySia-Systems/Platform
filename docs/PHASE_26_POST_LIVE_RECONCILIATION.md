# Phase 26 Post-Live Reconciliation

Phase 26 verifies the project state after a successful tiny live fill without
placing, cancelling, retrying, or preparing any live order.

Run:

```powershell
python -m pm_trader.cli post-live-reconciliation --output-dir .\release-artifacts
```

The command writes:

- `release-artifacts/post-live-reconciliation.json`
- `release-artifacts/post-live-reconciliation.md`

The report includes sanitized release state:

- branch, latest commit, and git clean status
- trading mode and live enabled flag
- kill switch status
- deployment readiness and final handoff availability
- tiny live execution summary
- live attempt count and order submitted flag
- order type, side/outcome, and max notional
- open order count when readable
- account readability, balance readability, approval readability, positive
  approval count, and position count
- geoblock status
- signer/funder configured booleans only
- token allowlist count only
- reconciliation status, blockers, warnings, and next steps

Safety rules:

- No live submit path.
- No live cancel path.
- No retry.
- No loop.
- No market making.
- No token IDs, wallet addresses, transaction hashes, API credentials, private
  keys, signed payloads, or allowlist values in reports.

Status rules:

- `blocked` if the kill switch is active.
- `blocked` if `LIVE_TRADING_ENABLED=true` after post-live testing.
- `blocked` if generated artifacts contain sensitive values.
- `blocked` if open orders remain after the tiny live execution.
- `warning` if account status or open orders cannot be read.
- `ready` only when no blockers or warnings remain.

