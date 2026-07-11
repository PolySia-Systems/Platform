# ADR-0005: Official Polymarket SDK and Beta Risk

- Status: Accepted
- Date: 2026-07-11

## Context

The verified baseline uses official `polymarket-client==0.1.0b11`; official b12
is newer and the unified SDK remains beta.

## Decision

Pin b11 through behavior and naming migration. Isolate SDK types in the adapter,
add method-level contract tests, then evaluate b12 as a separate change.

## Upgrade and rollback

Record official changelog/tag evidence, run public/read-only compatibility tests,
all local gates, and controlled signer/funder diagnostics before promotion.
Rollback restores the exact lock and reinstalls b11. Never silently change SDK
families.

