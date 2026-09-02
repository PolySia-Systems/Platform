# PolySia Documentation

This is the only canonical documentation entrance. Current repository
reality takes precedence over historical delivery evidence.

## 30 seconds

PolySia is a risk-controlled prediction-market platform. Polymarket is the
first venue adapter, not the product identity.

**What exists today:** one Python modular monolith with independent Risk,
paper/shadow execution, reconciliation, a SHADOW-only Control Kernel slice,
and DATA_ONLY Wallet Intelligence Stages 1–4B. Live trading stays disabled
by default. No new Live authorization exists.

**What is not implemented:** generalized OMS, capital allocation, execution
router, adapter registry, extra venues, operator web UI, and production Live
automation.

**Current focus:** observe the deployed DATA_ONLY/Shadow pipeline. Do not
promote modeled P&L into Live authority.

**Where to go next:** [project status](00-governance/PROJECT_STATUS.md) for
durable state, [architecture](04-architecture/README.md) to go deeper, and
the [server deployment runbook](10-operations/server-deployment.md#current-operational-truth)
to query the host.

## Durable project truth

- [Project status](00-governance/PROJECT_STATUS.md) — capabilities, limits,
  safety posture, and dated runtime snapshots. Not a live dashboard.
- [Roadmap](22-roadmap/roadmap.md)

## Architecture and decisions

- [Architecture overview](04-architecture/README.md)
- [Approved architecture decisions](04-architecture/adrs/)
- [Architecture visualization index](04-architecture/visual-system/architecture-visualization-index.md)

## Operations and safety

- [Operations documentation](10-operations/)
- [Current operational truth](10-operations/server-deployment.md#current-operational-truth)
- [Risk register](00-governance/registers/risks.md)
- [Live safety gates](04-architecture/adrs/ADR-0008-live-safety-gates.md)
- [Delivery and rollback](10-operations/delivery-and-rollback.md)

## Standards and governance

- [Master Operating Charter](00-governance/master-operating-charter.md)
- [Document control](00-governance/document-control.md)
- [Adopted Standards record](../standards/adoption.toml)
- [Standards conformance review](00-governance/standards-conformance-v0.4.0.md)

## Evidence

- [Current evidence index](18-ai-handoffs/README.md) — major operational,
  safety, and delivery evidence. Ordinary work resumes from the Issue or PR.
- [Immutable baseline audit](13-ai-handoffs/BASELINE_AUDIT.md)
- [Archived documentation](99-archive/) — provenance only, not current
  instructions.

## Baseline inventory

The [capability catalog](01-discovery/capability-catalog.md) is a baseline
non-live inventory of CAP-001 through CAP-012. It is not a complete statement
of current Wallet Intelligence or Stage 4B capabilities. Use project status
and architecture for CURRENT product truth.
