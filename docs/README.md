# PolySia Documentation

This is the only canonical documentation entrance. Current repository
reality takes precedence over historical delivery evidence.

## 30 seconds

PolySia is a risk-controlled prediction-market platform. Polymarket is the
first venue adapter, not the product identity.

**What exists today:** one Python modular monolith with independent Risk,
paper/shadow execution, reconciliation, a SHADOW-only Control Kernel slice,
and DATA_ONLY Wallet Intelligence Stages 1â€“4B. Stage 4B accounting fails closed
before publication; Live-capable paths require verified state and an exact
Risk-approved request. Live trading stays disabled by default. No new Live
authorization exists.

**What is not implemented:** generalized OMS, capital allocation, execution
router, adapter registry, extra venues, and production Live
automation.

**Current focus:** the [independent Platform Shadow and Console](10-operations/independent-platform-shadow.md) retain canonical reports, bounded discovery and
protected operations. Track separate implementation, deployment and observational
acceptance in the [execution record](18-ai-handoffs/platform-independent-shadow-2026-10-16.md).
Do not promote modeled P&L into Live authority.

**Where to go next:** [project status](00-governance/PROJECT_STATUS.md) for
durable state and [architecture](04-architecture/README.md) to go deeper.
For a disposable, scoped resume briefing use
`polysia system developer-context`; the packet is a generated view, not
project truth. A bounded, owner-authorized Helsinki `DATA_ONLY` run is recorded
in [the dated acceptance evidence](18-ai-handoffs/shared-data-shadow-acceptance-2026-09-27.md).
Query the host for current state only within an authorized operational task.
New developers should follow the [deterministic fixture entry](03-requirements/developer-context-packet.md#developer-entry).
Server administrators use [guided installation and maintenance](10-operations/independent-platform-shadow.md#release-and-isolated-roots).
Private SSH HTTPS, optional own-domain HTTPS and the existing Cloudflare route
share the same Console. Their engineering checks, public commissioning and
human acceptance are distinct evidence.
The earlier frozen Stage 4B backup remains documented in
[Target Exposure v1 baseline](18-ai-handoffs/shadow-target-exposure-v1-baseline.md).

## Durable project truth

- [Project status](00-governance/PROJECT_STATUS.md) â€” capabilities, limits,
  safety posture, and dated runtime snapshots. Not a live dashboard.
- [Roadmap](22-roadmap/roadmap.md)

SDK compatibility and rollback: [current boundary and upgrade procedure](10-operations/polymarket-sdk-upgrade.md).
Immutable v0.4.0 ships SDK 0.13.0 with clean disabled private commissioning and
independent cold recovery; [PR #200](https://github.com/PolySia-Systems/Platform/pull/200) records the migration.
Previous runtime receipts are historical after the owner's server reset.

## Architecture and decisions

- [Architecture overview](04-architecture/README.md)
- [Approved architecture decisions](04-architecture/adrs/)
- [Architecture visualization index](04-architecture/visual-system/architecture-visualization-index.md)

## Operations and safety

- [Human Console contract, static build and completed presentation migration](04-architecture/adrs/ADR-0024-human-console-contract-and-static-build.md)

- [Bounded financial-session engineering and commissioning prerequisites](10-operations/continuous-financial-session.md)

- [Operations documentation](10-operations/)
- [Retained research artifact intake](10-operations/wallet-intelligence-research-intake.md)
- [Current operational truth](10-operations/server-deployment.md#current-operational-truth)
- [Risk register](00-governance/registers/risks.md)
- [Live safety gates](04-architecture/adrs/ADR-0008-live-safety-gates.md)
- [Verified Live state and approved orders](03-requirements/live-verified-state-and-approved-order.md)
- [Shadow Target Exposure Replay v1](03-requirements/shadow-target-exposure-replay.md)
- [Prospective research evidence collector](03-requirements/prospective-evidence-collector.md)
- [Research and Shadow UI backend contracts](10-operations/research-shadow-ui-contracts.schema.json)
- [Developer context packet](03-requirements/developer-context-packet.md)
- [Delivery and rollback](10-operations/delivery-and-rollback.md)

## Standards and governance

- [Master Operating Charter](00-governance/master-operating-charter.md)
- [Document control](00-governance/document-control.md)
- [Adopted Standards record](../standards/adoption.toml)
- [Standards conformance review](00-governance/standards-conformance-v1.0.0.md)

## Evidence

- [Current evidence index](18-ai-handoffs/README.md) â€” major operational,
  safety, and delivery evidence. Ordinary work resumes from the Issue or PR.
- [Immutable baseline audit](13-ai-handoffs/BASELINE_AUDIT.md)
- [Archived documentation](99-archive/) â€” provenance only, not current
  instructions.

## Baseline inventory

The [capability catalog](01-discovery/capability-catalog.md) is a baseline
non-live inventory of CAP-001 through CAP-012. It is not a complete statement
of current Wallet Intelligence or Stage 4B capabilities. Use project status
and architecture for CURRENT product truth.
