# Stage 4B data lifecycle v1

Status: implementation and offline rehearsal are verified. Helsinki still runs
schema v5 at `dbb19c262dc6e28aa4872ac24682104356ffb2f7` until the merged SHA
from this change is deployed. This is not the 24-hour storage-acceptance
record.

## Root cause and fix

Every successful poll inserted one mark-history row per open position. Helsinki
evidence on 2026-09-02 showed 2.29 million marks over 8.77 days, 93% unchanged
consecutive prices, 1.67 GiB of marks/indexes, and backup growth that followed
that write path.

CURRENT valuation is now mutable position state. History is appended only for a
canonical Decimal price, mark status, relevant quantity, or settlement
transition. Health reads current position columns. Retention and recovery
bounds are versioned application policy (`stage4b-data-lifecycle-v1`), not
SQLite-specific meaning. SQLite and the modular monolith are unchanged.

## P0 capacity and recovery

Daily Intelligence backup timer `polysia-wallet-intelligence.timer` was
inhibited on 2026-09-02 because the next 03:18 UTC run would have added about
3.8 GiB on a volume with 9.4 GiB free. Prior state: enabled and active. It
must be re-enabled only after disk-safe backup behavior is verified.

The pinned 2026-09-02 05:38–05:55 UTC trio remains the migration checkpoint:

| Role | File | SHA-256 | Bytes |
|---|---|---|---|
| Intelligence | `wallet-intelligence-20260902T053846108697Z.sqlite3` | `0608f2b6895dae3d5dd744ebe92cd5e4297f76da87fa4168f41127f97429815b` | 2,101,231,616 |
| Stage 4B | `continuous-shadow-20260902T054800842182Z.sqlite3` | `599e3d9805d4bf7611be0f347075b4fe60c036631a1c27b7e7868c6b8064c997` | 1,793,335,296 |
| Latency | `wallet-intelligence-latency-20260902T055516138250Z.sqlite3` | `997bf56303ba8217863f0cd0cca23ee1d7a284dbd06fde678278cd1de3203b5f` | 52,330,496 |

On-host checksums, `PRAGMA integrity_check=ok`, and zero foreign-key violations
were reconfirmed. Nested backups were not deleted. An independent workstation
copy lives under `Documents/PolySia-backups/stage4b-data-lifecycle-v1-pre`
(latency and Stage 4B files verified; Intelligence copy may complete after this
record). No secrets were copied.

## Offline rehearsal (P2)

A disposable copy of the pinned Stage 4B backup was migrated, deduplicated, and
compacted with the new code. Experiment `71e7622c8a6e472f847d212b78099903`
stayed `RUNNING`. Ledger, events, and positions were unchanged. Ledger identity
remained balanced.

| Metric | Before | After |
|---|---|---|
| Schema | 5 | 6 |
| Marks | 2,138,848 | 587,730 |
| Duplicate history deleted | — | 1,551,118 |
| Expired 30-day deletes | — | 0 |
| Polls / events / ledger / positions | 7,305 / 31,782 / 9,241 / 465 | unchanged |
| File bytes | 1,793,437,696 | 562,573,312 compact |
| Compact restore integrity | — | `ok`, FK 0 |

The 69% compact-file reduction is a measured rehearsal result, not 24-hour
acceptance. Change-driven writes are expected to stop growth from tracking
open positions × poll frequency.

## Safety

Runtime remains `DATA_ONLY` with `LIVE_TRADING_ENABLED=false`. This change does
not authorize Live capability, orders, cancellations, or any `3x-ui` action.
Pruning uses the existing Stage 4B lease in explicit `--maintenance` only.
Compaction is offline `VACUUM INTO` only.

## Follow-up

Deploy the exact merged SHA, keep old history during the write-path canary,
then run bounded maintenance: recovery bundle, dedup, compact, restore-test,
re-enable the daily timer, and record T0 for the separate 24-hour check.
