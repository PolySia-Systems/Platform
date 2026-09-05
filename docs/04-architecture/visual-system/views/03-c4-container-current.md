# C4 Container View — Current

- **Diagram ID:** PSA-ARCH-03
- **Purpose:** Show the current modular-monolith runtime honestly at logical container level.
- **Scope:** Logical containers inside one deployable Python package/process; these are not independently deployed services.
- **Architecture status:** CURRENT
- **Audience:** Developers, owner, maintainers, and architecture reviewers.
- **Source commit:** `8d64bb7bd5182bde5ed3a95c6ac26f7c859737a6`
- **Reviewed:** 2026-09-05

## Mermaid diagram

Canonical source: [`03-c4-container-current.mmd`](../sources/03-c4-container-current.mmd)

```mermaid
flowchart TB
  Actor["Person: Owner / Researcher\n[CURRENT]"]:::current
  Venue["External System: Polymarket APIs\n[EXTERNAL]"]:::external
  DB[("SQLite / local files\n[CURRENT]")]:::storage

  subgraph PS["Software System: PolySia — one deployable Python modular monolith [CURRENT]"]
    CLI["Container: CLI and Safe Output\nTyper commands, parsing, redaction"]:::application
    Config["Container: Configuration and Safety Defaults\nDATA_ONLY / PAPER / gated LIVE"]:::risk

    subgraph DATA["Market-data path"]
      Adapter["Container: Polymarket Adapter\npublic, stream, secure, mapping, geoblock"]:::adapter
      Bus["Container: Events and In-Memory Bus\nnormalized market events"]:::data
      Book["Container: Order Book and Features\nDecimal book, microstructure"]:::data
    end

    subgraph DECISION["Decision and control"]
      DomainPorts["Container: Domain Models and Application Ports\nvenue-neutral contracts"]:::domain
      Services["Container: Application Services\nWallet Intelligence, selection, Shadow, protected handoff"]:::application
      Registry["Container: Minimal Strategy Registry\nversion, lifecycle, evidence"]:::strategy
      Strategies["Container: Strategy Framework\nresearch and bounded Copy strategies"]:::strategy
      Control["Container: SHADOW-only Control Kernel\nplan/apply, revisions, audit, intent gate"]:::application
      Risk["Container: Independent Risk and Kill Switch\napprove, reduce, reject, stop"]:::risk
    end

    subgraph STATE["Execution and state"]
      Execution["Container: Execution\npaper broker and guarded live broker"]:::execution
      Portfolio["Container: Positions and P&L\noperational ledger"]:::portfolio
      Storage["Container: Storage Repositories\nSQLite repositories"]:::storage
      Recon["Container: Reconciliation and Safety Pause\ninternal vs external"]:::risk
    end

    Ops["Container: Monitoring, Backtesting, Deployment\nreports, replay, readiness, handoff"]:::observability
  end

  Actor -->|commands| CLI
  CLI --> Config
  CLI --> Ops
  CLI --> Adapter
  CLI --> Control
  CLI --> Services
  Services --> DomainPorts
  Services ==>|pipeline and portfolio state| Storage
  Control ==>|desired/observed state and audit| Storage
  Control -.->|gates new stale-price Shadow intents only| Strategies
  Registry -.->|definition and lifecycle evidence| Strategies
  Adapter -.->|normalized events| Bus
  Bus -.-> Book
  Book --> Strategies
  DomainPorts --> Strategies
  Strategies -->|OrderIntent| Risk
  Config --> Risk
  Risk -->|ApprovedOrderIntent| Execution
  Risk -->|reject / kill| CLI
  Execution --> Adapter
  Adapter -->|API calls| Venue
  Execution ==>|fills / state update| Portfolio
  Portfolio ==>|state| Storage
  Bus ==>|events| Storage
  Adapter -.->|account and order state| Recon
  Portfolio --> Recon
  Recon -->|safety pause| Risk
  Recon --> Ops
  Storage ==>|persistent records| DB
  Ops --> CLI

  subgraph LEGEND["Legend"]
    L1["CURRENT logical container"]:::current
    L2["EXTERNAL"]:::external
    L3["SAFETY"]:::risk
    L4["Persistent update ==>"]:::storage
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef domain fill:#FFFFFF,stroke:#0F766E,stroke-width:2px,color:#0F172A;
  classDef application fill:#FFFFFF,stroke:#2563EB,stroke-width:2px,color:#0F172A;
  classDef strategy fill:#FFFFFF,stroke:#7C3AED,stroke-width:2px,color:#0F172A;
  classDef portfolio fill:#FFFFFF,stroke:#1D4ED8,stroke-width:2px,color:#0F172A;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2px,color:#0F172A;
  classDef execution fill:#FFFFFF,stroke:#0891B2,stroke-width:2px,color:#0F172A;
  classDef adapter fill:#FFFFFF,stroke:#4F46E5,stroke-width:2px,color:#0F172A;
  classDef data fill:#FFFFFF,stroke:#0D9488,stroke-width:2px,color:#0F172A;
  classDef storage fill:#FFFFFF,stroke:#475569,stroke-width:2px,color:#0F172A;
  classDef observability fill:#FFFFFF,stroke:#9333EA,stroke-width:2px,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Follow operator commands into data ingestion, decisions and risk, execution/state, reconciliation, and operator output.

## Current implementation mapping

Every container maps to current packages: CLI composition/commands/support, config, adapter, bus,
orderbook/features, domain/ports and services, the bounded Strategy Registry, strategies,
the SHADOW-only Control Kernel, risk, execution, portfolio, storage,
reconciliation, and monitoring/backtesting/deployment. The Control Kernel gates
only new `stale-price@0.1.0` Shadow intents and cannot reach Live trading.

## Target/future elements

No target container is claimed. OMS and orchestration are deliberately absent from this current view.

## Related repository files

`src/polysia/cli.py`, `src/polysia/cli_commands/`,
`src/polysia/cli_support/`, `src/polysia/config/`, `src/polysia/domain/`,
`src/polysia/application/`, `src/polysia/adapters/`, `src/polysia/bus/`,
`src/polysia/orderbook/`, `src/polysia/features/`,
`src/polysia/strategies/`, `src/polysia/control/`, `src/polysia/risk/`,
`src/polysia/execution/`, `src/polysia/portfolio/`,
`src/polysia/storage/`, `src/polysia/reconciliation/`,
`src/polysia/monitoring/`

## Related tests

`tests/integration/test_paper_vertical_slice.py`,
`tests/integration/test_shadow_control_vertical_slice.py`,
`tests/unit/strategies/test_registry.py`,
`tests/architecture/test_boundaries.py`,
`tests/contract/test_cli_surface.py`

## Related ADRs

ADR-0001, ADR-0002, ADR-0004, ADR-0006, ADR-0008, ADR-0012

## Related capabilities/requirements

CAP-001–CAP-012; REQ-001, REQ-002, REQ-004, REQ-006

## Assumptions

A C4 container may be a logical runtime boundary within the single deployment.

## Known limitations

Application services cover Wallet Intelligence and Shadow orchestration. They
are not universal runtime wiring for every older CLI path.

## Review trigger

A package boundary changes, a new deployable is introduced, or a current logical container is materially decomposed.
