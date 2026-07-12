# First Evidence Sprint ExecPlan

## Control

| Field | Value |
|---|---|
| Task | First evidence-oriented vertical slice |
| Status | SUPERSEDED BY POLYSIA-LIVE-001 |
| Prepared | 2026-07-11 |
| Repository baseline | `main` at `b641e14cdb371d8e3ae4e1d700ca4c76cf93d622` |
| Runtime mode | Public data plus paper execution only |
| Selected strategy | Existing `StalePriceStrategy` |
| Market scope | Active Polymarket BTC Up/Down 5-minute markets |

This plan extends verified behavior. It does not approve live order submission,
claim profitability, or promote TARGET architecture to CURRENT.

The StalePrice Paper Sprint is deferred, not rejected. `POLYSIA-LIVE-001` is
the active owner-authorized task and is defined in
`plans/active/tiny-live-round-trip-v1.md`.

## Hypothesis and economic mechanism

**Hypothesis.** When a valid BTC Up/Down 5-minute token book has sufficient
top-of-book depth, an absolute microprice-versus-mid edge of at least `0.02`
predicts a mid-price move in the signal direction over the next 30 seconds. The
evidence run will determine whether that signal retains positive net paper edge
after executable entry price, verified venue fees, conservative slippage, and
capital lockup, relative to the registered benchmarks. No positive result is
assumed.

The proposed mechanism is short-horizon order-book pressure: asymmetric bid and
ask depth shifts microprice away from the quoted midpoint before the midpoint
adjusts. The existing strategy already calculates this venue-neutral feature
and emits an `OrderIntent`; the sprint measures the mechanism instead of adding
a new strategy family.

## Evidence path

```text
Public live Polymarket data
-> existing adapter normalization and MarketDataEvent
-> existing Decimal BookBuilder and microstructure features
-> existing StalePriceStrategy
-> minimal single-strategy portfolio admission decision
-> existing independent RiskEngine decision
-> existing PaperBroker execution
-> existing PositionLedger and P&L update
-> existing ReconciliationManager comparison and safety pause
-> new daily evidence report using existing evaluation metrics
```

The portfolio step is a small, venue-neutral admission policy for one strategy
and one token at a time. It is not the TARGET portfolio/capital allocator,
strategy orchestrator, conflict resolver, or OMS.

## Scope and registered defaults

- Discover active, accepting-order `btc-updown-5m-*` markets through the public
  Polymarket adapter.
- Observe one explicitly recorded outcome token per selected market. Record the
  condition, outcome label, market start/end, and token mapping at the adapter
  boundary.
- Evaluate each valid best-bid/ask update, throttled to at most one portfolio
  decision per token per second.
- Admit no new intent while that token has an open paper order or non-zero paper
  position.
- Use `min_edge=0.02`, `order_size=1`, and the existing strategy confidence for
  the preregistered baseline. Store all Decimal values as strings in artifacts.
- Do not enter with less than 90 seconds to scheduled market end.
- Measure forward mid-price at 15, 30, and 60 seconds. The primary horizon is
  30 seconds. Close the paper position conservatively at the executable
  opposite top of book at the primary horizon; if unavailable, retain and mark
  it until a valid exit or verified resolution.

## Current implementation reused

- Public discovery and streaming in `src/polysia/adapters/polymarket/`.
- Canonical `MarketDataEvent`, in-memory bus, `BookBuilder`, validators, and
  Decimal local order book.
- Microstructure calculation and `StalePriceStrategy`.
- `RiskEngine`, risk limits, kill switch, stale-data checks, and independent
  approve/reject/reduce authority.
- `PaperBroker`, order state, `PositionLedger`, and P&L calculation.
- `ReconciliationManager`, mismatch detectors, and safety pause.
- `shadow-run-real-data` dependency injection, sanitization, and no-live guard.
- Strategy and extended evaluation metrics and report renderers.

## Missing implementation

1. A venue-neutral, single-strategy portfolio admission policy that records
   available cash, reserved notional, current position, open paper orders, and
   its admit/reject reason before Risk. It must not bypass or duplicate Risk.
2. An evidence-session orchestrator that reuses public collection and the
   existing strategy/risk/paper path, persists quote/decision/fill/position
   lineage, applies deterministic exits, and never resolves a live broker.
3. Public market-resolution capture and a fail-closed outcome state of
   `unresolved` when authoritative resolution is unavailable.
4. Paper-state reconciliation after every fill/exit and at session close,
   halting the run on a blocking mismatch.
5. A daily JSON plus Markdown evidence report with data quality, signal,
   benchmark, cost, execution, exposure, reconciliation, and P&L metrics.
6. A thin CLI command with explicit paper-only naming and safe defaults. The
   command must reject `LIVE_TRADING_ENABLED=true`.

## Benchmarks

