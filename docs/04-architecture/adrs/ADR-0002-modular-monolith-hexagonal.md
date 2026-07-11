# ADR-0002: Modular Monolith with Ports and Adapters

- Status: Accepted
- Date: 2026-07-11

## Context

PolySia needs venue-neutral boundaries without distributed-system overhead.

## Decision

Use one deployable Python package with domain, application, adapter, and
interface boundaries. Dependencies point inward; venue SDKs remain in adapters.

## Consequences and risks

This supports incremental extraction and local operation. Boundary erosion is a
risk, so architecture tests will reject SDK/adapter imports from inner layers.
Microservices require measured need and a superseding ADR.

