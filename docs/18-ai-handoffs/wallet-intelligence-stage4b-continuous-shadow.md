# Wallet Intelligence Stage 4B Continuous Shadow Handoff

## Delivery state

- Repository implementation: complete on `codex/continuous-shadow-portfolio`
- Merge, deployment SHA, server migration, timer, restart, and observation:
  recorded here after operational verification
- External mode: public GET reads only; local protected SQLite writes
- Trading: disabled; no order or account-mutation path exists in Stage 4B

## Implemented boundary

Stage 4B is additive to Stage 4A. It supplies a durable first-seen event journal,
incremental checkpoint, one persistent synthetic portfolio per Wallet, one shared
PolySia follower, per-leader attribution, capital/conflict limits, non-reused
liquidity, partial-fill evidence, official market fee schedules, cross-run exits,
exact 0/1 settlement, Decimal ledger reconciliation, interval-aware health, and
`RUNNING -> DRAINING -> FINALIZED` lifecycle.

The new CLI surface is:

```text
wallet-intelligence portfolio-start
wallet-intelligence portfolio-sync
wallet-intelligence portfolio-health
wallet-intelligence portfolio-results
wallet-intelligence portfolio-drain
wallet-intelligence portfolio-finalize
```

All output is address-free. Protected addresses remain inside the existing
wallet-intelligence identity tables and are passed only in memory to the official
read adapter.

## Safety and compatibility

- Stage 4A schema remains v1; Stage 4B schema is separately v2.
- The fast service forces `TRADING_MODE=DATA_ONLY` and
  `LIVE_TRADING_ENABLED=false`.
- Stage 4B imports no execution, Risk, strategy, wallet, signing, cancellation,
  transfer, or order-authority module.
- The one-minute poll is additive; the prior ten-minute Stage 4A timer remains.
- A failed poll does not advance the watermark or replace portfolio state.
- Rollback disables only the Stage 4B timer and restores the prior release.

## Operational evidence

To be completed after exact-SHA deployment:

- merged commit and CI run;
- pre-migration backup and disposable restore result;
- deployed archive SHA and image identity;
- `3x-ui` before/after digest and health;
- experiment and initial poll identifiers;
- real restart and post-restart dedupe/accounting result;
- timer and health state;
- cumulative events, evaluations, positions, P&L, fees, NAV, unknown ratio,
  accounting identity, and limitations after observation.
