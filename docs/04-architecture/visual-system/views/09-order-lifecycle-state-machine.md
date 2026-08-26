# Order Lifecycle State Machine

- **Diagram ID:** PSA-ARCH-09
- **Purpose:** Separate the actual current order states from approved lifecycle extensions.
- **Scope:** Intent/risk pre-states, the current `OrderStatus` enum, observed paper transitions, and target submission/recovery states.
- **Architecture status:** MIXED
- **Audience:** Execution developers, risk reviewers, reconciliation developers, and testers.
- **Source commit:** `ac104c708100bf9fff7e632acefd89bf90b8e509`

## Mermaid diagram

Canonical source: [`09-order-lifecycle-state-machine.mmd`](../sources/09-order-lifecycle-state-machine.mmd)

```mermaid
stateDiagram-v2
  state "OrderIntent [CURRENT pre-state]" as Intent
  state "Risk Evaluation [CURRENT pre-state]" as RiskEval
  state "Risk Rejected [CURRENT outcome]" as RiskRejected
  state "NEW [CURRENT]" as New
  state "ACCEPTED [CURRENT]" as Accepted
  state "PARTIALLY_FILLED [CURRENT]" as Partial
  state "FILLED [CURRENT]" as Filled
  state "CANCELLED [CURRENT enum]" as Cancelled
  state "REJECTED [CURRENT]" as Rejected

  [*] --> Intent
  Intent --> RiskEval
  RiskEval --> RiskRejected: failed check / kill switch
  RiskEval --> New: ApprovedOrderIntent
  New --> Accepted: accepted without immediate fill
  New --> Partial: partial paper fill
  New --> Filled: full immediate paper fill
  New --> Rejected: invalid or unfillable request
  Accepted --> Partial: partial fill
  Accepted --> Filled: full fill
  Accepted --> Cancelled: cancellation observed
  Partial --> Partial: additional partial fill
  Partial --> Filled: remaining quantity filled
  Partial --> Cancelled: remainder canceled
  RiskRejected --> [*]
  Filled --> [*]
  Cancelled --> [*]
  Rejected --> [*]

  state "TARGET lifecycle extensions" as TargetGroup {
    state "SUBMITTED / ACKNOWLEDGED [TARGET]" as Acknowledged
    state "CANCEL_REQUESTED [TARGET]" as CancelRequested
    state "EXPIRED [TARGET]" as Expired
    state "UNKNOWN / RECONCILIATION_REQUIRED [TARGET]" as Unknown
    Acknowledged --> CancelRequested
    CancelRequested --> Unknown
    Acknowledged --> Expired
  }

  note right of New
    Current OrderStatus enum:
    NEW, ACCEPTED, PARTIALLY_FILLED,
    FILLED, CANCELLED, REJECTED
  end note
  note right of TargetGroup
    Dashed/TARGET concepts are not
    current OrderStatus enum values.
  end note
  note left of TargetGroup
    Legend: CURRENT = implemented state;
    TARGET = approved extension;
    red = rejected before order creation.
  end note

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef target fill:#F1F5F9,stroke:#2563EB,stroke-width:2px,stroke-dasharray:6 4,color:#0F172A;
  classDef danger fill:#FEF2F2,stroke:#DC2626,stroke-width:2px,color:#0F172A;
  class Intent,RiskEval,New,Accepted,Partial,Filled,Cancelled,Rejected current
  class RiskRejected danger
  class Acknowledged,CancelRequested,Expired,Unknown target
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Start at `OrderIntent`, pass risk, then follow current states. Read the isolated target group only as a future extension.

## Current implementation mapping

Both domain and execution order models define `NEW`, `ACCEPTED`,
`PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, and `REJECTED`. `PaperOrder.add_fill`
drives partial/full transitions. The bounded live slice persists entry/exit
checkpoints, confirmed fills, and the terminal `FILLED` exit state separately;
FAK zero/partial/full outcomes use actual confirmed quantity and never create a
replacement entry.

## Target/future elements

`SUBMITTED`, `ACKNOWLEDGED`, `CANCEL_REQUESTED`, `EXPIRED`, and `UNKNOWN/RECONCILIATION_REQUIRED` are TARGET concepts, not current enum values.

## Related repository files

`src/polysia/domain/orders/models.py`, `src/polysia/execution/order_state.py`,
`src/polysia/execution/paper_broker.py`,
`src/polysia/execution/tiny_live_round_trip.py`,
`src/polysia/reconciliation/live_round_trip.py`

## Related tests

`tests/unit/execution/test_paper_broker.py`,
`tests/unit/execution/test_tiny_live_round_trip.py`, order-state,
reconciliation, integration, and property tests

## Related ADRs

ADR-0002, ADR-0008, ADR-0009

## Related capabilities/requirements

CAP-006, CAP-007, CAP-009, CAP-010; REQ-002, REQ-004

## Assumptions

Intent and risk are lifecycle pre-states, not values of the current order enum.

## Known limitations

`CANCELLED` exists in the current enum, but not every cancellation transition
is owned by the paper broker. Venue response/checkpoint phases are persistent
workflow evidence, not new canonical `OrderStatus` enum values.

## Review trigger

The canonical order enum, venue acknowledgement model, cancellation semantics, expiry, or recovery behavior changes.
