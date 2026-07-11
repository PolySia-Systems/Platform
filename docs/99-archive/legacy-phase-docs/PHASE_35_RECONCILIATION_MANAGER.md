# Phase 35 Reconciliation Manager

Phase 35 adds a professional read-only reconciliation layer for detecting manual
operator intervention and stale internal state.

## Scope

- This phase is read-only.
- It does not place live orders.
- It does not cancel live orders.
- It does not modify live orders.
- It does not add retries.
- It does not add live strategy automation.
- It does not add live market making.
- It does not change live trading behavior.

## Purpose

The reconciliation manager compares internal expected state against actual
external account state when read-only live-account access is explicitly allowed.
It detects cases where an operator manually changes the account from the
Polymarket website, including missing orders, unexpected orders, closed
positions, unexpected fills, stale internal state, failed account reads, and
geoblock/account status failures.

## Safety Behavior

When a mismatch or manual intervention is detected:

- status becomes `blocked`
- trading should pause
- manual acknowledgement is required before further live activity
- a safety pause or kill switch is activated when available
- no automatic repair by trading is attempted
- no live submit or cancel path is called

When live account state cannot be read, the system reports warning or blocked
state depending on runtime severity. Missing account data must never cause
automatic trading.

## Command

```powershell
python -m pm_trader.cli reconcile-account --output-dir .\release-artifacts
```

The command generates:

- `release-artifacts/reconciliation-report.json`
- `release-artifacts/reconciliation-report.md`

In `DATA_ONLY` mode the command stays in safe report mode and does not read live
account data. If live account reads are used in a future review, existing
acknowledgement rules must remain in place.

## Sanitization

Reports include only safe values: counts, booleans, high-level statuses, event
types, timestamps, warnings, and blocking reasons.

Reports must not include private keys, wallet addresses, full token IDs,
transaction hashes, raw signed payloads, API credentials, allowlist values, or
environment secrets.

## Phase 36 Boundary

Phase 35 does not perform the real manual-intervention live test. Any future
controlled live manual-intervention test requires Phase 35 review and explicit
operator approval before Phase 36 begins.
