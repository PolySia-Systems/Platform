# ADR-0006: SQLite for Local and Research MVP

- Status: Accepted
- Date: 2026-07-11

## Context

SQLite is implemented, tested, operationally simple, and appropriate for the
current single-node local/research workload.

## Decision

Retain SQLite behind repository ports. Use Decimal-safe serialization and
explicit transaction/recovery tests.

## Migration triggers

Reconsider when measured concurrent writers, availability, data volume,
multi-process deployment, recovery objectives, or audit requirements exceed
SQLite. A production database change requires an RFC, migration rehearsal, and
rollback; future-proofing alone is insufficient.

