# ADR-0017: Isolated Prospective Research-Evidence Store

- Status: Accepted
- Date: 2026-09-07

## Context

Pre-deployment research needs a restart-safe canonical observation log:
wallet-attributable public trades, official market-state snapshots, and
decision associations. Stage 4B already owns the Continuous Shadow financial
database. Latency telemetry already owns an isolated sidecar. Mixing research
evidence into either store would couple experimental retention to financial
invariants or to fail-open diagnostics.

PostgreSQL, queues, and extra services remain out of scope. The CURRENT
runtime is one Python modular monolith with SQLite.

## Decision

Add one isolated SQLite research-evidence store with a single writer,
versioned schema `research-evidence-v2`, and bounded retention. Domain
contracts stay venue-neutral. Polymarket adapters translate public REST and
the official market WebSocket. The authenticated user channel is recorded as
`UNAVAILABLE` without credential lookup.

Schema v2 distinguishes one source trade from its wallet-attributed
observations. Observation identity includes the sanitized leader alias while
`source_event_id` retains the common source identity. The v1-to-v2 migration is
additive, preserves the original per-row schema label, and cannot reconstruct
wallet observations missing from legacy evidence.

The store is RESEARCH CURRENT. The persistent collector is a dedicated Compose
`research` service with rolling ten-minute windows (`OPEN → VALID | INVALID`),
WAL, a 5 second busy timeout, and an exclusive local writer lock. It is not
Live state, not Stage 4B accounting, and not started by the default monitor.
Operators start it with `docker compose --profile research up --detach research-collector`.
Health is an atomic JSON file. Readers use the SQLite Backup API. Backups reuse
`polysia.deployment.sqlite_backup` in a dedicated research-evidence directory;
the current generic backup CLI retains its `polysia-` filename prefix.

Evidence writes, retention pruning, and WAL checkpointing have distinct success
boundaries. Evidence commits in a short transaction. Pruning commits in a
separate transaction. Routine checkpoints are `PASSIVE` and run only after all
write transactions have ended; `TRUNCATE` is not part of hot ingestion.
Maintenance contention after an evidence commit is reported as degraded health,
not as a failed event write. Full-disk, I/O, corruption, and actual evidence-write
failures remain fail-closed. Persistent ingestion and window rotation use one
ordered lifecycle boundary.

The public `/trades` cooldown circuit is route-local and uses a single
post-cooldown recovery probe. Collector health separates process health,
source availability, and research eligibility; a retrying required source is
not silently treated as complete collection.

One durable `research_experiments` record declares the active capture's time,
event-count, and storage bounds. Ordinary retention does not prune an active
experiment. Finalization is a separate operator action that creates one
SQLite Backup-API snapshot, restores and verifies it, reproduces replay, and
only then marks the experiment finalized. A verified bundle on disk is reused
when the live `FINALIZED` row is incomplete. Successful finalization is
idempotent. Missing valid intervals produce a `FAILURE_ARCHIVED` evidence
bundle, never a verified `FINALIZED` label. Analysis of a published bundle is
strictly read-only: the source database is opened immutable/query-only, and
any compatibility work uses a private copy. Compact deterministic replay
comparison extends the existing `prospective-replay` command. The bounded
research Runner records orchestration phase, receipts, and frozen non-secret
configuration in one workspace manifest. Canary and main profiles share the
same production path and differ only by declared parameters. This adds no
database service and does not turn rotating recovery backups into a
continuous archive.

Economic evaluation remains inside the same research boundary. Side-aware
book-depth and official fee-schedule provenance are stored as versioned
canonical market evidence; no financial or parallel research database is
added. The existing prospective replay joins each Wallet observation only to
market evidence already observed at its decision time and emits a deterministic
cost-aware Control-versus-Target report. This path has no Risk, Execution, or
Live authority.

## Consequences

Prospective collection and replay can proceed without mutating financial
invariants. Retention may prune unreferenced market-state snapshots. Accepted
wallet evidence referenced by a decision is not silently deleted; missing
decision evidence invalidates the interval.

Active experiment evidence may temporarily exceed ordinary rolling event
retention, but cannot exceed its separately declared hard bounds. After
finalization, normal retention applies and the immutable bundle owns the
experiment input.

The WAL file is allowed to retain bounded reusable allocation. Acceptance is
based on checkpoint progress, bounded growth, and uninterrupted evidence—not a
requirement that the WAL file always be zero bytes.

This does not authorize Live trading, claim Alpha, or select a faster-than-REST
wallet source when none qualifies.

## Alternatives rejected

- Write into Stage 4B financial SQLite: mixes research retention with ledger
  invariants.
- Write into the latency sidecar: that store is fail-open observational
  telemetry, not decision evidence.
- Cross-database transactions: forbidden and unnecessary.
- PostgreSQL / Kafka / extra services: no measured need; violates CURRENT
  modular-monolith architecture.
