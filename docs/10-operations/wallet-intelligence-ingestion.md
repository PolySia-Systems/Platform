# Wallet Intelligence Pipeline Runbook

## Status and boundary

This runbook covers the CURRENT repository implementation of Stage 1 source
ingestion, Stage 2 Candidate Intelligence, and Stage 3 copyability selection.
Deployment and timer installation remain an operator action. The workflow is
read-only toward external sources and cannot produce a signal, `OrderIntent`,
paper order, Live order, cancellation, transfer, or wallet mutation. Stage 3
does not prove profitability or authorize trading.

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
| `/var/lib/polysia/wallet-intelligence/data/wallet-intelligence.sqlite3` | Accepted source history, protected identities, derived features, policy history, and current candidate pool | UID/GID `10001`, private |
| `/var/lib/polysia/wallet-intelligence/backups/` | Checksummed local SQLite backups | UID/GID `10001`, private |
| `/var/lib/polysia/wallet-intelligence/reports/latest.json` | Sanitized health only | UID/GID `10001`, private |

These are the host paths. Compose mounts them onto the stable in-container
`/var/lib/polysia/data`, `/var/lib/polysia/backups/wallet-intelligence`, and
`/var/lib/polysia/reports/wallet-intelligence` paths. The narrow mounts prevent
this externally driven job from writing unrelated PolySia state.

The SQLite file is separate from `polysia.sqlite3`. Raw wallet addresses exist
only in `candidate_wallet_identities.external_wallet_id` and
`canonical_wallets.normalized_address` inside the protected database. Snapshot
rows, the candidate-pool view, health reports, CLI output, and logs use an
internal SHA-256 wallet key or canonical `wallet_id`. Database, backup, and report files are
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
- Stage 2 feature, policy, and run history: at least 365 days;
- Stage 3 score, membership, and run history: at least 365 days;
- local checksummed backups: newest 14 copies.

The current snapshot is never pruned, even if it is older than the retention
cutoff. After seven accepted versions, a row-count change below 50% or above
200% of the recent median is accepted only with an explicit health warning.
Completeness invariants still fail the attempt before promotion.

Stage 2 has an independent additive schema-version record. It canonicalizes a
wallet as `(chain, normalized_address)`, retains every source link, derives only
snapshot-supported point-in-time features, and records readiness separately
from policy status. Insufficient 1-, 7-, or 30-day history remains `NULL`; it is
never replaced with zero. No healthy raw source JSON retention is claimed.

Stage 3 has a second additive schema-version record. After a healthy Stage 2
publication, `wallet-intelligence ensure` scores copyability components and
publishes independent `SHADOW_ALPHA`, `SHADOW_STRESS`, `REJECTED`, and
`WATCHLIST` results. `LIVE_REVIEW_CANDIDATE` remains empty until official
Polymarket verification, copyability backtest, and Shadow evidence exist. A
Stage 3 failure keeps the previous Stage 3 pools and does not rewrite Stage 1
or Stage 2.

The processing identity includes source snapshot, feature-set version, policy
id/version, and ranking version. A successful identity is idempotent. The full
feature and evaluation result is validated and the current pointer is then
published in one transaction. Failed work cannot replace the previous pool.

Startup, timer, and manual entry points use one SQLite-backed 30-minute lease
by default. Atomic acquisition, heartbeat/renewal, expiry recovery, and a
monotonic fencing token prevent concurrent or expired owners from publishing.
The database transaction is never held across the PolyCop network read.

## First controlled run

Prepare private state without changing the existing trading database:

```bash
sudo install -d -o 10001 -g 10001 -m 0700 \
  /var/lib/polysia/wallet-intelligence/data \
  /var/lib/polysia/wallet-intelligence/backups \
  /var/lib/polysia/wallet-intelligence/reports
```

Build and run the full read-only pipeline from `/opt/polysia`:

```bash
docker compose build wallet-intelligence-sync
docker compose --profile wallet-intelligence run --rm wallet-intelligence-sync
```

