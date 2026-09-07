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
`polysia.deployment.sqlite_backup` with prefix `research-evidence-`.

## Consequences

Prospective collection and replay can proceed without mutating financial
invariants. Retention may prune unreferenced market-state snapshots. Accepted
wallet evidence referenced by a decision is not silently deleted; missing
decision evidence invalidates the interval.

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
