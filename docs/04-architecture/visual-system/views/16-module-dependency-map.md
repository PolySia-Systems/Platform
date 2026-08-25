# Module Dependency Map

- **Diagram ID:** PSA-ARCH-16
- **Purpose:** Show allowed inward dependencies, enforced forbidden leakage, SDK confinement, and acknowledged module debt.
- **Scope:** Architectural dependency zones rather than every import edge.
- **Architecture status:** CURRENT
- **Audience:** Developers, maintainers, architects, and code reviewers.
- **Source commit:** `ac104c708100bf9fff7e632acefd89bf90b8e509`

## Mermaid diagram

Canonical source: [`16-module-dependency-map.mmd`](../sources/16-module-dependency-map.mmd)

```mermaid
flowchart TB
  Interface["Interfaces: cli + cli_commands + cli_support\nmonitoring, deployment, backtesting\n[CURRENT]"]:::application
  Runtime["Runtime services: execution, reconciliation, bus, orderbook, features, portfolio, risk, strategies\n[CURRENT]"]:::current
  Storage["Storage adapters and repositories\n[CURRENT]"]:::storage
  Control["Control core and Shadow intent boundary\n[CURRENT bounded; venue-neutral]"]:::application
  Adapters["Adapters: adapters/polymarket\n[CURRENT]"]:::adapter
  Ports["Application ports\n[CURRENT protocols]"]:::application
  Services["Application services\nWallet Intelligence, selection, Shadow, handoff\n[CURRENT]"]:::application
  Domain["Domain models and clocks\n[CURRENT inner layer]"]:::domain
  SDK["Official polymarket SDK\n[EXTERNAL]"]:::external

  Interface --> Runtime
  Interface --> Storage
  Interface --> Control
  Interface --> Adapters
  Interface --> Services
  Runtime --> Domain
  Storage --> Domain
  Storage --> Control
  Control --> Runtime
  Adapters --> Domain
  Ports --> Domain
  Services --> Ports
  Services --> Domain
  Adapters --> SDK

  Forbidden1["FORBIDDEN: domain/application -> adapters or SDK"]:::danger
  Forbidden2["FORBIDDEN: strategies/storage -> venue adapters"]:::danger
  Forbidden3["FORBIDDEN: SDK import outside adapters/polymarket"]:::danger
  Forbidden4["FORBIDDEN: control core -> adapter, SDK, or SQLite adapter"]:::danger
  Tests["Architecture tests enforce all four boundaries\n[CURRENT]"]:::safe

  Tests --> Forbidden1
  Tests --> Forbidden2
  Tests --> Forbidden3
  Tests --> Forbidden4

  Debt1["Technical debt: operations/live command modules\nretain broad orchestration"]:::risk
  Debt2["Technical debt: oversized monitoring/live modules"]:::risk
  Interface -.-> Debt1
  Runtime -.-> Debt2

  subgraph LEGEND["Legend"]
    L1["Allowed dependency"]:::current
    L2["Adapter boundary"]:::adapter
    L3["Forbidden leakage"]:::danger
    L4["Known debt, not boundary failure"]:::risk
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef application fill:#FFFFFF,stroke:#2563EB,stroke-width:2px,color:#0F172A;
  classDef domain fill:#FFFFFF,stroke:#0F766E,stroke-width:2px,color:#0F172A;
  classDef adapter fill:#FFFFFF,stroke:#4F46E5,stroke-width:2px,color:#0F172A;
  classDef storage fill:#FFFFFF,stroke:#475569,stroke-width:2px,color:#0F172A;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2px,color:#0F172A;
  classDef danger fill:#FEF2F2,stroke:#DC2626,stroke-width:2.5px,color:#0F172A;
  classDef safe fill:#F0FDF4,stroke:#16A34A,stroke-width:2px,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Read allowed arrows toward domain, then the separate forbidden-boundary checks and non-failing technical-debt notes.

## Current implementation mapping

Architecture tests prohibit domain/application adapter or SDK imports,
strategy/storage adapter imports, and official SDK imports outside
`adapters/polymarket`. They also keep the Control Kernel venue-neutral and keep
its core free of the SQLite storage adapter. Current outer services may depend
on adapters where operationally required.

## Target/future elements

Wallet Intelligence, copyability selection, dynamic and continuous Shadow, and
protected-handoff application services are CURRENT. Broader dependency
inversion should continue incrementally through existing ports where it has
concrete value.

## Related repository files

`src/polysia/domain/`, `src/polysia/application/`, `src/polysia/control/`,
`src/polysia/adapters/`, `src/polysia/strategies/`, `src/polysia/storage/`,
`docs/00-governance/registers/technical-debt.md`

## Related tests

`tests/architecture/test_boundaries.py`, `tests/architecture/test_module_decomposition.py`

## Related ADRs

ADR-0002, ADR-0004, ADR-0011, ADR-0012

## Related capabilities/requirements

CAP-001–CAP-010; REQ-006

## Assumptions

Dependency direction is assessed at architectural zones; outer operational modules may coordinate several zones.

## Known limitations

This is not an exhaustive generated import graph. The CLI facade is
composition-only; operations/live command modules and monitoring retain broad
orchestration that remains tracked debt.

## Review trigger

An architecture test changes, SDK import moves, inner-layer dependency appears, or a top-level package is reclassified.
