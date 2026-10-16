# Current Platform Deployment Boundaries

- **Diagram ID:** PSA-ARCH-13
- **Purpose:** Separate implemented process boundaries from operational acceptance.
- **Scope:** Hosted artifacts, Helsinki, private Console and Nuremberg cold recovery.
- **Architecture status:** MIXED
- **Audience:** Operators, developers and security reviewers.
- **Source commit:** `2cfb2752bf6fa3f8cb118acda53794db15a86ec0`
- **Reviewed:** 2026-10-16

## Mermaid diagram

Canonical source: [`13-current-deployment-view.mmd`](../sources/13-current-deployment-view.mmd)

```mermaid
flowchart TB
  CI["GitHub hosted CI and retained release assets\nexact source / archive / schema identities [CURRENT]"]:::current
  API["Public Polymarket / PolyCop endpoints [EXTERNAL]"]:::external
  Access["Cloudflare Access + Tunnel\nverified owner only; setup BLOCKED [TARGET]"]:::target
  subgraph PRIMARY["Helsinki: implemented ownership; activation requires a dated receipt"]
    Worker["Worker UID 10101\nDATA_ONLY; bounded GET; no signer [CURRENT]"]:::current
    Authority[("Private durable counters and STOP [CURRENT]")]:::risk
    Financial[("Separate financial / telemetry SQLite [CURRENT]")]:::current
    Publisher["Publisher UID 10101\nnetwork none; financial snapshot only [CURRENT]"]:::current
    Published[("Private canonical JSON and immutable exports [CURRENT]")]:::current
    Queue[("Command queue; dedicated shared group [CURRENT]")]:::risk
    Web["Console UID 10102\nloopback; publication RO; no financial mount [CURRENT]"]:::current
    Backup["Coordinated snapshots and public-recipient encryption\nnetwork isolated; no decryption key [CURRENT software]"]:::current
  end
  subgraph SECONDARY["Nuremberg: dedicated 4 GiB bounded allocation [CURRENT]"]
    Incoming[("Chrooted SFTP ciphertext; two generations [CURRENT software]")]:::current
    Key["Protected root-only recovery key\noutside upload account [CURRENT]"]:::risk
    Drill["Isolated decrypt / verify / startup / exact replay\nnetwork none; acquisition disabled [CURRENT software]"]:::current
  end
  CI -->|verified immutable artifact| Worker
  CI -->|independently retained release identity| Drill
  Authority -->|caps, expiry, STOP| Worker
  Worker --> API
  Worker ==>|one financial writer| Financial
  Financial -->|SQLite Backup API| Publisher
  Publisher --> Published
  Published -->|RO mount| Web
  Web ==>|validated receipt| Queue
  Queue -->|worker validates authority| Worker
  Access -.->|required before publication| Web
  Authority --> Backup
  Financial --> Backup
  Backup -->|bounded encrypted upload| Incoming
  Incoming --> Drill
  Key -->|secondary only| Drill
  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef target fill:#F1F5F9,stroke:#2563EB,stroke-width:2px,stroke-dasharray:6 4,color:#0F172A;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2px,color:#0F172A;
```

## Reading and evidence

CURRENT software is verified in the package and tests; it is not a claim that
all host services or public access are commissioned. The [dated execution record](../../../18-ai-handoffs/platform-independent-shadow-2026-10-16.md)
owns operational receipts; a runtime query owns live state. The [runbook](../../../10-operations/independent-platform-shadow.md)
owns release, STOP, recovery and rollback actions. Existing WI roots, credentials,
campaigns and unrelated services are preserved. Old topology snapshots are dated
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
