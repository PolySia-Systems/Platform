# ADR-0001: Adopt the Existing Python Implementation

- Status: Accepted
- Date: 2026-07-11

## Context

The supplied project has 73 source files, 328 passing tests, guarded real
connectivity evidence, and substantial operational behavior.

## Decision

Use it as the PolySia foundation. Modernize through migration, extraction, and
characterization tests; do not rebuild from scratch.

## Consequences and risks

Existing coupling and oversized modules are inherited, but behavior and safety
evidence are preserved. The preserved folder and verified backup are rollback
sources. Revisit only if a baseline capability is proven irreparable.

