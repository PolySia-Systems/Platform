# AGENTS.md - PolySia Repository Operating Instructions

- **Version:** 1.2
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
`PolySia-Systems/Standards@v0.4.0` release at commit
`4ee4e6aca8f0a38379f18029f8db71828cd00759`, selecting only `PRF-BASE` and
`PRF-PYS`. The authoritative consumer record and resolved applicability set are
[`standards/adoption.toml`](standards/adoption.toml) and
[`standards/conformance.toml`](standards/conformance.toml), with the human review
at [`docs/00-governance/standards-conformance-v0.4.0.md`](docs/00-governance/standards-conformance-v0.4.0.md).

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

## 3. Required Start-of-Task Protocol

For a tiny, clearly scoped edit, state a one- or two-sentence plan and edit.

For every non-trivial task:

1. Confirm the repository root, branch, and `HEAD`.
2. Read only nested `AGENTS.md` files on the path to the files in scope.
3. Resume ordinary work from the Issue or PR. Do not rebuild context from chat
   or from `PROJECT_STATUS` runtime rows.
4. Read the smallest authoritative set of code, tests, ADRs, and evidence.
5. Identify the goal, in-scope files, constraints, acceptance criteria, and
   prohibited changes, then state a concise plan.
6. Do not repeat completed discovery, migration, tests, or audits unless current
   evidence or a new change requires revalidation.

Do not create planning files or handoff files solely for ceremony.

## 4. Efficiency and Context Discipline

Token and tool usage are project resources. Optimize them without sacrificing
correctness or safety.

- Search with `rg` or targeted inventories before opening large files.
- Read the smallest authoritative set of files that can resolve the task.
- Reuse verified findings from the current task.
- Prefer focused tests. Escalate to broader gates according to the files and
  behavior changed.
- For documentation-only changes, do not run the full runtime suite unless the
  documentation changes executable configuration, commands that require a
  smoke check, or repository policy explicitly requires it.
- Do not spawn reviewers, subagents, or duplicate analysis unless the task asks
  for them, applicable instructions require them, or independent work materially
  reduces risk and the active environment permits it.
- Never save tokens by skipping a required safety gate, source check, or evidence
  needed to support a material claim.

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

## 9. Python Engineering Standards

Follow `pyproject.toml`, repository tooling, and existing conventions.

- Supported Python is `>=3.14,<3.15`; CI verifies Python 3.14. Change the
  supported minor line only through an explicit compatibility decision with
  synchronized metadata, tooling, CI, and documentation updates.
- Use clear type annotations for public interfaces and non-trivial internal
  boundaries.
- Prefer small cohesive modules and explicit dependency injection over hidden
  global state.
- Keep pure domain logic independent from I/O.
- Use dataclasses, protocols, enums, and typed value objects where they clarify
  contracts; do not introduce abstractions without concrete value.
- Preserve deterministic behavior in tests.
- Handle errors explicitly and retain actionable context without leaking
  sensitive values.
- Use existing structured logging and correlation identifiers where available.
- Avoid broad exception swallowing and implicit timezone conversions.
- Keep CLI parsing/wiring separate from business logic, rendering, persistence,
  and network clients.
- Keep comments focused on intent, constraints, or non-obvious reasoning.
- Use English for code, identifiers, comments, schemas, documents, commits, PRs,
  dashboards, and alerts.

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

## 11. Documentation, Decisions, and Continuity

Update documentation when behavior, contracts, architecture, operating
procedures, configuration, or user-facing commands change.

- The canonical documentation entrance is [`docs/README.md`](docs/README.md).
  Do not add a parallel Start Here, Wiki, or vendor instruction forest.
- ADRs own material architecture decisions. RFCs own major proposals before
  implementation. Requirements own required behavior. Runbooks own operational
  actions.
- Ordinary in-progress work resumes from the Issue or PR. Create or update a
  file under `docs/18-ai-handoffs/` only for major operational, safety,
  deployment, incident, or compliance evidence that must outlive the PR.
- `docs/00-governance/PROJECT_STATUS.md` owns durable status. It must not
  present Markdown as live host truth.

Documents and diagrams must distinguish Fact, Assumption, Decision,
Recommendation, Risk, Open Question, Experimental Idea, CURRENT, TARGET,
FUTURE, and EXTERNAL as applicable.

Repository code and approved artifacts are authoritative; chat memory is not.

