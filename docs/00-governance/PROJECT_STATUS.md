# PolySia Project Status

## Document control

| Field | Value |
|---|---|
| Review date | 2026-09-27 |
| Source-of-truth branch | `main` |
| Repository | `https://github.com/PolySia-Systems/Platform.git` |
| Primary runtime | CPython `3.14.7` |
| Supported CI runtime | Python `3.14` only (`>=3.14,<3.15`) |
| Polymarket SDK | `polymarket-client==0.7.1` |
| Conformance status | `STANDARDS_V0_4_0_FULLY_ENFORCED` |

This document is durable repository status. It is not a live runtime
dashboard. Git HEAD is implementation truth. Current operational SHA, health,
and restart counts must be queried on the host.

## Truth ownership

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

## What is not yet implemented

Generalized intent aggregation, capital allocation, OMS/Transaction Manager,
generalized ledger, execution router, adapter registry, operator web UI,
additional venues, AI/ML, and production Live automation remain TARGET or
FUTURE unless an approved document proves otherwise.

## Current focus and blockers

The 2026-09-27 owner authorization reactivated Helsinki for a bounded
`DATA_ONLY` source benchmark, Canary, Continuous Shadow worker, and four-hour
exploratory Research run. The [dated acceptance
record](../18-ai-handoffs/shared-data-shadow-acceptance-2026-09-27.md) owns
their evidence and explicit unmet gates. This Markdown is not live host state
or authorization for another run. Query SHA, health, restarts, and final
experiment state through the [server deployment
runbook](../10-operations/server-deployment.md#current-operational-truth)
only within an authorized task. Nuremberg remains outside this scope.

Blockers and limitations:

- The Canary, four-hour Main failure archive, and two three-store bundles
  were encrypted off-host and recovery-checked on 2026-09-27. Recurring
  transfer and external alert delivery are unfinished; DPAPI recovery depends
  on the same Windows user profile.
- The 20-minute Canary did not meet the activity or executable-evidence gates.
  The owner-directed four-hour run closed with 24 valid but empty windows and
  a `FAILURE_ARCHIVED` unverified bundle. Its technical gate is `FAIL` and
  economics is `INSUFFICIENT_DATA`; it cannot retroactively make that Canary
  `PASS`. The dated acceptance record has the exact evidence.
- Branch-protection policy remains governance debt.
- Risk/Execution and Stage 4B accounting hardening are merged in Git. That is
  a repository fact, not a claim about a live host.
- One bounded profitable LIVE-004 round trip is statistically meaningless.
- Modeled Stage 4B P&L remains negative on Current Control and is not a
  promotion decision. Target Exposure v1 is a PARTIAL research Replay with
  UNKNOWN marks, not Alpha and not Live readiness.
- No production Live host or real order is authorized. Helsinki's dated
  `DATA_ONLY` acceptance is not Live readiness.

Next milestones: investigate the selected-wallet activity and market evidence
needed for a fresh standard Canary, continue explicit Shadow health checks,
and address recurring backup/alert delivery and branch protection separately.
The four-hour failure archive and deterministic empty-sample analyses are
preserved off-host. The Stage 1–3 daily timer was re-enabled after Main closed;
Stage 4B continued through its first period rollover. Any new experiment
requires its own authorized scope; do not access Nuremberg.

## Audited runtime snapshot

Audited as of 2026-09-04.

This snapshot is historical operational evidence copied from the Stage 4B
data-lifecycle 24-hour closeout. It is not a claim about the host at read time.

| Field | Audited value |
|---|---|
| Audited repository / release commit | `6743f7464f94d3fb76edc057834e8219ca7ebfe0` |
| Release path | `/opt/polysia-releases/6743f7464f94d3fb76edc057834e8219ca7ebfe0` |
| Archive SHA-256 | `83a827d6137cf4a3bf9997c89928fe5c191bbc67df9b956529b214f3991f7d8f` |
| Image ID | `sha256:98df02069c471e5e71aabcd31448a9a4862510f9e735ad9a3fe62c073855d3ee` |
| Wallet Intelligence modes | `TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false` |
| Stage 4B worker start after compact cutover | `2026-09-02T23:48:37Z`, `NRestarts=0` |
| Stage 4B schema | 6 |
| 3x-ui identity (unrelated) | `ab567d6d...`, started `2026-08-21T10:33:56Z` |

PR `#112` made change-driven mark history and bounded recovery CURRENT.
Helsinki 24-hour storage acceptance against `stage4b-data-lifecycle-v1` is
recorded as PASS in the lifecycle handoff (80.7% fewer history rows than the
old per-poll path in the T0 window; rotating keep-three restore-tested).

Query the host for anything newer. Full delivery, checksums, canary, T0, and
24-hour evidence:
[Stage 4B data lifecycle v1](../18-ai-handoffs/stage4b-data-lifecycle-v1.md).
The preceding schema-v5 ownership closeout remains
[Stage 4B ownership cutover](../18-ai-handoffs/stage4b-data-ownership-cutover.md).

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
