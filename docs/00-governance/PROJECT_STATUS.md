# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-11 |
| Source-of-truth branch | `main` |
| Source-of-truth Git HEAD | `0baa804e2a1407b47d019ca5430cc60da7e44277` |
| Remote baseline | `origin/main` at the same commit |
| Authoring branch | `codex/add-project-status`, created from the source-of-truth HEAD |
| Repository | `https://github.com/Movafeghm/polysia.git` |

At discovery, local `main` and `origin/main` were synchronized. The working tree
contained exactly two pre-existing untracked architecture prompt inputs, listed
under **Prompt status** below. They were not modified.

## Completed project stages

- Phase A established the verified migration baseline and immutable baseline
  audit evidence.
- Phases B-I completed governance, canonical `polysia` naming, venue-neutral
  domain and application ports, Polymarket adapter consolidation, targeted
  module decomposition, quality and supply-chain controls, controlled realistic
  validation, and final migration/delivery verification.
- PolySia is the canonical distribution, Python namespace, CLI, and operator
  identity. The previous Polymarket project remains retained for recovery.
- The architecture visualization stage produced 18 canonical Mermaid sources,
  18 paired Markdown views, 18 validated SVGs, design tokens, traceability, and
  a Figma/FigJam handoff specification. Repository Mermaid and Markdown remain
  authoritative.
- Root repository operating guidance is active through `AGENTS.md` version 1.1.
- GitHub `main` is established, Pull Request #1 was squash-merged, and CI has
  been observed successfully on the current `main` HEAD.

## Current architecture and runtime capabilities

- One deployable Python modular monolith with a Typer CLI.
- Venue-neutral domain models and application port protocols.
- A consolidated Polymarket adapter containing public, authenticated-read,
  stream, mapping, geoblock, capability, and guarded execution concerns; the
  official SDK is confined to the adapter boundary.
- Normalized market events, an in-memory event bus, a Decimal order book,
  microstructure features, `StalePriceStrategy`, and
  `PassiveMarketMakerStrategy`.
- The CURRENT execution path is Strategy -> independent Risk -> Execution ->
  Polymarket Adapter. Strategies do not call the venue directly.
- Independent risk checks, kill switch, geoblock, allowlist, hard caps,
  acknowledgement, one-attempt controls, and reconciliation safety pause.
- DATA_ONLY, PAPER, and gated LIVE runtime modes. Shadow is a workflow, not a
  `TradingMode` enum value.
- Conservative paper execution, guarded live tooling, positions/P&L, SQLite
  repositories, reconciliation, monitoring, backtesting, readiness, reporting,
  packaging, handoff, secret scanning, dependency auditing, and SBOM tooling.
- Current deployment remains a local Windows/Conda Python process with local
  SQLite/files. No cloud, VPS, container, HA, or microservice deployment is
  claimed as current.

The Strategy Registry/Orchestrator, Intent Aggregator/Conflict Resolver,
Portfolio and Capital Allocator, OMS/Transaction Manager, generic execution
router, Adapter Registry, generalized ledger, Operator Console, and stronger
deployment boundaries remain TARGET architecture, not implemented current
capabilities.

## Active or unfinished work

- Six Dependabot pull requests are open against `main`:
  - #2 updates `actions/upload-artifact` 4 -> 7; CI passed.
  - #3 updates `mypy` 2.1.0 -> 2.2.0; CI passed.
  - #4 updates `actions/setup-python` 5 -> 6; CI passed.
  - #5 updates `polymarket-client` 0.1.0b11 -> 0.1.0b18; quality jobs failed on
    Python 3.11 and 3.13, while supply-chain jobs passed.
  - #6 updates `actions/checkout` 4 -> 7; CI passed.
  - #7 updates `ruff` 0.15.20 -> 0.15.21; CI passed.
- The old `polymarket` Conda environment and preserved `Polymarket Python SDK`
  folder remain intentionally retained pending owner-reviewed cleanup and
  external-consumer confirmation.
- Open technical debt includes concentrated CLI wiring (TD-001), remaining
  oversized monitoring/live modules (TD-004), no portable cross-platform
  hash-locked dependency resolution (TD-005), and no formal environment-alias
  deprecation schedule (TD-007).
- The reconstructed Phase 0 record remains an open, non-blocking replacement
  target if the original record is recovered (ISS-001). The unavailable original
  Git history remains an accepted limitation (ISS-002).

