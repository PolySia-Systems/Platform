# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-12 |
| Source-of-truth branch | `main` |
| Runtime baseline | `ce24c848f73aa8c4b73beac3649fa483f3a97c86` |
| Remote baseline | `origin/main` at the same commit |
| Status authoring branch | `codex/live-001-handoff` |
| Repository | `https://github.com/Movafeghm/polysia.git` |
| Completed task | `POLYSIA-LIVE-001` |

The runtime baseline is the squash merge immediately before this
documentation-only update. The future documentation merge commit cannot
self-reference and remains discoverable from Git history. Two pre-existing
untracked architecture prompt inputs remain preserved and unchanged.

## Completed stages

- Phases A-I completed the verified baseline, governance, canonical `polysia`
  identity, venue-neutral boundaries, Polymarket adapter consolidation, module
  decomposition, quality and supply-chain controls, controlled validation, and
  delivery verification.
- The approved architecture pack, root `AGENTS.md` version 1.1, project-status
  source of truth, and accelerated-stabilization handoff remain current.
- Pull Request #10 implemented `POLYSIA-LIVE-001` and was independently
  reviewed, passed CI, and squash-merged as
  `ce24c848f73aa8c4b73beac3649fa483f3a97c86`.
- A minimal venue-neutral Strategy Registry is CURRENT. It stores versioned
  definitions, lifecycle state, run evidence, and explicitly unrated
  performance summaries in SQLite.
- `btc-15m-favorite-take-profit@0.1.0` is registered as `experimental`, with
  risk class `bounded-micro-live` and score `unrated`.
- The former StalePrice Paper Sprint is deferred, not rejected. Its plan is
  marked `SUPERSEDED BY POLYSIA-LIVE-001` rather than deleted.
- The one-time merged-code preflight completed as `NO_TRADE`. No live entry,
  exit, cancellation, transfer, retry, or external-state mutation occurred.

## Current architecture and runtime capabilities

- One Python modular monolith with a Typer CLI, venue-neutral domain models and
  application ports, and Polymarket as the first venue adapter.
- CURRENT executable intent path: Strategy -> independent Risk -> Execution ->
  Polymarket Adapter. Strategies cannot call venue, wallet, SDK, or execution
  clients directly.
- The minimal Strategy Registry, dynamic BTC Up/Down 15-minute discovery,
  canonical two-outcome order books, bounded portfolio admission, independent
  Risk gate, persistent one-entry authorization claim, and durable live-order
  checkpoints are implemented.
- The bounded runner supports one FOK entry attempt and, only after a confirmed
  fill and position reconciliation, one GTC exit at tick-normalized actual
  weighted-average fill price times `1.10`.
- Orders, fills, positions, fees, strategy runs, bounded ledger events, and
  reconciliation evidence have additive SQLite persistence and deterministic
  coverage, including partial exits and crash/restart duplicate prevention.
- DATA_ONLY, PAPER, gated LIVE, and Shadow workflows remain available. Existing
  strategies and runtime commands were preserved.
- A generalized multi-strategy orchestrator, conflict resolver, capital
  allocator, OMS/Transaction Manager, execution router, adapter registry,
  generalized ledger, and automatic post-fill recovery remain TARGET, not
  CURRENT.

## Validation and review

- Local `PolySia` validation passed: compile, Ruff, Mypy over 113 source files,
  all 418 Pytest tests, `pip check`, secret scan, and source/wheel build.
- The final implementation head
  `f4ab8ccef41c68cb76cf499f7b96fe9f8c0f2c4f` passed all six PR checks: quality
  on Python 3.11 and 3.13 plus strict OSV/SBOM supply-chain checks for both PR
  event runs.
- Independent re-review passed with no blocking findings. The reviewer ran 69
  relevant tests plus Ruff, Mypy, and diff checks.
- Exact Windows environment lock verification remains 22/22 Conda entries and
  119/119 comparable pip entries. The approved SDK remains
  `polymarket-client==0.1.0b11`; no dependency changed in this task.
- A later local strict OSV recheck could not reach the OSV feed. The same strict
  gate passed twice in CI for the final implementation head; this is recorded
  as a local external-service limitation, not a product defect.
