# AGENTS.md - PolySia Repository Operating Instructions

- **Version:** 1.3
- **Scope:** Entire repository
- **Audience:** Codex and other coding agents
- **Technical artifact language:** English

## 1. Purpose

PolySia is a risk-controlled, extensible trading and prediction-market
platform. Polymarket is the first venue adapter, not the identity of the core
platform. Preserve working behavior. Improve incrementally. Do not rebuild the
project from scratch for cosmetic reasons.

## 2. Fact Owners and Instruction Precedence

Higher-priority system, developer, and explicit user instructions always take
precedence over repository guidance.

Codex discovers project guidance from the repository root toward the current
working directory. In each directory it loads at most one file, checking
`AGENTS.override.md` before `AGENTS.md`. Instructions closer to the working
directory appear later and take precedence over broader root instructions.

| Fact | Owner |
|---|---|
| Implemented behavior | Current code, tests, schemas, and configuration |
| Required behavior | Requirements documents relevant to the task |
| Architecture rationale | Approved ADRs |
| Validation evidence | CI and tests |
| Active work and resume state | The Issue or PR |
| Current operational state | Read-only runtime query, not Git Markdown |
| Major operational evidence | Dated records under `docs/18-ai-handoffs/` |
| Immutable baseline | `docs/13-ai-handoffs/BASELINE_AUDIT.md` |
| Generated views | Disposable; never authoritative |

Use the Fact Owner table to determine factual truth. The authority order
governs instruction and decision precedence and never overrides the
authoritative owner of a fact.

For instruction and decision conflicts, use this precedence:

1. This root guidance plus applicable nested `AGENTS.md` files.
2. `docs/00-governance/master-operating-charter.md`.
3. Approved ADRs, RFCs, requirements, and `docs/00-governance/PROJECT_STATUS.md`
   for durable status. Treat PROJECT_STATUS snapshots as dated evidence, not
   live host truth.
4. The Issue/PR for ordinary resume. Read a `docs/18-ai-handoffs/` file only
   when the task needs that operational, safety, or delivery evidence.
5. Verified current code, tests, schemas, configuration, and runtime behavior.
6. Current official documentation for version-sensitive external systems.
7. Historical or archived documentation.

Do not silently resolve a material conflict. Preserve the safer verified
behavior, record the conflict, and use an ADR, RFC, or explicit owner decision
when required. Historical files are evidence, not automatically current truth.

### Adopted PolySia Standards

This repository adopts the exact immutable
`PolySia-Systems/Standards@v1.0.0` release at commit
`ccc3f4f69dbb9bdb94fefa10fc6bc22bd5f9bead`, selecting only `PRF-BASE` and
`PRF-PYS`. The authoritative consumer record and resolved applicability set are
[`standards/adoption.toml`](standards/adoption.toml) and
[`standards/conformance.toml`](standards/conformance.toml), with the human review
at [`docs/00-governance/standards-conformance-v1.0.0.md`](docs/00-governance/standards-conformance-v1.0.0.md).

Within that selected set, the pinned Standards release owns requirement meaning,
levels, Profile conditions, and exception semantics. This repository owns its
consumer facts, implementation, evidence, and stricter local trading-safety
rules. Local guidance may add a stricter compatible rule but must not silently
weaken, reinterpret, or expand the adopted requirement set. A material conflict
must be recorded and escalated before claiming conformance. No unselected,
Draft, Deferred, future, or transitive Standards requirement applies.

Normal CI validates the entire tracked repository, recorded pin, and local
evidence without network access or credentials for the private Standards
repository. The adopted requirement set has no grandfathered baseline.

Codex's default project-guidance budget is 32 KiB for the combined instruction
chain. Keep this root file for universal rules. Add a nested `AGENTS.md` only
when unique local MUST/NEVER rules exist. Nested files must stay short.

## 3. Working method

For tiny edits, state the change and edit. Otherwise confirm root, branch and
HEAD, preserve dirty/untracked user work, and read only root-to-scope guidance
and the smallest authoritative source set. Resume from the Issue/PR; state goal,
scope, constraints and acceptance briefly. Use targeted searches and focused
tests. Reuse applicable verified results; do not repeat completed discovery,
audits or tests without new evidence. No ceremonial planning/handoff files.
Reviewers/subagents require task authorization or applicable instructions and
must be permitted by the environment. Never omit required safety evidence to
save time/tokens. Keep combined guidance within the configured 32 KiB budget.

## 5. Project Identity

Use the canonical identity: product `PolySia`; repository `Platform`; Python
distribution and import namespace `polysia`; CLI `polysia`; service prefix
`polysia-`; operations console `PolySia Console`; first venue adapter
Polymarket; initial domain prediction and event markets.

