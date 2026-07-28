# PolySia Copy Trading Architecture Spike

## Document control

| Field | Verified value |
|---|---|
| Task | Stage 0 — Baseline Reconnaissance and Architecture Decision |
| Review date | 2026-07-28 |
| Baseline commit | `f4d1571494b4f6ed52d64290b48f0be42ab4ea62` |
| Working branch | `codex/copytrading-experiment` |
| Repository state before this document | Clean, detached at the baseline commit |
| Runtime environment checked | Existing Conda environment `PolySia` |
| Primary Python | CPython `3.14.6` |
| Decision status | Conditional GO for read-only Data Feasibility only |

## Outcome

Copy Trading fits the current PolySia modular monolith as a bounded
research-validation vertical slice. It does not require a separate repository,
microservice, execution engine, risk engine, wallet, generalized OMS, or
adapter registry.

The current architecture can accept a new external leader-trade source without
breaking its inward dependency boundaries by adding:

1. a venue-neutral leader-trade event contract;
2. a read-only application port;
3. a Polymarket source adapter that normalizes documented public data at the
   boundary.

Stage 1 must prove that a current official or otherwise approved documented
source exposes sufficiently complete and timely executed activity for an
arbitrary approved leader. The repository does not currently provide that
capability. Stage 1 must not create an `OrderIntent`, run a strategy, or mutate
venue state.

No runtime, configuration, dependency, deployment, database, risk, execution,
or live-trading behavior changed in Stage 0.

## Sources reviewed

- `AGENTS.md`
- `docs/00-governance/master-operating-charter.md`
- `docs/00-governance/PROJECT_STATUS.md`
- `docs/22-roadmap/roadmap.md`
- `docs/04-architecture/overview.md`
- `docs/04-architecture/module-decomposition.md`
- `docs/04-architecture/polymarket-adapter.md`
- `docs/18-ai-handoffs/polysia-controlled-server-deployment-handoff.md`
- Current strategy, domain order, risk, execution, adapter, storage,
  reconciliation, replay, shadow, CLI, Docker, and directly relevant test files

The owner-provided
`POLYSIA_COPYTRADING_CODEX_EXECUTION_PLAN.md` is the task plan. Where its
proposed contracts differ from current code, this spike records the current
fact and the smallest compatible future change.

## Current integration map

### CURRENT executable path

```text
Polymarket market API/stream
  -> Polymarket adapter normalization
  -> MarketDataEvent / MarketDetails / LocalOrderBook
  -> BaseStrategy
  -> OrderIntent
  -> RiskEngine
  -> ApprovedOrderIntent
  -> PaperBroker or guarded live execution
  -> Polymarket secure adapter
  -> orders / fills / positions / ledger
  -> reconciliation and reports
```

### Current contracts and composition

| Concern | Current implementation | Reuse decision |
|---|---|---|
| Application ports | `src/polysia/application/ports/protocols.py` | Reuse the pattern; add a focused copy-source port |
| Strategy input | `MarketDataEvent` through `BaseStrategy.on_market_event()` | Reuse for market strategies; do not force leader events into this contract |
| Strategy output | `OrderIntent` from `src/polysia/domain/orders/models.py` | Reuse later at the pre-risk boundary, with only justified compatible extensions |
| Strategy registry | Versioned definitions, lifecycle, runs, evidence, and performance summaries | Reuse without a new orchestrator |
| Risk | `RiskEngine.evaluate()` with kill switch, mode, notional, position, loss, order-count, stale-data, and edge checks | Reuse and retain final authority |
| Paper execution | `PaperBroker.submit_limit_order()` with immediate book-depth-based fills | Reuse as the base, but its simulation limits must be made explicit |
| Live execution | Guarded live brokers and bounded round-trip services | Out of scope until a separately authorized Stage 7 |
| Public venue reads | Markets, market details, order books, and market stream | Reuse for market mapping and executable-state observations |
| Authenticated reads | Current account orders, positions, balances, and account trades | Reuse only for the follower account; not evidence of arbitrary leader access |
| Persistence | Additive `schemas.sql`, repository classes, SQLite transactions | Reuse with new additive tables only when Stage 2 is approved |
| Reconciliation | Open-order and position mismatch detection, manual intervention detection, safety pause | Reuse; add copy-source correlation later without weakening existing blockers |
| Backtest | Deterministic market-event replay through Strategy, Risk, PaperBroker, positions, and P&L | Reuse components; add a copy-specific replay coordinator rather than replacing it |
| Shadow | Mocked and public-data paper-only shadow flows | Reuse safety pattern; current real-data runner is not a leader-trade worker |
| CLI | Typer composition in `src/polysia/cli.py` | Add one bounded read-only command in Stage 1 if data proof requires it |
| Server | One hardened Docker monitor in forced `DATA_ONLY` mode | Unchanged until Stage 5; no strategy currently runs on the server |

