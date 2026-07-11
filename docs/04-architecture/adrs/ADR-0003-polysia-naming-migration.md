# ADR-0003: PolySia Naming and Compatibility Migration

- Status: Accepted
- Date: 2026-07-11

## Context

The baseline is `polymarket-trading-system`, `pm_trader`, and `pm-trader`; the
approved identity is `polysia` for distribution, namespace, and CLI.

## Decision

Perform a direct, tested rename. No external consumer was found, so no legacy
shim will be added. Archived historical evidence is not rewritten.

## Consequences and rollback

Internal imports, tests, docs, entry points, generated titles, and editable
installation change together. Migration tests and full gates are required. The
previous commit, preserved folder, and backup provide rollback. A later verified
consumer requires an amended, dated compatibility decision.

