# Continuous Shadow lease recovery and telemetry isolation

Status: CURRENT implementation pending Helsinki three-hour acceptance
after merge. This change does not enable Live trading.

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
