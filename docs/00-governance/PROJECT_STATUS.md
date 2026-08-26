# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-08-26 |
| Source-of-truth branch | `main` |
| Audited repository baseline | `ac104c708100bf9fff7e632acefd89bf90b8e509` |
| Last verified deployed baseline | `b867408b5176541f3168767380d4a1e25b80f740` |
| Post-only repair merge baseline | `62342fee801aa2fabffa6fd78a728e2ce5b7279d` |
| Repository | `https://github.com/PolySia-Systems/Platform.git` |
| Latest repository maintenance | Stage 4B operational hardening (PR `#94`) deployed on Finland at `b867408` |
| Primary runtime | CPython `3.14.6` |
| Supported CI runtime | Python `3.14` only (`>=3.14,<3.15`) |
| Polymarket SDK | `polymarket-client==0.6.0` |
| Conformance status | `STANDARDS_V0_4_0_FULLY_ENFORCED` |

PR `#38` added the bounded Tiny Live Copy runtime. PR `#39` corrected its
preflight so the USD 10 cap applies to experiment exposure and only strictly
proven closed zero-value historical positions are ignored. The exact merged
commit was deployed before the first authorized worker run.
PR `#40` recorded the failed-safe diagnostic. PR `#41` delivered and deployed
the reliability repair. Its authorization was consumed by the terminal
12-hour run `tiny-live-copy-20260729T135013Z`. Authorization
`POLYSIA-TINY-LIVE-COPY-003` was consumed by failed-safe run
`tiny-live-copy-20260731T180428Z`. That run made one venue attempt but created no
order, fill, cycle, or follower exposure. `POLYSIA-TINY-LIVE-COPY-004` was then
consumed by run `tiny-live-copy-20260801T003600Z`, which created one accepted
unfilled Post-only order and stopped `FAILED_SAFE` when immediate cancellation
confirmation remained ambiguous. Later authenticated reads proved zero open
orders, fills, exposure, and experiment cost. No new Live authorization exists.

## Current Helsinki DATA_ONLY deployment

PRs `#80` through `#88` completed the all-market Dynamic Shadow consumer,
protected dynamic pre-Live handoff, read-only publication repair, official
position-pagination bound, persistent restore scratch, and the Continuous
Shadow Portfolio. Exact runtime commit
`d39f5b355b1d83ed2019a93c6647b8ceb1572e5f` is deployed from a verified immutable
Git archive because repository Deploy Keys are disabled. The later `main`
baseline `596e820` changes only Standards adoption, governance documentation,
and its validator; it does not change runtime behavior.

The monitor is healthy with no published port. `TRADING_MODE=DATA_ONLY`,
`LIVE_TRADING_ENABLED=false`, and the Live allowlist is empty. Credentials were
checked only as present/redacted; no new Copy authorization or acknowledgement
exists. Daily Stages 1–3, daily seven-day Historical Stage 4, and ten-minute
Forward Shadow timers are enabled. The dynamic handoff is an operator-only
one-shot with no timer and no network.

The verified real read-only sample contains 21 PolyCop pages and 2,022 wallets;
Stage 3 publishes Alpha 50 and Stress 100 with one overlap, five rejected, and
zero Live-review candidates. The seven-day Stage 4 run evaluated 22,368 events,
simulated 21,115, classified 1,253 unknown, rejected zero, and observed zero
rate-limit responses with the circuit closed. These are modeled research facts,
not proof of profit.

The handoff found 119 evidence-qualified wallets and atomically published the
existing runner's exact 102-wallet protected input. A one-cycle authenticated
dry-run then completed `DRY_RUN_BOUNDED_COMPLETE`: no venue attempt, order,
fill, cancellation, position, fee, or external mutation occurred. The protected
input was regenerated after the terminal dry-run. Generic all-market Live
execution remains out of scope; the legacy bounded Live runner still retains
its exact-102 and BTC 15-minute safety invariants.

## Stage 4B Continuous Shadow deployment

Continuous Shadow Portfolio v0.2 / schema v4 is CURRENT in `DATA_ONLY` on
`Hetzner-Finland-Helsinki-01` at exact merge commit
`b867408b5176541f3168767380d4a1e25b80f740` (PR `#94`, which includes PR `#92`
schema v4). The mixed FOLLOWER portfolio remains the labeled baseline.
Independent Alpha and Stress followers started empty after migration.
CLOSE/SETTLEMENT attribution, rolling 1h/6h/24h health, mark freshness, and a
persistent fenced worker are active. Encrypted off-host backup is still
absent. `3x-ui` was not restarted.

