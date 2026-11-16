# PolySia Project Status

Reviewed against repository source: 2026-11-16. This is durable engineering
status, not a live runtime dashboard. Current operational SHA, health and account
state must be queried through the [server runbook](../10-operations/server-deployment.md#current-operational-truth).

## Current delivery

- Development preview, proportional CI/Windows selection, dependency maintenance
  and recoverable branch cleanup were delivered in PRs #298 and #301.
- Historical report engines are retired; unverified preparation is explicit.
  Console reads and multi-query operational reports retain coherent snapshots.
- Current versions belong to [package declarations](../../pyproject.toml),
  [resolved locks](../../locks/), [CI](../../.github/workflows/ci.yml) and
  [image configuration](../../Dockerfile), not copied status-table numbers.
- Selected Standards adoption is recorded in [adoption](../../standards/adoption.toml),
  [conformance](../../standards/conformance.toml) and the
  [consumer review](standards-conformance-v1.0.0.md). No additional profiles apply.
- Engineering checks do not establish real-host commissioning, human usability,
  financial-account verification or Live authority. Those require their own
  applicable receipts and permissions.

## Dated operational evidence

The November 8 OP1 preparation and N3 incident closure remain dated evidence;
this review did not query a host, deploy, start a campaign or execute a trade.
See [OP1 readiness](../18-ai-handoffs/op1-operational-readiness-2026-11-08.md) and
[N3 incident closure](../18-ai-handoffs/nonlive-n3-health-2026-11-06.md#n3-r1-incident-closure).
Earlier observation outcomes, timings, blockers and snapshot tables are preserved
in the [original status at 4f0a596](https://github.com/PolySia-Systems/Platform/blob/4f0a596b598d65c50fc1a44e531f11b0ffb7e186/docs/00-governance/PROJECT_STATUS.md)
and the evidence owners below. They must not be interpreted as current host state.


## Truth ownership

Engineering addition, 2026-10-26: [bounded financial-session requirements](../03-requirements/continuous-financial-session.md)
describe a default-disabled connected session, immutable policies, bounded
Shadow Lab and scoped Console/CLI controls integrated through PR #230. Its
[ADR-0023](../04-architecture/adrs/ADR-0023-bounded-financial-session.md) is Proposed;
financial operational acceptance, run authority, human acceptance and observed
economics remain separate gates after D1 DATA_ONLY delivery. This note changes
no historical host receipt and does not claim an active financial session.

| Fact | Authoritative owner |
|---|---|
| Implementation, schemas, configuration | Git / current code |
| Architecture decisions | Approved ADRs under `docs/04-architecture/adrs/` |
| Required behavior | `docs/03-requirements/` |
| Validation evidence | CI and tests |
| Active work and ordinary resume | GitHub Issue or PR |
| Current operational SHA, health, restarts | Runtime query in the [server deployment runbook](../10-operations/server-deployment.md#current-operational-truth) |
| Historical operational evidence | Dated handoff or snapshot under `docs/18-ai-handoffs/` |
| Immutable migration baseline | [`docs/13-ai-handoffs/BASELINE_AUDIT.md`](../13-ai-handoffs/BASELINE_AUDIT.md) |
| Generated views | Disposable projections; never authoritative |

## What PolySia currently is

PolySia is a risk-controlled prediction-market platform. Polymarket is the
first venue adapter, not the product identity. CURRENT deployment is one
Python modular monolith.

Safety posture:

- Defaults remain `TRADING_MODE=DATA_ONLY` and `LIVE_TRADING_ENABLED=false`.
- Executable intents follow Strategy -> independent Risk -> Execution -> Adapter.
- Financial values use `Decimal` or an approved fixed-point type.
- No new Live authorization exists. LIVE-001 through LIVE-004 and all Tiny
  Live Copy authorizations are consumed.

CURRENT capabilities:

- Public Polymarket discovery, normalized market data, Decimal books, and a
  strategy framework with a versioned Strategy Registry.
- Independent pre-trade Risk, paper/shadow execution, positions, P&L, SQLite
  persistence, and fail-closed reconciliation. Stage 4B accounting and
  duplicate-publication invariants now block commit and watermark progression.
- Guarded authenticated reads and bounded Live tooling that stays dry-run by
  default. Live submission requires fresh verified account evidence and the
  exact immutable request approved by Risk; generic `live limit-order` is
  preview-only.
- A SHADOW-only Control Kernel slice for `stale-price@0.1.0`.
- Wallet Intelligence Stages 1–4B as DATA_ONLY research/Shadow systems. They
  are not profitability evidence and do not authorize trading.
- Stage 4B Continuous Shadow is a bounded experimental portfolio and ledger
  on its own store. It is not the TARGET OMS, allocator, or execution router.
- Research Replay can reconstruct the frozen local historical backup and compare
  Current Control with Target Exposure v1 without Live, Risk, or Execution
  authority. That backup remains historical evidence; the separately
  authorized 2026-09-27 Helsinki `DATA_ONLY` run has its own dated record. See
  [Target Exposure Replay](../03-requirements/shadow-target-exposure-replay.md).
- [ADR-0018](../04-architecture/adrs/ADR-0018-developer-context-packets.md),
  [ADR-0019](../04-architecture/adrs/ADR-0019-research-run-contracts.md), and
  [ADR-0020](../04-architecture/adrs/ADR-0020-wallet-flexibility-reanalysis.md)
  are CURRENT repository capabilities. Their decisions stay in those ADRs.
- A provider-neutral prospective collector and public source benchmark persist
  canonical research evidence in an isolated SQLite store. Schema v2 preserves
  distinct wallet observations of a shared source trade; replay isolates each
  Market/Outcome episode and requires explicit follower-execution evidence.
  Required-source recovery and research eligibility fail closed, and bounded
  active experiment evidence is retained until verified bundle finalization.
  They do not write into Stage 4B financial state or the latency sidecar. See
  [Prospective Research Evidence Collector](../03-requirements/prospective-evidence-collector.md).
- Prospective economic evaluation now has a frozen v1 contract and one
  deterministic command. It links each eligible Wallet observation to causal
  side-aware depth and verified fee evidence, then reports cost-aware Current
  Control versus Target Exposure results. Historical evidence without this
  bridge remains `INSUFFICIENT_DATA`. A bounded 2026-09-27 `DATA_ONLY` Canary
  was technically valid but short of its activity and execution-evidence
  thresholds; the separately authorized four-hour run is exploratory, not
  proof of Live readiness. See the
  [dated acceptance evidence](../18-ai-handoffs/shared-data-shadow-acceptance-2026-09-27.md).
- Combined backups validate staged snapshots before publishing and rotating a
  recovery bundle. Public book reads support bounded batches; historical reads
  enforce exact time windows. See the [operating runbook](../10-operations/wallet-intelligence-ingestion.md).
- Versioned Research and Shadow configuration now supports a software envelope
  of 1–40 wallets with explicit operational capacity admission, shared active
  selection, readiness diagnostics, and JSON contracts for a future UI. The
  envelope is not a measured Helsinki capacity. Existing frozen v1/v2 Research
  and v1 Shadow periods retain their original semantics.

## What is not yet implemented

Generalized intent aggregation, capital allocation, OMS/Transaction Manager,
generalized ledger, execution router, adapter registry,
additional venues, AI/ML, and production Live automation remain TARGET or
FUTURE unless an approved document proves otherwise.

## Historical evidence owners

Do not duplicate these records here.

| Topic | Owner |
|---|---|
| LIVE-004 completed round trip | [live-004 handoff](../18-ai-handoffs/polysia-live-004-final-handoff.md) |
| Tiny Live Copy 004 cancellation | [004 diagnostic](../18-ai-handoffs/polysia-tiny-live-copy-004-cancellation-diagnostic.md) |
| Helsinki Stages 1–4 deployment | [Finland deployment](../18-ai-handoffs/polysia-finland-wallet-intelligence-deployment.md) |
| Stage 4B data lifecycle T0 and 24h | [data lifecycle v1](../18-ai-handoffs/stage4b-data-lifecycle-v1.md) |
| Frozen Target Exposure v1 baseline | [Target Exposure v1](../18-ai-handoffs/shadow-target-exposure-v1-baseline.md) |
| Python 3.14 / SDK upgrade | [UPGRADE-006](../18-ai-handoffs/polysia-upgrade-006-handoff.md) |
| Architecture visual baseline | [architecture refresh](../18-ai-handoffs/architecture-truth-refresh-2026-08-18.md) |
| Roadmap | [roadmap](../22-roadmap/roadmap.md) |
| 2026-09-27 one-off off-host recovery and remaining automation gap | [dated acceptance evidence](../18-ai-handoffs/shared-data-shadow-acceptance-2026-09-27.md) |
