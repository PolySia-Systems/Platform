# Current Component Map

- **Diagram ID:** PSA-ARCH-05
- **Purpose:** Map real Python packages and the principal dependency relationships relevant to architecture.
- **Scope:** Top-level `src/polysia` packages; individual classes are shown in focused diagrams instead.
- **Architecture status:** CURRENT
- **Audience:** Developers, maintainers, reviewers, and onboarding engineers.
- **Source commit:** `449f1c308fc74bd2a541e0e905f281fd19e5cd9b`

## Mermaid diagram

Canonical source: [`05-current-component-map.mmd`](../sources/05-current-component-map.mmd)

```mermaid
flowchart TB
  subgraph INTERFACE["Interface and operations [CURRENT]"]
    CLI["cli.py + cli_support/"]:::application
    Monitor["monitoring/"]:::observability
    Deploy["deployment/"]:::observability
    Backtest["backtesting/"]:::application
  end

  subgraph CORE["Inner contracts [CURRENT]"]
    Domain["domain/\nevents, market, orders, portfolio, risk, ledger, reconciliation"]:::domain
    Registry["domain/strategy/\nminimal registry models"]:::domain
    Ports["application/ports/\nprotocol contracts"]:::application
  end

  subgraph CONTROL["Bounded operational control [CURRENT]"]
    ControlKernel["control/\nSHADOW-only kernel"]:::application
  end

  subgraph PIPELINE["Data and decision [CURRENT]"]
    Bus["bus/"]:::data
    Book["orderbook/"]:::data
    Features["features/"]:::data
    Strategies["strategies/"]:::strategy
    Risk["risk/"]:::risk
  end

  subgraph EXECSTATE["Execution and state [CURRENT]"]
    Execution["execution/"]:::execution
    Portfolio["portfolio/"]:::portfolio
    Storage["storage/"]:::storage
    Recon["reconciliation/"]:::risk
  end

  Adapter["adapters/polymarket/\nSDK-confined boundary"]:::adapter
  Config["config/"]:::risk
  SDK["polymarket-client 0.2.0\n[EXTERNAL]"]:::external

  CLI --> Monitor
  CLI --> Deploy
  CLI --> Backtest
  CLI --> Adapter
  CLI --> Execution
  CLI --> ControlKernel
  CLI --> Storage
  Ports --> Domain
  Adapter --> Domain
  Adapter --> Bus
  Adapter --> SDK
  Bus --> Domain
  Book --> Bus
  Features --> Book
  Strategies --> Features
  Strategies --> Book
  Strategies --> Domain
  Strategies -.->|OrderIntent type only; no execution call| Execution
  Risk --> Execution
  Risk --> Config
  Execution --> Adapter
  Execution --> Risk
  Execution --> Recon
  Execution --> Portfolio
  Portfolio --> Execution
  Storage --> Domain
  Storage --> Book
  Storage --> Registry
  Storage --> ControlKernel
  ControlKernel --> Bus
  ControlKernel --> Strategies
  ControlKernel -.->|intent type and Shadow boundary| Execution
  Recon --> Risk
  Backtest --> Strategies
  Backtest --> Risk
  Monitor --> Strategies
  Monitor --> Risk
  Monitor --> Adapter

  subgraph LEGEND["Legend"]
    L1["CURRENT package"]:::current
    L2["EXTERNAL dependency"]:::external
    L3["SAFETY package"]:::risk
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

Read from interface/operations packages through data/decision and execution/state packages toward domain and adapter boundaries.

## Current implementation mapping

All boxes are real packages. The map now includes `control/`, the bounded
registry models under `domain/strategy/`, and the current SDK version. The
strategy-to-execution edge is an `OrderIntent` type dependency only; it does
not represent a direct execution call or bypass of Risk. The traceability
register provides path and test evidence.

## Target/future elements

No target package is shown. Known debt is documented in the module-dependency view.

## Related repository files

`src/polysia/`, `docs/04-architecture/module-decomposition.md`

## Related tests

`tests/architecture/test_boundaries.py`, `tests/architecture/test_module_decomposition.py`, `tests/characterization/test_cli_contract.py`

## Related ADRs

ADR-0001, ADR-0002, ADR-0004, ADR-0011, ADR-0012

## Related capabilities/requirements

CAP-001–CAP-012; REQ-002, REQ-006

## Assumptions

Principal edges are more useful than every individual import.

## Known limitations

The map is not a generated exhaustive import graph; it intentionally groups
high-volume monitoring and CLI dependencies. Runtime flow is authoritative in
the signal-to-execution view, not inferred from type-import arrows here.

## Review trigger

A top-level package is added, removed, or changes architectural direction.
