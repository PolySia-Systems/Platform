# Continuous Shadow lease recovery and telemetry isolation

Status: HISTORICAL. This records the predecessor schema-v4 recovery work.
Current operation and recovery use the standalone schema-v5 store documented in
[`stage4b-data-ownership-cutover.md`](stage4b-data-ownership-cutover.md). PR
#104 confirmed stable ownership and telemetry isolation but failed its Helsinki
acceptance on orphaned-poll recovery. PR #105 corrected that boundary and was
deployed from exact merge commit
`2c73ca6765b4f15f7c3531b4b75131a6c1534842`. Neither change enables Live
trading.

## Root cause

`ContinuousShadowService.poll` generated a new `owner_id` on every poll.
The SQLite lease already allows the same owner to re-acquire an unexpired
row. After `release_lease` failed with `sqlite_busy`, the next poll looked
like a second worker and spent up to the 30-minute TTL in `lease_busy`.
TTL, fencing tokens, and expiry semantics were not the defect.

## Correction

- One unique `owner_id` per service instance / worker process lifetime.
- Non-blocking in-process guard so two overlapping polls in the same
  process cannot both pass `acquire_lease` as the same owner.
- Future latency telemetry writes go to
  `wallet-intelligence-latency.sqlite3` beside the financial database.
- Existing telemetry rows are copied read-only from the financial file;
  financial latency tables are not DROPped or rewritten. After a successful
  copy, `latency_telemetry_copy_state` makes later restarts skip the scan
  instead of rewriting sidecar health.
- Backups treat the two SQLite files independently.

`source_fetch` behavior is unchanged. A new worker process still cannot
steal an unexpired lease; that is required fencing, not a recovery bug.

## Helsinki follow-up

The first deployed acceptance window confirmed stable worker ownership and
physical telemetry isolation, but exposed a second recovery boundary. A poll
started at `2026-08-29T11:49:51Z`; persistence contention then prevented both
completion and failure recording. The row remained `running`, so later workers
exited on `persistence_failed/load_state` until initialization marked it
`abandoned_poll` at `2026-08-29T12:21:57Z`.

The follow-up correction lets `start_poll` replace an orphaned `running` row
only while holding a matching, unexpired SQLite lease and fencing token. The
orphan transition and the new poll insert share one transaction. An expired or
stale owner cannot recover or start a poll. TTL, fencing, Ledger, telemetry,
financial policy, and Live controls remain unchanged.

## Delivery verification

- All local gates passed, including 874 tests; GitHub quality, container,
  Windows compatibility, and aggregate CI gates passed on PR #105.
- Checksummed financial and latency backups were restored into disposable
  databases before cutover; integrity, foreign keys, schema versions, and row
  counts passed.
- Helsinki started the exact merge image at `2026-08-29T18:03:32Z` with
  `TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false`, and zero service
  restarts.
- The first three post-deployment polls succeeded. The latest health artifact
  reported a balanced Ledger and zero duplicate processing. No real order path
  was enabled.
- The unrelated `3x-ui` container retained its prior identity, zero restart
  count, and original start time.

This immediate smoke confirms delivery and normal-cycle recovery. The
deterministic integration test injects the exact combined `complete_poll`,
`fail_poll`, and `release_lease` contention sequence. A longer observation
window remains operational evidence, not a prerequisite for the code fix.
