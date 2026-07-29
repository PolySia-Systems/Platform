# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-29 |
| Source-of-truth branch | `main` |
| Deployed application source | `52c1bcc980f7db797066f982b23ab755dca31f58` |
| Final runtime baseline | `b7dce82976a5b4ff624d8efef687c7d0d3776732` |
| Repository | `https://github.com/Movafeghm/polysia.git` |
| Active maintenance task | Owner-bounded Tiny Live Copy experiment |
| Primary runtime | CPython `3.14.6` |
| Supported CI runtimes | Python `3.11`, `3.13`, and `3.14` |
| Polymarket SDK | `polymarket-client==0.2.0` |
| Phase status | `TINY_LIVE_EXCEPTION_IN_DELIVERY` |

The final runtime baseline remains the last trading-runtime implementation
merge. The current Git HEAD adds the approved server packaging and operations
layer without changing strategy, risk, execution, credential, or live-order
behavior.

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
- `POLYSIA-UPGRADE-006` established Python 3.14.6 as the primary runtime,
  upgraded the official unified Polymarket SDK to 0.2.0, updated direct
  dependencies and portable locks, added Python 3.14 and Linux smoke coverage
  to CI, removed the deprecated local wallet variable, and created a Python
  3.13 rollback export, which the owner later removed after verification.
- PR `#36` added the controlled single-server Docker deployment, exact runtime
  lock, non-root read-only monitor, periodic read-only reconciliation, health
  checks, rotating logs, persistent SQLite state, and verified backup/restore.
  It was deployed to `Hetzner-Finland-Helsinki-01` in enforced `DATA_ONLY`
  mode with no published port.

## Current architecture and runtime capabilities

- CURRENT deployment is one Python modular monolith with a Typer CLI and
  Polymarket as the first venue adapter. It can run locally in the `PolySia`
  Conda environment and now runs continuously in one hardened Docker container
  on the controlled Helsinki host.
- The server monitor is non-root, read-only, exposes no port, forces
  `TRADING_MODE=DATA_ONLY`, forces `LIVE_TRADING_ENABLED=false`, clears the
  live token allowlist, and persists state and sanitized reports under
  `/var/lib/polysia`.
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

- The current Python 3.14.6 environment passed compile, Ruff 0.16.0, Mypy 2.3.0
  over 120 source files, all 508 Pytest tests, `pip check`, secret scan,
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
- PR `#36` CI passed Python 3.11/3.13/3.14 quality jobs, Linux smoke,
  supply-chain checks, and the new Linux container build/runtime/database
  initialization job.

## Recovery status

- The owner intentionally removed the earlier external workstation recovery
  packages and obsolete legacy environment after verification.
- GitHub `main` and its CI history remain the source recovery path for tracked
  code.
- The server created and verified
  `polysia-20260728T130327484331Z.sqlite3` with SHA-256
  `47e58b7eb950f7d409522fc3ffa79abb31d99005c35cffecc4ef3513244102cf`.
  A restore rehearsal to a separate database passed and the rehearsal file was
  removed.
- The server backup is local to the same host. An encrypted off-host copy is
  not yet configured and remains a recovery limitation.

## Active work, blockers, and open decisions

- Copy Trading Stage 0 established a conditional architecture GO. Stage 1
  proved official read surfaces, normalization, deduplication, strict BTC
  15-minute mapping, and restart-stable event identity, but closed `NO_GO` for
  Stage 2 because no measured fresh-execution latency sample was captured.
- The owner explicitly authorized one bounded exception that jumps from that
  inconclusive evidence state to a maximum of three venue entry attempts and
  three terminal filled cycles. This exception does not complete Stages 2
  through 6 and does not authorize general or permanent Copy Trading.
- The exception preserves the current Strategy/Policy -> Risk -> Execution ->
  Polymarket Adapter path, uses exactly 102 protected candidate wallets through
  aliases, accepts only proven zero-to-positive BTC 15-minute OPEN events, and
  stores attempt/cycle limits durably before external submission.
- Its USD 10 limit applies to cumulative experiment entry cost, not total wallet
  collateral. Closed historical positions are ignored only with explicit
  past-end, zero-price, zero-value, and non-mergeable evidence. A venue
  `redeemable` label on a zero-value historical record does not alone block;
  active, positive-value, mergeable, or ambiguous state still fails closed.
- The pinned SDK requires a GTD timestamp at least 180 seconds ahead. The
  experiment retains a 90-second operational cancellation TTL and skips any
  signal whose 185-second venue backstop cannot expire before the final-entry
  cutoff. This is a stricter eligibility rule, not a weakened safety control.

- The private owner configuration now contains only the canonical funder
  variable. Redacted `configuration-status` reports no deprecated-variable
  conflict and no missing authenticated-read setting.
- The lifecycle monitor is now a continuously managed Docker service on the
  controlled host. External alert delivery and high availability remain
  deliberately deferred.
- One live sample is statistically meaningless. Capital scaling, broader live
  use, new strategies, new venues, AI/ML, cloud, and microservices are not the
  next task.
- Linux behavior is covered by CI and the controlled Ubuntu host. The server is
  suitable for data-only, paper, and shadow validation; it is not evidence of
  production readiness or authorization for automated live trading.
- The first server reconciliation completed with no blockers, readable account
  and open-order state, and zero open orders. Its only warning was the expected
  absence of a server-local tiny-live execution artifact.
- Automated encrypted off-host backups and an external alert provider remain
  unfinished operational work.
- Branch-protection policy remains governance debt.
- LIVE-001 through LIVE-004 authorizations are consumed. Historical live task
  prompts and the architecture-generation prompts are superseded as execution
  instructions; they remain provenance evidence only.

## Single recommended next task

**Complete and reconcile the single owner-bounded Tiny Live Copy exception,
then return to evidence collection.** Do not scale, generalize, or promote Copy
Trading from this sample. Review sanitized latency, fill, fee, P&L, restart,
and reconciliation evidence before deciding whether Stage 2 should be
reopened.

After that exception is terminal, the prior recommendation remains:

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
