# Current Deployment View

- **Diagram ID:** PSA-ARCH-13
- **Purpose:** Represent only verified current deployment and runtime facts.
- **Scope:** Owner workstation, controlled Helsinki host, Docker monitor, persistent state, secret boundaries, Polymarket endpoints, and configured CI.
- **Architecture status:** CURRENT
- **Audience:** Owner, operators, developers, security reviewers, and deployment reviewers.
- **Verified deployment source:** `52c1bcc980f7db797066f982b23ab755dca31f58`

## Mermaid diagram

Canonical source: [`13-current-deployment-view.mmd`](../sources/13-current-deployment-view.mmd)

```mermaid
flowchart LR
  Operator["Owner / Operator\n[CURRENT]"]:::current
  GitHost["GitHub repository / CI runtime\nremote and CI verified\n[EXTERNAL]"]:::external
  PublicAPI["Polymarket public endpoints\n[EXTERNAL]"]:::external
  SecureAPI["Polymarket authenticated endpoints\n[EXTERNAL]"]:::external

  subgraph WORKSTATION["Owner Windows workstation [CURRENT]"]
    Repo["Local Git repository\nmain branch"]:::storage
    Conda["Conda environment: PolySia\nPython 3.14.6"]:::current
    Process["Operator-run polysia CLI\nmodular monolith"]:::application
    Secrets["Ignored local .env\nsecret boundary; values never diagrammed"]:::risk
    SQLite[("SQLite databases / local files\nignored runtime state")]:::storage
  end

  subgraph SERVER["Hetzner Helsinki Ubuntu host [CURRENT]"]
    Checkout["Read-only deploy-key checkout\nmain branch"]:::storage
    Container["Non-root Docker monitor\nDATA_ONLY; no published port"]:::application
    ServerSecrets["/etc/polysia/polysia.env\nroot-only 0600"]:::risk
    ServerState[("/var/lib/polysia\nSQLite, reports, local backups")]:::storage
    DockerLogs["Rotating Docker logs\nhealth and reconciliation"]:::observability
  end

  Operator --> Process
  Operator -->|controlled SSH / Docker operations| Container
  Repo --> Conda
  Conda --> Process
  Secrets -->|configuration at runtime| Process
  Process ==>|persistent state| SQLite
  Process -->|public reads / stream| PublicAPI
  Process -->|acknowledged reads or guarded action| SecureAPI
  Repo -.->|push / workflow source| GitHost
  GitHost -.->|read-only deploy key| Checkout
  Checkout -->|approved image build| Container
  ServerSecrets -->|runtime-only configuration| Container
  Container ==>|persistent state and reports| ServerState
  Container -.->|structured output| DockerLogs
  Container -->|public and authenticated reads only| PublicAPI
  Container -->|authenticated reads only| SecureAPI

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

Start at the owner workstation and GitHub, then follow the approved source to
the single controlled Docker runtime, persistent state, monitoring, and
external read-only endpoints.

## Current implementation mapping

The current deployment remains one Python modular monolith. Local operator use
continues in the `PolySia` Python 3.14.6 Conda environment. The continuously
managed runtime is one non-root Docker container on the controlled Ubuntu host.
It forces `DATA_ONLY`, disables live trading, clears the live allowlist, exposes
no port, persists SQLite and reports, writes rotating logs, and runs read-only
monitoring and reconciliation. GitHub CI verifies Python 3.11/3.13/3.14, Linux,
the container, and supply-chain gates.

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

The server remains a single controlled host and operates only in read-only
`DATA_ONLY` mode.

## Known limitations

The verified backup remains on the same server; encrypted off-host backup is
not configured. External alert delivery and high availability are absent.
SQLite remains limited to the current single-runtime workload. Credentials and
operational state remain outside Git.

## Review trigger

Runtime host, environment, storage, secrets handling, CI ownership, or process topology changes.
