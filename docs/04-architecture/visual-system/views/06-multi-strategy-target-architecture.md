# Multi-Strategy Target Architecture

- **Diagram ID:** PSA-ARCH-06
- **Purpose:** Make the safe extension model for concurrent strategy plug-ins immediately understandable.
- **Scope:** Current strategy plug-ins plus target registration, supervision, conflict resolution, capital allocation, OMS, routing, and feedback.
- **Architecture status:** MIXED
- **Audience:** Owner, architects, strategy developers, risk reviewers, and execution developers.
- **Source commit:** `8d64bb7bd5182bde5ed3a95c6ac26f7c859737a6`
- **Reviewed:** 2026-09-05

## Mermaid diagram

Canonical source: [`06-multi-strategy-target-architecture.mmd`](../sources/06-multi-strategy-target-architecture.mmd)

```mermaid
flowchart LR
  subgraph INPUTS["Inputs and bounded current control"]
    direction TB
    Market["Normalized Market Events\n[CURRENT]"]:::data
    Context["Read-only Market / Portfolio / Risk Context\n[TARGET contract]"]:::target
    Registry["Minimal Strategy Registry\nidentity, version, lifecycle, run evidence\n[CURRENT bounded]"]:::current
    Control["Shadow Control Kernel\nRUNNING / PAUSED for stale-price@0.1.0\n[CURRENT bounded]"]:::application
    Orchestrator["Strategy Orchestrator\nsupervise concurrent instances\n[TARGET]"]:::target
  end

  subgraph CURRENTSTRAT["Strategy plug-ins"]
    direction TB
    Stale["StalePriceStrategy\n[CURRENT]"]:::strategy
    PMM["PassiveMarketMakerStrategy\n[CURRENT]"]:::strategy
    Copy["BTC 15-minute Copy strategy\n[CURRENT experimental]"]:::strategy
    NewPlugin["New strategy plug-in\n[FUTURE]"]:::future
  end

  subgraph COORDINATION["Target coordination"]
    direction TB
    Resolver["Intent Aggregator / Conflict Resolver\n[TARGET]"]:::target
    Allocator["Portfolio and Capital Allocation\n[TARGET]"]:::target
  end

  subgraph SAFETYEXEC["Independent safety and execution"]
    direction TB
    Risk["Independent Risk Engine\nfinal reject / reduce authority\n[CURRENT foundation]"]:::risk
    OMS["OMS / Transaction Manager\nidempotency and lifecycle\n[TARGET]"]:::target
    Exec["Generic Execution Port / Router\n[TARGET over CURRENT execution]"]:::target
    Adapter["Venue Adapter\nPolymarket CURRENT; others FUTURE"]:::adapter
  end

  subgraph STATE["Venue, state, and feedback"]
    direction TB
    Venue["Venue\n[EXTERNAL]"]:::external
    Ledger["Positions / Generalized Ledger\n[CURRENT foundation + TARGET]"]:::portfolio
    Recon["Reconciliation and Safety Pause\n[CURRENT]"]:::risk
    Health["Strategy Health and Monitoring\n[TARGET over CURRENT monitoring]"]:::observability
    Feedback["Context and registry feedback\n[TARGET summarized]"]:::target
  end

  Market -.-> Orchestrator
  Registry --> Orchestrator
  Control -.->|gate new Shadow intents only| Stale
  Orchestrator -.-> Stale
  Orchestrator -.-> PMM
  Orchestrator -.-> Copy
  Orchestrator -.-> NewPlugin
  Context -.-> Stale
  Context -.-> PMM
  Context -.-> Copy
  Context -.-> NewPlugin
  Stale -->|pre-risk intent| Resolver
  PMM -->|pre-risk intent| Resolver
  Copy -->|pre-risk intent| Resolver
  NewPlugin -.->|pre-risk intent| Resolver
  Resolver --> Allocator
  Allocator --> Risk
  Risk -->|approved / reduced| OMS
  Risk -->|reject| Health
  OMS --> Exec
  Exec --> Adapter
  Adapter --> Venue
  Venue -.->|fills and order events| Ledger
  OMS ==>|expected order state| Ledger
  Ledger --> Recon
  Recon -.-> Health
  Ledger -.-> Feedback
  Health -.-> Feedback

  subgraph GUARANTEE["Non-bypass guarantee"]
    direction TB
    G1["Strategy -> Resolver -> Allocator -> Risk -> OMS -> Execution -> Adapter"]:::safe
    G2["No Strategy -> Venue path"]:::danger
  end

  subgraph LEGEND["Legend"]
    direction TB
    L1["CURRENT solid"]:::current
    L2["TARGET dashed"]:::target
    L3["FUTURE dotted"]:::future
    L4["SAFETY amber / BLOCK red"]:::risk
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef target fill:#F1F5F9,stroke:#2563EB,stroke-width:2px,stroke-dasharray:6 4,color:#0F172A;
  classDef future fill:#F1F5F9,stroke:#64748B,stroke-width:2px,stroke-dasharray:2 5,color:#475569;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef strategy fill:#FFFFFF,stroke:#7C3AED,stroke-width:2px,color:#0F172A;
  classDef application fill:#FFFFFF,stroke:#2563EB,stroke-width:2px,color:#0F172A;
  classDef data fill:#FFFFFF,stroke:#0D9488,stroke-width:2px,color:#0F172A;
  classDef portfolio fill:#EFF6FF,stroke:#1D4ED8,stroke-width:2px,color:#0F172A;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2.5px,color:#0F172A;
  classDef adapter fill:#FFFFFF,stroke:#4F46E5,stroke-width:2px,color:#0F172A;
  classDef observability fill:#FFFFFF,stroke:#9333EA,stroke-width:2px,color:#0F172A;
  classDef safe fill:#F0FDF4,stroke:#16A34A,stroke-width:2px,color:#0F172A;
  classDef danger fill:#FEF2F2,stroke:#DC2626,stroke-width:2.5px,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Follow market/context inputs to independent strategy instances, then through resolver, allocator, risk, OMS, execution, adapter, venue, ledger, reconciliation, and health feedback.

## Current implementation mapping

`BaseStrategy`, `StalePriceStrategy`, `PassiveMarketMakerStrategy`, the bounded
BTC 15-minute Copy strategy, the minimal Strategy Registry, `OrderIntent`,
`RiskEngine`, execution services, position state, reconciliation, and monitoring
are CURRENT foundations. The Control Kernel is CURRENT only as a synchronous
`stale-price@0.1.0` Shadow intent gate.

## Target/future elements

Concurrent orchestration, conflict resolution, allocation, OMS/Transaction
Manager, a generic router, and generalized lifecycle/health integration are
TARGET. New plug-ins are FUTURE until implemented. Neither the current registry
nor the Control Kernel implies multi-strategy supervision.

## Related repository files

`src/polysia/strategies/`, `src/polysia/domain/strategy/`,
`src/polysia/domain/orders/`, `src/polysia/control/`, `src/polysia/risk/`,
`src/polysia/execution/`, `src/polysia/portfolio/`,
`src/polysia/reconciliation/`, `docs/00-governance/master-operating-charter.md`

## Related tests

`tests/integration/test_paper_vertical_slice.py`,
`tests/integration/test_shadow_control_vertical_slice.py`,
`tests/unit/strategies/`, `tests/property/test_risk_properties.py`,
`tests/architecture/test_boundaries.py`

## Related ADRs

ADR-0002, ADR-0004, ADR-0008, ADR-0009, ADR-0012

## Related capabilities/requirements

CAP-005–CAP-010; Charter §§24–32 and §59

## Assumptions

Strategies remain pure producers of pre-risk intents and receive read-only context.

## Known limitations

No concurrent orchestrator, allocator, conflict resolver, or OMS package currently exists.

## Review trigger

Strategy lifecycle, multi-strategy concurrency, capital competition, or OMS work is approved.
