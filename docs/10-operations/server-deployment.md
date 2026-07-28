# Controlled Single-Server Deployment

## Status and scope

This runbook deploys the CURRENT PolySia modular monolith to one controlled
Linux host using Docker Compose. It is intended for read-only account
monitoring, public data access, paper/shadow experiments, and operator-led
validation.

The default service is forcibly configured as:

```text
TRADING_MODE=DATA_ONLY
LIVE_TRADING_ENABLED=false
POLYMARKET_LIVE_TOKEN_ALLOWLIST=
```

The Compose service cannot submit or cancel orders through its configured
monitor command. Enabling live trading is not part of this runbook and still
requires a separate, run-specific owner authorization and every existing
safety gate.

## Host layout

| Path | Purpose | Required owner/mode |
|---|---|---|
| `/opt/polysia` | Git checkout and Compose definition | `polysia:polysia`, no secrets |
| `/etc/polysia/polysia.env` | Runtime configuration and credentials | `root:root`, `0600` |
| `/var/lib/polysia/data` | SQLite runtime state | UID/GID `10001`, private |
| `/var/lib/polysia/reports` | Sanitized monitoring snapshots | UID/GID `10001`, private |
| `/var/lib/polysia/backups` | Checksummed SQLite backups | UID/GID `10001`, private |

The container runs as UID/GID `10001`, has a read-only root filesystem, drops
all Linux capabilities, gains no new privileges, exposes no network port, and
uses bounded CPU, memory, processes, and rotating local Docker logs.

## Initial installation

1. Create the dedicated non-root `polysia` account with UID/GID `10001` if
   those identifiers are available.
2. Create the host paths above without changing unrelated services.
3. Clone the approved `main` branch into `/opt/polysia`.
4. Copy the operator's private configuration to
   `/etc/polysia/polysia.env` without displaying it, then set mode `0600`.
5. Confirm the file contains the canonical funder setting and does not contain
   the deprecated wallet setting.
6. Build the approved image:

```bash
docker compose build --pull monitor
```

7. Initialize the persistent SQLite schema:

```bash
docker compose --profile operations run --rm \
  --entrypoint python backup \
  -m polysia.deployment.sqlite_backup \
  init --database /var/lib/polysia/data/polysia.sqlite3
```

8. Start only the monitor:

```bash
docker compose up --detach monitor
```

No host firewall change or inbound port is required.

## Routine operation

Run these commands from `/opt/polysia`:

```bash
docker compose ps
docker compose logs --tail 100 monitor
docker compose exec monitor python -m polysia.cli health
docker compose restart monitor
docker compose stop monitor
docker compose up --detach monitor
```

The monitor writes a sanitized account, geoblock, clock, open-order, position,
and configuration snapshot every 60 seconds. It also runs the existing
read-only post-live reconciliation every 15 cycles. Docker restarts it after
an unexpected exit. The health check verifies that the application loads
safely and persistent storage remains writable.

## Backup and verification

SQLite backups use the online SQLite backup API, run an integrity check, write
a SHA-256 sidecar, and retain the newest 14 copies by default:

```bash
docker compose --profile operations run --rm backup
```

Verify one backup before relying on it:

```bash
docker compose --profile operations run --rm \
  --entrypoint python backup \
  -m polysia.deployment.sqlite_backup \
  verify --backup /var/lib/polysia/backups/<backup-name>.sqlite3
```

Copy backups to a separate encrypted host or object store for disaster
recovery. Local retention alone does not protect against total server loss.

## Restore rehearsal and recovery

Rehearse without touching active state by restoring to a new file:

```bash
docker compose --profile operations run --rm \
  --entrypoint python backup \
  -m polysia.deployment.sqlite_backup \
  restore \
  --backup /var/lib/polysia/backups/<backup-name>.sqlite3 \
  --database /var/lib/polysia/data/restore-check.sqlite3
```

For an actual replacement, stop the monitor, preserve the current database,
verify the chosen backup, and only then use `--overwrite`. Restart the monitor
and reconcile before any higher runtime mode is considered.

## Update and rollback

Update only from an approved synchronized `main`:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
docker compose build --pull monitor
docker compose up --detach monitor
```

Rollback the application by checking out the previously recorded Git commit,
rebuilding, and starting the monitor. Do not run `docker compose down --volumes`
and do not delete `/var/lib/polysia`. If a schema or state change is involved,
restore only from a verified backup after stopping the service.

## Stop conditions

Stop the affected action and preserve evidence when:

- geoblock reports blocked or cannot be verified;
- clock drift exceeds the configured safety threshold;
- monitoring cannot read expected account state;
- SQLite integrity or checksum verification fails;
- credentials or funder/signature settings are ambiguous;
- an unexpected open order, position, container, port, or host change appears;
- the requested action would enable live mutation without fresh authorization.
