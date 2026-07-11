# ADR-0004: Polymarket as First Adapter

- Status: Accepted
- Date: 2026-07-11

## Context

Polymarket is the proven initial venue, while PolySia must not hardcode it into
the core.

## Decision

Keep all working Polymarket behavior and consolidate it behind canonical models,
capability metadata, mappers, and application ports.

## Consequences

Token IDs, condition IDs, wallet types, SDK models, and geoblock details remain
adapter concerns. Explicit capability profiles avoid a lowest-common-denominator
core. Contract tests protect adapter behavior.

