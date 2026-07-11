# Capability Roadmap

- **Diagram ID:** PSA-ARCH-18
- **Purpose:** Visualize current capabilities, next architecture priorities, and later optional extensions without implying release dates.
- **Scope:** Foundation/MVP/limited-live capabilities, target orchestration and platform boundaries, and future multi-market/Web3/institutional categories.
- **Architecture status:** MIXED
- **Audience:** Owner, roadmap reviewers, architects, developers, and risk reviewers.
- **Source commit:** `44a8ae0fbccd0de916a0621236ea5931e7c3a256`

## Mermaid diagram

Canonical source: [`18-capability-roadmap.mmd`](../sources/18-capability-roadmap.mmd)

```mermaid
flowchart LR
  subgraph NOW["Implemented foundation / MVP / limited-live [CURRENT]"]
    N1["Public data, stream, normalization, event bus, order book"]:::current
    N2["Research strategies, risk, kill switch, paper execution, P&L"]:::current
    N3["SQLite, reconciliation, monitoring, backtesting, delivery tooling"]:::current
    N4["Authenticated reads and guarded tiny-live tools"]:::risk
  end

  subgraph NEXT["Next architecture priorities [TARGET]"]
    T1["Strategy registry, orchestration, and conflict resolution"]:::target
    T2["Portfolio and capital allocation"]:::target
    T3["OMS / Transaction Manager and generalized ledger"]:::target
    T4["Adapter registry, operator console, portable runtime hardening"]:::target
  end

  subgraph LATER["Later optional capabilities [FUTURE]"]
    F1["Additional prediction markets, exchanges, and brokers"]:::future
    F2["Wallet intelligence and copy trading"]:::future
    F3["Web3 / DeFi data and controlled execution"]:::future
    F4["Institutional hardening and justified high availability"]:::future
  end

  N1 --> T1
  N2 --> T1
  N2 --> T2
  N3 --> T3
  N4 --> T4
  T1 -.-> F1
  T2 -.-> F2
  T3 -.-> F3
  T4 -.-> F4

  Gate1["Gate: evidence, tests, risk independence, reconciliation"]:::safe
  Gate2["Gate: no release dates or capability claims without approval"]:::risk
  NOW --> Gate1
  Gate1 --> NEXT
  NEXT --> Gate2
  Gate2 -.-> LATER

  subgraph LEGEND["Legend"]
    L1["CURRENT solid"]:::current
    L2["TARGET dashed"]:::target
    L3["FUTURE dotted"]:::future
    L4["SAFETY / PROMOTION GATE"]:::risk
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef target fill:#F1F5F9,stroke:#2563EB,stroke-width:2px,stroke-dasharray:6 4,color:#0F172A;
  classDef future fill:#F1F5F9,stroke:#64748B,stroke-width:2px,stroke-dasharray:2 5,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2.5px,color:#0F172A;
  classDef safe fill:#F0FDF4,stroke:#16A34A,stroke-width:2px,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Read CURRENT capabilities, pass the evidence gate into TARGET priorities, then pass a separate approval gate before any FUTURE category.

## Current implementation mapping

Current capabilities are the twelve entries in the baseline capability catalog and the verified Phase I delivery.

## Target/future elements

Strategy orchestration, allocator, OMS/generalized ledger, adapter registry, operator console, and portable hardening are TARGET. Multi-venue, wallet intelligence/copy trading, Web3/DeFi, and institutional HA are FUTURE.

## Related repository files

`docs/01-discovery/capability-catalog.md`, `docs/22-roadmap/roadmap.md`, `docs/00-governance/master-operating-charter.md`, `docs/18-ai-handoffs/phase-i-final-handoff.md`

## Related tests

Phase I handoff; architecture, contract, integration, migration, property, and characterization test evidence

## Related ADRs

ADR-0001–ADR-0010

## Related capabilities/requirements

CAP-001–CAP-012; REQ-001–REQ-007; future charter taxonomy

## Assumptions

Later capability categories are options, not committed scope or dates.

## Known limitations

The roadmap does not prioritize by cost, regulatory feasibility, or economic value and is not a delivery schedule.

## Review trigger

Capability status, roadmap priority, approval gate, or product scope changes.