## Test and CI status

- Phase I records: compile passed; secret scan passed; Ruff passed; Mypy passed
  for 105 source files; the full Pytest suite passed with 351 tests collected;
  `pip check`, source/wheel build, isolated wheel import/version/35-command
  smoke, strict OSV audit, and CycloneDX SBOM generation passed.
- Authenticated read-only, deterministic paper, local shadow, and public
  real-data paper-shadow validation passed. No state-changing live-network
  validation was authorized or executed.
- All changes from the Phase I baseline commit
  `44a8ae0fbccd0de916a0621236ea5931e7c3a256` through the current `main` HEAD are
  documentation, diagrams, SVG exports, handoffs, and `AGENTS.md`; runtime code,
  tests, dependencies, and executable configuration did not change.
- GitHub Actions CI completed successfully on current `main` HEAD
  `0baa804e2a1407b47d019ca5430cc60da7e44277` for quality on Python 3.11 and
  3.13 and for the supply-chain job.
- Dependency-update CI is not uniformly green because Dependabot PR #5 fails
  quality checks.

## Blockers and open decisions

- There is no blocker to the verified DATA_ONLY, paper, shadow, packaging, or
  read-only operational workflows.
- Any state-changing live-network test remains blocked until explicit owner
  authorization for that exact run and all existing safety gates are satisfied.
- The Polymarket SDK remains pinned at `0.1.0b11`. The proposed b18 update is not
  compatible with current quality gates and must not be merged without diagnosis,
  contract tests, and rollback evidence.
- Branch protection is not available for the current private repository under
  the current GitHub plan; the GitHub API returned HTTP 403 with an upgrade-or-
  public-repository requirement. The owner must decide whether to upgrade the
  plan, make the repository public, or retain manual merge controls.
- A portable cross-platform hash lock remains required before a cross-platform
  release claim.
- Deletion of the retained legacy folder/environment requires an owner-reviewed
  cleanup decision and external-consumer confirmation.
- TARGET architecture components have no approved implementation paths or
  delivery dates. Their implementation requires scoped RFC/ADR and requirement
  approval.

## Prompt status

- `prompts/POLYSIA_CODEX_START_FINAL.txt` and
  `prompts/POLYSIA_CODEX_MASTER_PROMPT_FINAL_v1.1.md` are retained execution
  inputs for the completed modernization. They are provenance, not current
  repository operating guidance; `AGENTS.md`, controlled governance documents,
  current code/tests, and this status file now govern new tasks.
- `POLYSIA_CODEX_ARCHITECTURE_START_FINAL.txt` and
  `POLYSIA_CODEX_ARCHITECTURE_VISUALIZATION_MASTER_PROMPT_FINAL_v1.0.md` are
  pre-existing untracked inputs for the completed architecture visualization
  stage. The architecture handoff records that they were intentionally left
  untracked. They are superseded as execution instructions by the completed
  architecture pack and should remain untouched until the owner chooses to
  archive or remove them.
- Historical phase prompts and status documents under
  `docs/99-archive/legacy-phase-docs/` are archived evidence, not current
  authority.
- No `prompts/active/` or `prompts/archive/` directory currently exists.

## Single recommended next task

**Dependabot update triage for Pull Requests #2-#7.**

Review each open dependency PR independently against current `main`. Merge only
low-risk, isolated updates whose diffs are appropriate and whose required checks
remain green. Diagnose PR #5's Python 3.11/3.13 quality failures, but preserve
`polymarket-client==0.1.0b11` and do not merge, repin, or alter live behavior
unless SDK compatibility is proven by focused contract, architecture, adapter,
and regression tests with a documented rollback. Do not bulk-merge the queue.
Update this status document with each final PR disposition.

## Next three high-level milestones

1. **Dependency and repository governance hardening:** complete the Dependabot
   triage, decide the branch-protection approach, add portable dependency locking,
   and make the owner-reviewed legacy-retention decision.
2. **Target architecture definition:** approve scoped RFCs/ADRs and requirements
   for strategy orchestration, intent conflict resolution, capital allocation,
   OMS/transaction management, generalized ledger, and operator control while
   preserving the modular monolith and independent risk authority.
3. **Controlled target vertical slice:** implement the first approved
   multi-strategy orchestration slice with characterization, architecture,
   property, integration, reconciliation, and rollback evidence before any
   adapter expansion or live-capital promotion.
