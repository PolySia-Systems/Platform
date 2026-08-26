# Wallet Intelligence Pipeline Runbook

## Status and boundary

This runbook covers the CURRENT repository implementation of Stage 1 source
ingestion, Stage 2 Candidate Intelligence, Stage 3 copyability selection, and
Stage 4 dynamic copyability Shadow evidence.
Deployment and timer installation remain an operator action. The workflow is
read-only toward external sources and cannot produce a signal, `OrderIntent`,
paper order, Live order, cancellation, transfer, or wallet mutation. Stage 3
does not prove profitability or authorize trading. Stage 4 reads public
Polymarket data and writes local simulation evidence; it has no order authority.

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
| `/var/lib/polysia/wallet-intelligence/reports/continuous-shadow.json` | Sanitized interval, accounting, lifecycle, and freshness health for Stage 4B | UID/GID `10001`, private |
| `/var/lib/polysia/runtime/candidate-banks/` | Versioned protected pre-Live handoff bank and address-free manifest | UID/GID `10001`, mode `0700`; files `0600` |
| `/var/lib/polysia/runtime/candidates.txt` | Atomic current link consumed only by the separately gated legacy Tiny Live Copy runner | UID/GID `10001`, mode `0600`; may be deleted by a terminal dry-run |

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
- Stage 4 event, wallet-summary, cost-model, and run history: 365 days by default;
- Stage 4B experiment journal, portfolio, fill, fee, ledger, mark, and settlement
  evidence: retained for the experiment lifetime; pruning requires a later explicit
  retention decision after real growth is measured;
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

Stage 4 consumes the deduplicated union of current `SHADOW_ALPHA` and
`SHADOW_STRESS`; it does not read the old fixed 102-wallet file. The legacy
execution source remains BTC 15-minute by default, while Stage 4 explicitly
requests all event markets whose event, condition, token, outcome, and UTC
interval can be verified from official Polymarket metadata. Historical mode is
a versioned fee/slippage/delay/liquidity model, not historical-book proof.
Forward mode walks current official order-book depth. Results and current
pointers are atomic, versioned, address-free, and last-known-good preserving.

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

## Dynamic Historical and Forward Shadow

Run one bounded 30-day Historical cost-model backfill after Stages 1–3 exist:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-shadow wallet-intelligence shadow-sync \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3 \
  --mode HISTORICAL --lookback-hours 720
```

Run one Forward observation with the reviewed ten-minute polling assumptions:

```bash
docker compose --profile wallet-intelligence run --rm wallet-intelligence-shadow
```

The default Forward command uses a 15-minute observation window, a 15-minute
maximum measured delay, a 2% configured fee, and a maximum simulated notional
of 5 per event. These are explicit conservative research assumptions, not venue
fee discovery or a profitability claim. Any change creates a distinct
cost-input fingerprint. The full evidence contract is in
`docs/03-requirements/wallet-intelligence-stage4-dynamic-shadow.md`.

Read the current per-wallet result without exposing addresses:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-shadow wallet-intelligence shadow-results \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3 \
  --mode FORWARD --limit 100
```

Stage 4 uses the same persistent `wallet-intelligence-pipeline` lease as Stages
1–3. A collision fails safely and the next timer invocation may retry. A
successful refresh never calls Risk, Execution, or a venue order endpoint.

Install the seven-day Historical Shadow job at 04:00 UTC after the daily source
pipeline. Its cost assumptions are explicit and versioned; it is not a claim of
historical order-book reconstruction:

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence-history.{service,timer} \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now polysia-wallet-intelligence-history.timer
```

Install the separate Forward Shadow one-shot and timer only after review:

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence-shadow.service \
  /etc/systemd/system/polysia-wallet-intelligence-shadow.service
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence-shadow.timer \
  /etc/systemd/system/polysia-wallet-intelligence-shadow.timer
sudo systemctl daemon-reload
sudo systemctl enable --now polysia-wallet-intelligence-shadow.timer
```

Stop it without affecting the daily source pipeline:

```bash
sudo systemctl disable --now polysia-wallet-intelligence-shadow.timer
```

## Continuous Shadow Portfolio v0.2 / schema v4

Stage 4B is additive to the immutable Stage 4A windows above. It persists a
first-seen journal, cross-run inventory, independent Wallet portfolios, a labeled
mixed baseline follower, independent Alpha and Stress followers, market-specific
official fees, marks, settlement, and Decimal ledger evidence. Schema v4 keeps
Wallet, Pool, market, and event attribution on CLOSE and SETTLEMENT. Its complete
contract is
`docs/03-requirements/wallet-intelligence-stage4b-continuous-shadow.md`.

