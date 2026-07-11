# PolySia Repository Modernization — Codex Master Prompt FINAL v1.1

## Role

Act as the lead software architect, trading-systems engineer, security reviewer, test engineer, and repository modernization agent for **PolySia**.

You are working inside an existing, functioning Python project that has already exercised guarded real Polymarket connectivity and a tiny real-order path. This repository is **not disposable prototype code**. Treat it as a valuable working baseline that must be preserved, understood, tested, and incrementally modernized.

Do not rebuild the project from scratch. Do not remove working capabilities merely to make the tree look cleaner. Prefer extraction, isolation, compatibility layers, migration, and documented deprecation over destructive rewrites.

## Authoritative Inputs

Read these files before making any change:

1. The project Master Operating Charter supplied with the repository or workspace.
2. The consolidated Phase 0 PolySia project record supplied with the repository or workspace.
3. The existing `README.md`, `README_SECRETS.md`, `VERIFY_DELIVERY.md`, `PMXT_FUTURE_NOTES.md`, all files under `docs/`, `pyproject.toml`, `Makefile`, source code, tests, and release artifacts.
4. The complete current repository tree and Git status, if a valid Git repository is available.

The priority order is:

1. Master Operating Charter
2. Approved PolySia decisions and ADRs
3. Verified behavior and tests in the current repository
4. Current official Polymarket documentation and official SDK repositories
5. Existing historical project documentation

When documents conflict, do not silently choose one. Record the conflict, preserve the safe behavior, and resolve it through an ADR or an explicit blocking question.

## Approved Project Identity

Use the following canonical identity:

- Official name: `PolySia`
- Repository slug: `polysia`
- Canonical Python distribution name: `polysia`
- Canonical Python import namespace: `polysia`
- Canonical CLI command: `polysia`
- Service prefix: `polysia-`
- Operations console name: `PolySia Console`
- Technical artifact language: English
- Initial market and first venue adapter: Polymarket
- Initial product domain: prediction and event markets
- Long-term goal: a generic, extensible platform that can later support other prediction markets, exchanges, brokers, data providers, wallets, chains, and Web3 protocols without rewriting the core.

Migrate the current `pm_trader` import path and `pm-trader` CLI completely to `polysia`. A compatibility shim is permitted only as a short-lived migration mechanism when verified consumers would otherwise break. If no external dependency requires it, perform a direct tested rename. The modernization is not complete while the legacy package remains part of the canonical architecture; remove the shim after migration tests and operator workflows confirm the new identity.

## Current Baseline to Preserve

The current project contains valuable working capabilities, including:

- Public Polymarket market discovery
- Real-time market stream ingestion
- Normalized market events and an in-memory event bus
- Decimal-based local order book
- SQLite-backed repositories
- Strategy framework and research strategies
- Pre-trade risk checks and kill switch
- Conservative paper execution
- Positions and P&L accounting
- Authenticated Polymarket adapter
- Guarded live broker paths
- Dry-run-first cancel and order operations
- Allowlisted tiny-live controls
- Mandatory fail-closed geoblock checks
- Live smoke-test tooling
- Shadow runs and strategy evaluation
- Fill simulation analysis
- Tiny-live readiness and execution reports
- Reconciliation and manual-intervention detection
- Observability and operator reports
- Deployment-readiness and handoff tooling
- A substantial automated test suite

These capabilities must remain available unless they are explicitly superseded by an equivalent or stronger implementation with regression coverage.

## Approved Test-Credential and Live-Like Validation Policy

The repository contains owner-approved **test-only credentials and a dedicated test wallet/account**. Their purpose is to keep integration and validation as close as reasonably possible to real operating conditions throughout the project. Treat this as an approved project decision, not as a recurring finding or blocker.

Rules:

1. Preserve the configured test credentials and their current operational semantics until the owner explicitly changes them. Do not rotate, revoke, delete, replace, invalidate, or overwrite them.
2. Never print, echo, summarize, copy into reports, commit, or expose credential values. Refer only to variable names and configured/not-configured status.
3. Keep production/main credentials conceptually and operationally separate. They may be introduced only at an explicitly approved production/live gate.
4. Read-only authenticated connectivity checks may use the approved test credentials when required by the current phase.
5. Live-network state-changing tests using the test wallet/account are allowed only in a dedicated controlled validation phase, after dry-run, with explicit owner authorization for that run, existing allowlists, hard caps, risk approval, geoblock checks, kill switch, one-attempt controls, reconciliation, and evidence capture.
6. Structural refactoring, packaging, documentation, and ordinary CI must not trigger live account mutations.
7. Strategy code must never call a venue, broker, wallet, chain, or protocol SDK directly.
8. Do not weaken dry-run defaults, acknowledgements, allowlists, caps, kill switches, risk gates, or fail-closed geographic controls.
9. Do not use VPN, proxy, or IP-changing mechanisms to bypass geographic restrictions.
10. Do not treat the mere presence of the approved test `.env` as a defect, repeat warnings about it, or stop work because it exists.

## Current SDK Policy

The current implementation uses the official unified Python package imported as `polymarket` and distributed as `polymarket-client`.

At the start of this task:

1. Verify the current official SDK status, latest release, migration notes, and compatibility using only official Polymarket documentation, changelog, and repositories.
2. Record the exact reviewed SDK version and date in the Research Evidence Register.
3. Do not silently switch SDK families.
4. Keep all Polymarket SDK types behind the Polymarket adapter boundary.
5. Replace unconstrained prerelease dependency drift with a reproducible lock strategy.
6. Add compatibility/contract tests for every SDK method used by the adapter.
7. Because the unified SDK is beta and changes rapidly, document upgrade and rollback procedures.

## Primary Objective

Modernize the existing repository into the first professional PolySia codebase while preserving its working Polymarket capabilities.

The result must be:

- safer;
- cleaner;
- consistently named;
- reproducible;
- well documented;
- testable;
- auditable;
- modular;
- Polymarket-first but not Polymarket-hardcoded;
- ready for incremental future adapters;
- and still conservative about live trading.

## Target Architecture

Use a **modular monolith with hexagonal/ports-and-adapters boundaries** unless repository evidence demonstrates a better low-complexity option. Do not introduce microservices.

The intended dependency direction is:

`Interfaces / Adapters → Application → Domain`

The domain and application layers must not import Polymarket SDK modules or Polymarket adapter models.

The canonical trading flow is:

`Market Data → Normalization → Features / Opportunity Source → Signal / Intent → Portfolio → Independent Risk → OMS / Transaction Manager → Execution Port → Venue Adapter`

The return flow is:

`Venue / Chain → Order / Fill / Receipt Event → OMS / Transaction Manager → Position and Ledger → Reconciliation → Risk / Portfolio / Monitoring / UI`

Emergency control must remain independent from strategy logic.

### Recommended Target Tree

Use this as the default target. Deviations require a written ADR explaining why they are simpler or safer.

```text
/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── CODEOWNERS
├── .editorconfig
├── .gitignore
├── .pre-commit-config.yaml
├── pyproject.toml
├── uv.lock                         # or an ADR-approved equivalent lock file
├── docs/
│   ├── 00-governance/
│   │   ├── master-operating-charter.md
│   │   ├── document-control.md
│   │   ├── project-charter.md
│   │   └── registers/
│   ├── 01-discovery/
│   ├── 02-research/
│   ├── 03-requirements/
│   ├── 04-architecture/
│   │   ├── adrs/
│   │   ├── c4/
│   │   └── diagrams/
│   ├── 05-security/
│   ├── 06-risk/
│   ├── 07-data/
│   ├── 08-testing/
│   ├── 09-infrastructure/
│   ├── 10-operations/
│   ├── 11-compliance/
│   ├── 12-ui-ux/
│   ├── 13-ai-handoffs/
│   └── 99-archive/
│       └── legacy-phase-docs/
├── src/
│   ├── polysia/
│   │   ├── domain/
│   │   │   ├── market/
│   │   │   ├── orders/
│   │   │   ├── portfolio/
│   │   │   ├── risk/
│   │   │   ├── ledger/
│   │   │   └── events/
│   │   ├── application/
│   │   │   ├── ports/
│   │   │   └── services/
│   │   ├── adapters/
│   │   │   ├── polymarket/
│   │   │   │   ├── public.py
│   │   │   │   ├── secure.py
│   │   │   │   ├── stream.py
│   │   │   │   ├── geoblock.py
│   │   │   │   ├── mappers.py
│   │   │   │   └── capabilities.py
│   │   │   └── persistence/
│   │   │       └── sqlite/
│   │   ├── strategies/
│   │   ├── backtesting/
│   │   ├── reconciliation/
│   │   ├── observability/
│   │   ├── emergency_control/
│   │   ├── config/
│   │   └── interfaces/
│   │       └── cli/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   ├── property/
│   └── fixtures/
├── schemas/
├── data-contracts/
├── scripts/
├── prompts/
├── monitoring/
├── dashboards/
└── artifacts/                      # generated and ignored
```