## Plan versus current-code differences

| Proposed plan concept | Verified current fact | Minimal response |
|---|---|---|
| Observe arbitrary approved leader fills | No current adapter method reads arbitrary leader activity. `list_account_trades()` reads the authenticated follower account. | Stage 1 must verify an official or approved documented read-only source before implementation proceeds. |
| Feed leader activity through `BaseStrategy` | `BaseStrategy` accepts only `MarketDataEvent` and exposes market/order-book context. | Keep leader ingestion as a separate application input. A copy policy may produce a canonical `CopyDecision` before mapping to the existing pre-risk intent. |
| Venue-neutral `OrderIntent` | Current `OrderIntent` requires Polymarket-style `token_id`. | Do not redesign it in Stage 1. Keep leader and policy contracts venue-neutral, then resolve the execution instrument at the adapter/composition boundary in a later stage. |
| `position_effect`, source correlation, and expiry | These fields do not exist on the current `OrderIntent`. | Evaluate a backward-compatible extension in Stage 3; do not encode these semantics only in free-text `reason`. |
| Strategy emits `ENTER`, `EXIT`, or `SKIP` | Current strategies return zero or more BUY/SELL `OrderIntent` objects. | Model the copy decision separately. `SKIP` remains an audited decision with no intent. |
| Linked cancel after leader exit | There is no generalized OMS or application service linking source events to open orders. | Add a narrow copy coordinator only after paper evidence. Strategy must never call cancel directly. Live cancellation remains separately gated. |
| Persistent source deduplication/checkpoint | Existing event persistence has no stable external event key or copy-source checkpoint. | Add dedicated, additive copy-event and checkpoint tables in Stage 2 after data feasibility passes. |
| Versioned schema migration | Current schema initialization is additive `CREATE TABLE IF NOT EXISTS`; no migration framework exists. | Avoid altering existing tables. Add dedicated tables and test initialization against an existing database. |
| Copy replay | Current loader accepts only Polymarket `MarketDataEvent` JSONL and requires `token_id`. | Add a copy-specific replay input/coordinator that reuses Risk, PaperBroker, position, and P&L components. |
| Realistic paper execution | PaperBroker supports immediate full/partial depth-limited fills but not fees, tick/minimum enforcement, later resting-order matching, cancellation latency, or venue delay. | Treat these as explicit Stage 4 model extensions; do not claim current replay is economically realistic. |
| BTC 15-minute leader shadow | Current public shadow auto-selection is BTC 5-minute and consumes order-book events, not leader fills. | Add a dedicated BTC 15-minute copy shadow composition in Stage 5 only after prior gates pass. |
| Shadow runtime mode | `TradingMode` contains `DATA_ONLY`, `PAPER`, and `LIVE`; no `SHADOW` enum exists. | Keep server deployment forced to `DATA_ONLY`; a copy shadow service may run paper simulation internally and must reject live-enabled settings. |
| Copy feature flag | No current Copy Trading flag exists. | Add a generic `POLYSIA_` flag defaulting to false no earlier than the executable vertical slice. |
| Copy-specific registry fields | Registry already supports `EXPERIMENTAL`, `PAPER`, `SHADOW`, evidence references, parameters, decisions, risk results, orders, fills, and reconciliation. | Reuse the registry; no new registry fields are required for the first experiment. |
| Manual intervention handling | Current reconciliation detects missing orders, closed positions, unexpected positions/fills, stale state, and account-read failures. | Reuse detection and safety pause; persist source-to-decision-to-order linkage before relying on it for copy-specific recovery. |

