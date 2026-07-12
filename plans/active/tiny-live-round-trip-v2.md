# Tiny Live Round-Trip v2 ExecPlan

## Control

| Field | Value |
|---|---|
| Task ID | `POLYSIA-LIVE-002` |
| Status | IMPLEMENTATION AND PREFLIGHT |
| Baseline | `main` at `4a8632bf268e664f8191dfacfeeedcfe8a13dbe1` |
| Strategy | `btc-15m-favorite-take-profit` version `0.2.0` |
| Owner authorization | One real BTC 15-minute entry attempt, all-in cap `10.00`, then one GTC exit at actual fill price times `1.10` |

## Scope and safety

Raise only this bounded round-trip authorization from `1.00` to `10.00` so the
venue minimum can be satisfied. Preserve the one-market, one-position,
one-entry-attempt, FOK entry, actual-fill reconciliation, one GTC exit, dynamic
allowlist, geoblock, account, kill-switch, synchronized-main, green-CI, and
durable checkpoint gates.

The real attempt occurs only after focused and full validation, deliberate
second-pass review, merge, synchronized `main`, authenticated read-only preflight, and an
explicit `POLYSIA-LIVE-002` acknowledgement. Any failed or unreadable gate
produces `NO_TRADE` or `SAFETY_STOP`; no retry or replacement is authorized.

The profit target is a limit price, not guaranteed profit. If the GTC exit is
open, the position remains exposed until filled or manually managed. If a crash
occurs after a fill, the existing fail-closed checkpoint prevents duplicate
entry; automatic exit recovery remains out of scope and requires operator
reconciliation before any manual action.

## Validation and evidence

Run the relevant strategy, Risk, execution, integration, property, CLI, and
architecture tests, then the repository quality gates. Persist sanitized local
JSON and Markdown evidence. Update project status and create a final handoff
with the actual result; never commit credentials, account identifiers, live
balances, token IDs, order IDs, or live evidence artifacts.