Create or idempotently reuse one versioned experiment before enabling the worker.
Existing v0.2 experiments continue after the v4 migration; Alpha and Stress
followers start empty and are not backfilled.

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-shadow-portfolio wallet-intelligence portfolio-start \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3
```

Inspect sanitized current health from the atomic artifact on the host. Do not
query the active worker database. Do not `docker compose run` the
`wallet-intelligence-shadow-portfolio` service while the worker is up: that
service owns `container_name: polysia-shadow-portfolio-worker`.

```bash
python3 - <<'PY'
import json
from pathlib import Path
print(json.dumps(json.loads(Path(
    "/var/lib/polysia/wallet-intelligence/reports/continuous-shadow.json"
).read_text()), sort_keys=True))
PY
```

Inside the image the same file is
`/var/lib/polysia/reports/wallet-intelligence/continuous-shadow.json`. Host
artifact reads on Helsinki completed in 0.0001–0.0002 s.

The artifact is rewritten atomically after each successful poll and includes a
concise `operator_summary` for MIXED_BASELINE, SHADOW_ALPHA, and SHADOW_STRESS
(NAV, modeled P&L, fees, exposure, drawdown, and open position counts), plus
fresh/stale/missing mark counts and the latest sanitized failure code. If the
post-poll health query meets a transient SQLite lock, the successful poll stays
committed, the worker continues, and the prior artifact remains last-known-good.
The interval log reports `health_refresh.status=failed` with a sanitized category
and `report_health` stage; the next normal interval retries. Backlog age is the
age of the current uninterrupted nonzero-backlog episode.

Run detailed historical analytics only against a verified snapshot or backup
file, never against the active SQLite file. Use `docker run --network none`
with a read-only backup mount so the one-shot does not join or tear down the
worker Compose network:

```bash
docker run --rm --network none \
  --user 10001:10001 \
  -v /var/lib/polysia/wallet-intelligence/backups:/var/lib/polysia/backups/wallet-intelligence:ro \
  "polysia:${POLYSIA_IMAGE_TAG}" \
  wallet-intelligence portfolio-results \
  --database /var/lib/polysia/backups/wallet-intelligence/<verified-backup>.sqlite3 \
  --limit 100
```

On the 268 943 360-byte Helsinki backup, `results(limit=100)` completed in
1.811 s. The CLI import inside the image added about 6 s; that is process
startup, not SQLite lock.

`portfolio-results.operator_summary` remains the detailed snapshot operator
view. `follower_portfolios` separates MIXED_BASELINE, SHADOW_ALPHA, and
SHADOW_STRESS. `policy_experiments` are walk-forward fill filters on recorded
evidence, not a profitability claim. Encrypted off-host backup is not
configured; local backup and disposable restore remain the current recovery
path.

Install the persistent worker and disable the previous one-minute oneshot timer:

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence-shadow-portfolio.service \
  /etc/systemd/system/
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence-shadow-portfolio.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl disable --now polysia-wallet-intelligence-shadow-portfolio.timer
sudo systemctl enable --now polysia-wallet-intelligence-shadow-portfolio.service
```

The unit uses `docker compose up` so the worker stays a Compose project member.
Oneshot `docker compose run` jobs on the same project then cannot drop its
network when they exit. Health still reads the host artifact; detailed
analytics still use a verified snapshot, not the live SQLite file.

The worker stays fenced by `continuous-shadow-portfolio-pipeline` and sleeps
between polls. The separate ten-minute Stage 4A job remains enabled as windowed
comparison and recovery evidence. A schema-v3 rollback restores the prior image
and the oneshot timer; switching v4 code onto a v3 database migrates forward,
while switching v3 code onto a v4 database fails closed.

Stop the persistent worker before drain or finalize. Those commands still use
`docker compose run` against the live database and must not race the writer.

```bash
docker compose --profile wallet-intelligence run --rm --no-deps \
  wallet-intelligence-shadow-portfolio wallet-intelligence portfolio-drain \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3
docker compose --profile wallet-intelligence run --rm --no-deps \
  wallet-intelligence-shadow-portfolio wallet-intelligence portfolio-finalize \
  --database /var/lib/polysia/data/wallet-intelligence.sqlite3
```

Do not finalize by deleting positions or changing lifecycle rows. Missing fee,
book, mark, or settlement evidence remains `UNKNOWN` or last-known-good and must
be investigated from the address-free health and journal evidence.

## Dynamic pre-Live runtime bank

The `runtime-bank` command replaces the manually maintained 102-wallet artifact
as an operational dependency. It selects exactly 102 identities dynamically
because the existing bounded Tiny Live Copy safety contract still requires that
count. It does **not** populate `LIVE_REVIEW_CANDIDATE`, authorize trading, call
Strategy/Risk/Execution, or relax the legacy BTC 15-minute Live runner.