## Proposed minimal contracts

### Stage 1 contract: `LeaderTradeEvent`

Add a frozen, venue-neutral model only after the source feasibility is confirmed
against current official documentation:

```text
event_id: str
source_id: str
leader_id: str
market_reference: str
outcome_reference: str
trade_action: BUY | SELL
position_effect: OPEN | REDUCE | CLOSE | UNKNOWN
executed_price: Decimal
executed_size: Decimal
executed_at: aware UTC datetime
observed_at: aware UTC datetime
external_evidence_reference: str | None
schema_version: str
```

Required invariants:

- stable deterministic `event_id`;
- positive Decimal price and size with market-appropriate price bounds;
- timezone-aware timestamps with `observed_at >= executed_at`, unless clock
  uncertainty is explicitly classified;
- no SDK object or raw response in the domain model;
- no private key, credential, signer, funder, or raw wallet value;
- an owner-controlled leader alias in domain/application logic;
- `UNKNOWN` position effect must fail closed and cannot generate an intent.

### Stage 1 port

Add a focused asynchronous read-only `LeaderTradeSourcePort` under
`src/polysia/application/ports/`. It should expose bounded historical or
incremental reads plus a source checkpoint, without exposing an SDK paginator,
HTTP response, or Polymarket model.

The Stage 1 adapter belongs under
`src/polysia/adapters/polymarket/` and may import the official SDK or call an
official documented public endpoint. Retry is allowed only for bounded,
idempotent reads under the existing read-retry policy.

### Later contract: `CopyDecision`

Do not implement in Stage 1. The later venue-neutral decision should contain:

```text
decision_id
source_event_id
strategy_id
strategy_version
decision: ENTER | EXIT | SKIP
position_effect: OPEN | CLOSE
market_reference
outcome_reference
proposed_price
proposed_quantity
reason_code
decided_at
expires_at
```

The copy policy produces `CopyDecision`; a narrow mapping/composition boundary
resolves the Polymarket token and creates the existing pre-risk `OrderIntent`.
Risk remains the only component that can approve or reduce executable size.

### Later compatible `OrderIntent` decision

The current required fields must remain compatible. Before Stage 3, review a
minimal optional extension for:

- `position_effect`;
- `source_correlation_id`;
- `expires_at`.

If added, Risk must enforce that a close intent cannot exceed the confirmed
available position. Existing strategies must continue to work unchanged.
`token_id` removal or a repository-wide instrument-model migration is explicitly
out of scope for this experiment.

## Likely files by future stage

These are planned paths, not Stage 0 changes.

### Stage 1 — Data Feasibility

- `src/polysia/domain/copytrading/__init__.py`
- `src/polysia/domain/copytrading/models.py`
- `src/polysia/application/ports/copytrading.py`
- `src/polysia/application/ports/__init__.py`
- `src/polysia/adapters/polymarket/copytrading_source.py`
- `src/polysia/adapters/polymarket/__init__.py`
- `src/polysia/cli.py` only if a bounded operator command is needed
- `tests/unit/domain/copytrading/`
- `tests/unit/adapters/test_polymarket_copytrading_source.py`
- `tests/contract/test_polymarket_sdk_surface.py` only if a new SDK method is used
- deterministic fixtures under `tests/fixtures/copytrading/`
- ignored research output under `artifacts/copytrading/data-feasibility/`

### Stage 2 — Dataset and persistence

- `src/polysia/storage/schemas.sql`
- `src/polysia/storage/repositories.py` or a focused copy repository module
- storage migration/initialization and repository tests
- dataset manifest, dictionary, and scoring research modules

### Stage 3 — Paper vertical slice

- `src/polysia/application/services/copytrading.py`
- copy policy and decision models
- a copy strategy definition registered as `EXPERIMENTAL`
- possible compatible `OrderIntent` and Risk extensions
- focused unit, property, architecture, persistence, and integration tests

### Stage 4 — Backtest

