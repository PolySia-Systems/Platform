# Target Deployment View

- **Diagram ID:** PSA-ARCH-14
- **Purpose:** Show a conservative single-host target path with explicit secrets, persistence, monitoring, backup, and operator boundaries.
- **Scope:** Developer workstation, CI, controlled host/VPS, runtime profiles, secrets, persistent database, monitoring, backup, operator access, venue, and optional later HA.
- **Architecture status:** TARGET
- **Audience:** Owner, architects, operations engineers, security reviewers, and release planners.
- **Source commit:** `44a8ae0fbccd0de916a0621236ea5931e7c3a256`

## Mermaid diagram

Canonical source: [`14-target-deployment-view.mmd`](../sources/14-target-deployment-view.mmd)

```mermaid
flowchart LR
  Developer["Developer Workstation\n[TARGET]"]:::target
  Operator["Operator Access\nstrong authentication and explicit live state\n[TARGET]"]:::target
  CI["CI Pipeline\nquality, security, package, signed evidence\n[TARGET]"]:::target

  subgraph HOST["Controlled single host or VPS [TARGET]"]
    Runtime["PolySia modular-monolith runtime\nseparate paper / shadow / limited-live profiles"]:::target
    SecretStore["Secrets boundary\nleast privilege, no research access"]:::risk
    Database[("Persistent database\ntransactional state and audit")]:::target
    Monitor["Monitoring and alerting\nhealth, risk, reconciliation"]:::target
    Backup["Encrypted backup and restore evidence"]:::target
  end

  Venue["Venue APIs\n[EXTERNAL]"]:::external
  HA["High-availability / failover boundary\n[FUTURE only after measured need]"]:::future

  Developer -->|versioned change| CI
  CI -->|approved package| Runtime
  Operator -->|controlled commands and approvals| Runtime
  SecretStore -->|runtime-only credentials| Runtime
  Runtime ==>|orders, fills, ledger, audit| Database
  Runtime -.->|metrics and alerts| Monitor
  Database ==>|backup| Backup
  Runtime --> Venue
  Runtime -.->|later replication / failover| HA

  subgraph LEGEND["Legend"]
    L1["TARGET dashed"]:::target
    L2["FUTURE dotted"]:::future
    L3["EXTERNAL"]:::external
    L4["SECRET / SAFETY"]:::risk
  end

  classDef target fill:#F1F5F9,stroke:#2563EB,stroke-width:2px,stroke-dasharray:6 4,color:#0F172A;
  classDef future fill:#F1F5F9,stroke:#64748B,stroke-width:2px,stroke-dasharray:2 5,color:#475569;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2.5px,stroke-dasharray:6 4,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Follow a versioned change through CI to one controlled runtime, then inspect operator, secrets, state, monitoring, backup, and venue boundaries.

## Current implementation mapping

Current local runtime, CI configuration, SQLite, monitoring, and safe configuration are foundations only.

## Target/future elements

Controlled host/VPS, runtime profiles, managed secret boundary, stronger database, monitoring/alerts, backup/restore, and authenticated operator access are TARGET. High availability is FUTURE.

## Related repository files

`docs/00-governance/master-operating-charter.md`, `docs/22-roadmap/roadmap.md`, `.github/workflows/ci.yml`, `src/polysia/config/`, `src/polysia/monitoring/`

## Related tests

Current foundation evidence: deployment/readiness tests, storage tests, security/redaction tests

## Related ADRs

ADR-0002, ADR-0006, ADR-0007, ADR-0008, ADR-0009

## Related capabilities/requirements

Current CAP-004, CAP-008, CAP-011, CAP-012; Charter §§47 and 63

## Assumptions

A single controlled host is preferred until measured reliability or isolation needs justify more.

## Known limitations

No provider, database product, orchestration platform, RTO, RPO, or HA design has been approved.

## Review trigger

A deployment RFC selects a host, database, secret store, backup objective, or availability target.