- **No trade:** zero return with no capital committed.
- **Executable-price hold:** enter at the same executable price on every
  otherwise eligible observation without using the microprice direction;
  alternate direction deterministically by observation index.
- **Shuffled signal:** preserve timestamps, prices, and signal count while
  permuting directions with a committed deterministic seed.
- **Midpoint-only diagnostic:** measure the signal at midpoint without execution
  costs, clearly labeled non-tradable and excluded from promotion decisions.

Report paired differences on the same eligible observations. Do not choose the
best benchmark after seeing results.

## Data requirements and quality gates

Required fields are market/condition/token identifiers, outcome label,
scheduled end, authoritative resolution state, event type, exchange and receive
timestamps, sequence information when supplied, best bid/ask and sizes,
microprice/mid/spread, strategy parameters, portfolio and risk decisions,
paper order/fill state, fees, slippage, cash, reserved capital, positions, P&L,
reconciliation state, and correlation/run identifiers.

An observation is eligible only when:

- bid and ask exist, satisfy `0 < bid < ask < 1`, and the book is not crossed;
- exchange/receive timestamps are valid and event age is at most 1,000 ms;
- sequence handling has no unresolved gap or regression;
- spread is at most `0.04`;
- displayed size at the executable side is at least five times the order size;
- market mapping is unambiguous and scheduled end is known;
- at least 90 seconds remain before scheduled end;
- fee inputs and all monetary fields are valid Decimals.

Duplicate events are idempotently ignored. Invalid and ineligible observations
remain counted with reason codes. A report is not promotable if eligible-record
completeness is below 99%, outcome mapping is ambiguous, fee inputs are
unverified, or a sequence gap remains unresolved.

## Costs, liquidity, and resolution risk

- Use the actual displayed executable side, never midpoint, for paper entry and
  exit.
- Apply the versioned fee rule verified from current official venue data or
  documentation at implementation time. If it cannot be verified, mark the run
  non-promotable; never assume zero fees.
- Slippage is the worse of the conservative paper fill result and the next
  valid executable quote for the required size. Partial or unavailable depth is
  a missed/partial fill, not an optimistic fill.
- Reserve entry notional plus modeled fees until exit or verified resolution.
  Report time-weighted committed capital, utilization, and return on committed
  capital; do not recycle locked capital.
- Only an authoritative finalized venue outcome may settle a position. An
  unresolved, delayed, disputed, or unreadable outcome remains unresolved,
  contributes no realized profit, retains capital lockup, and blocks promotion
  if it prevents the required resolved sample.

## Frequency, duration, and sample

- Decision frequency: every eligible update, throttled to one decision per
  token per second.
- Primary holding period: 30 seconds; diagnostics at 15 and 60 seconds.
- Minimum evidence: 200 eligible resolved market observations, 5,000 valid book
  updates, and at least seven consecutive calendar days.
- Paper-run duration: seven days and until both sample minima are met, capped at
  14 days for the first cycle. Failure to reach the sample is an inconclusive
  result, not evidence of success or failure of the economic hypothesis.

## Metrics and decision rules

Success metrics to report are eligible/invalid counts, data completeness,
directional accuracy at each horizon, paired net edge versus each benchmark,
fee and slippage totals, fill/partial/miss ratios, realized/unrealized/net paper
P&L, return on committed capital, maximum drawdown, exposure, risk approvals and
denials by reason, reconciliation outcomes, latency percentiles, unresolved
positions, and outcome-resolution coverage.

The baseline may advance to scheduled real-data Shadow only when all of these
hold on the preregistered out-of-sample run:

- both sample minima and seven-day duration are satisfied;
- 100% of intents follow portfolio decision -> Risk -> PaperBroker;
- there is no live broker use, risk bypass, secret exposure, or blocking
  reconciliation event;
- required data completeness is at least 99% and all sampled positions are
  exited or authoritatively resolved;
- net paper edge after verified fees, conservative slippage, and capital lockup
  exceeds every registered executable benchmark, with the paired 95% bootstrap
  confidence interval lower bound above zero;
- maximum drawdown and exposure remain within the preregistered paper risk
  limits.

Failure metrics are a non-positive paired net edge, confidence interval crossing
zero, negative net paper P&L, limit breach, reconciliation pause, data-quality
failure, missing fee/resolution evidence, sample shortfall, or any optimistic
fill/cost assumption. Report every failure without retuning it away.

## Stop conditions and refinement limit

Stop the run immediately on live broker resolution or invocation, live mode,
credential leakage, Risk bypass, blocking reconciliation mismatch, ambiguous
token/outcome mapping, invalid fee model, corrupted artifact lineage, or a paper
risk/maximum-drawdown limit breach. Stop new entries when public data is stale,
sequence integrity is uncertain, resolution is unreadable, or the kill switch
is active.

