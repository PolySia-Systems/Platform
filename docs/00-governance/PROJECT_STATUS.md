# PolySia Project Status

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-11 |
| Source-of-truth branch | `main` |
| Stabilized main baseline | `b641e14cdb371d8e3ae4e1d700ca4c76cf93d622` |
| Remote baseline | `origin/main` at the same commit |
| Status authoring branch | `codex/first-evidence-sprint-docs` |
| Repository | `https://github.com/Movafeghm/polysia.git` |

The stabilized baseline is the `main` commit immediately before this
documentation-only update. The enclosing status/handoff merge commit is
discoverable from Git history and cannot self-reference its future hash. Local
`main` and `origin/main` were synchronized at the recorded baseline. Two
pre-existing untracked architecture prompt inputs remain preserved and
unchanged.

## Completed stages

- Phases A-I completed the verified baseline, governance, canonical `polysia`
  identity, venue-neutral boundaries, Polymarket adapter consolidation, module
  decomposition, quality/supply-chain controls, controlled validation, and
  delivery verification.
- The approved architecture pack contains 18 Mermaid sources, paired Markdown
  views, validated SVGs, design tokens, traceability, and design handoff
  specifications. Repository sources remain authoritative.
- `AGENTS.md` version 1.1 is active on `main`.
- Pull Request #8 added this project-status source of truth and was
  squash-merged as `c81d79cde1c92c832c493564ef4cccf44e278a61`.
- The six Dependabot PRs opened for this stabilization were reviewed
  independently. Three isolated GitHub Actions updates were merged one at a
  time; three Python dependency updates remain held.

## Current architecture and runtime capabilities

- One Python modular monolith with a Typer CLI, venue-neutral domain models and
  application ports, and Polymarket as the first adapter.
- Canonical public/stream market events, Decimal order book and features,
  `StalePriceStrategy`, and `PassiveMarketMakerStrategy`.
- CURRENT executable intent path: Strategy -> independent Risk -> Execution ->
  Polymarket Adapter. Strategies do not call venues.
- DATA_ONLY, PAPER, and gated LIVE modes; Shadow is a workflow. Paper execution,
  positions/P&L, SQLite repositories, reconciliation/safety pause, monitoring,
  backtesting, evaluation, packaging, secret scanning, auditing, and SBOM
  generation are implemented.
- The Strategy Registry/Orchestrator, conflict resolver, generalized portfolio
  allocator, OMS/Transaction Manager, execution router, adapter registry,
  generalized ledger, operator console, and stronger deployment boundaries are
  TARGET, not CURRENT.

## Dependency disposition

| PR | Dependency | Change | Type | Disposition | Verified reason |
|---|---|---|---|---|---|
| #2 | `actions/upload-artifact` | 4 -> 7 | direct production, major | MERGED | One workflow line; updated branch CI passed; current upload behavior remained compatible. Squash commit `b641e14cdb371d8e3ae4e1d700ca4c76cf93d622`. |
| #3 | `mypy` | 2.1.0 -> 2.2.0 | direct development, minor | HOLD | CI passed, but only `pyproject.toml` changes while `locks/pip-win-64.lock` remains at 2.1.0. Reproducibility evidence is incomplete. |
| #4 | `actions/setup-python` | 5 -> 6 | direct production, major | MERGED | Node 24/runner migration exercised successfully on hosted Windows CI for Python 3.11/3.13. Squash commit `530a9d2becaea4312ed831e1d5b289cd8d61fb3f`. |
| #5 | `polymarket-client` | 0.1.0b11 -> 0.1.0b18 | direct production, prerelease | HOLD | Lock remains b11; Python 3.11/3.13 quality failed the approved SDK-pin contract (350 passed, 1 failed); adapter, signing, execution, cancellation, streaming, and reconciliation compatibility is unproven. |
| #6 | `actions/checkout` | 4 -> 7 | direct production, major | MERGED | Two isolated workflow lines; Node 24 action completed successfully in updated PR and post-merge CI. Squash commit `efe3a185ea4705a968fd2d90bd3cb059c7aece1a`. |
| #7 | `ruff` | 0.15.20 -> 0.15.21 | direct development, patch | HOLD | CI passed, but only `pyproject.toml` changes while `locks/pip-win-64.lock` remains at 0.15.20. Reproducibility evidence is incomplete. |