- a focused copy replay module under `src/polysia/backtesting/`
- conservative execution-cost assumptions
- copy evaluation reports and deterministic replay tests

### Stage 5 — Shadow

- a focused copy shadow module under `src/polysia/monitoring/`
- default-off generic settings in `src/polysia/config/settings.py`
- one bounded CLI command
- a disabled-by-default Docker Compose profile or service using the existing
  image and state directory
- a copy shadow runbook and operational tests

Risk, live execution, and secure adapter files are not presumed change targets.
Any future need to change them requires separate justification and tests.

## Data assumptions

The following are assumptions, not current repository facts:

1. A current official or owner-approved documented source can read executed
   activity for an arbitrary public leader identifier.
2. The source exposes enough identity to reconstruct a stable event ID.
3. Market, outcome, side, price, size, and execution time are available without
   inference from future state.
4. Pagination or cursor semantics allow deterministic bounded replay.
5. Observation latency is compatible with a BTC 15-minute decision horizon.
6. A leader exit can be distinguished from a reduction, transfer, opposite
   outcome purchase, or unrelated trade.
7. Raw evidence retention is legally and operationally acceptable to the owner.

Open leader orders are not assumed observable. The first source proof is limited
to confirmed executed activity.

## Safety boundaries

- Stage 1 is public/read-only and produces no `CopyDecision`, `OrderIntent`,
  paper order, live order, cancel, transfer, or wallet mutation.
- Approved leader identifiers must be supplied through untracked or protected
  configuration and represented by safe aliases in reports.
- Raw evidence must be sanitized and excluded from Git unless a reviewed,
  deterministic fixture contains no sensitive value.
- No credentials are needed merely to prove a public source. If a source
  unexpectedly requires authentication, stop and review the trust boundary.
- Domain, application, strategy, storage, and tests must not import the
  Polymarket SDK.
- Live flags, token allowlists, geoblock, kill switch, acknowledgement,
  authorization, caps, duplicate prevention, and reconciliation remain
  unchanged.
- Venue mutations must never be retried automatically.
- Ambiguous mappings and unknown position effects are recorded and skipped.

## Repository questions resolved

1. **Where is `OrderIntent`?**
   `src/polysia/domain/orders/models.py`; `src/polysia/execution/intents.py`
   re-exports it.
2. **How should `position_effect` be introduced?**
   First on the copy event/decision. Consider an optional backward-compatible
   intent field only in Stage 3, paired with a Risk close-size check.
3. **Where is the composition root?**
   Typer wiring is in `src/polysia/cli.py`; Docker currently invokes that CLI.
   There is no generalized worker/orchestrator.
4. **Where should the source adapter live?**
   A port in `application/ports` and implementation in
   `adapters/polymarket`, separate from strategies.
5. **What is the migration pattern?**
   SQLite initializes an additive `schemas.sql`; no versioned migration
   framework currently exists.
6. **How are new replay events handled?**
   Current replay accepts only Polymarket market-data JSONL. Use a focused
   copy replay coordinator rather than overloading market-book events.
7. **How does PaperBroker model fills?**
   It fills immediately up to aggregate best-level depth, supports partial
   status, and leaves the remainder open. It does not model later matching,
   fees, tick/minimum rules, or cancellation latency.
8. **How are source linkage and expiry stored?**
   They are not first-class current intent/order fields. Decision payloads can
   carry evidence, but durable source-order linkage needs a focused later
   contract.
9. **Where should linked cancellation live?**
   In a narrow application coordinator using execution cancellation behind
   existing safety controls, never inside strategy code. No live version is
   needed before Stage 7.
10. **How are manual exits and restart detected?**
    Reconciliation compares internal orders/positions with external state and
    can activate a safety pause. Copy-specific source correlation and ingestion
    checkpoint recovery are not current.
11. **How is market/outcome mapped to a token?**
    The Polymarket mapper converts SDK market outcomes to canonical market
    models carrying adapter-resolved token IDs. Generic copy policy must not
    consume the SDK object or raw token mapping.
12. **How can server shadow run safely?**
    A later copy shadow command can reuse the image, protected state directory,
    non-root user, read-only filesystem, no ports, and forced live-off settings.
    The current server service does not run strategies.
