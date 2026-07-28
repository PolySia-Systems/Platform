# PolySia Controlled Server Deployment Handoff

## Outcome

PolySia is deployed on `Hetzner-Finland-Helsinki-01` as one hardened Docker
container from Git commit
`52c1bcc980f7db797066f982b23ab755dca31f58`.

The server runtime is healthy and continuously managed. It forces
`TRADING_MODE=DATA_ONLY`, forces `LIVE_TRADING_ENABLED=false`, clears the live
token allowlist, exposes no port, and does not run a strategy or any
state-changing venue command.

## Delivery

- Repository PR: `https://github.com/Movafeghm/polysia/pull/36`
- Merge commit: `52c1bcc980f7db797066f982b23ab755dca31f58`
- CI: all Python, Linux smoke, supply-chain, and container jobs passed.
- Server checkout: private GitHub repository through a read-only deploy key.
- Host account: dedicated `polysia` UID/GID `10001`, no sudo and no Docker
  group membership.
- Container account: UID/GID `10001`, read-only root filesystem, all
  capabilities dropped, no-new-privileges enabled.
- Existing `3x-ui` container, firewall, SSH policy, and published ports were
  not changed.

## Runtime evidence

- Container: `polysia-monitor-1`
- Image: `polysia:local`
- Health: healthy
- Restart policy: `unless-stopped`
- Published ports: none
- NTP synchronized: yes
- Geoblock: allowed during discovery and monitoring
- Configuration status: ready, values redacted, canonical funder configured,
  deprecated wallet variable absent
- Live readiness: intentionally blocked by DATA_ONLY, disabled live flag, and
  empty allowlist
- Authenticated account reads: available
- Open orders at handoff: zero
- Reconciliation: warning with zero blockers; the only warning is the expected
  absence of a server-local tiny-live execution artifact

## Persistence and recovery

- Database: `/var/lib/polysia/data/polysia.sqlite3`, mode `0600`
- Monitoring reports: `/var/lib/polysia/reports`
- Backup:
  `/var/lib/polysia/backups/polysia-20260728T130327484331Z.sqlite3`
- SHA-256:
  `47e58b7eb950f7d409522fc3ffa79abb31d99005c35cffecc4ef3513244102cf`
- Backup integrity and checksum verification: passed
- Restore rehearsal to a separate database: passed
- Rehearsal database: removed after verification
- Container restart persistence check: passed

The backup is on the same host. Encrypted off-host copying remains required for
disaster recovery.

## Operations

The authoritative runbook is
`docs/10-operations/server-deployment.md`. Run Docker Compose commands from
`/opt/polysia`.

No live order, cancellation, transfer, strategy execution, SSH-policy change,
firewall change, or unrelated service mutation occurred.

## Remaining limitations

- No encrypted off-host backup target is configured.
- No external alert-delivery provider is configured.
- No high availability or failover exists.
- This deployment proves controlled operation, not strategy profitability or
  production readiness.
- Any future live mutation still requires a fresh, run-specific owner
  authorization and all existing safety gates.
