# Current Deployment View

- **Diagram ID:** PSA-ARCH-13
- **Purpose:** Represent only verified current deployment and runtime facts.
- **Scope:** Owner workstation, controlled Helsinki host, verified release transfer, Docker monitor, scheduled Stages 1–4A, persistent Stage 4B worker, physically separate stores, secret boundaries, external data endpoints, and configured CI.
- **Architecture status:** CURRENT
- **Audience:** Owner, operators, developers, security reviewers, and deployment reviewers.
- **Source commit:** `8d64bb7bd5182bde5ed3a95c6ac26f7c859737a6`
- **Reviewed:** 2026-09-05
- **Verified deployment source:** `6743f7464f94d3fb76edc057834e8219ca7ebfe0`

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
    Conda["Conda environment: PolySia\nPython 3.14.7"]:::current
    Process["Operator-run polysia CLI\nmodular monolith"]:::application
    Secrets["Ignored local .env\nsecret boundary; values never diagrammed"]:::risk
    SQLite[("SQLite databases / local files\nignored runtime state")]:::storage
  end

  subgraph SERVER["Hetzner Helsinki Ubuntu host [CURRENT]"]
    Release["Read-only verified Git archive release\nexact deployed revision"]:::storage
    Container["Non-root Docker monitor and reconciliation\nDATA_ONLY; no published port"]:::application
    WalletJobs["Scheduled Docker Wallet Intelligence jobs\nStages 1-4A; DATA_ONLY"]:::application
    ShadowWorker["Persistent Docker Wallet Intelligence worker\nStage 4B; DATA_ONLY"]:::application
    Timers["Persistent systemd timers\nscheduled Stage 1-4A jobs and backups"]:::observability
    ShadowService["Persistent systemd service\nStage 4B worker supervision"]:::observability
    ServerSecrets["/etc/polysia/polysia.env\nroot-only 0600"]:::risk
    IntelligenceStore[("Intelligence store\nwallet-intelligence.sqlite3")]:::storage
    ShadowStore[("Continuous Shadow store\ncontinuous-shadow.sqlite3")]:::storage
    TelemetryStore[("Telemetry store\nwallet-intelligence-latency.sqlite3")]:::storage
    ServerFiles[("/var/lib/polysia\nreports and local backups")]:::storage
    DockerLogs["Rotating Docker logs\nhealth and reconciliation"]:::observability
  end

  Operator --> Process
  Operator -->|controlled SSH / Docker operations| Container
  Operator -->|controlled timer operations| Timers
  Operator -->|controlled service operations| ShadowService
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
  Release -->|approved image build| ShadowWorker
  Timers --> WalletJobs
  ShadowService --> ShadowWorker
  ServerSecrets -->|runtime-only configuration| Container
  ServerSecrets -->|runtime-only configuration| WalletJobs
  ServerSecrets -->|runtime-only configuration| ShadowWorker
  Container ==>|persistent state and reports| ServerFiles
  WalletJobs ==>|Stages 1-4A state| IntelligenceStore
  ShadowWorker ==>|Stage 4B state| ShadowStore
  WalletJobs -.->|fail-open latency| TelemetryStore
  ShadowWorker -.->|fail-open latency| TelemetryStore
  WalletJobs ==>|reports and backups| ServerFiles
  ShadowWorker ==>|reports and backups| ServerFiles
  Container -.->|structured output| DockerLogs
  WalletJobs -.->|structured output| DockerLogs
  ShadowWorker -.->|structured output| DockerLogs
  Container -->|public and authenticated reads only| PublicAPI
  Container -->|authenticated reads only| SecureAPI
  WalletJobs -->|public market and trade reads| PublicAPI
  WalletJobs -->|authorized discovery reads| PolyCop
  ShadowWorker -->|public market and trade reads| PublicAPI

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
continues in the `PolySia` Python 3.14.7 Conda environment. The continuously
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
after `6743f7464f94d3fb76edc057834e8219ca7ebfe0` are not claimed as deployed.

## Review trigger

Runtime host, environment, storage, secrets handling, CI ownership, or process topology changes.