Publication requires a successful current seven-day Historical Shadow run for
the same Stage 3 selection, no rejected event, at least one simulated event per
selected wallet, an unknown ratio no greater than 0.50, and evidence no older
than eight days. Alpha membership is prioritized, then simulated-event count,
unknown ratio, modeled PnL, Stage 3 ranks, and canonical wallet id. Fewer than
102 qualifying wallets fails without replacing the last-known-good bank.

Generate the protected bank offline from SQLite:

```bash
docker compose --profile wallet-intelligence run --rm --no-deps \
  wallet-intelligence-handoff
```

The handoff service has no network, forces `TRADING_MODE=DATA_ONLY`, forces
`LIVE_TRADING_ENABLED=false`, clears the Live allowlist, mounts the intelligence
database read-only, and emits only a redacted summary. Versioned bank files and
manifests are immutable. The current `candidates.txt` hard link is replaced
atomically only after the complete bank validates.

Install the reviewed operator-only one-shot, with no timer:

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/polysia-wallet-intelligence-handoff.service \
  /etc/systemd/system/polysia-wallet-intelligence-handoff.service
sudo systemctl daemon-reload
sudo systemctl start polysia-wallet-intelligence-handoff.service
```

A later `live tiny-copy --dry-run --maximum-poll-cycles 1` may consume this bank
for authenticated read-only preflight. `--submit` remains prohibited without a
new run-specific owner authorization, matching acknowledgement, exact green-CI
commit, and every existing Live safety gate.

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

Every successful Stage 1–3 `wallet-intelligence ensure` invocation creates and
verifies an online backup unless `--no-backup` is explicitly used. A repeated
idempotent invocation does not duplicate the database snapshot, but it refreshes
the recoverable backup so a retry can repair a prior backup failure. Stage 4 and
4B polling reuse that database and do not create a backup on every poll; their
recovery point is the latest verified pipeline or operator-requested backup.

At least weekly, select one exact backup name and run a disposable restore:

```bash
docker compose --profile wallet-intelligence run --rm \
  wallet-intelligence-sync wallet-intelligence restore-check \
  --backup /var/lib/polysia/backups/wallet-intelligence/<exact-name>.sqlite3
```

`restore-check` verifies the SHA-256 sidecar, restores into a temporary database,
runs SQLite integrity and foreign-key checks, verifies the dedicated schema
version, and reports restored snapshot and row counts. It never overwrites the
active database. The disposable restore is created beside the protected backup
by default, so a growing database is not constrained by the container's small
`/tmp` tmpfs; the scratch directory is removed automatically. Use
`--working-directory` only to select another protected path with sufficient
space.

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
| Stage 4 source/book/evaluation failure | Previous current Shadow evidence retained; no order sent | Inspect rate circuit and safe error; retry after recovery |
| Stage 4B source/book/fee/transaction failure | Watermark and persistent portfolio remain last-known-good; failed poll recorded with a sanitized category and stage | Inspect the atomic `continuous-shadow.json` artifact; do not query the live database; systemd `Restart=on-failure` remains |
| Stage 4A overlap causes Stage 4B `sqlite_busy` | Initialization, lease, or poll persistence rolls back, or post-poll health refresh keeps the prior atomic artifact; persistent worker continues | Confirm the sanitized `initialize`, lease, `persist`, or `report_health` stage, unchanged `NRestarts`, balanced ledger, and zero duplicate processing; the next normal interval retries |
| Stage 4B ledger mismatch or finalized experiment with positions | Health `critical`; no new trusted result | Disable only the Stage 4B timer, preserve DB/backup, investigate before restart |
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

Disable the Stage 4B timer first, then the other affected timer if required.
Wait until the Stage 4B one-shot service is inactive before collecting stable
manual results, replacing the database, or exercising backup and restore. A
concurrent poll can legitimately hold SQLite's write lock; do not bypass the
lock or treat a partial read as evidence. Retry only after the worker is
quiescent.

After any maintenance pause, explicitly start the timer and verify both
`is-enabled` and `is-active`; enabled alone does not prove that the timer is
scheduled. Confirm one subsequent service run has `Result=success` and
`ExecMainStatus=0`. Operational command sequences must restart the timer in an
EXIT trap or equivalent `finally` path so an intermediate failure cannot leave
the enabled timer inactive.

For a code-only rollback within the same Stage 4B schema version, restore the
previously approved application revision and rebuild. A rollback from Stage 4B
schema v3 to code that requires schema v2 is different: verify the exact
pre-migration backup, restore that database while the timer remains stopped,
then start the prior release and read the atomic health artifact. Merely switching the
release symlink leaves the older Stage 4B worker fail-closed on the unsupported
schema. Stage 1 through Stage 4A remain additive and do not require the main
trading database to be rolled back. Preserve the v3 database and all backups for
forward recovery; never delete them merely because application code is rolled
back.