Do not reintroduce `pm_trader`, `pm-trader`, or "Polymarket Trading System" as
canonical names. A legacy compatibility layer is allowed only when a verified
consumer requires it, with tests, an owner-visible expiry condition, and an
explicit removal task.

Keep generic runtime configuration under `POLYSIA_` names and Polymarket-specific
configuration under `POLYMARKET_` names, following existing tested migration
rules.

<!-- polysia-safety:start -->

## 6. Architectural Invariants

These rules are non-negotiable:

- The current deployment style is one Python modular monolith unless an approved
  ADR says otherwise.
- Domain and application code must remain venue-neutral.
- Domain/application modules must not import Polymarket SDK types or adapter
  models.
- External SDK objects must be translated at adapter boundaries.
- Strategies produce signals or pre-risk order intents; they never call a venue,
  wallet, chain, broker, or protocol directly.
- In the CURRENT runtime, executable intents pass from Strategy to independent
  Risk, then Execution, then the venue Adapter. Reconciliation may pause Risk.
  Preserve this non-bypass path.
- Intent aggregation/conflict resolution, portfolio/capital allocation, OMS or
  Transaction Manager, generalized ledger, execution router, and adapter
  registry are TARGET architecture unless current code and approved documents
  explicitly prove otherwise. Do not require or claim them as implemented.
- The Risk Engine has final authority to approve, reject, reduce, pause, or
  block. Emergency control remains independent of strategy logic.
- Order and transaction lifecycles use explicit state machines. Handle
  idempotency, duplicates, restart recovery, partial fills, cancellation,
  rejection, and unknown external state explicitly.
- Positions, fees, realized/unrealized P&L, ledger events, and reconciliation
  are part of the execution lifecycle, not optional reporting extras.
- Use `Decimal` or an approved fixed-point representation for financial values.
  Do not introduce binary floating-point into monetary or quantity calculations.
- Use UTC internally and explicit clock abstractions where deterministic testing
  matters.
- Reconciliation compares internal expected state with externally observed
  state and fails safely on material uncertainty.
- Preserve CURRENT, TARGET, FUTURE, and EXTERNAL distinctions in code comments,
  documents, diagrams, and delivery claims. Never present target or future
  architecture as implemented.

Do not introduce microservices, Kubernetes, distributed infrastructure, machine
learning, online learning, PostgreSQL migration, or new production
infrastructure merely for future-proofing. Such changes require measured need
and an approved ADR or RFC.

When working in `src/polysia/adapters/polymarket/`, also follow
[`src/polysia/adapters/polymarket/AGENTS.md`](src/polysia/adapters/polymarket/AGENTS.md).

## 7. Runtime and Trading Safety

Owner-approved test credentials and the dedicated test wallet/account may be
used only for explicitly authorized controlled validation. Never print, copy
into tracked files, include in reports, or expose credential values.

Default rules:

- Runtime defaults to `TRADING_MODE=DATA_ONLY` and
  `LIVE_TRADING_ENABLED=false`.
- Unit, property, architecture, contract, integration, and ordinary CLI tests
  must not mutate an external account.
- Network tests must be opt-in and clearly marked.
- Authenticated read-only, paper, and shadow validation may run only when the
  task authorizes them and existing gates are satisfied.
- Any state-changing external action requires explicit owner authorization for
  that specific run.
- A state-changing validation must remain within the approved test account,
  hard caps, allowlists, geoblock checks, kill switch, acknowledgement
  requirements, one-attempt controls, and reconciliation evidence.
- Never substitute production/main credentials during test validation.
- Never bypass geographic, venue, account, risk, or safety restrictions.
- Never weaken dry-run defaults, approval gates, hard limits, redaction,
  fail-closed behavior, or emergency controls to make a test pass.
- Do not claim production readiness from test success or a limited real-world
  execution.

If external state is ambiguous, stop mutation, preserve evidence, reconcile,
and report.

## 8. Scope and Change Discipline

- Make the smallest coherent change that fully satisfies the task.
- Do not perform unrelated refactoring.
- Preserve public behavior unless the task explicitly changes it.
- Prefer extraction, dependency inversion, adapters, migrations, and documented
  deprecation over destructive rewrites.
- Do not delete working behavior without an equivalent or stronger replacement
  and regression coverage.
- Do not edit generated artifacts when their source can be changed instead.
- Do not modify files outside the approved scope without explaining why.
- Do not add a production dependency without documenting the need,
  alternatives, maintenance status, security/licensing impact, and rollback
  path.
- Keep changes reviewable and split large migrations into independently
  verifiable milestones.
- Treat warnings, ignored errors, skipped checks, and flaky tests as findings,
  not successful validation.
- Preserve unrelated user changes and pre-existing untracked files.

<!-- polysia-safety:end -->