Allow at most two refinement cycles after the registered baseline. Each cycle
may change one documented parameter or one data/execution defect, must explain
the mechanism before inspecting the new result, and must use a new out-of-sample
period. After two unsuccessful cycles, stop and archive the hypothesis rather
than adding strategy complexity.

## Observability and artifacts

- Correlation identifiers from public event through strategy, portfolio, risk,
  paper order/fill, ledger, reconciliation, and report.
- Structured reason codes for every filter, admission, risk, fill, exit, and
  reconciliation decision.
- Append-only JSONL evidence records plus daily JSON and Markdown summaries.
- Counts of received, duplicate, invalid, stale, eligible, and dropped events;
  stream reconnects and sequence gaps; latency p50/p95/p99.
- Cash, reserved notional, position, exposure, realized/unrealized P&L,
  drawdown, fee, slippage, and locked-capital time series.
- Explicit `live_broker_used=false` and no-live statement in every report.
- Secret scan over generated tracked fixtures and report schemas; public
  artifacts must contain no wallet, signer, credential, or raw authenticated
  payload.

## Required tests

- Unit tests for eligibility, portfolio admission, cost/slippage accounting,
  deterministic exits, resolution states, benchmarks, and report calculations.
- Property tests for Decimal cost/P&L arithmetic, capital reservation,
  idempotency, and position invariants.
- Architecture tests proving domain/application code remains venue-neutral and
  the SDK stays inside the Polymarket adapter.
- Contract tests for public market/token/resolution mapping using deterministic
  fixtures; no authenticated or mutating calls.
- Integration test for the complete public-event fixture -> normalization ->
  strategy -> portfolio -> Risk -> paper fill -> ledger -> reconciliation ->
  daily report path.
- Characterization/CLI tests proving paper-only defaults, live-mode rejection,
  deterministic seed, and artifact names.
- Fault tests for stale/gapped/duplicate data, missing depth, partial fills,
  unreadable resolution, reconciliation mismatch, and restart recovery.
- Existing compile, Ruff, Mypy, full Pytest, pip check, secret scan, build,
  strict OSV audit, SBOM, and Python 3.11/3.13 CI gates.

## Acceptance criteria

1. The new bounded command uses public data and paper execution only and fails
   closed when live mode is enabled.
2. Every accepted event has end-to-end lineage and every intent passes through
   the portfolio admission record and independent Risk before PaperBroker.
3. Position, cash, reserved capital, fees, slippage, P&L, and reconciliation are
   internally consistent and restart-safe in tests.
4. Daily JSON/Markdown reports reproduce all registered metrics and benchmarks
   from append-only evidence records.
5. Resolution uncertainty and missing fee evidence cannot produce promotable
   results.
6. The minimum sample, duration, success, failure, and stop rules are evaluated
   mechanically; insufficient evidence is reported as inconclusive.
7. All required local and CI gates pass with no runtime safety weakening.
8. CURRENT/TARGET claims remain accurate; no general allocator or orchestration
   capability is claimed.

## Expected files to change

- `src/polysia/monitoring/real_data_shadow_run.py`
- `src/polysia/monitoring/first_evidence_sprint.py` (new)
- `src/polysia/portfolio/evidence_policy.py` (new)
- `src/polysia/cli.py`
- `tests/unit/monitoring/test_first_evidence_sprint.py` (new)
- `tests/unit/portfolio/test_evidence_policy.py` (new)
- `tests/integration/test_first_evidence_vertical_slice.py` (new)
- `tests/property/test_evidence_accounting_properties.py` (new)
- `tests/contract/test_polymarket_public_evidence_mapping.py` (new)
- `tests/architecture/test_boundaries.py`
- `tests/characterization/test_cli_contract.py`
- `README.md`

The implementation task must justify any additional file before changing it.
No dependency, schema migration, or live-execution file is expected.

## Rollback

Revert the evidence-sprint commit/PR, remove the new CLI registration and new
modules/tests, and restore the prior `real_data_shadow_run.py`. Generated
evidence artifacts are outside source control and may be archived separately.
No database migration, dependency downgrade, credential change, live order, or
external-state rollback is required.

## Explicit exclusions

- Live orders, cancellations, authenticated writes, or account mutation.
- SDK upgrade, signer/funder/wallet/signature changes, or new venue adapter.
- New strategy family, passive-market-maker comparison as a candidate strategy,
  multi-strategy orchestration, conflict resolution, generalized allocator,
  OMS, generalized ledger, or execution router.
- Figma, Penpot, architecture visualization, UI work, Web3/DeFi/copy trading,
  machine learning, microservices, Kubernetes, PostgreSQL, or production
  infrastructure.
- Profitability claims, parameter fishing, synthetic outcome invention, or
  promotion based on midpoint-only/zero-fee results.

No owner decision blocks implementation. The thresholds above are the
recommended preregistered defaults; changing them requires an owner-visible plan
revision before evidence collection begins.