Current approved versions are `polymarket-client==0.1.0b11`, `mypy==2.1.0`,
`ruff==0.15.20`, `actions/setup-python@v6`, `actions/checkout@v7`, and
`actions/upload-artifact@v7`.

## Validation and CI

- GitHub Actions run `29158912577` passed on stabilized `main`: quality on
  Python 3.11 and 3.13 plus strict OSV supply-chain audit/SBOM upload.
- Local `PolySia` environment uses Python 3.13.14. Compile, Ruff, Mypy over 105
  source files, all 351 Pytest tests, `pip check`, secret scan, and source/wheel
  build passed.
- The full suite includes architecture, contract, integration, property, and
  migration tests. No flaky or skipped test was reported.
- Exact lock verification passed for 22 Conda packages and 119 pip packages;
  the Conda-managed pip bootstrap URL is intentionally outside the pip lock.
- CycloneDX SBOM JSON parsed successfully with 121 components.
- Two local strict OSV audit attempts received HTTP 403 from the external OSV
  API. This is an environment/service failure; the same strict OSV gate passed
  in current GitHub CI. No formatter check is configured.
- No authenticated write, live order, cancellation, or other external-state
  mutation was run.

## Active work and blockers

- Active plan: `plans/active/first-evidence-sprint.md`. Implementation has not
  started.
- PRs #3 and #7 require synchronized `pyproject.toml` and Windows lock updates
  plus reproducibility validation before merge.
- PR #5 requires the full SDK compatibility program recorded in repository
  guidance and the PR hold comment. The approved b11 pin remains unchanged.
- Branch protection remains unavailable for the current private-repository plan;
  manual merge controls remain in use.
- Portable cross-platform hash locking, legacy environment/folder retirement,
  and recovered original Git/Phase 0 provenance remain open governance items.
- State-changing live validation always requires explicit authorization for the
  specific run and all existing safety gates.

## Prompt and deferred status

- Root modernization prompts and archived phase documents are provenance, not
  current operating authority.
- `POLYSIA_CODEX_ARCHITECTURE_START_FINAL.txt` and
  `POLYSIA_CODEX_ARCHITECTURE_VISUALIZATION_MASTER_PROMPT_FINAL_v1.0.md` remain
  pre-existing untracked, unchanged, and superseded as execution instructions.
- Figma, Penpot, architecture visualization expansion, UI redesign, new venue
  adapters, Web3/DeFi/copy trading, machine learning, microservices, Kubernetes,
  PostgreSQL, and production infrastructure are deferred and outside the active
  plan.

## Single next implementation task

**Implement `plans/active/first-evidence-sprint.md` as one bounded, paper-only
vertical slice.** Reuse public Polymarket BTC Up/Down 5-minute data,
normalization, `StalePriceStrategy`, independent Risk, PaperBroker,
PositionLedger, ReconciliationManager, and evaluation tooling. Add only the
minimal single-strategy portfolio admission record and daily evidence report.
Do not use live execution or implement generalized TARGET components.

## Next three milestones

1. Implement and review the bounded evidence runner with deterministic fixtures,
   complete lineage, cost/resolution handling, and all required gates.
2. Run the preregistered paper evidence period and issue the daily/final report;
   classify the result as promote, refine, reject, or inconclusive without
   retuning the baseline.
3. If and only if promotion criteria pass, approve a separate scheduled
   real-data Shadow task; otherwise perform at most two registered refinement
   cycles and archive the hypothesis if unsuccessful.