The initial uninterrupted run exceeded 90 minutes with zero duplicate
processing and a balanced ledger. A later operator-workflow interruption left
the intentionally stopped timer inactive for about 14 hours. Recovery resumed
from the durable watermark without state loss, but correctly classified 1,270
backlog events as `UNKNOWN` because their fresh executable-book evidence no
longer existed. Subsequent natural polls recorded zero UNKNOWN and zero rate
limits. Cumulative evidence at closeout contained 1,336 unique events, 34
overlap duplicates, zero duplicate processing, 10 settlements, and six follower
closes.

The current follower P&L is a negative, partial synthetic estimate and some
marks are not fully current. Confidence is `LOW`; this evidence cannot support
a profitability, Live-readiness, or promotion claim. See the Stage 4B handoff
for exact backup, rollback, financial, and limitation evidence.

Operational health on Helsinki now reads the atomic `continuous-shadow.json`
artifact instead of the live SQLite file. Thirty host artifact reads completed
in 0.0001–0.0002 s while the worker held the database. Fifteen `portfolio-health`
CLI invocations inside the running worker did not increase `NRestarts` and
produced no `database is locked` log lines. Snapshot `portfolio-results` against
the verified 268 943 360-byte backup completed in 1.811 s inside a detached
container; SQL latest-mark and aggregation queries on that file were all under
90 ms. Indexes, WAL, and schema version were not changed.

A later `docker compose run` one-shot used for snapshot timing tore down the
Compose project veth and stopped the `compose run` worker at 12:59:06 UTC.
systemd `Restart=on-failure` restarted it (`NRestarts` 0→1, `OOMKilled=false`).
The failed poll recorded sanitized `source_unavailable` at 12:59:05 UTC rather
than a generic `continuous_shadow_failed` code. After recovery, health was
`warning` with `last_poll_status=succeeded`, `ledger_balanced=true`,
`duplicate_processing_count=0`, fresh/stale/missing marks 168/82/0, and no
real order. `3x-ui` remained restart count 0 since `2026-08-21T10:33:56Z`.
The runbook now forbids `docker compose run` for reporting while this worker
uses `compose run` on the same project.

## Completed stages

- Repository modernization milestones completed baseline recovery, governance, canonical `polysia`
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
- The final pre-submit Post-only recheck, streaming signal handling, atomic
  reservation, and scoped market-time gate were implemented and exercised by
  Tiny Live Copy runs 003 and 004. Run 004 proved venue acceptance without a
  fill, while preserving fail-safe behavior on uncertain cancellation state.
- The exact Standards v0.4.0 `PRF-BASE` and `PRF-PYS` profiles are fully
  enforced. CI is optimized for Python 3.14 with dependency security fixes,
  path-conditional quality/container/supply-chain jobs, and lightweight
  documentation checks.
- The first SHADOW-only Control Kernel vertical slice is complete for
  `stale-price@0.1.0`, with versioned desired state, optimistic concurrency,
  idempotency, synchronous observed state, audit history, and no Live authority.
- Stage 1 protected PolyCop ingestion, Stage 2 Candidate Intelligence v1,
  Stage 3 copyability selection v0.1, and Stage 4 Dynamic Shadow are complete
  and deployed DATA_ONLY. The
  data-only path canonicalizes wallet identity, calculates source-derived
  time-safe features, separates readiness from policy, ranks deterministically,
  and publishes address-free Shadow Alpha/Stress selection pools under a
  persistent fenced SQLite lease. Live-review remains empty. Stage 4 uses
  official read-only all-market evidence for modeled Historical and Forward
  Shadow. It has no Live authority and does not prove profitability.

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
- Wallet Intelligence Stages 1–4 are CURRENT and deployed DATA_ONLY. PolyCop
  remains discovery evidence; official Polymarket GET data supplies Stage 4
  trade and current-book evidence. Historical order-book reconstruction,
  statistically sufficient Shadow evidence, and any new Tiny-Live authorization
  remain deferred.
- Stage 4B Continuous Shadow is CURRENT as a deployed DATA_ONLY bounded
  experimental portfolio and ledger. It is not the generalized TARGET
  portfolio, capital allocator, OMS, or execution router, and its current LOW
  confidence evidence is not a Live promotion decision.
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
- The CURRENT cancellation finality gate durably marks the mutation boundary,
  permits at most one cancellation send per operation, and then uses only
  bounded read-only order, trade, and position evidence. It requires two
  consecutive complete clean observations before `CONFIRMED_NO_FILL`; fill,
  still-open, unknown, timeout, endpoint-failure, and conflicting outcomes are
  explicit and fail safe. A restart never automatically resends cancellation.

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

- The Python 3.14.6 baseline has passed compile, Ruff 0.16.4, Mypy 2.3.0,
  Pytest, `pip check`, secret scan, source/wheel build, isolated wheel
  installation, and CLI smoke. Exact run-specific counts belong in the
  corresponding PR or handoff rather than this long-lived status document.
