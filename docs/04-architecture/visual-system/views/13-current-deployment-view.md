# Current Deployment View

- **Diagram ID:** PSA-ARCH-13
- **Purpose:** Represent only verified current deployment and runtime facts.
- **Scope:** Owner workstation, controlled Helsinki host, verified release transfer, Docker monitor and Wallet Intelligence jobs, persistent state, secret boundaries, external data endpoints, and configured CI.
- **Architecture status:** CURRENT
- **Audience:** Owner, operators, developers, security reviewers, and deployment reviewers.
- **Source commit:** `ac104c708100bf9fff7e632acefd89bf90b8e509`
- **Verified deployment source:** `d39f5b355b1d83ed2019a93c6647b8ceb1572e5f`

## Mermaid diagram

Canonical source: [`13-current-deployment-view.mmd`](../sources/13-current-deployment-view.mmd)

```mermaid
flowchart LR
  Operator["Owner / Operator\n[CURRENT]"]:::current
  GitHost["GitHub repository / CI\nPython 3.14 checks verified\n[EXTERNAL]"]:::external
  PublicAPI["Polymarket public endpoints\n[EXTERNAL]"]:::external
  SecureAPI["Polymarket authenticated endpoints\n[EXTERNAL]"]:::external
  PolyCop["PolyCop discovery source\n[EXTERNAL]"]:::external

  subgraph WORKSTATION["Owner Windows workstation [CURRENT]"]
    Repo["Local Git repository\nmain branch"]:::storage
    Conda["Conda environment: PolySia\nPython 3.14.6"]:::current
    Process["Operator-run polysia CLI\nmodular monolith"]:::application
    Secrets["Ignored local .env\nsecret boundary; values never diagrammed"]:::risk
    SQLite[("SQLite databases / local files\nignored runtime state")]:::storage
  end

  subgraph SERVER["Hetzner Helsinki Ubuntu host [CURRENT]"]
    Release["Read-only verified Git archive release\nexact deployed revision"]:::storage
    Container["Non-root Docker monitor and reconciliation\nDATA_ONLY; no published port"]:::application
    WalletJobs["Ephemeral Docker Wallet Intelligence jobs\nStages 1-4B; DATA_ONLY"]:::application
    Timers["Persistent systemd timers\ndaily ingestion and bounded Shadow cycles"]:::observability
    ServerSecrets["/etc/polysia/polysia.env\nroot-only 0600"]:::risk
    ServerState[("/var/lib/polysia\nSQLite, reports, local backups")]:::storage
    DockerLogs["Rotating Docker logs\nhealth and reconciliation"]:::observability
  end

  Operator --> Process
  Operator -->|controlled SSH / Docker operations| Container
  Operator -->|controlled timer operations| Timers
  Repo --> Conda
  Conda --> Process
  Secrets -->|configuration at runtime| Process
  Process ==>|persistent state| SQLite
  Process -->|public reads / stream| PublicAPI
  Process -->|acknowledged reads or guarded action| SecureAPI
  Repo -.->|push / workflow source| GitHost
  Repo -.->|verified archive and SHA transfer| Release
  Release -->|approved image build| Container
  Release -->|approved image build| WalletJobs
  Timers --> WalletJobs
  ServerSecrets -->|runtime-only configuration| Container
  ServerSecrets -->|runtime-only configuration| WalletJobs
  Container ==>|persistent state and reports| ServerState
  WalletJobs ==>|wallet intelligence state and reports| ServerState
  Container -.->|structured output| DockerLogs
  WalletJobs -.->|structured output| DockerLogs
  Container -->|public and authenticated reads only| PublicAPI
  Container -->|authenticated reads only| SecureAPI
  WalletJobs -->|public market and trade reads| PublicAPI
  WalletJobs -->|authorized discovery reads| PolyCop

  subgraph LEGEND["Legend"]
    L1["CURRENT deployment"]:::current
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

Start at the owner workstation and GitHub, then follow the verified archive to
the controlled Docker monitor and scheduled Wallet Intelligence jobs,
persistent state, monitoring, and external read-only endpoints.

## Current implementation mapping

The current deployment remains one Python modular monolith. Local operator use
continues in the `PolySia` Python 3.14.6 Conda environment. The continuously
managed runtime includes the non-root Docker monitor plus systemd-triggered,
ephemeral Wallet Intelligence Stage 1–4B jobs on the controlled Ubuntu host.
The host receives a verified exact-commit Git archive because repository Deploy
Keys are disabled. All current services force `DATA_ONLY`, disable live trading,
expose no port, persist SQLite and reports, and write bounded operational output.
Current GitHub CI supports Python 3.14 only. It
runs lightweight documentation/Standards/secret checks on every pull request,
uses Linux as the canonical complete quality and applicable locked-wheel path,
keeps full Windows workstation compatibility weekly, manually, and for
Windows-sensitive changes, adds container checks for deployment-relevant
changes, and runs supply-chain checks for dependency changes, weekly schedules,
and manual dispatch.

## Target/future elements

External alert delivery, encrypted off-host backups, high availability,
additional hosts, queues, and orchestration remain TARGET or FUTURE.

## Related repository files

`Dockerfile`, `compose.yaml`, `deploy/polysia.env.example`,
`docs/10-operations/server-deployment.md`, `environment.yml`, `locks/`,
`.github/workflows/ci.yml`, `src/polysia/storage/`,
`src/polysia/config/settings.py`

## Related tests

Container CI, deployment/readiness tests, SQLite backup tests, storage tests,
and the controlled server deployment handoff

## Related ADRs

ADR-0002, ADR-0006, ADR-0007, ADR-0009

## Related capabilities/requirements

CAP-004, CAP-008, CAP-011, CAP-012; REQ-005, REQ-007

## Assumptions

The latest approved deployment evidence records one controlled host operating
only in read-only `DATA_ONLY` mode. This documentation refresh did not contact
or mutate the external host.

## Known limitations

The verified backup remains on the same server; encrypted off-host backup is
not configured. External alert delivery and high availability are absent.
SQLite remains limited to the current single-runtime workload. Credentials and
operational state remain outside Git.
The deployed revision predates this repository baseline; repository changes
after `d39f5b355b1d83ed2019a93c6647b8ceb1572e5f` are not claimed as deployed.

## Review trigger

Runtime host, environment, storage, secrets handling, CI ownership, or process topology changes.
