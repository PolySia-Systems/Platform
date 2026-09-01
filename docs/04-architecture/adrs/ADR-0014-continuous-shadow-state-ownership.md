# ADR-0014: Isolate Continuous Shadow Financial State

- Status: Accepted
- Date: 2026-09-01

## Context

Stages 1–4A and the persistent Stage 4B worker wrote different products into
one SQLite file. Their separate leases protected product-level publication but
could not serialize SQLite's file-level writer lock. Helsinki evidence showed
Stage 4A failures and Stage 4B busy/recovery churn when those independent jobs
overlapped. Changing SQLite tuning would reduce symptoms without defining who
owns mutable financial state.

## Decision

Keep one Python modular monolith and SQLite, but split storage ownership:

- Stages 1–4A own `wallet-intelligence.sqlite3` as research/intelligence state.
- Stage 4B is the sole runtime writer of `continuous-shadow.sqlite3`.
- latency telemetry remains in `wallet-intelligence-latency.sqlite3`.

Stage 4B reads one coherent, versioned Stage 3 selection in a short read-only
transaction. It then records the protected candidates, complete provenance, and
SHA-256 digest atomically in its own database. There is no SQLite `ATTACH`,
cross-database transaction, queue, RPC, or new service boundary.

The Stage 4B lease and fencing epoch are local to the new database. Migration
does not copy the old lease. It does preserve experiment identity, watermark,
journal, polls, candidates, portfolios, positions, attribution, evaluations,
liquidity consumption, ledger, marks, settlement cache, and selection history.

If the source selection cannot be read, Stage 4B may use its last-known-good
local snapshot. Once that snapshot exceeds the versioned freshness policy,
new exposure is rejected while exits, marks, and settlement continue.

## Migration and rollback

Cutover is an offline Stage 4B maintenance operation: stop the worker, create
and verify a combined-state backup, atomically extract schema v4 into standalone
schema v5, rehearse restore of both files, and start the exact reviewed image.
The destination must not already exist and migration refuses unfinished polls,
integrity failures, foreign-key failures, missing provenance, or an unbalanced
ledger.

Before the first successful schema-v5 mutation, code and files may be rolled
back to the cutover checkpoint. After schema v5 progresses, silently restarting
the old image against stale combined state is prohibited because it creates a
state fork. Operators must stop the worker, preserve both database versions,
then either restore the explicit cutover checkpoint or record that post-cutover
Shadow evidence is abandoned before restarting the prior image.

## Consequences

Stage 4A cannot contend with the Stage 4B financial writer, and Stage 4B can be
moved to another store later without changing the intelligence boundary. The
cost is one additional protected SQLite file and a coordinated backup/restore
bundle. This does not authorize Live trading or claim production readiness.

## Alternatives rejected

- More retries or longer SQLite timeouts: mitigates contention but leaves
  ownership ambiguous.
- One shared global lease: unnecessarily couples research cadence to the
  continuous financial experiment.
- PostgreSQL, a queue, or microservices now: no measured need justifies the
  operational complexity.
- Copying only current positions: loses auditability and restart continuity.