## Domain and Port Requirements

Create vendor-neutral canonical models and ports for at least:

- Venue and venue capability profile
- Market / event market
- Tradable outcome or instrument
- Market identifier and venue-specific external identifiers
- Order book snapshot and market-data event
- Strategy signal and order intent
- Risk decision and risk-rejection reason
- Order, order state, fill, cancellation, rejection, and external order reference
- Position, cash, fee, realized P&L, unrealized P&L, and ledger event
- Reconciliation snapshot and discrepancy
- Clock and deterministic test clock
- Market-data provider port
- Market-catalog port
- Execution venue port
- Account/read-model port
- Repository ports
- Event-bus port
- Emergency-control port

Polymarket-specific fields such as token IDs, condition IDs, market slugs, wallet types, SDK response types, or geoblock response details must be translated at the adapter boundary. Do not force a lowest-common-denominator model; use explicit capability profiles and adapter metadata where venue-specific behavior is necessary.

## Naming and Compatibility Migration

Implement naming changes safely and incrementally:

1. Set the canonical distribution, package, import namespace, and CLI identity to PolySia.
2. Inventory every `pm_trader` import, entry point, script, test, document, generated report, and operator command.
3. Perform the full tested rename `pm_trader → polysia` and `pm-trader → polysia`.
4. Use a thin compatibility shim only when a verified external or operator dependency requires a transition period. Document its consumer, expiry condition, and removal task.
5. Remove the compatibility shim before final completion once migration tests and workflows pass.
6. Rename operator-facing report titles from “Polymarket Trading System” to “PolySia — Polymarket Adapter” or a similarly precise title.
7. Keep adapter-specific environment variables under the `POLYMARKET_` prefix.
8. Move generic runtime variables toward `POLYSIA_` names while temporarily supporting existing names only through tested aliases.
9. Never rename or alter a live-related configuration key without migration tests and a rollback note.

## Repository Hygiene and Runtime Configuration

Perform these actions before structural refactoring:

1. Detect whether `.git` is a valid repository. The supplied archive may contain a worktree pointer to an unavailable local Windows path.
2. If Git metadata is invalid:
   - preserve the pointer as historical evidence under `docs/99-archive/repository-metadata/`;
   - create a complete filesystem backup outside the working tree;
   - initialize a new repository only after recording the original metadata and baseline checksums;
   - do not invent historical commits.
3. Preserve the owner-approved test `.env` and configured test credentials. Do not alter their values.
4. Keep runtime credentials outside tracked source files and exclude `.env`, databases, caches, generated reports, build products, and local artifacts from commits and distributable source archives. This is repository hygiene, not a request to remove or rotate the approved test credentials.
5. Produce an `.env.example` containing required variable names and only empty values or safe non-secret defaults.
6. Inventory environment variables by name only and classify them as generic PolySia, Polymarket adapter-specific, active, deprecated, legacy, or future.
7. Remove caches and generated artifacts from the tracked source tree, while preserving meaningful sanitized historical evidence with a manifest.
8. Add a safe source-export script that excludes runtime-only files without modifying the working test environment.
9. Add automated checks preventing accidental credential-value exposure in commits, logs, reports, and handoffs.

## Documentation Modernization

Preserve existing phase documents as historical evidence, but do not leave them as the primary navigation structure.

Create or update:

- Document control record
- Project charter
- Vision, scope, goals, and non-goals
- Project naming pack
- Glossary
- Assumption register
- Decision register
- Risk register
- Issue and dependency registers
- Technical debt register
- Capability catalog
- Functional and non-functional requirements
- Traceability matrix
- Research Evidence Register
- Technology evaluation matrix
- Architecture overview
- C4 context and container diagrams
- Module dependency diagram
- Canonical trading-flow diagram
- Order-state diagram
- Reconciliation-flow diagram
- Security trust-boundary diagram
- Environment matrix
- Threat model
- Test strategy
- Operations and incident runbooks
- Live-readiness policy
- SDK upgrade/rollback runbook
- Repository map and contributor guide
- AI task and handoff templates

Correct stale or contradictory documentation. For example, test counts, branch names, phase status, and current package versions must be generated or verified rather than manually copied indefinitely.

## Required ADRs

Create at least these ADRs:

1. `ADR-0001`: Adopt the existing working Python implementation as the PolySia foundation.
2. `ADR-0002`: Modular monolith with hexagonal ports and adapters.
3. `ADR-0003`: PolySia naming and compatibility migration.
4. `ADR-0004`: Polymarket as the first adapter, with vendor-neutral core contracts.
5. `ADR-0005`: Official Polymarket SDK selection, version pinning, beta-risk management, and rollback.
6. `ADR-0006`: SQLite for local/research MVP and migration triggers for a production database.
7. `ADR-0007`: Approved test credentials, runtime configuration, and production credential separation.
8. `ADR-0008`: Live-trading safety gates and human approval boundaries.
9. `ADR-0009`: Testing layers and prohibition of live network actions in CI.
10. `ADR-0010`: Legacy phase-document archival and documentation information architecture.

## Code Modernization Priorities

### Priority 1 — Preserve Behavior

- Capture a baseline inventory of all public APIs, CLI commands, environment variables, file outputs, schemas, safety gates, and test expectations.
- Run the existing tests in a sanitized environment.
- Create characterization tests before changing behavior.
- Preserve all operator-critical commands and report formats or provide versioned migrations.

### Priority 2 — Isolate Polymarket

- Remove core-layer imports from `pm_trader.adapters.polymarket_public` and other adapter modules.
- Move market summaries and other canonical data models into the domain layer.
- Introduce ports for public market data, secure account operations, and order execution.
- Make Polymarket classes implement those ports.
- Translate SDK models to domain models through explicit mappers.
- Add a Polymarket capability profile describing supported order types, wallet requirements, identifiers, settlement semantics, resolution metadata, fees, and limitations.

### Priority 3 — Split Oversized Modules

- Split the current monolithic CLI into command groups and small command modules.
- Separate report models, business logic, rendering, persistence, and CLI wiring in large monitoring/execution modules.
- Do not change behavior during file splitting unless a separate tested commit documents the change.

### Priority 4 — Strengthen OMS, Ledger, and Reconciliation Boundaries

- Preserve and formalize the explicit order state machine.
- Add idempotency keys and duplicate-prevention contracts where missing.
- Define external/internal order identity mapping.
- Ensure partial fills, cancel/reject paths, restart recovery, and reconciliation are testable independently of Polymarket.
- Keep Decimal/fixed-point arithmetic for financial values.
- Record rounding and precision rules.

### Priority 5 — Reproducibility and Quality Gates

- Add a dependency lock file.
- Define supported Python versions and test them in CI.
- Add formatting, linting, type checking, unit tests, contract tests, integration tests, secret scanning, dependency auditing, build verification, and package smoke tests.
- Add a pre-commit configuration.
- Add an SBOM generation path if it can be done without excessive complexity.
- Keep network integration tests opt-in and read-only.

## Testing Requirements

The existing suite is valuable but is concentrated under `tests/unit`. Preserve all tests and add missing layers.

Required minimum test categories:

1. Unit tests for domain models, risk checks, accounting, state machines, mappers, and services.
2. Property-based tests for order states, Decimal arithmetic, position updates, idempotency, and limits.
3. Adapter contract tests against deterministic fakes/fixtures matching the current official SDK surface.
4. Integration tests covering:
   - market event → normalization → strategy → risk → paper execution → ledger → reconciliation;
   - persistence with a temporary SQLite database;
   - restart/recovery behavior;
   - duplicate and out-of-order events.
