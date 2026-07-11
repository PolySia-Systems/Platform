# ADR-0009: Testing Layers and No Live Mutation in CI

- Status: Accepted
- Date: 2026-07-11

## Context

The 328-test baseline is valuable but concentrated in `tests/unit`.

## Decision

Retain it and add contract, integration, property/state-machine, migration,
golden-report, and end-to-end layers. Network tests are opt-in and read-only by
default. Metered/state-changing tests are separately marked and impossible in
ordinary CI.

## Consequences

Critical priorities are order states, idempotency, Decimal accounting, restart,
duplicates/out-of-order events, redaction, adapter compatibility, and negative
live-gate proofs. Promotion requires all applicable layers.

