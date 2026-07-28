# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-28 |
| Source-of-truth branch | `main` |
| Final runtime baseline | `b7dce82976a5b4ff624d8efef687c7d0d3776732` |
| Starting main baseline for this upgrade | `c3e0cdddefd437f8367d58a551658f887bd04a7e` |
| Upgrade branch | `codex/python314-platform-upgrade` |
| Repository | `https://github.com/Movafeghm/polysia.git` |
| Active maintenance task | `POLYSIA-UPGRADE-006` |
| Primary runtime | CPython `3.14.6` |
| Supported CI runtimes | Python `3.11`, `3.13`, and `3.14` |
| Polymarket SDK | `polymarket-client==0.2.0` |
| Phase status | `READY_FOR_RESEARCH_VALIDATION_CYCLE` |

The final runtime baseline remains the last trading-runtime implementation
merge. `POLYSIA-UPGRADE-006` changes the development/runtime platform baseline,
dependency contracts, reproducibility files, and SDK version guard without
changing strategy, risk, execution, reconciliation, credential, or live-control
behavior. Its final merge and CI runs remain discoverable from Git/PR history
because this tracked document cannot self-reference them. Two pre-existing
untracked architecture prompt inputs remain preserved and unchanged.

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
- `POLYSIA-UPGRADE-006` established Python 3.14.6 as the primary runtime,
  upgraded the official unified Polymarket SDK to 0.2.0, updated direct
  dependencies and portable locks, added Python 3.14 and Linux smoke coverage
  to CI, removed the deprecated local wallet variable, and created a Python
  3.13 rollback export.

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

- The Python 3.14.6 upgrade environment passed compile, Ruff 0.16.0, Mypy 2.3.0
  over 119 source files, all 504 Pytest tests, `pip check`, secret scan,
  source/wheel build, isolated wheel installation, and CLI smoke.
- A clean locked dependency environment passed strict OSV audit with no known
  vulnerabilities and generated a CycloneDX JSON SBOM.
- A second Conda environment recreated from `environment.yml` and the portable
  pip lock, passed `pip check`, and passed all five SDK surface contracts.
- CI now verifies Python 3.11, 3.13, and 3.14 on Windows, runs a Python 3.14
  Linux build/test/wheel smoke, and performs strict OSV/SBOM validation from
  the exact dependency lock. Final PR CI evidence is resolved from GitHub
  history after this document is committed.
- The approved versions are `polymarket-client==0.2.0`, `mypy==2.3.0`, and
  `ruff==0.16.0`. `setuptools==83.0.0` removes the known 82.0.1 finding.

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

Python 3.13 environment rollback export:

`C:\Users\Siamak\Documents\PolySia-backups\PolySia-py313-rollback-20260728-133429`

It contains explicit Conda, portable environment, pip-freeze, and SHA-256
records created before canonical environment promotion. The legacy project
folder, local database, ignored live evidence, and prompt inputs remain
preserved. The owner had already removed the obsolete `polymarket` Conda
environment; PolySia does not depend on it.

## Active work, blockers, and open decisions

- The private owner configuration now contains only the canonical funder
  variable. Redacted `configuration-status` reports no deprecated-variable
  conflict and no missing authenticated-read setting.
- The lifecycle monitor is a local bounded command, not a continuously managed
  production service. Scheduling, escalation providers, and high availability
  are deliberately deferred.
- One live sample is statistically meaningless. Capital scaling, broader live
  use, new strategies, new venues, AI/ML, cloud, and microservices are not the
  next task.
- Linux behavior is covered by CI rather than a local Linux host. Production
  server deployment and operations remain a separate authorized task.
- Branch-protection policy remains governance debt.
- LIVE-001 through LIVE-004 authorizations are consumed. Historical live task
  prompts and the architecture-generation prompts are superseded as execution
  instructions; they remain provenance evidence only.

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
