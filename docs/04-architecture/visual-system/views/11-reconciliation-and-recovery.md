# Reconciliation and Recovery

- **Diagram ID:** PSA-ARCH-11
- **Purpose:** Show comparison of internal expectations with external account state and the resulting recovery controls.
- **Scope:** Expected/actual snapshots, detectors, event severity, status classification, safety pause, operator review, recovery, and audit output.
- **Architecture status:** CURRENT
- **Audience:** Operators, reconciliation developers, risk reviewers, and incident reviewers.
- **Source commit:** `44a8ae0fbccd0de916a0621236ea5931e7c3a256`

## Mermaid diagram

Canonical source: [`11-reconciliation-and-recovery.mmd`](../sources/11-reconciliation-and-recovery.mmd)

```mermaid
flowchart LR
  Internal["Internal Expected State\nopen orders, positions, last states, fills, timestamps\n[CURRENT]"]:::portfolio
  External["External Account State\nreadability, orders, positions, geoblock\n[EXTERNAL data]"]:::external
  Compare["ReconciliationManager + Detectors\n[CURRENT]"]:::risk
  Events["Reconciliation Events\nmanual cancel/close, unexpected fill/order, missing order, stale/read failure\n[CURRENT]"]:::observability
  Ready["READY\ncontinue under existing controls"]:::safe
  Warning["WARNING\noperator review"]:::risk
  Blocked["BLOCKED\ntrading_should_pause"]:::danger
  Pause["Safety Pause / Kill Switch\n[CURRENT]"]:::danger
  Operator["Operator Review and Manual Acknowledgement\n[CURRENT]"]:::current
  Recover["Correct state, restore readability, or rollback\n[CURRENT operational action]"]:::current
  Audit["Reports, audit evidence, monitoring\n[CURRENT]"]:::observability

  Internal --> Compare
  External --> Compare
  Compare --> Events
  Events -->|no blocking event| Ready
  Events -->|non-blocking discrepancy| Warning
  Events -->|blocking or live uncertainty| Blocked
  Blocked --> Pause
  Pause --> Operator
  Warning --> Operator
  Operator --> Recover
  Recover -->|new snapshot| Compare
  Ready --> Audit
  Warning --> Audit
  Blocked --> Audit

  subgraph LEGEND["Legend"]
    L1["CURRENT"]:::current
    L2["EXTERNAL STATE"]:::external
    L3["WARNING / SAFETY"]:::risk
    L4["BLOCK / PAUSE"]:::danger
    L5["HEALTHY"]:::safe
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
  classDef portfolio fill:#EFF6FF,stroke:#1D4ED8,stroke-width:2px,color:#0F172A;
  classDef risk fill:#FFF7ED,stroke:#D97706,stroke-width:2.5px,color:#0F172A;
  classDef observability fill:#FFFFFF,stroke:#9333EA,stroke-width:2px,color:#0F172A;
  classDef safe fill:#F0FDF4,stroke:#16A34A,stroke-width:2px,color:#0F172A;
  classDef danger fill:#FEF2F2,stroke:#DC2626,stroke-width:2.5px,color:#0F172A;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Feed internal and external state into reconciliation, classify events, then follow ready, warning, or blocked paths. Blocked paths activate safety pause before review and recovery.

## Current implementation mapping

Current models capture orders, positions, fills, read status, geoblock status, timestamps, event types, severity, blocking reasons, warnings, pause, and manual acknowledgement.

## Target/future elements

No target element is needed for the current recovery logic. A future generalized ledger may provide richer snapshots and immutable audit events.

## Related repository files

`src/polysia/reconciliation/`, `src/polysia/risk/kill_switch.py`, `src/polysia/monitoring/post_live_reconciliation.py`, `src/polysia/execution/manual_intervention_live_test.py`

## Related tests

reconciliation manager, detector, safety-pause, post-live, and manual-intervention tests; `tests/integration/test_paper_vertical_slice.py`

## Related ADRs

ADR-0008, ADR-0009

## Related capabilities/requirements

CAP-010, CAP-011; REQ-002, REQ-004

## Assumptions

Unreadable or uncertain live state is treated conservatively and may block.

## Known limitations

Recovery is operator-led and local; automated disaster recovery is not a current capability.

## Review trigger

Snapshot fields, mismatch taxonomy, blocking rules, safety-pause behavior, or acknowledgement changes.
