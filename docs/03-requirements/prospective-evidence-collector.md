# Prospective Research Evidence Collector

- **Status:** IMPLEMENTED as DATA_ONLY research capability; persistent collector is CURRENT for Compose profile `research`
- **Mode:** public read-only collection and local replay
- **External mutation:** none
- **No authority:** no Live, Risk, Execution, wallet, or order path

## Goal

Benchmark public real-time sources, collect a typed canonical observation
stream, and run a restart-safe persistent collector that produces rolling
ten-minute `OPEN → VALID | INVALID` windows for later DATA_ONLY acceptance.

This requirement does not prove profitability, Alpha, or Live readiness.

## Sources

Wallet-attributable and market-state latencies are measured separately. A
market WebSocket is never treated as a wallet identity source.

| Candidate | Kind | Public? | Role |
|---|---|---|---|
| `rest_activity` | wallet event | yes | current REST `/activity` poll baseline |
| `rest_trades` | wallet event | yes | second official REST `/trades` poll |
| `clob_market_ws` | market state | yes | official CLOB market WebSocket |
| `clob_user_ws` | wallet event | no | UNAVAILABLE; authenticated credentials are required and are not searched |

No more than two wallet-attributable candidates are compared. Lowest
normalize latency alone does not win. Attribution, recovery, and integrity
are mandatory. Insufficient samples stay `INSUFFICIENT`. Credential-gated
sources stay `UNAVAILABLE`.

## Canonical event

Schema `research-evidence-v2` separates the source trade identity from each
wallet-attributed observation identity. Two wallets observing the same source
trade therefore remain distinct evidence while retaining a shared
`source_event_id`. The schema also preserves market and outcome references,
side, price, size, source time, observed time, hashed leader alias,
confirmation/reversion, classification, and sanitized provenance. UTC wall
clocks are persisted. Durations use monotonic clocks. Existing v1 stores are
migrated additively; no research evidence is deleted or relabeled. Legacy v1
rows remain readable but cannot recover wallet observations that were already
collapsed before migration, so new comparative research must use v2 capture.

Classifications: `ACCEPTED`, `DUPLICATE`, `LATE`, `CONFLICTING`, `REVERTED`,
`UNATTRIBUTABLE`, `INCOMPLETE`, `GAP`, `OVERLOAD`.

## Collector

The collector is provider-neutral. Venue translation stays in adapters.

- Single-writer isolated SQLite (`research-evidence.sqlite3`) with WAL and a
  5 second busy timeout
- Exclusive local writer lock; a second writer is rejected
- Dedup across retries and restarts
- Rolling ten-minute windows: `OPEN` until complete closure, then `VALID` or
  `INVALID_*`
- Source connections stay alive across window rotation
- Orphaned `OPEN` windows become `INVALID_SHUTDOWN` on restart
- Bounded queue; overload invalidates the current window
- Missing decision evidence, drain failure, evidence-write/storage failure, or
  incomplete shutdown prevent `VALID`
- Empty windows keep an independent identity and may be `VALID` when collection
  completed with a successful, quiet required-source request
- A quiet wallet is not a failed source
- Service health, source availability, and research-data eligibility are
  independent. An unresolved required-source failure makes the affected
  window ineligible and therefore not `VALID`; evidence from healthy optional
  sources remains usable.
- The `/trades` circuit is route-local. After cooldown it permits exactly one
  `RECOVERY` probe; a successful probe returns later reads to `DISCOVERY`.
  Sanitized health and window evidence preserve failure class, retry time,
  last successful request/event, and recovery count. Error control events are
  not source progress.
- Decisions record evidence IDs, code SHA, configuration digest, and policy
  version
- Health is a sanitized atomic JSON file, refreshes at most every 30 seconds
  during an open window, and does not scan event tables
- Consistent readers use the SQLite Backup API
- Event persistence commits independently from maintenance. A post-commit
  retention or checkpoint failure must never be reported as an event-write
  failure.
- Retention pruning uses its own short transaction. Routine WAL checkpoints
  are non-blocking `PASSIVE` operations outside write transactions; the hot
  ingest path never requests `TRUNCATE`.
- Transient maintenance contention is health degradation, not lost evidence.
  Three consecutive pruning failures stop collection before retention can fail
  indefinitely. Real write, full-disk, I/O, or corruption failures remain
  immediately fail-closed.
- Event persistence and window rotation share one lifecycle ordering boundary,
  so a committed event cannot cross a summary/close/start boundary ambiguously.
- Reports are sanitized; wallet addresses never appear
- Window reports retain the newest 36 by authoritative window time, not UUID
  filename order.
- Each persistent run is a bounded experiment: four hours, 750,000 events, and
  768 MiB by default. Its events are protected from ordinary pruning until
  verified finalization. Reaching any bound stops new evidence fail-closed.
- Finalization creates one immutable checksummed SQLite bundle, restores it in
  isolation beside the staged bundle, verifies integrity and foreign keys, and
  reproduces replay before marking the experiment `FINALIZED`. Replay consumes
  only independently `VALID` windows; invalid windows remain immutable evidence
  and their reasons and excluded event counts stay explicit in the manifest.
  Backups are recovery points, not a substitute for continuous experiment
  evidence.

Do not write research evidence into the Stage 4B financial database or the
latency sidecar. No cross-database transactions.

## CLI

```text
python -m polysia.cli research source-benchmark --duration-seconds 600
python -m polysia.cli research prospective-replay --database artifacts/research-evidence.sqlite3 --run-id <id>
python -m polysia.cli research prospective-collect --window-seconds 600
python -m polysia.cli research prospective-health --health-report <path>
python -m polysia.cli research prospective-health --health-report <path> --require-research-eligible
python -m polysia.cli research prospective-finalize --database <stopped-db> --run-id <id> --bundle-root <dir>
```

Raw databases stay under `artifacts/` or `/var/lib/polysia/data/` and are not
committed. The Compose `research` profile runs `research-collector`. Official
comparison windows are 10–20 minutes. Ordinary pytest does not use the network.

## Replay

Current Control and Target Exposure v1 consume the same accepted observations.
Replay is chronological by observed time and keeps independent episode state
for each Portfolio x Market x Outcome. Admission requires an explicit,
side-aware executable quote observed no later than the wallet observation,
with available quantity and recorded fee. A leader trade price is never
substituted for follower execution evidence. Missing attribution, books,
prices, fees, marks, or gaps remain `UNKNOWN`.

Leader markouts use source event time. Follower-actionable markouts use local
observed time. Both use stored 5s / 30s / 5m snapshots, select the earliest
qualifying snapshot deterministically, and never interpolate prices.

This is not a second accounting engine. Stage 4B ledger semantics remain in
the historical replay path.

## Later research capture

Wallet+Market research needs accepted wallet-attributable trades plus
event-time market snapshots at decision and markout horizons. Market-only
research needs market-state evidence without using wallet fills as labels.
Neither is implemented as an Alpha contest here.

Sanitized measurement evidence:
[prospective-source-benchmark-v1](../18-ai-handoffs/prospective-source-benchmark-v1.md).
