# Stage 4B data lifecycle v1

Status: CURRENT on `Hetzner-Finland-Helsinki-01` in `DATA_ONLY` / Shadow.
This file is the deployment, T0, and 24-hour storage-acceptance record.
Dated runtime rows are snapshots, not live host truth.

## Root cause and fix

Every successful poll inserted one mark-history row per open position.
Helsinki evidence on 2026-09-02 showed about 2.29 million marks over 8.77 days,
93% unchanged consecutive prices, 1.67 GiB of marks/indexes, and backup growth
that followed that write path.

CURRENT valuation is mutable position state. History is appended only for a
canonical Decimal price, mark status, relevant quantity, or settlement
transition. Health reads current position columns. Retention and recovery
bounds are versioned application policy (`stage4b-data-lifecycle-v1`), not
SQLite-specific meaning. SQLite and the modular monolith are unchanged.

## Delivery identity

- PR `#112`: [feat(shadow): bound Stage 4B mark history and recovery artifacts](https://github.com/PolySia-Systems/Platform/pull/112) — MERGED.
- Implementation commit: `4fc2a3d5bebdca0071cac01a2bc6c7204f4a868f`.
- Merged / deployed SHA: `6743f7464f94d3fb76edc057834e8219ca7ebfe0`.
- Release path: `/opt/polysia-releases/6743f7464f94d3fb76edc057834e8219ca7ebfe0`.
- Workstation `git archive` SHA-256:
  `83a827d6137cf4a3bf9997c89928fe5c191bbc67df9b956529b214f3991f7d8f`.
- Image: `polysia:local` / `sha256:98df02069c471e5e71aabcd31448a9a4862510f9e735ad9a3fe62c073855d3ee`.
- Embedded `BUILD_COMMIT` matches the merged SHA.
- CI on PR `#112`: quality, container, Windows Compatibility, and CI Gate
  succeeded. Supply-chain was skipped (no dependency change).

## Safety

Runtime remains `TRADING_MODE=DATA_ONLY` with `LIVE_TRADING_ENABLED=false`.
This change did not authorize Live capability, orders, cancellations, or any
`3x-ui` action. The `3x-ui` container identity stayed
`ab567d6d3f4ed7246e13459cfabd58387e413f900dcb693dc2a26a44dba76bb2`, started
`2026-08-21T10:33:56Z`. The monitor container was not rebuilt or restarted.

## P0 capacity and recovery

Daily Intelligence backup timer `polysia-wallet-intelligence.timer` was
inhibited on 2026-09-02 because the next 03:18 UTC run would have added about
3.8 GiB on a volume with 9.4 GiB free. Prior state: enabled and active. It was
re-enabled at T0 after compact backups and restore checks. Next elapse at T0:
`2026-09-03T03:17:03Z`.

The pinned 2026-09-02 05:38–05:55 UTC trio remains the migration checkpoint
under `backups/pinned/migration-checkpoint-20260902/`:

| Role | File | SHA-256 | Bytes |
|---|---|---|---|
| Intelligence | `wallet-intelligence-20260902T053846108697Z.sqlite3` | `0608f2b6895dae3d5dd744ebe92cd5e4297f76da87fa4168f41127f97429815b` | 2,101,231,616 |
| Stage 4B | `continuous-shadow-20260902T054800842182Z.sqlite3` | `599e3d9805d4bf7611be0f347075b4fe60c036631a1c27b7e7868c6b8064c997` | 1,793,335,296 |
| Latency | `wallet-intelligence-latency-20260902T055516138250Z.sqlite3` | `997bf56303ba8217863f0cd0cca23ee1d7a284dbd06fde678278cd1de3203b5f` | 52,330,496 |

Nested unique backups were not treated as orphans. An independent workstation
copy lives under `Documents/PolySia-backups/stage4b-data-lifecycle-v1-pre`.
No secrets were copied.

## Offline rehearsal (P2)

A disposable copy of the pinned Stage 4B backup was migrated, deduplicated, and
compacted before deploy. Experiment `71e7622c8a6e472f847d212b78099903` stayed
`RUNNING`. Ledger identity remained balanced.

| Metric | Before | After |
|---|---|---|
| Schema | 5 | 6 |
| Marks | 2,138,848 | 587,730 |
| Duplicate history deleted | — | 1,551,118 |
| Expired 30-day deletes | — | 0 |
| Polls / events / ledger / positions | 7,305 / 31,782 / 9,241 / 465 | unchanged |
| File bytes | 1,793,437,696 | 562,573,312 compact |
| Compact restore integrity | — | `ok`, FK 0 |

## Helsinki canary (write path, old history retained)

Worker started on the merged SHA at `2026-09-02T22:43:15Z`. Schema migrated
v5→v6 in place. Ten successful polls after `2026-09-02T22:43:15Z` completed by
`2026-09-02T23:01:47Z`.

| Check | Result |
|---|---|
| Marks before first new poll | 2,331,368 |
| Marks after 10 successful polls | 2,332,542 (+1,174) |
| Old path forecast for ~507 opens × 10 | about 5,070 history rows |
| Health | freshness updated; `missing_mark_count=0`; `ledger_balanced=true` |
| Duplicate processing | 0 |
| Worker restarts | 0 |
| One failed poll | `source_unavailable__at__collect_events` at `22:56:08Z`; next poll succeeded |

Unchanged observations no longer insert one history row per open position.
The +1,174 rows are real price/status/quantity/settlement transitions plus the
first catch-up poll after the deploy gap. This is not 24-hour storage
acceptance.

## Helsinki maintenance (dedup, compact, cutover)

Stopped-worker pre-maintenance snapshot:

| Metric | Value |
|---|---|
| Schema | 6 |
| Experiment | `71e7622c8a6e472f847d212b78099903` `RUNNING` |
| Marks | 2,333,045 |
| Polls / events / ledger / evaluations | 7,795 / 38,468 / 9,970 / 112,579 |
| Shadow file | 1,968,054,272 bytes |
| Prior fencing token | 813 |

Verified recovery bundle while stopped:
`continuous-shadow-20260902T232702842262Z.sqlite3`
SHA-256 `73945fee58d345c7ede82d3c026396730606d9d7fd351cab897f41578d27f8b9`.

Live prune through `portfolio-prune-history --maintenance --deduplicate`:

| Metric | After prune |
|---|---|
| Duplicate history deleted | 1,696,885 |
| Expired 30-day deletes | 0 |
| Marks | 636,160 |
| Polls / events / ledger | unchanged 7,795 / 38,468 / 9,970 |
| Integrity / foreign keys | `ok` / 0 |

Offline `VACUUM INTO` compact (never the live writer):

| Item | Value |
|---|---|
| Compact bytes | 620,560,384 |
| SHA-256 | `45078cccc254eb7925deb1b326c8607d673e2426810355f89b838478548ce382` |
| Restore rehearsal | schema 6, polls 7,795, ledger 9,970, balanced, events 38,468 |

Cutover replaced the live file with that compact copy and deleted the cloned
lease row. A fresh local fencing epoch started at token `1`. The compact
cutover file is pinned at
`backups/pinned/compact-cutover-20260902T2348/`.

Worker restarted at `2026-09-02T23:48:37Z` on the same merged SHA.
`NRestarts=0`. Three successful post-cutover polls: marks 636,160 → 636,537
(+377), file 620,564,480 → 621,895,680 bytes, `ledger_balanced=true`,
`duplicate_processing_count=0`, `missing_mark_count=0`, fencing tokens 1→4.

## Compact recovery bundle and timer

Post-cutover rotating bundle (restore-tested):

| Role | File | SHA-256 |
|---|---|---|
| Intelligence | `wallet-intelligence-20260902T235947562506Z.sqlite3` | `36d391172b863158059036c11a826c07d3d6036a4482a4956be8f1b1295559c3` |
| Stage 4B | `continuous-shadow-20260903T000301139328Z.sqlite3` | `b9fb18436a4ea546e391bc6852c247e503ed43f359425166ac9bc033342603c1` |
| Latency | `wallet-intelligence-latency-20260903T000526565654Z.sqlite3` | `321b3cef1a777e7dd270e26b5ca208c2067aa47843453cd1422038c8920dc2be` |

Shadow restore: schema 6, polls 7,806, ledger 9,974, balanced, events 38,541.
Intelligence restore: 7 snapshots, 13,007 rows, 1,884 candidate-pool rows.
Latency restore: schema 1, 51,000 spans, 52,981 measurements.

`polysia-wallet-intelligence.timer` is enabled and waiting. Temporary `/tmp`
deploy scripts and the release archive were removed. Rotating DATA_ONLY
bundles keep three verified copies; `pinned/` is never auto-pruned.

## T0 for the separate 24-hour check

**T0 = `2026-09-03T00:11:07Z`.**

At T0 the host was on merge SHA `6743f74`, schema v6, compact Stage 4B
database, fresh fencing epoch, daily timer restored, `DATA_ONLY` /
`LIVE_TRADING_ENABLED=false`, worker `NRestarts=0`, and about 6.2 GiB free.
Do not treat earlier sections as 24-hour storage acceptance.

## 24-hour storage acceptance

Audited as of `2026-09-04T11:07:43Z` (T0 + 34.94 hours). Policy authority:
`stage4b-data-lifecycle-v1` / `recovery-bundle-v1` (`30`-day history,
`keep=3`, `4 GiB` disk floor, `3600 s` bundle skew). Verdict: **PASS**.

The worker was still the T0 release `6743f7464f94d3fb76edc057834e8219ca7ebfe0`
at `/opt/polysia-releases/6743f7464f94d3fb76edc057834e8219ca7ebfe0`, image
`sha256:98df02069c471e5e71aabcd31448a9a4862510f9e735ad9a3fe62c073855d3ee`.
`TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false`, empty live token
allowlist. No order or cancellation path was used. `3x-ui` identity remained
`ab567d6d3f4ed7246e13459cfabd58387e413f900dcb693dc2a26a44dba76bb2`, started
`2026-08-21T10:33:56Z`, `RestartCount=0`. Worker `NRestarts=0` since
`2026-09-02T23:48:37Z`. Schema v6. Experiment
`71e7622c8a6e472f847d212b78099903` remained `RUNNING`. Ledger health
`ledger_balanced=true`. `duplicate_processing_count=0`.
`missing_mark_count=0`.

| Metric | Value |
|---|---|
| Open positions (`quantity != 0`) | 551 |
| Marks at audit | 761,241 |
| Marks with `marked_at < T0` | 637,439 |
| Marks with `marked_at >= T0` | 123,802 |
| Successful polls since T0 | 1,165 |
| Failed polls since T0 | 158, all `source_unavailable__at__collect_events`; next polls succeeded |
| Old per-poll forecast (`opens × successful polls`) | 641,915 |
| Retained history ratio vs that path | 0.193 (80.7% fewer history rows) |
| Normalized 24-hour mark inserts | 85,030 / day |
| Live Stage 4B file | 742,735,872 bytes |
| Compact cutover file | 620,560,384 bytes |
| Last recorded live size after three post-cutover polls | 621,895,680 bytes |
| Growth vs that live size | +120,840,192 bytes in 34.94 h → 82,995,582 bytes/day |
| Pre-maintenance live file (2026-09-02) | 1,968,054,272 bytes (now 37.7% of that size) |
| Disk free | 7,747,817,472 bytes (above 4 GiB floor) |
| Oldest retained mark | `2026-08-25T01:32:35Z` (inside 30 days) |

30/90/365-day mark projections at the observed insert rate are 2.55 M / 7.65 M /
31.0 M if nothing is pruned. Policy caps history at 30 days; prune remains an
explicit maintenance command, not the poll path. Linear 365-day file growth is
therefore not the acceptance bound.

Rotating recovery: exactly three `bundle-*` directories, each with Intelligence,
Stage 4B, and latency files plus SHA-256 sidecars and `recovery-bundle.json`.
Latest bundle `bundle-20260904T032309827736Z` hashes matched the manifest,
skew 0 s, `integrity=ok` for all three after copy into `/var/tmp` and
read-only SQLite checks (Stage 4B schema 6). Temporary copies were deleted.
Pinned migration and compact-cutover directories were unchanged. Nested
2026-09-01 unique backups and empty leftover `*-wal`/`*-shm` next to rotating
files were left in place.

Workstation `Documents/PolySia-backups/stage4b-data-lifecycle-v1-pre` still
holds checksum sidecars and rehearsal scripts; the full SQLite copies were not
present at this audit. Local keep-three plus pinned checkpoints remain the
CURRENT recovery set. Manifest `release_sha` is still null.

## Limitations

- Intelligence still has a large freelist; daily Intelligence backups remain
  about 2.1 GiB until a separate offline compact of that file is authorized.
- The 03:17 UTC timer may briefly approach the 4 GiB disk floor while writing
  a new bundle before `keep=3` prunes the oldest rotating copy.
- Recovery-bundle manifests recorded `release_sha=null` on this host.
- Nested 2026-09-01 backups under `backups/wallet-intelligence/` were left in
  place because they are unique checksums, not proven orphans.
- One canary poll failed on an external source blip; it was not a lease or
  restart failure.
- Mark-history prune is maintenance-only. Schedule it before history older
  than 30 days accumulates (oldest mark at this audit: 2026-08-25).
- Operator health remained `warning` for unmarked/LKG current quotes
  (`unmarked_position_count=439`) and a settlement backlog (64). Those are
  freshness/settlement issues, not per-poll history amplification.
- 158 classified source-unavailable poll failures occurred in the window;
  the worker did not restart.
