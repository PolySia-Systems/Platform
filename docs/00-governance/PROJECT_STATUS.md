# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-13 |
| Source-of-truth branch | `main` |
| Final runtime baseline | `b7dce82976a5b4ff624d8efef687c7d0d3776732` |
| Remote baseline | `origin/main` at the same commit |
| Documentation branch | `codex/polysia-phase-close-005` |
| Repository | `https://github.com/Movafeghm/polysia.git` |
| Active closure task | `POLYSIA-PHASE-CLOSE-005` |
| Phase status | `READY_FOR_RESEARCH_VALIDATION_CYCLE` |

The final runtime baseline is the last implementation merge before this
documentation-only update. The documentation merge cannot self-reference and
remains discoverable from Git history. Two pre-existing untracked architecture
prompt inputs remain preserved and unchanged.

## Completed stages

- Phases A-I completed baseline recovery, governance, canonical `polysia`
  naming, venue-neutral boundaries, Polymarket adapter consolidation, module
  decomposition, quality/supply-chain controls, controlled validation, and
  delivery verification.
- `POLYSIA-LIVE-001` stopped before submission because the one-USDC cap could
  not satisfy the venue minimum. `POLYSIA-LIVE-002` and `003` each consumed one
  authorization on a rejected FOK submission without a fill.
- `POLYSIA-LIVE-004` submitted exactly one venue-minimum FAK entry, filled five
  shares, and placed exactly one actual-fill-sized GTC exit. The exit later
  filled and is now durably reconciled as a completed round trip.
- `POLYSIA-RECON-005` added idempotent delayed-fill ingestion, terminal-state
  classification, position/ledger/P&L updates, and durable reconciliation.
- Bounded read-only lifecycle monitoring, fee-aware take-profit calculation,
  structured adapter diagnostics, fail-closed server-clock preflight, canonical
  configuration reporting, and bounded read-only retry behavior are CURRENT.
- A verified external recovery package exists for the final runtime baseline.

## Current architecture and runtime capabilities

- CURRENT deployment is one Python modular monolith with a Typer CLI, local
  SQLite persistence, and Polymarket as the first venue adapter.
- CURRENT executable path is Strategy -> independent Risk -> Execution ->
  Polymarket Adapter. Strategies do not call venue, wallet, SDK, or execution
  clients directly.
- The minimal Strategy Registry is CURRENT and keeps versioned definitions,
  lifecycle state, run evidence, and explicitly unrated performance summaries.
  Generalized orchestration, conflict resolution, capital allocation, OMS,
  generalized ledger, execution routing, and adapter registry remain TARGET.
- The bounded BTC Up/Down 15-minute runner uses the smallest venue-valid
  quantity, one FAK entry, confirmed-fill reconciliation, and at most one GTC
  exit sized from actual available position. Duplicate authorization and entry
  attempts remain persistently blocked.
- New take-profit calculations are fee-aware: entry cost, confirmed/applicable
  fees, expected exit fees, tick size, quantity, and desired net return are
  included. The historical LIVE-004 exit used the earlier nominal 10% price
  target; the fee-aware implementation was added afterward without placing a
  new order.
- `reconcile-live-round-trip` performs authenticated read-only delayed-fill
  reconciliation. `monitor-live-round-trip` provides scheduler-friendly,
  bounded read-only lifecycle monitoring and persistent idempotent alerts.
- Adapter diagnostics classify common authentication, signing, amount, size,
  tick, balance, allowance, order-type, market, geoblock, rate-limit, clock,
  SDK, server, timeout, and unknown failures without exposing sensitive values.
- Authenticated round-trip preflight reads official CLOB server time and fails
  closed above the configured threshold, whose maximum is five seconds. Read
  retries are bounded and apply only to idempotent calls; trading mutations are
  never automatically retried.

## LIVE-004 final state

| Fact | Verified value |
|---|---|
| Run | `23108979-2693-4bb4-8199-5c34acaaf39b` |
| Authorization | `POLYSIA-LIVE-004`, consumed and terminal |
| Market | BTC Up/Down 15-minute, `Down` |
| Entry | BUY 5 at `0.52`; confirmed entry fee `0.08736` |
| Exit | SELL 5 at `0.58`; confirmed maker exit fee `0` |
| Gross exit proceeds | `2.90` USDC |
| Allocated all-in entry cost | `2.68736` USDC |
| Confirmed net realized P&L | `+0.21264` USDC |
| Remaining position | `0` |
| Final classification | `COMPLETED_ROUND_TRIP` |

