# Diagram Conventions

## Naming and metadata

- Diagram IDs are `PSA-ARCH-01` through `PSA-ARCH-18`.
- Titles use plain business language; technical names appear as secondary labels.
- Every view records the source commit, status, paths, tests, ADRs, capabilities,
  assumptions, limitations, and review trigger.
- C4 terms mean Person, Software System, Container, and Component. Containers in
  this pack are logical runtime boundaries, not separately deployed services.

## Mermaid rules

- Mermaid `.mmd` files are canonical.
- Node IDs are stable, short, and independent of display text.
- Labels include `[CURRENT]`, `[TARGET]`, `[FUTURE]`, or `[EXTERNAL]` when a
  diagram mixes states.
- Current implementation claims cite repository paths in the paired view.
- Target and future nodes never cite nonexistent implementation paths.
- Secrets, wallet identifiers, token identifiers, balances, and account data are
  prohibited.

## Reusable class palette

Diagrams use consistent Mermaid classes: `current`, `target`, `future`,
`external`, `domain`, `application`, `strategy`, `portfolio`, `risk`,
`execution`, `adapter`, `data`, `storage`, `observability`, `safe`, and `danger`.

## Compact legend pattern

Every source includes a `Legend` subgraph or legend nodes. Solid means CURRENT,
dashed means TARGET, dotted means FUTURE, gray means EXTERNAL, amber means
SAFETY, red means BLOCK/EMERGENCY, and green means APPROVED/HEALTHY.

## Accuracy rules

- No direct Strategy to Venue arrow is allowed.
- `SHADOW` is a current workflow, not a `TradingMode` enum value.
- The current order state machine uses only code-defined states; extensions are
  separated as TARGET.
- Current deployment views distinguish the owner workstation, the last verified
  controlled single-host deployment revision, and newer repository-only work.
- GitHub CI is remotely verified at the audited repository baseline; it supports
  Python 3.14 only and selects heavier jobs by changed-path scope.