- A clean locked dependency environment passed strict OSV audit with no known
  vulnerabilities and generated a CycloneDX JSON SBOM.
- A second Conda environment recreated from `environment.yml` and the portable
  pip lock, passed `pip check`, and passed the pinned SDK surface contracts.
- CI verifies only Python 3.14. Pull requests receive lightweight diff, local
  path/link, Standards, and secret checks; executable Python changes add one
  canonical Linux quality path with complete Pytest and applicable locked-wheel
  validation. Full Windows compatibility runs weekly, manually, and for
  verified Windows-sensitive changes rather than for ordinary pull requests.
  Relevant deployment changes add container validation. Strict OSV/SBOM
  validation runs for dependency changes, on a weekly schedule, and by manual
  dispatch. Push workflows run only on `main`, and superseded pull-request runs
  are cancelled.
- The approved versions include `polymarket-client==0.6.0`, `mypy==2.3.0`,
  `hypothesis==6.165.10`, `pre-commit==4.6.2`, `ruff==0.16.4`, and
  `setuptools==84.0.0` in the completed pip environment. The Conda bootstrap
  remains on the latest available Python 3.14 build, `setuptools==83.0.0`,
  before the portable pip lock promotes it to `84.0.0`.
- Before the Linux-first migration, representative PR run `32479986498` ran the
  same 686-test suite in about 340 seconds on Windows and 29 seconds on Linux;
  the corresponding jobs took 503 and 74 seconds. This measured duplication is
  the optimization baseline. PR `#72` comprehensive run `32494449623` passed
  694 tests on both platforms, reduced canonical Linux Quality to 101 seconds,
  and retained strict OSV/SBOM, container, and final CI Gate evidence. The
  79.9% Quality-job reduction excludes Windows from ordinary PR critical paths;
  that migration run intentionally executed Windows in 283 seconds.

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
- The owner downloaded and verified two SQLite snapshots and 67 sanitized
  server report files into an untracked workstation archive on 2026-08-02.
  Protected candidate input remains outside Git. This is retained evidence,
  not a replacement for automated encrypted off-host backups.

## Active work, blockers, and open decisions

- Tiny Live Copy run four is terminal `FAILED_SAFE`. One Post-only order was
  accepted and remained unfilled during its 90-second operational lifetime.
  The runtime sent a cancellation request, but its single immediate open-order
  read did not confirm removal. Later authenticated reads proved the account
  flat with zero open order, confirmed fill, exposure, and experiment cost.
- The durable run intentionally retains ambiguous entry state. Do not alter it
  without a separately reviewed reconciliation procedure. The protected
  102-wallet input remains server-local and outside Git.
- The cancellation-confirmation implementation gap is closed in repository
  code. The secure adapter now maps complete paginated order evidence into
  venue-neutral contracts, treats only a verified 404 as not found, and rejects
  malformed or unavailable order detail. Deterministic fixtures cover the
  pinned SDK's `OpenOrder` aliases/Decimals and mixed cancellation response.
- This engineering change did not deploy, mutate an external account, or alter
  the retained ambiguous Tiny Live run. Any future operational use still needs
  a separately reviewed deployment and explicit authorization.
- Wallet Intelligence Stages 1–4 and their timers are deployed. Startup reuse,
  idempotent Stage 2/3 replay, natural Forward scheduling, Historical evaluation,
  rate telemetry, protected handoff, and large-database restore were exercised.
  Local backups are verified but still lack an encrypted off-host destination.
- All four Tiny Live Copy authorizations and entry-attempt capacity are
  consumed. Any future Live run requires a new explicit owner authorization,
  new Run ID, exact green commit, zero-mutation Shadow, and all readiness gates.
- The bounded exception did not complete the broader Copy Trading stages and
  does not authorize generalized or permanent Copy Trading. See the
  [fourth-run diagnostic](../18-ai-handoffs/polysia-tiny-live-copy-004-cancellation-diagnostic.md).

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

**Observe the deployed DATA_ONLY/Shadow pipeline long enough to evaluate data
quality, stability, and copyability evidence.**
Do not promote modeled PnL or one successful dry-run into Live authority. Any
Tiny-Live must be a new run-specific review and authorization after the evidence
gate.

## Next three milestones

1. Observe scheduled Stages 1–4, alert on stale/failure conditions, and establish
   an encrypted off-host backup plus external alert delivery.
2. Acquire reproducible historical data, run realistic fee/slippage-aware
   backtests, and run a large Paper/Shadow sample with promotion gates. Consider
   any new Tiny-Live test only after the safety repair, statistical evidence,
   and a new explicit owner authorization.
3. Add branch protection and encrypted off-host backup through separate
   governance and operational tasks.
