# ADR-0008: Live-Trading Safety and Human Approval

- Status: Accepted
- Date: 2026-07-11

## Context

The baseline includes dry-run, live flags, allowlists, caps, risk approval,
geoblock, kill switch, acknowledgement, one-attempt, and reconciliation controls.

## Decision

Preserve or strengthen every gate. Emergency control remains independent of
strategy code. Any state-changing live validation occurs only in its dedicated
phase with explicit authorization for that run.

## Consequences

Geoblock errors fail closed; VPN/proxy bypass is prohibited; normal refactoring
and CI cannot mutate live state. A gate reduction is a breaking security change
requiring owner approval, tests, and rollback.

