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
| `/opt/polysia` | Current approved checkout or atomic link to an immutable release | no secrets; readable by `polysia` |
| `/opt/polysia-releases/<commit>` | Verified operator-uploaded Git archive when repository Deploy Keys are disabled | `root:polysia`, read-only release tree |
| `/etc/polysia/polysia.env` | Runtime configuration and credentials | `root:root`, `0600` |
| `/var/lib/polysia/data` | SQLite runtime state | UID/GID `10001`, private |
| `/var/lib/polysia/data/research-evidence.sqlite3` | Optional isolated prospective research-evidence store | UID/GID `10001`, private; never the Stage 4B financial DB or latency sidecar |
| `/var/lib/polysia/reports` | Sanitized monitoring snapshots | UID/GID `10001`, private |
| `/var/lib/polysia/backups` | Checksummed SQLite backups | UID/GID `10001`, private |

The container runs as UID/GID `10001`, has a read-only root filesystem, drops
all Linux capabilities, gains no new privileges, exposes no network port, and
uses bounded CPU, memory, processes, and rotating local Docker logs.

The default monitor process does not start the prospective collector. Start the
persistent collector explicitly:

```bash
docker compose --profile research up --detach research-collector
```

The research-evidence database must stay isolated from Stage 4B financial
SQLite and `wallet-intelligence-latency.sqlite3`. Raw files stay out of Git.
Windows are `OPEN` until complete closure. Interrupted windows are
`INVALID_SHUTDOWN`, never `VALID`. Backup the research store with:

```bash
docker compose --profile operations run --rm research-evidence-backup
```

### Persistent collector restart proof and T0

After deploying an approved SHA, start the monitor and the research collector
without enabling Live or changing the token allowlist:

```bash
export POLYSIA_IMAGE_TAG=<exact-merged-main-sha>
docker compose build --pull monitor
docker compose up --detach monitor
docker compose --profile research up --detach research-collector
```

Perform one controlled collector restart before recording final T0:

```bash
docker compose --profile research restart research-collector
```

Confirm the interrupted window is `INVALID_SHUTDOWN` (never `VALID`), the
restarted service owns the writer lock, and accepted evidence is not duplicated.
Then record T0 from UTC wall time and allow one complete ten-minute window.
Verify health JSON, a Backup-API snapshot, schema `research-evidence-v2`,
integrity, foreign keys, bounded WAL/logs, and zero real orders. Do not wait
for T0+3h in the deployment task; that observation is an independent read-only
acceptance.

Before treating a window as wallet-research eligible, run:

```bash
docker compose --profile research exec -T research-collector \
  python -m polysia.cli research prospective-health \
  --health-report /var/lib/polysia/reports/research-evidence-health.json \
  --require-research-eligible
```

The ordinary container healthcheck proves service health only. The stricter
command additionally requires a successful required-source request in the
active window. A quiet successful request is eligible; `retrying`, an
unresolved transport failure, or an ended required source is not.

For an economic canary, use a fresh database/run and freeze T0 before starting.
Stop after exactly two ten-minute windows, snapshot through the SQLite Backup
API, and run the canonical evaluation twice on that stopped snapshot:

```bash
python -m polysia.cli research prospective-replay \
  --database <canary-snapshot.sqlite3> --run-id <run-id> \
  --output <canary-analysis.json>
```

When using `--cycles 2`, keep `--experiment-duration-seconds` strictly above
1,200 seconds (1,800 is the operator default). The cycle limit still stops
collection after exactly two windows; the duration is a safety cap and must not
collide with the second window boundary or that window correctly becomes
`INVALID_DRAIN`.

The two economic and decision digests must match. Data `PASS` additionally
requires 20 eligible wallet observations, complete accounting, mapping >= 95%,
and executable-evidence coverage >= 90%. The stopped canary must also show no
outstanding invalid book state and complete terminal snapshot coverage for all
requested tokens within the 500-token cap. A closed market may satisfy terminal
coverage with its exact official zero/one settlement instead of a nonexistent
book. Terminal capture failure, unresolved missing evidence, or a reached cap
remains `INSUFFICIENT_DATA`; do not increase quote age.
The market-source health must show continuing periodic snapshot refresh and
must expose any refresh failure or missing book; repeated failures are not
source progress.
Verify health, restart count, bounded
DB/WAL/report/log growth, empty Live allowlist, Live disabled, and zero mutating
order calls separately. `INSUFFICIENT_ACTIVITY` is not permission to extend the
canary. Any `FAIL` requires a new green SHA and new T0; never weaken thresholds.

Only after a canary `PASS`, start one fresh experiment for no more than four
hours under the unchanged SHA, follow set, contract, and caps. Finalize and
restore-test it with `prospective-finalize`, copy the complete bundle and
analysis off-host, and rerun canonical evaluation twice. Keep the technical
result separate from `POSITIVE`, `NEGATIVE`, or `INSUFFICIENT_DATA`; none of
these authorizes Live trading.

The Compose collector declares a four-hour / 750,000-event / 768-MiB active
experiment. Stop the collector before finalization, then create the one-time
verified evidence bundle:

```bash
docker compose --profile research stop research-collector
docker compose --profile research run --rm research-collector \
  research prospective-finalize \
  --database /var/lib/polysia/data/research-evidence.sqlite3 \
  --run-id <health-run-id> \
  --bundle-root /var/lib/polysia/backups/research-experiments
```

