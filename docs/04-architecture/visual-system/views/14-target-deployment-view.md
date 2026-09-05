# Deployment Evolution View

- **Diagram ID:** PSA-ARCH-14
- **Purpose:** Show the current conservative single-host foundation and the next justified operational improvements.
- **Scope:** Developer workstation, CI, controlled host, runtime safety, secrets, SQLite state, monitoring, local backup, target off-host recovery and alerts, and optional later HA.
- **Architecture status:** MIXED
- **Audience:** Owner, architects, operations engineers, security reviewers, and release planners.
- **Source commit:** `8d64bb7bd5182bde5ed3a95c6ac26f7c859737a6`
- **Reviewed:** 2026-09-05

## Mermaid diagram

Canonical source: [`14-target-deployment-view.mmd`](../sources/14-target-deployment-view.mmd)

```mermaid
flowchart LR
  Developer["Owner Workstation\nverified source and release archive\n[CURRENT]"]:::current
  Operator["Operator Access\ncontrolled SSH and explicit runtime state\n[CURRENT]"]:::current
  CI["GitHub CI\nquality, security, package evidence\n[CURRENT]"]:::current

  subgraph HOST["Controlled Helsinki host [CURRENT]"]
    Runtime["PolySia modular-monolith runtime\nDATA_ONLY monitor and Shadow jobs; Live disabled"]:::current
    SecretStore["Root-only runtime secrets boundary"]:::risk
    Database[("Persistent SQLite state and audit")]:::current
    Monitor["Local health, logs, reports, and timers"]:::current
    Backup["Verified same-host backup and restore evidence"]:::current
  end

  Venue["Venue APIs\n[EXTERNAL]"]:::external
  OffHost["Encrypted off-host backup\n[TARGET]"]:::target
  Alerts["External alert delivery\n[TARGET]"]:::target
  HA["High-availability / failover boundary\n[FUTURE only after measured need]"]:::future

  Developer -->|versioned change| CI
  CI -->|verified commit evidence| Developer
  Developer -->|verified Git archive| Runtime
  Operator -->|controlled commands and approvals| Runtime
  SecretStore -->|runtime-only credentials| Runtime
  Runtime ==>|events, evaluations, simulated fills, ledger, audit| Database
  Runtime -.->|metrics and alerts| Monitor
  Database ==>|backup| Backup
  Backup -.->|approved encrypted copy| OffHost
  Monitor -.->|health and failure events| Alerts
  Runtime --> Venue
  Runtime -.->|later replication / failover| HA

  subgraph LEGEND["Legend"]
    L1["CURRENT solid"]:::current
    L2["TARGET dashed"]:::target
    L3["FUTURE dotted"]:::future
    L4["EXTERNAL"]:::external
    L5["SECRET / SAFETY"]:::risk
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef target fill:#F1F5F9,stroke:#2563EB,stroke-width:2px,stroke-dasharray:6 4,color:#0F172A;
  classDef future fill:#F1F5F9,stroke:#64748B,stroke-width:2px,stroke-dasharray:2 5,color:#475569;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2.5px,stroke-dasharray:6 4,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Follow a versioned change through CI and the verified archive to the controlled
runtime, then inspect operator, secrets, state, monitoring, backup, and venue
boundaries before the target recovery and alert extensions.

## Current implementation mapping

The controlled Helsinki host, immutable release transfer, DATA_ONLY Docker
runtime, systemd timers, root-only secret file, SQLite state, local monitoring,
and verified same-host backup/restore are CURRENT.

## Target/future elements

Encrypted off-host backup and external alert delivery are TARGET. A stronger
database or high availability remains optional and must be justified by measured
need rather than assumed now.

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

No off-host backup provider, external alert provider, RTO, RPO, stronger database
product, orchestration platform, or HA design has been approved.

## Review trigger

A deployment, storage, alerting, backup objective, or availability boundary changes.
