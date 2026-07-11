# PolySia Architecture Visualization Final Handoff

## Git references

- Source baseline: `44a8ae0fbccd0de916a0621236ea5931e7c3a256`
- Architecture pack implementation: `c5ffa54cd7c6d88c22d64c92c0e4b77f7e71c1fb`
- Final handoff commit: `HEAD` (resolve after this handoff is committed)

## Objective

Create an English, repository-first C4 and Mermaid architecture visualization
system for the completed PolySia repository, plus a complete Figma/FigJam
handoff, without changing runtime behavior, dependencies, credentials, or live
controls.

## Discovery summary

PolySia is one Python modular monolith with a Typer CLI, venue-neutral domain
models, application port protocols, a consolidated Polymarket adapter,
normalized events and in-memory bus, Decimal order book, features, two research
strategies, independent risk and kill switch, paper and guarded live execution,
positions/P&L, SQLite repositories, reconciliation/safety pause, monitoring,
backtesting, and deployment tooling. Architectural tests enforce inner-layer
neutrality and official SDK confinement.

The source worktree contained two pre-existing untracked instruction files.
They were read as inputs and left unchanged/untracked.

## Diagrams created

Eighteen canonical Mermaid sources, paired Markdown views, and SVG exports:

1. System Landscape
2. C4 System Context
3. C4 Container — Current
4. C4 Container — Target
5. Current Component Map
6. Multi-Strategy Target Architecture
7. Market Data to Decision Flow
8. Signal to Execution Sequence
9. Order Lifecycle State Machine
10. Risk and Emergency Control
11. Reconciliation and Recovery
12. Runtime Modes and Promotion
13. Current Deployment View
14. Target Deployment View
15. Trust Boundaries
16. Module Dependency Map
17. Adapter Extension Model
18. Capability Roadmap

The index is `docs/04-architecture/visual-system/architecture-visualization-index.md`.

## Current-state findings

- Current deployment is one local Windows/Conda Python process with local
  SQLite/files and ignored secrets/artifacts.
- `TradingMode` contains DATA_ONLY, PAPER, and LIVE; shadow is a workflow.
- Current order states are NEW, ACCEPTED, PARTIALLY_FILLED, FILLED, CANCELLED,
  and REJECTED.
- Strategies produce pre-risk intents and do not call venues directly.
- Risk and emergency controls remain independent and authoritative.
- Application ports exist; application services are currently empty and the
  protocols are not yet universal runtime wiring.
- CI is configured but remote execution is not verified.

## Target-state findings

The approved modular-monolith evolution introduces a Strategy Registry and
Orchestrator, Intent Aggregator/Conflict Resolver, Portfolio and Capital
Allocator, OMS/Transaction Manager, generic execution routing, Adapter
Registry/Capability Discovery, generalized ledger, Operator Console, and
stronger deployment boundaries. These are labeled TARGET, not implemented.
Additional venues, wallet intelligence/copy trading, Web3/DeFi, and
institutional hardening remain FUTURE.

## Assumptions

- The modular monolith remains the default until measured needs justify a new ADR.
- Strategies receive read-only context and only emit pre-risk intents.
- Future venue capability profiles remain explicit rather than forcing a
  lowest-common-denominator core.
- Future deployment selection requires a separate RFC/ADR and measured targets.

## Contradictions resolved

- Conceptual OMS/Transaction Manager language is shown as TARGET, not current.
- Current application ports are distinguished from the empty application
  services layer.
- SHADOW is shown as a workflow, not an enum value.
- Target lifecycle extensions are separated from the six current order states.
- The successful Phase I OSV audit supersedes older pending-audit text.
- Configured CI is not presented as remotely verified.

## Files created or modified

- 45 architecture documentation/source files in the architecture-pack commit.
- 18 validated SVG exports under `docs/04-architecture/visual-system/rendered/`.
- 2 final handoff files under `docs/18-ai-handoffs/`.
- Runtime source, project dependencies, environment files, credentials, and
  execution configuration: unchanged.

## Validation commands and results

- `git rev-parse HEAD`, `git status --short`, and repository/path inventories:
  baseline recorded; no unresolved conflicts.
- Design-token JSON parsed with PowerShell `ConvertFrom-Json`: passed.
- Mermaid source headers, legends, required view sections, paired source/view
  equality, local links, and repository-path references: 18/18 passed.
- `npx @mermaid-js/mermaid-cli --version`: Mermaid CLI 11.16.0 available through
  temporary Node cache; no PolySia dependency change.
- Mermaid CLI render with existing system Chrome: 18/18 parsed and rendered.
- SVG structural checks and visual contact-sheet inspection: 18/18 non-empty;
  no clipping or empty diagram found.
- `python -m polysia.security.secret_scan`: passed.
- `pytest -q tests/architecture/test_boundaries.py tests/architecture/test_module_decomposition.py`:
  6 passed. The full Python suite was correctly not rerun.
- `git diff --check`: passed.

## Mermaid renderer status

Complete. Mermaid CLI 11.16.0 parsed all sources and produced SVG derivatives.
The Mermaid `.mmd` files remain canonical.

## Figma handoff status

Complete. The handoff defines pages, reusable components, semantic tokens,
frame metadata, transfer order, and review checks. Validated SVGs are ready for
import. No Figma file was created or treated as a source of truth.

## Known limitations

- Dense component, multi-strategy, and sequence views require individual SVG
  viewing at normal zoom; the contact sheet is only a QA overview.
- Target components have no implementation paths or delivery dates.
- The pack is an architecture visualization system, not a complete threat
  model, infrastructure RFC, or production-readiness approval.
- The pre-existing untracked prompt files remain outside the documentation commits.

## Recommended reviewer focus

1. CURRENT/TARGET/FUTURE separation.
2. Multi-strategy non-bypass path through allocation, risk, OMS, and execution.
3. Current order-state accuracy and target extension separation.
4. Independent risk, kill switch, geoblock, reconciliation pause, and operator gates.
5. Conservative current/target deployment and trust-boundary claims.

## Exact next step

Review and approve the repository index and the multi-strategy, risk/emergency,
current-container, trust-boundary, and roadmap views. After approval, import the
matching SVGs into Figma/FigJam using `figma-handoff-spec.md`, rebuild only the
high-value presentation frames, and record the final repository commit in every
Figma frame.