The command refuses a second writer and marks the run finalized only after
snapshot, checksum, isolated restore, integrity/foreign-key checks, and
deterministic replay of the independently valid windows passes. If that
verified bundle already exists, the command reuses it and does not republish
evidence. Repeating a successful finalize is idempotent. A run with no valid
replayable interval writes a failure archive and records `FAILURE_ARCHIVED`;
never treat that as verified finalization. Invalid windows remain in the
immutable database and are reported as excluded evidence. The temporary
restore is staged under the bundle root so a bounded experiment is not
constrained by the service's small `/tmp` tmpfs. Restarting the collector
then starts the next bounded experiment. Do not treat rotating backups as the
experiment archive.

Analyze a published bundle only with `prospective-replay`. It must leave the
source database, manifest, checksums, and protected companions byte-for-byte
unchanged. Use `--output` for detailed evidence and `--compare` for compact
deltas. Prove the production path offline with `research prospective-prove`
before another multi-hour experiment. That laboratory is not the operational
Runner planned for a later change; do not deploy a runner, run manifest, or
long-running orchestration from this PR.

Finalize an active experiment before deploying collector code or configuration
that would change its recorded SHA or configuration digest.

Routine collector health may report maintenance as `degraded` after transient
checkpoint contention while committed evidence continues. It must recover on a
later `PASSIVE` checkpoint. A fatal evidence write, full-disk, I/O, or corruption
error remains fail-closed. Do not require WAL size zero: require continuing
checkpoint progress, bounded aggregate database/WAL growth, and uninterrupted
window closure. Before recording T0 after a storage change, exercise the prior
WAL threshold in an isolated fixture and observe at least two complete runtime
windows.

## Initial installation

1. Create the dedicated non-root `polysia` account with UID/GID `10001` if
   those identifiers are available.
2. Create the host paths above without changing unrelated services.
3. Install the exact green-CI `main` commit into `/opt/polysia`. Prefer a
   repository-approved read-only Deploy Key. When repository Deploy Keys are
   disabled, create `git archive` on the trusted operator workstation, compare
   SHA-256 before and after transfer, extract it into the immutable
   `/opt/polysia-releases/<commit>` directory, and atomically point
   `/opt/polysia` at that release. Never place a write-capable GitHub credential
   on the server.
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

## Current operational truth

Git Markdown is not live host state. Query the controlled host when the
current release SHA, service health, or restart count is required. Do not
copy the result into `PROJECT_STATUS.md` as if it were still true later.

From the host, typical read-only checks are:

```bash
readlink -f /opt/polysia
basename "$(readlink -f /opt/polysia)"
docker compose ps
docker compose exec monitor python -m polysia.cli system health
systemctl show polysia-wallet-intelligence-shadow-portfolio.service \
  -p ActiveState,NRestarts,ExecMainStartTimestamp --no-pager
```

Inspect only. Do not restart services, deploy, read secrets, or send orders
unless a separately authorized operational task says so. Dated snapshots may
appear in `docs/00-governance/PROJECT_STATUS.md` or
`docs/18-ai-handoffs/` labeled `Audited as of <timestamp>`.

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

Update only from an approved synchronized `main`. With an approved read-only
checkout:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
docker compose build --pull monitor
docker compose up --detach monitor
```

With a verified release archive, transfer and verify the new exact-commit
artifact, extract it into a new immutable release directory, build the tagged
image, and atomically switch `/opt/polysia`. Keep the previous release archive,
image, and symlink target until post-deployment health and restore rehearsal
pass. After an application update that includes the research collector, also
rebuild and start `research-collector` with the same image tag. Keep the
previous `/opt/polysia-releases/<sha>` directory for rollback.

Rollback the application by checking out the previously recorded Git commit,
rebuilding, and starting the monitor and, when it was running, the research
collector. Do not run `docker compose down --volumes` and do not delete
`/var/lib/polysia`. If a schema or state change is involved, restore only from
a verified backup after stopping the service. Research-evidence restore uses
`research-evidence-backup` and an isolated file; verify schema v2, integrity,
foreign keys, window lifecycle, and collector continuation before replacing
the active store.

## Stop conditions

Stop the affected action and preserve evidence when:

- geoblock reports blocked or cannot be verified;
- clock drift exceeds the configured safety threshold;
- monitoring cannot read expected account state;
- SQLite integrity or checksum verification fails;
- credentials or funder/signature settings are ambiguous;
- an unexpected open order, position, container, port, or host change appears;
- the requested action would enable live mutation without fresh authorization.

## Dynamic pre-Live input and legacy Tiny Live Copy experiment

The CURRENT DATA_ONLY wallet-intelligence path can generate the protected
`/var/lib/polysia/runtime/candidates.txt` input from matching Stage 3 and
seven-day Stage 4 evidence. Follow the wallet-intelligence ingestion runbook.
Generation is offline, address-redacted, atomic, and cannot authorize or submit
an order. The current file still contains exactly 102 addresses because the
legacy bounded runner below intentionally retains that reviewed invariant.

### Historical bounded runner contract

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

The pinned `polymarket-client==0.7.1` requires a GTD timestamp at least 180
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
