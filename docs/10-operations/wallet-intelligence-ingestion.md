# Candidate-Wallet Ingestion Runbook

## Status and boundary

This runbook covers the CURRENT repository implementation of Stage 1
candidate-wallet ingestion. Deployment and timer installation remain an
operator action. The workflow is read-only toward external sources and cannot
produce a signal, `OrderIntent`, paper order, Live order, cancellation,
transfer, or wallet mutation.

PolyCop access is permitted only while the owner has valid permission covering
the endpoint, daily frequency, and retention. Disable the timer immediately if
that permission is withdrawn or becomes ambiguous. The implementation does not
bypass access controls and does not treat `robots.txt` as authorization.

## Source contract

The first explicit adapter is `source_id=polycop`. It reads the owner-approved
public endpoint with these fixed semantics:

```text
GET https://polycop.fun/api/leaderboard
page=<dynamic page>
sort_by=score
sort_order=DESC
min_score=50
full=1
```

The adapter follows the returned `total_pages`; it does not assume 22 pages.
Five, 22, or 50 valid pages are processed using the same code path. It enforces
bounded response, page, record, retry, and timeout limits; exact reviewed
envelope and row fields; valid EVM addresses; unique wallets and ranks; and
Decimal-safe numeric decoding. It rereads page 1 after the complete pass. If
page 1 or `total_pages` changed, the complete read is retried once and otherwise
fails without publishing mixed data.

Source numeric metrics are persisted as canonical decimal strings. Embedded
JSON and `last_active` remain source evidence; `last_active` is not silently
interpreted as UTC because the external contract does not declare its timezone.

This is the complete list that PolyCop exposes through the reviewed leaderboard
contract, not a claim that it contains every Polymarket wallet. The source-side
minimum score remains 50. PolyCop's undocumented, unversioned endpoint and
offset pagination remain external limitations.

## Protected host layout

| Path | Content | Handling |
|---|---|---|
| `/var/lib/polysia/wallet-intelligence/data/wallet-intelligence.sqlite3` | Complete accepted history and protected source identities | UID/GID `10001`, private |
| `/var/lib/polysia/wallet-intelligence/backups/` | Checksummed local SQLite backups | UID/GID `10001`, private |
| `/var/lib/polysia/wallet-intelligence/reports/latest.json` | Sanitized health only | UID/GID `10001`, private |

These are the host paths. Compose mounts them onto the stable in-container
`/var/lib/polysia/data`, `/var/lib/polysia/backups/wallet-intelligence`, and
`/var/lib/polysia/reports/wallet-intelligence` paths. The narrow mounts prevent
this externally driven job from writing unrelated PolySia state.

The SQLite file is separate from `polysia.sqlite3`. Raw wallet addresses exist
only in `candidate_wallet_identities.external_wallet_id` inside the protected
database. Snapshot rows, ordinary joins, health reports, CLI output, and logs
use an internal SHA-256 wallet key. Database, backup, and report files are
excluded from Git. On Linux, the application applies mode `0700` to owned
directories and `0600` to files.

This is access-control and disclosure protection, not encrypted storage.
Encrypted off-host backup remains separate unfinished operational work.

## Data lifecycle

Each attempt has a unique `run_id`; each candidate version has a distinct
`snapshot_id`. A successful source/date is idempotent by default, so a repeated
timer invocation does not fetch or duplicate the snapshot. An operator may use
`--force-new` for an intentional corrected same-day version.

The promotion transaction writes identities, every normalized row, the
snapshot manifest, and the current pointer together. Any failure rolls the
transaction back. A failed or quarantined attempt never replaces the previous
current snapshot.

Default retention is:

- accepted normalized snapshots: 365 days;
- schema-change quarantine evidence: 30 days;
- local checksummed backups: newest 14 copies.

The current snapshot is never pruned, even if it is older than the retention
cutoff. After seven accepted versions, a row-count change below 50% or above
200% of the recent median is accepted only with an explicit health warning.
Completeness invariants still fail the attempt before promotion.

## First controlled run

Prepare private state without changing the existing trading database:

```bash
sudo install -d -o 10001 -g 10001 -m 0700 \
  /var/lib/polysia/wallet-intelligence/data \
  /var/lib/polysia/wallet-intelligence/backups \
  /var/lib/polysia/wallet-intelligence/reports
```