13. **Does Strategy Registry need new fields?**
    No for the first experiment. `EXPERIMENTAL`, parameters, evidence
    references, run decisions, risk results, fills, and reconciliation are
    already present.
14. **What governance status changes?**
    The roadmap explicitly deferred Copy Trading. The owner's current
    instruction supersedes that priority only for a bounded research-validation
    slice. It does not authorize live operation, capital scaling, or production
    promotion. This handoff records that limited decision; broader roadmap
    changes wait for data proof.

## Explicit unknowns for Stage 1

- Which current official Polymarket API or SDK surface, if any, exposes
  arbitrary leader executed activity.
- Whether the source identifies both sides of an execution consistently.
- Whether proxy/funder/signer identities require grouping for one leader.
- Whether historical and incremental endpoints share stable identifiers.
- Whether timestamps represent execution, matching, indexing, or observation.
- Whether reductions and complete exits are inferable without reconstructing
  the leader's prior position history.
- Pagination limits, retention window, rate limits, outage behavior, and
  duplicate semantics.
- Measured observation latency for BTC Up/Down 15-minute markets.
- Owner approval to retain raw public wallet evidence and the retention period.

## Stage 1 acceptance criteria

Stage 1 is complete only if:

- current official documentation and the pinned SDK surface are reviewed;
- at least one real historical or current executed trade can be normalized
  without guessing required fields;
- BTC 15-minute market and outcome mapping is deterministic;
- event identity is stable across repeated ingestion;
- pagination and restart do not create duplicate normalized events;
- missing and ambiguous fields are measured;
- p50, p95, and maximum observation latency are reported;
- raw and normalized artifacts are reproducible and checksummed;
- reports contain safe aliases rather than raw wallet values;
- no intent, paper order, live order, cancellation, or venue mutation occurs.

Stop and return `NO-GO` if price, time, side, market, outcome, or stable identity
cannot be established reliably from an approved source.

## Required Stage 1 tests and gates

Focused tests:

- raw response to `LeaderTradeEvent` normalization;
- Decimal and aware-UTC validation;
- deterministic event identity;
- duplicate suppression across repeated pages and restart checkpoints;
- pagination boundary behavior;
- BTC 15-minute and outcome mapping;
- missing/ambiguous field fail-closed behavior;
- sanitization of leader and evidence fields;
- contract test for any newly used official SDK method.

Required PR-A validation after code changes:

```text
python -m compileall -q src tests
python -m ruff check .
python -m mypy src
python -m pytest -q
python -m pip check
python -m polysia.security.secret_scan
python -m build
```

Stage 0 is documentation-only, so the full runtime suite is not required.

## Risks and rollback

Primary risk is data-source inadequacy, not internal architecture. Building copy
policy or execution behavior before proving source identity, semantics, and
latency would create false confidence and disposable code.

Stage 0 rollback is deletion of this handoff and the experimental branch. No
schema, runtime, dependency, environment, server, or external state must be
restored.

## Go/No-Go recommendation

**Decision: CONDITIONAL GO for Stage 1 Data Feasibility.**

Conditions:

1. read-only scope only;
2. one to three owner-approved leader identifiers supplied through a protected,
   untracked mechanism;
3. owner decision on whether sanitized raw wallet evidence may be retained;
4. current official source documentation verified before adapter code;
5. immediate stop if arbitrary leader executions cannot be reconstructed
   reliably.

No owner trading-limit decision is needed in Stage 1 because it creates no
intent or order.

## Exact next task

After owner approval, continue on `codex/copytrading-experiment` and execute only
Stage 1 of `POLYSIA_COPYTRADING_CODEX_EXECUTION_PLAN.md`.

Verify current official Polymarket documentation and pinned SDK support, then
prove or reject a bounded read-only source for one to three approved leader
aliases on BTC Up/Down 15-minute markets. Produce sanitized, checksummed raw and
normalized evidence plus fixture-based tests. Do not create a strategy,
`CopyDecision`, `OrderIntent`, paper order, live order, cancellation, schema
migration, or server deployment.
