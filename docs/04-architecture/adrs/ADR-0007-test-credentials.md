# ADR-0007: Test Credentials and Environment Separation

- Status: Accepted
- Date: 2026-07-11

## Context

The owner supplied approved test-only credentials and dedicated account state
for realistic validation.

## Decision

Preserve their values and semantics in ignored local `.env`. Report only
configured status. Research and ordinary CI receive no live credentials;
production credentials are separate and outside this modernization.

## Consequences

Secret-value scanning, redaction tests, safe exports, and access-controlled
evidence are mandatory. Rotation, deletion, or production substitution requires
an explicit owner decision.