5. CLI smoke tests for all commands without live access.
6. Golden/snapshot tests for sanitized operator reports.
7. Credential-value redaction tests for logs, reports, errors, and handoffs.
8. Migration tests for old and new package/CLI/config names, including final legacy-name removal.
9. Negative tests proving that live mutations remain blocked outside the dedicated controlled-validation path.
10. Opt-in controlled live-network validation tests may exist only under a clearly separated marker/suite, must never run in ordinary CI, and must enforce all approved test-wallet safety gates.

## Baseline Commands

Run these before and after every meaningful migration phase, adapting only when the repository’s approved tooling changes:

```bash
python -m compileall -q src tests
python -m ruff check .
python -m mypy src
python -m pytest -q
python -m pip check
```

Also run the approved build, lock verification, secret scan, dependency audit, and package-install smoke test after those tools are introduced.

## Execution Plan

Execute the work in small, reviewable phases. Create a commit after each successful phase if valid Git is available. Never combine all refactoring into one unreviewable change.

### Phase A — Baseline, Backup, and Runtime Safety

- Inventory files, modules, CLI commands, dependencies, schemas, docs, tests, generated artifacts, and environment-variable names.
- Verify Git status and preserve invalid worktree metadata if present.
- Create a complete backup and a separate safe source-export path.
- Preserve the approved test `.env` without displaying or changing values.
- Confirm structural validation cannot accidentally trigger a live mutation.
- Run and record baseline checks.
- Create `docs/13-ai-handoffs/BASELINE_AUDIT.md`.

### Phase B — Governance and Documentation Foundation

- Add the Master Operating Charter to the canonical governance location.
- Add the Phase 0 project record.
- Create document control, naming pack, registers, capability catalog, traceability skeleton, and repository map.
- Archive existing phase documents without deleting them.
- Create the initial ADR set.

### Phase C — Complete Naming and Packaging Migration

- Rename the canonical package, distribution, imports, CLI, report titles, and internal references to PolySia.
- Add a temporary compatibility shim only when an inventory proves it is necessary.
- Migrate and test every internal consumer.
- Remove the legacy `pm_trader` package and `pm-trader` entry point before phase completion when no external dependency remains; otherwise create an explicit, dated removal gate.
- Add migration and rollback documentation.
- Keep all operational and safety behavior unchanged.

### Phase D — Domain and Ports Extraction

- Extract vendor-neutral models from adapter modules.
- Introduce application ports.
- Invert dependencies so strategies, storage, portfolio, risk, orders, and ledger do not import Polymarket adapters.
- Add architecture-boundary tests.

### Phase E — Polymarket Adapter Consolidation

- Move public, secure, streaming, geoblock, mapping, and capability code under one coherent Polymarket adapter package.
- Preserve current signer/funder behavior.
- Pin and lock the verified official SDK version.
- Add SDK contract and compatibility tests.

### Phase F — Module Decomposition

- Split the large CLI and oversized monitoring/execution modules.
- Separate models, services, renderers, persistence, and command wiring.
- Use characterization tests to prevent behavior drift.

### Phase G — Test, CI, and Supply-Chain Foundation

- Add missing test layers.
- Add CI workflows and pre-commit checks.
- Add secret and dependency scanning.
- Verify build/install/package entry points.

### Phase H — Controlled Realistic Validation

- Use the approved test credentials and dedicated test wallet/account for the highest-fidelity validation justified by the current maturity stage.
- Progress in order: authenticated read-only checks → paper → shadow → controlled tiny live-network test.
- A state-changing live-network test requires explicit owner authorization for that run and must remain inside existing hard caps, allowlists, geoblock checks, kill switch, one-attempt controls, reconciliation, and evidence requirements.
- Never substitute production/main credentials during this phase.
- Record observed latency, fills, fees, order states, reconciliation results, and any deviation from simulation.

### Phase I — Final Verification and Handoff

- Run all checks.
- Produce a before/after architecture and capability comparison.
- Confirm canonical `polysia` naming and document any strictly temporary legacy compatibility that still has a verified consumer.
- Update roadmap and technical-debt register.
- Generate a complete delivery package and rollback instructions.
- Do not deploy or activate production/main credentials.

