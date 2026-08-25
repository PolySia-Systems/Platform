# Trust Boundaries

- **Diagram ID:** PSA-ARCH-15
- **Purpose:** Make trusted runtime, secrets, persistent state, operator, CI, public API, authenticated venue, and future signer boundaries explicit.
- **Scope:** Security-relevant data and command crossings without any real identifiers or account data.
- **Architecture status:** MIXED
- **Audience:** Security reviewers, owner, operators, architects, and execution developers.
- **Source commit:** `ac104c708100bf9fff7e632acefd89bf90b8e509`

## Mermaid diagram

Canonical source: [`15-trust-boundaries.mmd`](../sources/15-trust-boundaries.mmd)

```mermaid
flowchart LR
  Operator["Operator\nexplicit acknowledgements\n[EXTERNAL actor]"]:::external
  CI["CI / build service\nno live credentials\n[EXTERNAL]"]:::external
  Public["Public venue APIs\nuntrusted input\n[EXTERNAL]"]:::external
  AuthVenue["Authenticated venue boundary\naccount and order APIs\n[EXTERNAL]"]:::external
  Web3["Web3 signer / chain boundary\n[FUTURE]"]:::future

  subgraph LOCAL["Trusted local runtime boundary [CURRENT]"]
    CLI["CLI and safe output"]:::application
    Control["SHADOW-only Control Kernel\nno Live or credential authority"]:::application
    Core["Domain, strategy, risk, execution, reconciliation"]:::current
    Adapter["Polymarket adapter\nSDK confinement"]:::adapter
    Scan["Redaction and tracked-file secret scan"]:::risk
  end

  subgraph SECRET["Configuration and secrets boundary [CURRENT]"]
    Env["Ignored .env\nvalues not logged or tracked"]:::risk
  end

  subgraph DATA["Persistent data boundary [CURRENT]"]
    DB[("SQLite / local state")]:::storage
    Evidence["Ignored reports and operational evidence"]:::storage
  end

  Operator -->|commands / approvals| CLI
  CLI --> Core
  CLI --> Control
  Control -.->|gates new stale-price Shadow intents| Core
  Env -->|runtime-only configuration| Adapter
  Core --> Adapter
  Adapter --> Public
  Adapter --> AuthVenue
  Public -.->|validate and normalize| Adapter
  AuthVenue -.->|sanitize and reconcile| Adapter
  Core ==>|state| DB
  Core ==>|sanitized evidence| Evidence
  Scan -->|blocks unsafe tracked output| CLI
  CI -->|source checks only| Core
  Adapter -.->|future signer port| Web3

  subgraph LEGEND["Legend"]
    L1["CURRENT trusted"]:::current
    L2["EXTERNAL / untrusted"]:::external
    L3["SECRET / SAFETY"]:::risk
    L4["FUTURE"]:::future
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef application fill:#FFFFFF,stroke:#2563EB,stroke-width:2px,color:#0F172A;
  classDef adapter fill:#FFFFFF,stroke:#4F46E5,stroke-width:2px,color:#0F172A;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef future fill:#F1F5F9,stroke:#64748B,stroke-width:2px,stroke-dasharray:2 5,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2.5px,color:#0F172A;
  classDef storage fill:#FFFFFF,stroke:#475569,stroke-width:2px,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Read from external actors/services into the trusted local runtime, then inspect separate secrets and persistent-data boundaries.

## Current implementation mapping

Current controls include ignored `.env`, safe settings output, SDK confinement,
redaction, tracked-file secret scan, local SQLite, and ignored evidence. The
Control Kernel is inside the trusted process but is bounded to Shadow intent
gating; it has no Live or credential authority.

## Target/future elements

A future Web3 signer/chain integration requires a new isolated trust boundary. CI remains credential-free for ordinary jobs.

## Related repository files

`.gitignore`, `src/polysia/config/settings.py`, `src/polysia/control/`,
`src/polysia/security/secret_scan.py`, `src/polysia/adapters/polymarket/`,
`src/polysia/storage/`, `.github/workflows/ci.yml`

## Related tests

security scanner tests, redaction tests, `tests/architecture/test_boundaries.py`, deployment/readiness tests

## Related ADRs

ADR-0004, ADR-0007, ADR-0008, ADR-0009, ADR-0012

## Related capabilities/requirements

CAP-004, CAP-008–CAP-012; REQ-004, REQ-005, REQ-006

## Assumptions

All external API data is untrusted until validated/mapped; secrets are runtime-only.

## Known limitations

This is an architecture trust view, not a complete threat model or network-control design.

## Review trigger

A credential source, signer, external API, persistent store, CI privilege, or operator access path changes.