The default Compose command is `wallet-intelligence ensure`. On the first run it
fetches Stage 1 immediately at any time, then publishes Stage 2 and Stage 3. On
later runs it reuses a healthy snapshot younger than 24 hours; otherwise it
refreshes Stage 1, then replays or republishes Stage 2 and Stage 3.
The daily timer still anchors subsequent checks at 03:15 UTC. The command exits
nonzero on a source, schema, consistency, persistence, lease, publication, or
backup failure. Its JSON output and health file contain counts, identifiers,
versions, freshness, and safe error codes, but no wallet addresses.

Inspect health separately:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-sync wallet-intelligence health \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3 \
  --health-report /var/lib/polysia/reports/wallet-intelligence/latest.json
```

Health is `warning` after 36 hours without a new accepted snapshot and
`critical` after 72 hours. A missing candidate pool is critical. A candidate
pool behind the current Stage 1 snapshot, or a fresh last-known-good pool plus a
failed latest Stage 1/Stage 2 attempt, is warning. Missing Stage 3 after a
healthy Stage 2, Stage 3 behind Stage 2, or a failed latest Stage 3 attempt is
warning and does not invent a Stage 2 outage. A non-empty Live-review pool is
warning. `critical` exits with status 1.
External alert delivery is not implemented; systemd failure monitoring or a
separately configured alert provider must observe nonzero exits.

## Candidate pool query contract

The protected SQLite view `candidate_trading_pool_current` contains every
current evaluation and no address. Candidate Policy v1 maps `READY` to
`SELECTED`, partial/stale/unknown evidence to `WATCHLIST`, and invalid evidence
to `INELIGIBLE`. It is a discovery ranking, not a profitability claim.

Read deterministic Top 100 selected wallets:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-sync wallet-intelligence pool \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3 \
  --limit 100
```

Consumers use `candidate_status='SELECTED' ORDER BY candidate_rank`. Ranking is
source score descending, source rank ascending, presence ratio descending, and
canonical `wallet_id` ascending. The last field is the stable tie-break. The
complete feature/time/version contract is frozen in
`docs/03-requirements/wallet-intelligence-stage2.md`.

## Copyability selection query contract

Stage 3 pools are address-free. Read a pool or watchlist:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-sync wallet-intelligence selection \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3 \
  --pool SHADOW_ALPHA \
  --limit 50
```

Allowed `--pool` values are `SHADOW_ALPHA`, `SHADOW_STRESS`,
`LIVE_REVIEW_CANDIDATE`, `REJECTED`, and `WATCHLIST`. Ordinary JSON contains
`wallet_id` only. `LIVE_REVIEW_CANDIDATE` must return count 0 in v0.1. The
scoring and eligibility contract is frozen in
`docs/03-requirements/wallet-intelligence-stage3.md`.

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
| Unexpired pipeline lease | Second startup/timer/manual call fails safely as busy | Let the owner finish; do not run parallel copies |
| Expired lease after crash | New owner increments fencing token and recovers | Inspect the abandoned process before retrying external operations |
| Stage 2 calculation/publication failure | Previous candidate pool retained; failed run recorded | Inspect safe error code and repair before republishing |
| Stage 3 calculation/publication failure | Previous copyability pools retained; Stage 1/2 unchanged | Inspect safe error code; Stage 2 may still be healthy |
| Abandoned Stage 1 run older than two hours | Marked `failed`; a new run may acquire the source | Inspect host/process history |
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
identities stay in the identity tables. Add an explicit chain mapping in
composition. The same canonical wallet may then receive another provenance
link; source observations remain separate and cannot overwrite each other.

## Rollback

Disable the timer, check out the previously approved application revision, and
rebuild. Stage 2 and Stage 3 are additive. Earlier code ignores those tables, so
no main trading-database rollback is required. Retain the database and backups
for forward recovery; do not delete them merely because application code is
rolled back.