The venue's terminal order-detail read was unavailable, so reconciliation is
classified as a non-blocking warning. The confirmed exit fill and zero venue
position prove closure; there are no blocking reasons. The internal exit order
is `FILLED`, the position is zero, four unique lifecycle ledger events exist,
and the authorization state is terminal. Reconciliation and monitoring did not
submit, cancel, replace, retry, or otherwise mutate any venue state.

One profitable round trip proves that the bounded execution and reconciliation
path can work. It does not prove strategy profitability, repeatability, or
production readiness. Broader live use remains blocked pending statistical
evidence.

## Validation and CI

- Final runtime validation at `b7dce829...` passed compile, Ruff, Mypy over 119
  source files, 504 Pytest tests, `pip check`, secret scan, source/wheel build,
  isolated wheel smoke, strict OSV audit, and CycloneDX SBOM generation.
- Pull Requests #20-#24 passed the Python 3.11, Python 3.13, and supply-chain
  checks. Post-merge main CI run `29277417903` passed for the final runtime
  baseline.
- The approved versions remain `polymarket-client==0.1.0b11`, `mypy==2.1.0`,
  and `ruff==0.15.20`.
- Draft PR #25 passed all six required CI checks and its focused
  documentation-only review found no blocking issue. No source, dependency,
  build, or runtime setting is changed by this documentation work.

## Recovery status

Verified external package:

`C:\Users\Siamak\Documents\PolySia-backups\PolySia-recovery-20260713-224436`

- Git bundle SHA-256:
  `8c321f7e9bcf7e54fd90ee86e5bb9764d0ccc2e7c7eec7226713dbf768d8cb5f`
- Source archive SHA-256:
  `d58e9816df276e81c1d3ae46d15b51e0f81f58a80563f10d0ae76f5f0bbbabde`
- Manifest SHA-256:
  `c4ab63b9a31afcef7326682ce44c83adba56b9ec2a893c5ee2031c3c5e5ef0aa`
- Restore result: PASS; bundle clone, expected commit, Git object check,
  source extraction, all 365 tracked files, and exclusion checks verified.

The legacy project folder, old Conda environment, local database, ignored live
evidence, and prompt inputs remain preserved. They are not authorized for
deletion by this task.

## Active work, blockers, and open decisions

- The owner configuration currently sets both canonical
  `POLYMARKET_FUNDER_ADDRESS` and deprecated `POLYMARKET_WALLET_ADDRESS`.
  `configuration-status` reports this conflict as blocked without exposing
  either value. Remove the deprecated variable through an owner-reviewed
  configuration task before a future authenticated/live run.
- The lifecycle monitor is a local bounded command, not a continuously managed
  production service. Scheduling, escalation providers, and high availability
  are deliberately deferred.
- One live sample is statistically meaningless. Capital scaling, broader live
  use, new strategies, new venues, AI/ML, cloud, and microservices are not the
  next task.
- Dependency upgrade PRs for the SDK, Mypy, and Ruff remain on hold pending
  synchronized lock/contract evidence. Portable cross-platform locking and
  branch-protection policy remain governance debt.
- LIVE-001 through LIVE-004 authorizations are consumed. Historical live task
  prompts and the architecture-generation prompts are superseded as execution
  instructions; they remain provenance evidence only. The phase-closure prompt
  remains active until the closure PR is merged and verified.

## Single recommended next task

**Start a historical-data and strategy-validation slice for BTC Up/Down
15-minute markets.** Define data-quality gates, acquire and validate a
reproducible historical dataset, and establish fee/slippage-aware benchmark and
backtest rules. Do not place live orders or expand platform architecture.

## Next three milestones

1. Acquire and validate historical market, book, outcome, fee, and timing data
   with completeness, timestamp, leakage, and reproducibility checks.
2. Run realistic fee/slippage/liquidity-aware backtests against explicit
   baselines and report net P&L, drawdown, calibration, and regime sensitivity.
3. Run a large Paper/Shadow sample with promotion gates; consider a separately
   authorized Tiny-Live test only if the statistical evidence passes.
