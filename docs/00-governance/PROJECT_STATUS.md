# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-08-17 |
| Source-of-truth branch | `main` |
| Last verified deployed baseline | `46efce066c95c0d1f4a230aae33c99d0b98ce7cd` |
| Post-only repair merge baseline | `89d2dbbadbf3f4fadc7501805b50bc52cc0fb533` |
| Repository | `https://github.com/PolySia-Systems/Platform.git` |
| Active maintenance task | SHADOW-only Control Kernel vertical slice |
| Primary runtime | CPython `3.14.6` |
| Supported CI runtime | Python `3.14` only (`>=3.14,<3.15`) |
| Polymarket SDK | `polymarket-client==0.2.0` |
| Phase status | `STANDARDS_V0_1_1_FULLY_ENFORCED` |

PR `#38` added the bounded Tiny Live Copy runtime. PR `#39` corrected its
preflight so the USD 10 cap applies to experiment exposure and only strictly
proven closed zero-value historical positions are ignored. The exact merged
commit was deployed before the first authorized worker run.
PR `#40` recorded the failed-safe diagnostic. PR `#41` delivered and deployed
the reliability repair. Its authorization was consumed by the terminal
12-hour run `tiny-live-copy-20260729T135013Z`. Authorization
`POLYSIA-TINY-LIVE-COPY-003` was consumed by failed-safe run
`tiny-live-copy-20260731T180428Z`. That run made one venue attempt but created no
order, fill, cycle, or follower exposure. No new Live authorization exists.

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
- PRs `#38` and `#39` implemented and corrected the owner-bounded Tiny Live
  Copy experiment. Its first authorized worker run failed safely on a public
  Data API HTTP 429 before any venue attempt. Durable counters prove zero
  submissions, fills, positions, fees, collateral debit, and cumulative entry
  cost. The diagnostic also proved an independent Gamma market-time mapping
  defect. See the latest Tiny Live Copy diagnostic handoff.
- The deployed Tiny Live Copy 002 repair adds endpoint-aware pacing, shared
  429 recovery, follower-management priority, strict Gamma `eventStartTime`
  validation, rotating 48-alias discovery, and durable read/cooldown state.
  Its 12-hour run finalized normally with zero venue attempts or mutations.

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
- The first Control Kernel slice is CURRENT only for
  `stale-price@0.1.0` in deterministic SHADOW. It provides CLI plan/apply/status/
  history, immutable desired-state revisions, optimistic concurrency,
  idempotency, in-process intent gating, separate observed state, and append-only
  audit evidence. It has no PAPER, LIVE, Web, API, AI, generalized parameter, or
  background-controller authority.
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
- CI now verifies only Python 3.14. Pull requests receive lightweight diff,
  local path/link, and secret checks; executable Python changes add complete
  Windows quality and Linux build/test/wheel smoke; relevant deployment changes
  add container validation. Strict OSV/SBOM validation runs for dependency
  changes, on a weekly schedule, and by manual dispatch. Push workflows run only
  on `main`, and superseded pull-request runs are cancelled.
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

- The second bounded Tiny Live Copy worker run is terminal `FINALIZED` with
  classification `NO_SIGNAL_INCONCLUSIVE`. It observed 170 sanitized BTC
  15-minute trades, including 33 `OPEN` and 137 `INCREASE` events, but made zero
  venue attempts or mutations. Its only accepted signal reached the worker at
  7.525 seconds old and was rejected at 13.159 seconds because the 48-response
  `asyncio.gather` barrier delayed evaluation.
- The current delivery candidate processes each wallet response as it completes,
  adds an atomic durable pre-submit signal reservation that does not consume an
  entry attempt, and retains a second ten-second freshness check immediately
  before external submission.
- The Tiny Live Copy-specific market-time gate is proposed at four minutes;
  the shared domain default remains seven minutes. Existing 90-second
  cancellation and 185-second GTD backstop controls remain unchanged.
- The repair fixes the measured burst behavior with 48 active aliases, a
  100-attempt rolling `/trades` budget, an 80-attempt discovery budget, 20
  reserved attempts, and at most four calls in flight. Discovery is evenly
  paced and rotates every 30 minutes by step 34 only while flat.
- One shared `/trades` circuit honors integer and HTTP-date `Retry-After`,
  applies bounded deterministic fallback and jitter, permits one probe, and
  finalizes a flat 120-second outage as `INCONCLUSIVE_DATA_SOURCE`.
- Strict BTC interval mapping now verifies slug epoch against Gamma child
  `eventStartTime` and verifies child `endDate` is exactly 900 seconds later.
  Gamma `startDate` is ignored as interval-start evidence.
- Active follower management and authenticated reconciliation precede public
  leader reads. Public outage cannot block management of actual exposure, and
  discovery remains off while capacity is occupied.
- Discovery ordering, cursor, active aliases, subset digest, cooldown metadata,
  per-alias read checkpoints, and sanitized pending events are durable. Raw
  candidate addresses remain protected runtime input.
- Authorization IDs are supplied only through protected runtime input.
  `POLYSIA-TINY-LIVE-COPY-003` is consumed and terminal. Any future Live run
  requires a different, explicit owner authorization and an exact unclaimed
  Run ID after zero-mutation Shadow and all readiness gates pass.
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

**Complete only the final Post-only recheck repair and zero-mutation Shadow
stage.** Pass the full repository and CI gates, merge normally, deploy only the
final integrated merge commit, initialize additive schema safely, and run one
fully isolated bounded Shadow. Stop without Live if evidence is adverse,
ambiguous, or inconclusive. Do not create, claim, or consume another
authorization or Live Run ID during this stage.

After a separately authorized experiment becomes terminal, the broader
recommendation remains:

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