- Post-merge `main` CI run `29182788976` passed for the runtime merge: quality
  on Python 3.11 and 3.13 plus strict OSV audit and SBOM generation.

## Read-only live preflight result

- Merged-code run ID: `aa060a47-03ed-449b-8001-5ec1f8209327`.
- Source commit: `ce24c848f73aa8c4b73beac3649fa483f3a97c86` on synchronized `main`.
- Authenticated API connectivity, configured identity consistency, balance,
  allowance, open-order state, position state, and geoblock were readable.
  Confidential account values remain only in ignored local evidence.
- The geoblock endpoint returned allowed for the actual run.
- Public market inspected: `btc-updown-15m-1783837800`, active and accepting
  orders at the read time. No outcome was selected for execution.
- Stop reason: `venue minimum order size cannot be satisfied within the 1.00
  cap`.
- Strategy result: `NO_TRADE`; portfolio and Risk were not approved because no
  executable intent was produced.
- Live entry attempts: zero. Entry order: none. Exit order: none. Actual task
  fees: zero. Task-created position or exposure: none.
- Pre-existing account positions were observed but not identified, changed, or
  included in committed documentation. No open order was observed.
- Reconciliation was not entered because the strategy stopped before an intent
  or authorization claim. The database contains one StrategyRun, zero live
  checkpoints, zero run ledger events, and zero `POLYSIA-LIVE-001` claims.
- Local ignored evidence:
  `release-artifacts/tiny-live-round-trip/aa060a47-03ed-449b-8001-5ec1f8209327/`.
  JSON SHA-256:
  `74906A604BDE601E2BEDD9513794894DA8416C1FE7483A00C14535B71534EB0C`.
  Markdown SHA-256:
  `EF84476AB77BE160FE5225E27A27B16DED913475FC55051C5CCD6EC92E9B531C`.

## Dependency disposition

- PR #3 (`mypy` 2.2.0) remains HOLD pending synchronized lock updates and
  reproducibility validation.
- PR #5 (`polymarket-client` 0.1.0b18) remains HOLD because the approved SDK-pin
  contract fails and compatibility evidence is incomplete.
- PR #7 (`ruff` 0.15.21) remains HOLD pending synchronized lock updates and
  reproducibility validation.
- Approved versions remain `polymarket-client==0.1.0b11`, `mypy==2.1.0`, and
  `ruff==0.15.20`.

## Active work, blockers, and open decisions

- `POLYSIA-LIVE-001` is complete as an honest pre-entry `NO_TRADE`; its owner
  authorization is not reused. Raising the `1.00` cap or making another live
  attempt requires a new explicit owner decision and a new task.
- Current Polymarket minimum order size and the authorized cap are incompatible
  for the inspected market. The cap must not be weakened to force a trade.
- Restart handling is fail-closed and prevents duplicate entry, but a crash
  after confirmed fill does not automatically resume or place a missing exit.
  Explicit recovery and operator reconciliation are required before broader
  limited-live reuse.
- Three dependency PRs remain on HOLD as recorded above. Branch protection,
  portable cross-platform hash locking, and legacy environment/folder
  retirement remain governance debt.
- The two untracked architecture prompt files are provenance inputs,
  superseded as execution instructions, and remain untouched.

## Single recommended next task

**Implement and independently review a fail-closed post-fill recovery and
operator-reconciliation slice for the bounded round-trip runner.** It must load
durable checkpoints and actual read-only account state, detect an interrupted
entry or exit, produce a deterministic operator action plan, and prevent every
duplicate entry or automatic replacement order. Validate with deterministic
crash/restart, partial-fill, and authenticated read-only tests only. Do not
perform another live attempt, change the `1.00` cap, upgrade the SDK, or add
generalized orchestration.

## Next three milestones

1. Add checkpoint-driven post-fill recovery classification, reconciliation,
   operator-safe reporting, and deterministic tests without external mutation.
2. Run a paper/shadow feasibility study for current 15-minute venue minimums,
   liquidity, fees, and the fixed cap; keep the strategy experimental and
   unrated.
3. Present the recovery evidence and feasibility result for an explicit owner
   decision on whether a separately authorized limited-live task is justified.
