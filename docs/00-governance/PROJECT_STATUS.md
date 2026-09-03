# PolySia Project Status

## Document control

| Field | Value |
|---|---|
| Review date | 2026-09-03 |
| Source-of-truth branch | `main` |
| Repository | `https://github.com/PolySia-Systems/Platform.git` |
| Primary runtime | CPython `3.14.6` |
| Supported CI runtime | Python `3.14` only (`>=3.14,<3.15`) |
| Polymarket SDK | `polymarket-client==0.6.0` |
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
  persistence, and fail-closed reconciliation.
- Guarded authenticated reads and bounded Live tooling that stays dry-run by
  default.
- A SHADOW-only Control Kernel slice for `stale-price@0.1.0`.
- Wallet Intelligence Stages 1–4B as DATA_ONLY research/Shadow systems. They
  are not profitability evidence and do not authorize trading.
- Stage 4B Continuous Shadow is a bounded experimental portfolio and ledger
  on its own store. It is not the TARGET OMS, allocator, or execution router.

## What is not yet implemented

Generalized intent aggregation, capital allocation, OMS/Transaction Manager,
generalized ledger, execution router, adapter registry, operator web UI,
additional venues, AI/ML, and production Live automation remain TARGET or
FUTURE unless an approved document proves otherwise.

## Current focus and blockers

**Next task:** observe the deployed DATA_ONLY/Shadow pipeline for data
quality, stability, and copyability. Do not promote modeled P&L into Live
authority.

Blockers and limitations:

- Encrypted off-host backups and external alert delivery are unfinished.
- Branch-protection policy remains governance debt.
- One bounded profitable LIVE-004 round trip is statistically meaningless.
- Modeled Stage 4B P&L remains negative and is not a promotion decision.
- The Helsinki host is suitable for DATA_ONLY, paper, and shadow validation.
  It is not production readiness.

Next milestones: scheduled observation plus alerts and off-host backup;
reproducible historical data and fee-aware backtests before any new Tiny-Live
review; branch protection through a separate governance task.

## Audited runtime snapshot

Audited as of 2026-09-03.

This snapshot is historical operational evidence copied from the Stage 4B
data-lifecycle T0 closeout. It is not a claim about the host at read time.

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
Helsinki migrated v5→v6, retained history for a 10-poll canary, then
deduplicated and compacted Stage 4B offline. This is not 24-hour storage
acceptance.

Query the host for anything newer. Full delivery, checksums, canary, and T0:
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
| Stage 4B data lifecycle T0 | [data lifecycle v1](../18-ai-handoffs/stage4b-data-lifecycle-v1.md) |
| Python 3.14 / SDK upgrade | [UPGRADE-006](../18-ai-handoffs/polysia-upgrade-006-handoff.md) |
| Architecture visual baseline | [architecture refresh](../18-ai-handoffs/architecture-truth-refresh-2026-08-18.md) |
| Roadmap | [roadmap](../22-roadmap/roadmap.md) |
| Recovery limitation (no off-host backup) | [server deployment](../10-operations/server-deployment.md) |