## 12. Git and Pull Request Workflow

Unless the task or active environment specifies otherwise:

- Work on a focused branch named `codex/<short-task-slug>` for changes intended
  for review. Do not create a branch for read-only inspection.
- Do not commit directly to `main` unless the owner explicitly authorizes it or
  an established repository workflow requires it.
- Keep the working tree understandable and review diffs before committing.
- Preserve unrelated changes; stage only task files.
- Do not force push unless explicitly authorized; if required, use
  `--force-with-lease`.
- Use Conventional Commits in English:

```text
<type>(<scope>): <concise imperative summary>
```

Allowed types include `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`,
`chore`, `perf`, and `security`.

- Do not mention AI or Codex in commit subjects.
- Prefer small, meaningful commits at verified milestones.
- Create draft pull requests by default when a PR is requested.
- Never merge with failing required checks or invent repository history.

For substantial changes, PR descriptions should cover objective, summary,
affected modules, validation, architecture/risk impact, compatibility,
limitations, rollback, and reviewer focus. Omit empty boilerplate for tiny
documentation-only changes. The PR is the default resume artifact.

## 13. Review Standard

Before declaring completion, review the final diff as a skeptical independent
reviewer. Check requirement compliance, architecture boundaries, safety,
state transitions, idempotency, Decimal behavior, data leakage, defaults,
external mutation paths, reconciliation, error handling, compatibility, tests,
documentation, unrelated changes, and credential exposure as relevant.

Classify material findings as blocking or non-blocking and resolve blocking
findings before completion. For changes affecting risk, execution, live
controls, authentication/signing, ledger, reconciliation, schemas, supply
chain, or architecture boundaries, perform a deliberate second-pass review.
Use a separate reviewer or subagent only when explicitly requested, required by
applicable instructions, materially justified, and permitted by the active
environment.

## 14. Definition of Done

A task is complete only when:

1. The requested scope and acceptance criteria are satisfied.
2. Existing working behavior is preserved unless explicitly changed.
3. Architecture and safety invariants remain intact.
4. Relevant tests are added or updated when behavior changed.
5. Required checks pass, or unavailable checks are explicitly documented.
6. The final diff contains no unrelated changes.
7. Documentation, decisions, migrations, and runbooks are updated when needed.
8. Compatibility and rollback are addressed when relevant.
9. Current versus target/future status is represented honestly.
10. A concise delivery summary exists. Ordinary work uses the PR. Major
    operational evidence may use `docs/18-ai-handoffs/`.

## 15. Stop and Escalation Conditions

Stop the affected action and report clearly when:

- The repository root or expected project identity is wrong.
- Git contains unresolved conflicts or unexpected destructive changes.
- A source-of-truth conflict materially changes architecture or safety.
- A requested change would bypass risk, emergency, geoblock, allowlist,
  acknowledgement, or reconciliation controls.
- A state-changing external action lacks explicit authorization for that run.
- Required credentials, permissions, environment, or external access are
  unavailable.
- Current official documentation contradicts the requested implementation.
- A migration would break an unassessed external consumer.
- Completion requires inventing data, test results, commits, links, or
  operational evidence.
- A critical test or safety check cannot be made reliable.

For non-critical ambiguity, make the safest reversible assumption, record it,
and continue.

## 16. Final Response

Default to a concise delivery report containing:

- outcome and files changed;
- validation performed and skipped checks with reasons;
- architecture, safety, compatibility, or rollback impact when relevant;
- known limitations or remaining work;
- branch, commit, and final Git status when applicable.

For major migrations or high-risk work, expand the report to include assumptions,
decisions, exact commands/results, acceptance-criteria status, configuration or
migration actions, rollback instructions, and reviewer focus. Do not emit empty
sections or repeat information solely to satisfy a template. Never claim work
that was not performed.

## 17. Nested Instructions

This root file contains universal rules. Add a nested `AGENTS.md` only when a
directory has stable, unique local MUST/NEVER rules that are not already
stated here. Current nested files:

- `src/polysia/adapters/polymarket/AGENTS.md`
- `docs/04-architecture/AGENTS.md`
- `tests/AGENTS.md`

Do not add nested files for Risk or Execution solely because those directories
exist; their universal invariants remain in this root file. Nested files must
not duplicate or weaken root safety. Use `AGENTS.override.md` only for a
deliberate same-directory replacement. Keep the combined instruction chain
within the configured guidance budget.
