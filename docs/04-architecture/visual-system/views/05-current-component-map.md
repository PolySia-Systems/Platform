# Current Component Map

- **Diagram ID:** PSA-ARCH-05
- **Purpose:** Map real Python packages and the principal dependency relationships relevant to architecture.
- **Scope:** Top-level `src/polysia` packages; individual classes are shown in focused diagrams instead.
- **Architecture status:** CURRENT
- **Audience:** Developers, maintainers, reviewers, and onboarding engineers.
- **Source commit:** `44a8ae0fbccd0de916a0621236ea5931e7c3a256`

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
    Ports["application/ports/\nprotocol contracts"]:::application
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
  SDK["polymarket-client b11\n[EXTERNAL]"]:::external

  CLI --> Monitor
  CLI --> Deploy
  CLI --> Backtest
  CLI --> Adapter
  CLI --> Execution
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
  Strategies --> Execution
  Risk --> Execution
  Risk --> Config
  Execution --> Adapter
  Execution --> Risk
  Execution --> Recon
  Execution --> Portfolio
  Portfolio --> Execution
  Storage --> Domain
  Storage --> Book
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

All boxes are real packages. The diagram highlights actual broad imports while the traceability register provides evidence and capability mapping.

## Target/future elements

No target package is shown. Known debt is documented in the module-dependency view.

## Related repository files

`src/polysia/`, `docs/04-architecture/module-decomposition.md`

## Related tests

`tests/architecture/test_boundaries.py`, `tests/architecture/test_module_decomposition.py`, `tests/characterization/test_cli_contract.py`

## Related ADRs

ADR-0001, ADR-0002, ADR-0004

## Related capabilities/requirements

CAP-001–CAP-012; REQ-002, REQ-006

## Assumptions

Principal edges are more useful than every individual import.

## Known limitations

The map is not a generated exhaustive import graph; it intentionally groups high-volume monitoring and CLI dependencies.

## Review trigger

A top-level package is added, removed, or changes architectural direction.
