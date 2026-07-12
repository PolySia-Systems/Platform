# Tiny Live Round-Trip v1 ExecPlan

## Control

| Field | Value |
|---|---|
| Task ID | `POLYSIA-LIVE-001` |
| Status | COMPLETE - `NO_TRADE`; pre-entry venue-minimum stop |
| Baseline | `main` at `bfc7eaddbde21271c5f9856e1962030e8c4959ff` |
| Strategy | `btc-15m-favorite-take-profit` version `0.1.0` |
| Authorization | At most one entry attempt, maximum 1.00 collateral unit, then at most one exit order for the confirmed position |

This plan validates execution plumbing, not profitability. Any failed or
unreadable gate produces `NO_TRADE` or `SAFETY_STOP`; no retry is permitted.

The merged-code read-only preflight completed on 2026-07-12. The active market
minimum could not be satisfied within the owner-authorized `1.00` cap, so the
required outcome was zero live attempts and `NO_TRADE`. This authorization is
closed and must not be reused.

## Required path

```text
Dynamic BTC Up/Down 15m discovery
-> canonical market and two-outcome order books
-> registered experimental strategy decision
-> bounded portfolio admission
-> independent bounded-live Risk decision
-> one-attempt order manager
-> Polymarket execution adapter
-> confirmed fills, position and fee accounting
-> one GTC exit at actual weighted fill price x 1.10
-> read-only reconciliation
-> local immutable evidence report
```

## Invariants

- Strategy code has no adapter or SDK import and emits only an `OrderIntent`.
- Maximum entry notional is `1.00`; market minimums never raise the cap.
- `maximum_entry_attempts=1`, `maximum_markets=1`, and
  `maximum_positions=1` are enforced in state, not operator convention.
- Entry uses FOK with a worst-price bound so partial exposure is not accepted.
- Exit is submitted only after confirmed entry fill and reconciled position.
- Exit quantity never exceeds the actual reconciled available position.
- Raw exit target is weighted-average entry price multiplied by `1.10`, rounded
  upward to the market tick. A target above `1 - tick_size` blocks entry when
  knowable and triggers a safety stop if discovered only after fill.
- No automatic retry, replacement, averaging down, pyramiding, second market,
  second entry, recurring run, or strategy self-modification exists.
- All values use `Decimal`; collateral and conditional balance base units are
  normalized explicitly at six decimals.
- Geoblock, signer/funder/signature, allowances, fee schedule, clock, market
  state, freshness, liquidity, repository/CI, kill switch, account conflicts,
  Risk, and reconciliation fail closed.

## Implementation

1. Add venue-neutral strategy definition, lifecycle, run, and performance
   models plus a minimal registry and SQLite repository.
2. Register `btc-15m-favorite-take-profit@0.1.0` as `experimental`, `unrated`,
   and evidence `insufficient`.
3. Add canonical order-book and market fee/state fields at the Polymarket
   adapter boundary.
4. Implement pure favorite selection using fresh executable best bid/ask data
   from both outcomes. Ties, stale books, wide/empty books, or ambiguous mapping
   reject the decision.
5. Add a minimal one-strategy portfolio admission record. It is not the TARGET
   generalized allocator.
6. Compose the existing `RiskEngine` with bounded-live authorization checks;
   Risk remains final authority.
7. Add a one-attempt round-trip order manager with explicit states, account
   reads, FOK entry, trade confirmation, GTC exit, persistence, redaction, and
   reconciliation.
8. Add a dry-run-default CLI command. Real mode requires the merged commit,
   synchronized clean tracked `main`, green CI evidence, explicit live settings,
   and the task acknowledgement.

## Preflight and market rules

Select one active `btc-updown-15m-*` market dynamically. Require two distinct
outcome tokens, order-book enabled, accepting orders, not archived/closed,
known end time, at least 180 seconds remaining, books no older than 5 seconds,
valid tick/minimum size, adequate executable depth, readable fee schedule,
valid 10% exit target, no conflicting order/position, sufficient available
collateral after reservations and estimated fees, positive allowances, identity
consistency, allowed geoblock, inactive kill switch, and synchronized Git/CI.

Current official documentation says fees are determined per market from
`feeSchedule`; the implementation records the schedule and actual trade fee
rate. If the effective fee cannot be determined, the run is not tradable.

## Tests and validation

- Registry validation, duplicate ID/version, lifecycle, persistence, run links,
  and default unrated performance.
- Favorite selection, ties, ambiguity, freshness, liquidity, remaining time,
  tick/minimum size, fee, target normalization, and maximum price.
- Portfolio and Risk rejection for every authorization invariant.
- One-attempt persistence across restart, FOK response/fill handling, no-fill,
  rejected entry, actual-position exit sizing, duplicate prevention, and
  reconciliation mismatch.
- Report redaction and result classifications.
- Architecture and SDK-boundary tests, adapter contract tests, integration
  vertical slice, Decimal/property invariants, migration/schema tests, and CLI
  inventory/default tests.
- Full compile, Ruff, Mypy, Pytest, pip check, secret scan, build, lock checks,
  strict OSV audit, SBOM, and CI Python 3.11/3.13.

## Live sequence

After the implementation PR is independently reviewed, green, squash-merged,
and local `main` is synchronized:

1. Run merged-code readiness and a dry-run using real public data plus
   authenticated read-only account state.
2. Emit an operator-safe preflight summary and persist it locally.
3. If every gate passes, invoke real mode once. The persistent attempt guard is
   written before adapter submission.
4. If no fill occurs, reconcile and finish `ENTRY_NOT_FILLED` without exit or
   retry.
5. If filled, confirm trades and position, submit one GTC exit for the available
   quantity, read its immediate state, reconcile, and stop.
6. Never commit live artifacts or account identifiers.

## Result classes

`COMPLETED_ROUND_TRIP`, `ENTRY_FILLED_EXIT_OPEN`,
`ENTRY_FILLED_EXIT_REJECTED`, `ENTRY_NOT_FILLED`, `NO_TRADE`, `SAFETY_STOP`, or
`EXECUTION_ERROR`.

## Stop and rollback

Stop before entry for any failed task stop condition, including official
geoblock denial or inability to satisfy the venue minimum under the 1.00 cap.
After entry, stop new actions on unknown order state, inconsistent position,
reconciliation mismatch, invalid exit, or emergency activation.

Rollback reverts the implementation squash commit. New SQLite tables are
additive and can remain unread; no destructive migration or dependency change
is required. A submitted live order/position is never rolled back through Git;
it remains governed by reconciliation and the approved cleanup path.

## Explicit exclusions

No new venue, dependency upgrade, full strategy orchestration, generalized
allocator/OMS/router, recurring execution, scheduling, scaling, martingale,
grid trading, averaging down, ML, Web3/DeFi, UI, Figma, Penpot, or unrelated
refactor.

## Future strategy evolution

Every future strategy change must use a new version, retain deterministic
tests, compare evidence against the current version, progress separately
through Paper, Shadow, and controlled Live gates, and have a reversible
rollback. Versions are scored independently. A strategy may never rewrite,
promote, or deploy its own live implementation automatically.