## 9. Engineering

Follow pyproject.toml and existing conventions. Python is `>=3.14,<3.15`;
changing the minor requires an explicit compatibility decision and synchronized
metadata, tooling, CI and docs. Use typed public/nontrivial interfaces, cohesive
modules, explicit injection and pure domain logic. Dataclasses/protocols/enums
must justify their complexity. Separate CLI wiring from business logic,
rendering, persistence and clients. Preserve deterministic tests/clocks,
structured logging/correlation and actionable redacted errors. Avoid swallowed
exceptions, hidden global state and implicit timezone conversion. Comments
explain intent. Technical artifacts, code, docs, alerts and Git messages use English.

## 10. Test and Validation Policy

Add or update tests whenever behavior, contracts, state transitions, mappings,
risk logic, accounting, persistence, or external integration changes.

Use the appropriate layers: unit tests for domain logic; property tests for
Decimal arithmetic, limits, state transitions, idempotency, and position
updates; architecture tests for dependency boundaries and SDK confinement;
contract tests for adapter/SDK surfaces using deterministic fakes or fixtures;
integration tests for internal slices and temporary SQLite; characterization
tests before behavior-preserving decomposition; migration tests; CLI smoke
tests for non-mutating commands; and opt-in network tests only under the
runtime-safety rules above.

The current CI quality gates are:

```bash
python scripts/validate_standards.py --mode full
python -m compileall -q src tests
python -m ruff check .
python -m mypy src
python -m pytest -q
python -m pip check
python scripts/dependency_locks.py check
python -m polysia.security.secret_scan
python -m build
```

The configured supply-chain gates are:

```bash
python -m pip_audit --strict --vulnerability-service osv
cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json
```

Validation rules:

- Run focused tests during implementation and all relevant gates before
  completion.
- Use `git diff --check`, path/link checks, size checks, and a content review for
  documentation-only changes. Do not run the full runtime suite when no source,
  test, build, dependency, or executable configuration changed unless explicitly
  required.
- Run the secret scan when tracked content, configuration examples, reports, or
  generated handoffs could contain sensitive material.
- Report the exact commands and results. Do not claim success when required
  checks fail, are unavailable, or were not run.
- Distinguish environment/tooling failure from a product defect.
- Never weaken a test assertion unless expected behavior was explicitly changed.

## 11. Documentation, Git and completion

[docs/README.md](docs/README.md) is the sole documentation entrance. ADRs own
material decisions, RFCs major proposals, requirements required behavior and
runbooks operational procedures. Update affected docs/contracts when behavior
changes. Label Fact, Assumption, Decision, Recommendation, Risk, Open Question
and Experimental Idea where relevant. Ordinary continuity belongs in Issue/PR;
only major operational/safety/deployment/incident/compliance evidence belongs in
`docs/18-ai-handoffs/`. PROJECT_STATUS is durable dated evidence, never live host
truth. Do not create a parallel wiki or instruction forest.

Use a focused `codex/<task>` branch for edits; no branch for read-only review.
No direct main commit without explicit authority/workflow. Review diffs and stage
only task files. No force-push without authority; use lease when approved.
Conventional Commits in English; no model/tool attribution in subjects. Draft
PRs by default when requested. Never merge failing required checks.

Before completion, skeptically review scope, architecture, safety, state,
idempotency, Decimal, recovery, credentials, compatibility, tests and docs as
relevant. Resolve blocking findings. Deliberately review a second time for
Risk/execution/live controls/auth/signing/ledger/reconciliation/schemas/supply
chain/architecture boundaries. A separate reviewer is conditional, not automatic.
Completion requires satisfied acceptance, preserved behavior/invariants, relevant
tests, required validation or explicit unavailable results, no unrelated diff,
updated docs and coherent rollback/migration where relevant. Report outcome,
actual checks/limitations, remaining work, branch/commit/PR and Git status
concisely. CI does not prove deployment, production readiness or owner acceptance.

Stop the affected action on wrong project identity, conflicts/unexpected
destruction, material safety/source conflict, bypassed financial controls,
unauthorized external mutation, missing essential access, unassessed consumer
breakage, contradictory official documentation or unreliable critical gates.
Preserve evidence and report. Resolve non-critical ambiguity through the safest
reversible assumption and continue independent work; never invent evidence.

## 12. Scoped guidance and presentation

Keep nested guides short and unique. Current guides: adapter, architecture docs
and tests. Do not add Risk/Execution guides that duplicate universal rules.
Use AGENTS.override.md only for deliberate same-directory replacement.
For user-facing workflows, including Console, CLI and setup, follow
[product design](docs/04-architecture/product-design-system.md): reuse semantic
tokens/primitives, preserve exact financial strings, command ownership and static
asset custody, and validate rendered output.
