# ADR-0015: Bound Stage 4B Mark History and Recovery Artifacts

- Status: Accepted
- Date: 2026-09-03

## Context

Stage 4B persisted one mark-history row per open position on every successful
poll. Helsinki DATA_ONLY evidence showed about 2.29 million marks in 8.77 days,
93% unchanged consecutive prices, and backup copies that grew with that history.
Health joined history to the latest poll, so current freshness appeared to need
a history row matching the current poll.

SQLite and the modular monolith remain the CURRENT store. PostgreSQL, queues,
microservices, and a new storage service are out of scope. Ledger, fills,
events, settlements, positions, provenance, checkpoints, and duplicate-processing
evidence must stay complete.

## Decision

Keep current valuation as mutable position state. Record mark history only for
meaningful transitions: canonical Decimal price, mark status, relevant quantity,
or a required settlement/lifecycle transition. Existing Event, Ledger, and
Position identity distinguish OPEN → CLOSE → REOPEN; no new lifecycle identifier
is added.

Health and latest-mark reporting read current position columns. A successful
poll always refreshes `observed_at`, freshness, source age, and
`last_observed_poll_run_id`. A failed or unavailable source is never presented
as `FRESH`.

Retention and recovery bounds are versioned application policy, independent of
the database engine. The initial DATA_ONLY default is 30 days of change history.
Local recovery keeps three verified rotating DATA_ONLY bundles plus separately
pinned migration checkpoints that rotating prune never deletes. Compaction uses
offline `VACUUM INTO`; the active writer is never vacuumed.

Pruning runs only through the existing Stage 4B single-writer lease while the
worker is in explicit maintenance. No analytical aggregation is added: current
consumers are Health, operator latest marks, poll persistence, and settlement.

## Consumer Matrix

| Consumer | Current need | History rows required |
|---|---|---|
| Health / freshness | Current valuation fields on open positions | No |
| `portfolio-results` latest marks | Current price, status, source age | No |
| Poll persistence / LKG | Mutable current state plus last good quote | No |
| Settlement marks | Transition evidence | Yes, on settlement |
| Ledger, journal, fills, checkpoints | Unchanged existing tables | N/A |
| Operator analytics | None in CURRENT runtime | No |

## Consequences

Storage growth is no longer proportional to open positions × poll frequency ×
experiment lifetime. Historical marks remain a bounded change log. Backup
amplification is limited by rotating bundle keep-three plus pinned checkpoints.
This does not authorize Live trading or claim 24-hour storage acceptance.

## Alternatives rejected

- Keep per-poll history and only prune backups: leaves the write amplification.
- PostgreSQL or a separate storage service: no measured need; violates SQLite
  modular-monolith CURRENT architecture.
- Analytical OHLCV buckets now: no current consumer requires them.
- Vacuuming the live writer: blocks the poll path and is unnecessary when an
  offline compact/cutover path exists.