Build and run one read-only ingestion from `/opt/polysia`:

```bash
docker compose build wallet-intelligence-sync
docker compose --profile wallet-intelligence run --rm wallet-intelligence-sync
```

The command exits nonzero on a source, schema, consistency, persistence, or
backup failure. Its JSON output and health file contain counts, identifiers,
digests, freshness, and safe error codes, but no wallet addresses.

Inspect health separately:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-sync wallet-intelligence health \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3 \
  --health-report /var/lib/polysia/reports/wallet-intelligence/latest.json
```

Health is `warning` after 36 hours without a new accepted snapshot and
`critical` after 72 hours. A fresh last-known-good snapshot plus a failed or
quarantined latest attempt is `warning`. `critical` exits with status 1.
External alert delivery is not implemented; systemd failure monitoring or a
separately configured alert provider must observe nonzero exits.

## Daily automation at 03:15 UTC

Install the reviewed one-shot unit and timer:

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence.service \
  /etc/systemd/system/polysia-wallet-intelligence.service
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence.timer \
  /etc/systemd/system/polysia-wallet-intelligence.timer
sudo systemctl daemon-reload
sudo systemctl enable --now polysia-wallet-intelligence.timer
systemctl list-timers polysia-wallet-intelligence.timer
```

The timer is persistent and has a bounded five-minute randomized delay. It runs
the Compose service once, which exits after success or failure. It does not
create another always-running worker.

Check the last attempt:

```bash
systemctl status polysia-wallet-intelligence.service
journalctl -u polysia-wallet-intelligence.service --since today
```

Disable access immediately when source permission or semantics are uncertain:

```bash
sudo systemctl disable --now polysia-wallet-intelligence.timer
```

## Backup and real restore rehearsal

Every successful CLI invocation creates and verifies an online backup unless
`--no-backup` is explicitly used. A repeated idempotent invocation does not
duplicate the database snapshot, but it refreshes the recoverable backup so a
retry can repair a prior backup failure.

At least weekly, select one exact backup name and run a disposable restore:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-sync wallet-intelligence restore-check \
  --backup /var/lib/polysia/backups/wallet-intelligence/<exact-name>.sqlite3
```

`restore-check` verifies the SHA-256 sidecar, restores into a temporary database,
runs SQLite integrity and foreign-key checks, verifies the dedicated schema
version, and reports restored snapshot and row counts. It never overwrites the
active database.

Local backups do not protect against host loss. Copy verified backups to an
approved encrypted off-host location when that separate capability is
authorized and implemented.

## Failure and recovery

| Condition | Result | Operator action |
|---|---|---|
| HTTP, timeout, or bounded retry failure | Run `failed`; previous current snapshot retained | Inspect service status; retry after the source recovers |
| Page count/page 1 changes mid-read | Complete read retried once, then failed | Retry later; do not promote partial data |
| Missing, added, or invalid source field | Run `quarantined`; redacted compressed sample retained | Disable timer if persistent; review adapter contract before code change |
| Abandoned running attempt older than two hours | Marked `failed`; a new run may acquire the source | Inspect host/process history |
| Row-count baseline warning | Snapshot retained with warning | Compare source behavior and recent history |
| SQLite/backup integrity failure | Nonzero exit | Stop automation; preserve database and backups; rehearse a known-good restore |
| Health older than 72 hours | `critical`, nonzero exit | Use the last-known-good dataset only as stale evidence; repair before downstream promotion |

Never edit the current pointer manually. Before an actual database replacement,
disable the timer, preserve the active file, verify and rehearse the chosen
backup, then use a separately reviewed recovery procedure.

## Adding another candidate source

The database and application port are source-neutral and partition every run,
snapshot, identity, and current pointer by `source_id`. Adding another source
requires a focused adapter implementing `CandidateWalletSourcePort` plus an
explicit composition branch in the CLI. Do not add runtime module scanning or
claim a generalized adapter registry; that remains TARGET architecture.

Source-specific fields remain inside `metrics_json`, while protected external
identities stay in the identity table. Stage 2 selection must be a separate
application flow and must not change ingestion history or the current source
pointer.

## Rollback

Disable the timer, check out the previously approved application revision, and
rebuild. The earlier code ignores the separate wallet-intelligence database, so
no main trading-database rollback is required. Retain the database and backups
for forward recovery; do not delete them merely because application code is
rolled back.
