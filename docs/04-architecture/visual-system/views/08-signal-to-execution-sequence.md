# Signal to Execution Sequence

- **Diagram ID:** PSA-ARCH-08
- **Purpose:** Show the end-to-end command/event sequence, including conflict, risk, venue rejection, and reconciliation paths.
- **Scope:** Current data, strategy, risk, adapter, state, reconciliation, and monitoring participants plus target allocator, OMS, and execution-port boundaries.
- **Architecture status:** MIXED
- **Audience:** Architects, execution developers, strategy developers, risk reviewers, and operators.
- **Source commit:** `a1b95235dbf430cb8fcc356e4ac4951a3359ccf9`
- **Reviewed:** 2026-09-06

## Mermaid diagram

Canonical source: [`08-signal-to-execution-sequence.mmd`](../sources/08-signal-to-execution-sequence.mmd)

```mermaid
sequenceDiagram
  autonumber
  participant MDA as Market Data Adapter [CURRENT]
  participant EB as Event Bus [CURRENT]
  participant OB as Order Book [CURRENT]
  participant FP as Feature Pipeline [CURRENT]
  participant S as Strategy [CURRENT]
  participant PA as Portfolio / Allocator [TARGET]
  participant VS as Verified Live State [CURRENT bounded]
  participant R as Risk Engine [CURRENT]
  participant OMS as OMS / Transaction Manager [TARGET]
  participant EP as Execution Boundary [CURRENT bounded]
  participant PM as Polymarket Adapter [CURRENT]
  participant V as Venue [EXTERNAL]
  participant LP as Ledger / Positions [CURRENT]
  participant RC as Reconciliation [CURRENT]
  participant MON as Monitoring [CURRENT]

  Note over MDA,MON: Legend - CURRENT implemented, TARGET approved evolution, EXTERNAL outside PolySia
  MDA-->>EB: normalized MarketDataEvent
  EB-->>OB: book snapshot or update
  OB-->>FP: Decimal book state
  FP-->>S: read-only features and context
  S->>R: pre-risk intent or canonical request
  opt portfolio allocation / conflict resolution [TARGET]
    S->>PA: candidate intent
    PA->>R: allocated intent plus portfolio context
  end
  opt guarded Live path [CURRENT bounded]
    PM-->>VS: authenticated read-only account evidence
    VS-->>R: fresh VerifiedLiveRiskSnapshot
  end
  alt risk rejects, state is unknown, or kill switch is active
    R-->>S: rejection / reduction reason
    R-->>MON: risk decision
  else risk approves exact request
    R->>EP: immutable ApprovedOrder / ApprovedOrderIntent
    opt transaction management [TARGET]
      EP->>OMS: idempotent execution command
      OMS-->>EP: authorized dispatch
    end
    EP->>PM: exact approved venue request
    PM->>V: guarded API request
    alt venue rejects or times out
      V-->>PM: rejection / uncertain state
      PM-->>EP: error or unknown response
      EP->>RC: reconciliation required
    else venue accepts and fills
      V-->>PM: order and fill events
      PM-->>EP: normalized execution result
      EP->>LP: order state and fill
      LP->>RC: internal expected state
      RC-->>MON: ready, warning, or blocked
    end
  end
  Note over S,V: No direct Strategy-to-Venue call is permitted
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Read top to bottom. The alternatives show conflict/no-capital, risk rejection, venue uncertainty, and accepted fill paths.

## Current implementation mapping

Market adapter, event bus, order book, features, strategies, independent risk,
execution services, Polymarket adapter, positions, reconciliation, and
monitoring exist. The CURRENT bounded Live slice refreshes authenticated
read-only state, rejects unknown or assumed state, canonicalizes the economic
request before Risk, and freezes the approved request before Execution. It
retains persistent authorization, one-attempt mutation, and read-only delayed
fill reconciliation.

## Target/future elements

Portfolio/Allocator and OMS/Transaction Manager are TARGET. They formalize
responsibilities currently spread across CLI, brokers, state models, and
repositories; the bounded current Execution boundary is not a generalized
execution router.

## Related repository files

`src/polysia/bus/`, `src/polysia/orderbook/`, `src/polysia/features/`, `src/polysia/strategies/`, `src/polysia/risk/`, `src/polysia/execution/`, `src/polysia/adapters/polymarket/`, `src/polysia/portfolio/`, `src/polysia/reconciliation/`, `src/polysia/monitoring/`

## Related tests

`tests/integration/test_paper_vertical_slice.py`, live-broker negative-gate tests, reconciliation tests

## Related ADRs

ADR-0002, ADR-0004, ADR-0008, ADR-0009, ADR-0016

## Related capabilities/requirements

CAP-001–CAP-011; REQ-002, REQ-004, REQ-006

## Assumptions

Target sequencing preserves current independent risk authority and adapter isolation.

## Known limitations

The sequence unifies current and target participants for clarity; labels must
be read before treating a participant as implemented. The TARGET allocator and
OMS must not be inserted into claims about the current bounded live path.

## Review trigger

Allocator, OMS, execution-port, or asynchronous execution-event behavior is implemented.
