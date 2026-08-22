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
docker compose exec monitor python -m polysia.cli system health
docker compose restart monitor
docker compose stop monitor
docker compose up --detach monitor
```

The monitor writes a sanitized account, geoblock, clock, open-order, position,
and configuration snapshot every 60 seconds. It also runs the existing
read-only post-live reconciliation every 15 cycles. Docker restarts it after
an unexpected exit. The health check verifies that the application loads
safely and persistent storage remains writable.

The optional, read-only candidate-wallet ingestion is defined separately from
the monitor and must be deployed and scheduled as an explicit operator action.
Follow the [candidate-wallet ingestion runbook](wallet-intelligence-ingestion.md);
do not install its timer without current source permission.

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

## Owner-bounded Tiny Live Copy experiment

This section applies only to an exact, separately owner-authorized Tiny Live
Copy run. It is not a general live-trading procedure. Authorizations 001, 002,
and 003 are consumed historical evidence. Authorization 003 ended failed-safe
after one definitive Post-only rejection and created no order, fill, or
exposure. Any future Live run requires a different explicit owner authorization
and an exact unclaimed Run ID. Stages 2 through 6 of the Copy Trading plan
remain incomplete.

The experiment runs as the `copy-experiment` Compose profile with:

- one protected 102-candidate input at
  `/var/lib/polysia/runtime/candidates.txt` (`0600`, UID/GID `10001`);
- exactly 48 active discovery aliases, rotated every 30 minutes by a circular
  step of 34 only while the account is flat and monitoring;
- response-by-response signal processing without waiting for the other active
  wallet reads, plus one atomic durable pre-submit signal reservation;
- a maximum of 100 `/trades` attempts per rolling 10 seconds, of which at most
  80 are discovery attempts and 20 remain reserved, with at most four calls in
  flight;
- one shared `/trades` cooldown, one recovery probe, `Retry-After` support,
  bounded deterministic fallback, and a 120-second flat-account cutoff;
- one protected root-owned environment file at
  `/etc/polysia/tiny-live-copy.env` (`0600`);
- no published port;
- a read-only container filesystem and the existing persistent state bind;
- no more than three venue entry submissions, three terminal filled cycles,
  one pending entry, one position, and one related exit;
- a per-entry all-in debit cap of USD 5 and a cumulative confirmed-entry plus
  next-reserved-entry cost cap of USD 10 for the experiment;
- a 90-second operational entry TTL;
- a ten-second maximum signal age and a Tiny Live Copy-specific four-minute
  market-time gate; the shared Copy Trading domain default remains seven minutes;
- a detached heartbeat watchdog and `on-failure:3` restart policy.

The pinned `polymarket-client==0.6.0` requires a GTD timestamp at least 180
seconds in the future. PolySia therefore cancels and confirms the entry at the
90-second operational TTL, while allowing a 185-second venue GTD backstop only
when that backstop still expires before the final-entry cutoff. Signals that
cannot satisfy both constraints are skipped. Do not weaken either boundary.
Cancellation confirmation requires two consecutive complete observations over
paginated open orders, explicit order detail, linked trades, and the recorded
position baseline. Timeout, endpoint failure, `not_canceled`, persistent open
state, or contradictory evidence stops fail safe. A durable pre-send marker
prevents automatic cancellation resend after restart.

Before launch, verify synchronized clean `main`, green CI for the exact commit,
host NTP, official geoblock, sufficient collateral, no unrelated open order or
active/positive-value/mergeable/ambiguous position, existing allowances,
authenticated reads,
User WebSocket access, SQLite backup, and the image `BUILD_COMMIT`. A failed or
ambiguous check means no live launch.

The read-only preflight must also validate the 102-candidate bank, the
48-alias window and safe subset digest, durable cursor/checkpoint/cooldown
state, limiter telemetry, fresh public data, and restart reconciliation. It
must create no order or other venue mutation. Verify cancellation and
emergency-cancel readiness from authenticated order-query access, configuration,
code paths, and deterministic tests; never create an order solely to test
cancellation. If `/trades` remains unavailable for 120 continuous seconds
while flat, do not launch and record `INCONCLUSIVE_DATA_SOURCE_PREFLIGHT`.

The wallet may hold more than USD 10 because the cap applies to this
experiment's entry cost, not total wallet collateral. A historical position is
ignored only when its end date is before the current UTC date, both current
price and current value are exactly zero, and the venue explicitly reports it
as non-mergeable. The venue may still label a zero-value historical record
`redeemable`; that label does not create economic exposure. Missing or
contradictory fields fail closed.

The protected runtime environment must set distinct, matching values for
`POLYSIA_COPY_AUTHORIZATION_ID` and `POLYSIA_COPY_LIVE_ACK`. A Dry-run/Shadow
omits both values and never uses `--submit`. Build the exact merged commit and
start the one-off profile only after separate Live authorization:

```bash
export POLYSIA_IMAGE_TAG=<merged-main-sha>
export POLYSIA_COPY_ENV_FILE=/etc/polysia/tiny-live-copy.env
docker compose build copy-experiment
docker compose --profile live-experiment up --detach --no-deps copy-experiment
```

Inspect without continuously polling:

```bash
docker compose --profile live-experiment ps copy-experiment
docker compose --profile live-experiment logs --tail 100 copy-experiment
python -m json.tool /var/lib/polysia/reports/<run-id>/status.json
sha256sum --check /var/lib/polysia/reports/<run-id>/checksum.sha256
```

Do not stop or roll back while a follower position exists unless the owner has
an explicit manual containment plan. A shutdown cancels resting orders for
safety, but it cannot remove a filled position. For a pending entry,
`docker compose --profile live-experiment stop copy-experiment` triggers the
bounded cancellation path. Preserve `/var/lib/polysia`, the SQLite database,
and the run report during any rollback.

At `FINALIZED`, `FAILED_SAFE`, or `REDEEMABLE`, the worker deletes the protected
candidate input. It retains only aliases, hashes, lifecycle evidence, and
checksummed sanitized reports. A winning unresolved token may require manual
redemption; the experiment does not add a new redemption path.

During a public `/trades` cooldown, follower order and position management,
authenticated reconciliation, kill-switch handling, and emergency controls
take priority. Discovery remains off while capacity is occupied. A public 429
alone does not authorize emergency cancel-all. While flat, 120 seconds of
continuous source outage finalizes as `INCONCLUSIVE_DATA_SOURCE`; with exposure,
manage only that exposure to a terminal state.
