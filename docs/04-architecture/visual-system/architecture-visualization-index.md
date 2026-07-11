# Architecture Visualization Index

Baseline: `44a8ae0fbccd0de916a0621236ea5931e7c3a256`
Reviewed: 2026-07-11
Owner: PolySia project owner

| ID | View | Status | Canonical Mermaid | Documentation |
|---|---|---|---|---|
| PSA-ARCH-01 | System Landscape | MIXED | [source](sources/01-system-landscape.mmd) | [view](views/01-system-landscape.md) |
| PSA-ARCH-02 | C4 System Context | MIXED | [source](sources/02-c4-system-context.mmd) | [view](views/02-c4-system-context.md) |
| PSA-ARCH-03 | C4 Container — Current | CURRENT | [source](sources/03-c4-container-current.mmd) | [view](views/03-c4-container-current.md) |
| PSA-ARCH-04 | C4 Container — Target | TARGET | [source](sources/04-c4-container-target.mmd) | [view](views/04-c4-container-target.md) |
| PSA-ARCH-05 | Current Component Map | CURRENT | [source](sources/05-current-component-map.mmd) | [view](views/05-current-component-map.md) |
| PSA-ARCH-06 | Multi-Strategy Target Architecture | MIXED | [source](sources/06-multi-strategy-target-architecture.mmd) | [view](views/06-multi-strategy-target-architecture.md) |
| PSA-ARCH-07 | Market Data to Decision Flow | CURRENT | [source](sources/07-market-data-to-decision-flow.mmd) | [view](views/07-market-data-to-decision-flow.md) |
| PSA-ARCH-08 | Signal to Execution Sequence | MIXED | [source](sources/08-signal-to-execution-sequence.mmd) | [view](views/08-signal-to-execution-sequence.md) |
| PSA-ARCH-09 | Order Lifecycle State Machine | MIXED | [source](sources/09-order-lifecycle-state-machine.mmd) | [view](views/09-order-lifecycle-state-machine.md) |
| PSA-ARCH-10 | Risk and Emergency Control | CURRENT | [source](sources/10-risk-and-emergency-control.mmd) | [view](views/10-risk-and-emergency-control.md) |
| PSA-ARCH-11 | Reconciliation and Recovery | CURRENT | [source](sources/11-reconciliation-and-recovery.mmd) | [view](views/11-reconciliation-and-recovery.md) |
| PSA-ARCH-12 | Runtime Modes and Promotion | MIXED | [source](sources/12-runtime-modes-and-promotion.mmd) | [view](views/12-runtime-modes-and-promotion.md) |
| PSA-ARCH-13 | Current Deployment View | CURRENT | [source](sources/13-current-deployment-view.mmd) | [view](views/13-current-deployment-view.md) |
| PSA-ARCH-14 | Target Deployment View | TARGET | [source](sources/14-target-deployment-view.mmd) | [view](views/14-target-deployment-view.md) |
| PSA-ARCH-15 | Trust Boundaries | MIXED | [source](sources/15-trust-boundaries.mmd) | [view](views/15-trust-boundaries.md) |
| PSA-ARCH-16 | Module Dependency Map | CURRENT | [source](sources/16-module-dependency-map.mmd) | [view](views/16-module-dependency-map.md) |
| PSA-ARCH-17 | Adapter Extension Model | MIXED | [source](sources/17-adapter-extension-model.mmd) | [view](views/17-adapter-extension-model.md) |
| PSA-ARCH-18 | Capability Roadmap | MIXED | [source](sources/18-capability-roadmap.mmd) | [view](views/18-capability-roadmap.md) |

## Reading order

Owners should read 01, 02, 03, 06, 10, 12, and 18. Developers should add 05,
07, 08, 09, 11, 16, and 17. Operations and reviewers should add 13, 14, and 15.

## Known baseline contradictions

- OMS and transaction management in the conceptual flow are TARGET, not a
  current package.
- Application ports exist, while application services are presently empty.
- Current runtime enum values are DATA_ONLY, PAPER, and LIVE; shadow is a
  workflow.
- The later Phase I OSV audit result supersedes the stale pending-audit text in
  `before-after.md`.
