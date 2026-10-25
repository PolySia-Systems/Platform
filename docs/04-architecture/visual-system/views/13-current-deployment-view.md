# Current Platform Deployment Boundaries

- **Diagram ID:** PSA-ARCH-13
- **Purpose:** Separate implemented process boundaries from operational acceptance.
- **Scope:** Hosted artifacts, Helsinki, private Console and Nuremberg cold recovery.
- **Architecture status:** MIXED
- **Audience:** Operators, developers and security reviewers.
- **Source commit:** `4f3b611adae17defbcc6e24b4f9f917b466d5ad8`
- **Reviewed:** 2026-10-19

## Mermaid diagram

Canonical source: [`13-current-deployment-view.mmd`](../sources/13-current-deployment-view.mmd)

```mermaid
flowchart LR
  CI["GitHub retained v0.4.0 assets<br/>source, image and runtime identities [CURRENT]"]:::current
  Owner["Operator [EXTERNAL actor]<br/>verified SSH and scoped CA trust"]:::external
  subgraph PRIMARY["Helsinki: fresh disabled installation [CURRENT]"]
    Gateway["HTTPS localhost:8443<br/>reader / operator authentication"]:::current
    Web["Console UID 10102<br/>Unix socket; publication RO<br/>no financial mount or Docker socket"]:::current
    Publisher["Publisher UID 10101<br/>network none; retained reports"]:::current
    Published[("Canonical private publication<br/>UNKNOWN economics; no campaign")]:::current
    Queue[("Durable control receipts<br/>dedicated shared group")]:::risk
    Worker["Worker [CURRENT software]<br/>UNCONFIGURED; OS restart fenced<br/>no manifest, admission or provider key"]:::risk
    Backup["Bounded snapshots and age encryption<br/>public recipient only"]:::current
  end
  subgraph SECONDARY["Nuremberg: independent cold recovery [CURRENT]"]
    Cold["Same verified immutable assets<br/>no active worker or Console"]:::current
    Incoming[("Restricted SFTP chroot<br/>at most two ciphertext generations")]:::current
    Key["Root-only recovery key<br/>outside upload chroot and primary"]:::risk
    Drill["Daily isolated restore verification<br/>network none; acquisition disabled"]:::current
  end
  Owner -->|SSH forward| Gateway
  Gateway -->|authenticated identity| Web
  CI -->|exact tested artifact| Worker
  CI -->|independently retained| Cold
  Publisher --> Published
  Published -->|RO mount| Web
  Web ==>|validated command| Queue
  Queue -.->|applied before OS fencing| Worker
  Published --> Backup
  Queue --> Backup
  Backup -->|pinned SSH upload| Incoming
  Incoming --> Drill
  Key --> Drill
  Cold --> Drill
  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2px,color:#0F172A;
```

## Reading and evidence

The fresh v0.4.0 private installation has a separate dated receipt. Software is
verified in the package and tests; this diagram does not claim that
all host services or public access are commissioned. The [dated execution record](../../../18-ai-handoffs/platform-independent-shadow-2026-10-16.md)
owns operational receipts; a runtime query owns live state. The [runbook](../../../10-operations/independent-platform-shadow.md)
owns release, STOP, recovery and rollback actions. Unrelated services are
preserved. Old topology snapshots are dated
evidence, not the authority for new activation.

## Boundaries and limitations

The web process has no financial mount or Docker socket. Only the worker applies
validated control receipts under durable authority. Report windows do not reset
capital or force financial-session closure. Backup upload cannot decrypt. Recovery
starts isolated and disabled; stale counters never authorize resumed acquisition.
Access permissions, nonempty numerical usefulness and owner comprehension each
need separate actual receipts. No profitability, Live authority, active/active
operation or automatic failover is implied.

## Implementation and tests

`deploy/platform_bootstrap.py`, `deploy/platform_backup.py`,
`src/polysia/cli_commands/platform_worker.py`, `src/polysia/deployment/platform_recovery.py`,
`src/polysia/monitoring/console.py`, `tests/unit/deployment/test_platform_bootstrap.py`,
`tests/browser/test_console_browser.py`, `tests/integration/test_continuous_shadow_portfolio.py`.
ADR-0021 records ownership. Review on any process, state, identity, host, release,
network or recovery-boundary change.
