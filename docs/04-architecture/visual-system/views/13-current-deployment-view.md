# Current Deployment View

- **Diagram ID:** PSA-ARCH-13
- **Purpose:** Represent only verified current deployment and runtime facts.
- **Scope:** Owner Windows workstation, Conda environment, local Python process, local Git/files/SQLite, ignored secrets/evidence, Polymarket endpoints, and configured CI.
- **Architecture status:** CURRENT
- **Audience:** Owner, operators, developers, security reviewers, and deployment reviewers.
- **Source commit:** `44a8ae0fbccd0de916a0621236ea5931e7c3a256`

## Mermaid diagram

Canonical source: [`13-current-deployment-view.mmd`](../sources/13-current-deployment-view.mmd)

```mermaid
flowchart LR
  Operator["Owner / Operator\n[CURRENT]"]:::current
  GitHost["Git provider / CI runtime\nconfiguration present; remote run unverified\n[EXTERNAL]"]:::external
  PublicAPI["Polymarket public endpoints\n[EXTERNAL]"]:::external
  SecureAPI["Polymarket authenticated endpoints\n[EXTERNAL]"]:::external

  subgraph WORKSTATION["Owner Windows workstation [CURRENT]"]
    Repo["Local Git repository\nmain branch"]:::storage
    Conda["Conda environment: PolySia\nPython 3.13 workstation baseline"]:::current
    Process["One local Python process\npolysia CLI / modular monolith"]:::application
    Secrets["Ignored local .env\nsecret boundary; values never diagrammed"]:::risk
    SQLite[("SQLite databases / local files\nignored runtime state")]:::storage
    Reports["Ignored artifacts and reports\nlocal operator evidence"]:::observability
  end

  Operator --> Process
  Repo --> Conda
  Conda --> Process
  Secrets -->|configuration at runtime| Process
  Process ==>|persistent state| SQLite
  Process ==>|sanitized output| Reports
  Process -->|public reads / stream| PublicAPI
  Process -->|acknowledged reads or guarded action| SecureAPI
  Repo -.->|push / workflow source when configured| GitHost

  subgraph LEGEND["Legend"]
    L1["CURRENT local deployment"]:::current
    L2["EXTERNAL"]:::external
    L3["SECRET / SAFETY boundary"]:::risk
    L4["Persistent local state"]:::storage
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef application fill:#FFFFFF,stroke:#2563EB,stroke-width:2px,color:#0F172A;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2.5px,color:#0F172A;
  classDef storage fill:#FFFFFF,stroke:#475569,stroke-width:2px,color:#0F172A;
  classDef observability fill:#FFFFFF,stroke:#9333EA,stroke-width:2px,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Start at the owner workstation, then follow local process dependencies to files and external endpoints. Treat Git/CI as configured but not remotely verified.

## Current implementation mapping

The current deployment is one local Python process in the `PolySia` Conda environment. SQLite and reports are local. `.env` is ignored. Public and authenticated Polymarket endpoints are external.

## Target/future elements

No cloud, VPS, container, queue, scheduler, or production infrastructure is shown as current.

## Related repository files

`environment.yml`, `locks/`, `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml`, `src/polysia/storage/`, `src/polysia/config/settings.py`

## Related tests

Phase I handoff, deployment/readiness tests, storage tests, migration tests

## Related ADRs

ADR-0002, ADR-0006, ADR-0007, ADR-0009

## Related capabilities/requirements

CAP-004, CAP-008, CAP-011, CAP-012; REQ-005, REQ-007

## Assumptions

The verified owner workstation remains the current execution host.

## Known limitations

Remote CI execution and branch protection are not verified; local SQLite files and operational artifacts are intentionally ignored.

## Review trigger

Runtime host, environment, storage, secrets handling, CI ownership, or process topology changes.