## Prohibited Changes

Do not:

- delete working features because they are Polymarket-specific;
- replace the entire implementation with generated boilerplate;
- introduce microservices, Kubernetes, distributed queues, or cloud infrastructure without measured need and an approved ADR;
- introduce machine learning;
- connect strategies to live execution;
- reduce or bypass risk controls;
- loosen dry-run or acknowledgement requirements;
- expose credential values or private keys in generated reports or handoffs; identifiers such as token IDs, wallet addresses, and transaction hashes may appear only in access-controlled operational evidence when required for reconciliation;
- rewrite the database layer to PostgreSQL merely for future-proofing;
- change public behavior and file formats without compatibility tests and migration notes;
- trust stale project documentation over current code and tests;
- claim completion while tests, type checks, lint, security checks, or build checks fail.

## Acceptance Criteria

The modernization is complete only when:

1. The working Polymarket capabilities remain available and regression-tested.
2. The owner-approved test credentials remain usable, unchanged unless explicitly requested, and never appear in tracked source, logs, reports, or handoff content.
3. The canonical identity is fully PolySia: distribution `polysia`, import namespace `polysia`, CLI `polysia`, and operator-facing PolySia naming.
4. The legacy `pm_trader`/`pm-trader` identity is removed, or any strictly temporary shim has a verified consumer, tests, owner-visible expiry condition, and explicit removal task.
5. Core domain/application modules do not import Polymarket SDK or adapter models.
6. Polymarket is isolated behind documented ports and a capability profile.
7. The project has a reproducible dependency lock and documented SDK upgrade/rollback process.
8. Existing checks pass and the expanded test suite passes.
9. CI and local quality gates are documented and executable.
10. Current architecture, operational safety, risks, assumptions, requirements, and roadmap are documented.
11. Historical phase documentation is preserved but no longer controls the primary information architecture.
12. Generated artifacts are separated from source and excluded from clean source archives.
13. Any controlled live-network validation used only the approved test wallet/account, followed the dedicated gated process, and produced complete reconciliation evidence.
14. Production/main credentials were not introduced or activated.
15. A complete AI handoff package exists for the next task.

## Stop and Escalation Conditions

Stop the affected phase and report clearly if:

- a change would require revealing, overwriting, or invalidating the approved test credentials;
- a state-changing live-network test is about to run without the dedicated controlled-validation phase and explicit owner authorization for that run;
- current official SDK behavior conflicts with the existing signer/funder flow;
- baseline tests fail before modifications;
- the supplied Git state cannot be safely reconstructed;
- a working capability cannot be preserved without a breaking migration;
- documentation and code materially disagree about live safety;
- a legal, geographic, custody, or account-access decision is required;
- a destructive deletion has no verified replacement;
- or a required owner decision would materially change architecture or live risk.

Do not stop because the approved test `.env` exists. Do not repeat credential warnings. Do not stop for minor naming or formatting ambiguity; use a conservative assumption, record it, and continue.

## Required Delivery Package

At the end of every phase and at final handoff, provide:

- Executive summary
- Baseline state
- Assumptions
- Files created, changed, moved, archived, and deleted
- Compatibility impact
- Architecture decisions
- Runtime-safety findings
- Test-credential usage status without values
- Commands executed
- Test/lint/type/build/security results
- Acceptance-criteria status
- Known limitations
- Risks introduced or mitigated
- Migration actions
- Rollback instructions
- Remaining work
- Recommended reviewer focus
- Exact Git branch and commit, if valid Git is available
- A machine-readable handoff under `docs/13-ai-handoffs/`

## First Response Required from Codex

Before editing any file, respond with:

1. A concise summary of your understanding.
2. The detected repository/Git state.
3. The current baseline commands you will run.
4. Confirmation that the owner-approved test credentials will be preserved, not displayed, and used only according to the controlled-validation policy.
5. The first implementation phase you will execute.
6. Any truly blocking issue; otherwise proceed without asking unnecessary questions.

Then begin with **Phase A — Baseline, Backup, and Runtime Safety**.
