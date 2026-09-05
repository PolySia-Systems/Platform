# Standards Adoption — PolySia Platform

Status: HISTORICAL. This adoption was superseded by the current
[Standards v0.4.0 adoption](standards-adoption-v0.4.0.md) and is retained as
immutable-version provenance.

| Field | Value |
|---|---|
| Record ID | `ADP-PLATFORM-001` |
| Record status | Superseded by v0.4.0; retained as historical evidence |
| Authority | Conformant consumer adoption for the selected v0.1.1 profiles |
| Consumer identity | `PolySia-Systems/Platform` |
| Accountable Consumer Owner | PolySia Platform Owner |
| Standards release | `v0.1.1` |
| Released commit | `921db357c07bf1d940f72cfbb662d940288132ca` |
| Adoption date | 2026-08-17 |
| Review date or trigger | 2026-11-17, or earlier on a Standards, Profile, Python-support, public-interface, environment-vocabulary, or consumer-boundary change |

## Consumer Boundary

### Included

- the canonical `PolySia-Systems/Platform` repository;
- first-party Python under `src/polysia/`;
- Python tests under `tests/` and maintained Python utilities under `scripts/`;
- project metadata, dependency declarations, build configuration, CI, current
  documentation, and repository-controlled durable paths; and
- the repository-owned environment vocabulary represented by current code,
  examples, and operating documentation.

### Excluded

- `PolySia-Systems/Standards`, `Infrastructure`, `Market-Data`, and every other
  repository without its own adoption record;
- servers, deployments, accounts, wallets, credentials, external systems, and
  live-system state;
- third-party, provider-generated, protocol-generated, and vendored identifiers;
- historical delivery evidence under `docs/13-ai-handoffs/` and
  `docs/18-ai-handoffs/`; and
- archived material under `docs/99-archive/` and `prompts/archive/`.

The exclusions prevent transitive adoption and prohibit historical rewrites.
They do not exempt current code, configuration, or documentation from the
selected rules.

## Released Authority Verification

| Check | Result | Evidence |
|---|---|---|
| Repository authority | PASS | Private authority repository `PolySia-Systems/Standards`; `STANDARD.md` declares published Approved and Active material authoritative for an adopting consumer |
| Exact tag | PASS | `refs/tags/v0.1.1` resolves directly to commit `921db357c07bf1d940f72cfbb662d940288132ca` |
| Final release | PASS | GitHub Release `368473737`, published 2026-08-11, is neither Draft nor prerelease |
| Immutability | PASS | GitHub Release API reports `immutable: true` |
| Lifecycle authority | PASS | `PRF-FRM`, `PRF-BASE`, `PRF-PYS`, selected Core documents, and `ENG-PY` are Active in the adopted release |

Release evidence: <https://github.com/PolySia-Systems/Standards/releases/tag/v0.1.1>.
Normal Platform CI uses only the recorded immutable pin and local validator; it
does not require network access, cross-repository credentials, or private-repo
tokens.

## Selected Profiles

| Profile ID and version | Selection reason | Profile authority check | Selection evidence |
|---|---|---|---|
| `PRF-BASE@v0.1.1` | Platform is a PolySia-controlled repository with durable paths, current documents, repository identity, and an explicit adoption | Active since `v0.1.0`; present and unchanged in immutable `v0.1.1` | Repository metadata, tracked inventory, this record |
| `PRF-PYS@v0.1.1` | Platform is a maintained, installable Python project intended for repeatable execution and reuse | Active since `v0.1.0`; present and unchanged in immutable `v0.1.1` | `pyproject.toml`, `src/polysia/`, `tests/`, locks, and CI |

No Infrastructure, Data Platform, Security, AI, design, content, provider,
wallet, deployment, or trading Profile is active and applicable in this
release. Existing local safety rules remain authoritative project policy; they
are not imported into `PRF-BASE` or `PRF-PYS`.

## Material Selection Facts

| Fact | Value | Source | Change trigger |
|---|---|---|---|
| PolySia-controlled repository | Yes | GitHub repository ownership and metadata | Ownership or repository-boundary change |
| Primary implementation | Python | `src/polysia/` tracked inventory | Primary-runtime change |
| Supported interpreter | `>=3.14,<3.15` | `pyproject.toml`, CI, locks, `AGENTS.md` | Python-support decision |
| Installable project | Yes | PEP 517 metadata and Hatch wheel configuration | Packaging or build-backend change |
| Reusable library interface | Present | `polysia` import root and explicit package exports | Supported import or export change |
| Public command-line interface | Present | `polysia=polysia.cli:app` | Entry point, command, or option change |
| Python-owned serialized models | Present | Domain models and explicit JSON conversion boundaries | Schema or serialization change |
| External-effect tests by default | Absent | Test defaults, fakes, and runtime safety policy | Network-test or test-mutation change |
| Repeatable verification environment | Present | `locks/pip-py314.lock`, `environment.yml`, and CI | Dependency-resolution change |
| Environment vocabulary | Present | `APP_ENV`, CI, deployment examples, and operating charter | Environment token or deployment-class change |

## Conditional Applicability

The exact machine-readable IDs, facts, conditions, evidence, and outcomes are
in [`standards/adoption.toml`](../../standards/adoption.toml). Ranges below are
closed ranges at the immutable release and are presentation-only.

| Profile group or condition | Result | Included or excluded requirement IDs | Reason |
|---|---|---|---|
| Profile consumer controls | Applicable | `PRF-FRM-005`–`007`, `010`, `013`–`014` | The consumer resolves and assesses released Profiles and records local precedence |
| Profile-author controls | Source authority | `PRF-FRM-001`–`004`, `009`, `012`, `016`; `PRF-BASE-009`; `PRF-PYS-007`; `ENG-PY-021` | These govern immutable Profile/Standard artifacts and their external owners |
| Absent Profile events | N/A | `PRF-FRM-008`, `011`, `015` | No scoped refinement, conflict, or Profile change exists |
| Base consumer controls | Applicable | `PRF-BASE-001`–`008` | Exact boundary, map-limited selection, environment mapping, and non-transitive adoption are present |
| Python consumer controls | Applicable | `PRF-PYS-001`–`006` | All objective Python selection facts are present |
| Core interpretation and assessment | Applicable | `CORE-REQ-020`–`022`, `024`, `026`, `029`–`030`, `032`, `034`, `052`, `057`, `059` | The adoption interprets and assesses a combined requirement set |
| Conflict and exception events | N/A | `CORE-REQ-027`, `053`–`055` | No incompatible requirement set, conflict, or approved mandatory exception exists |
| Base repository naming | Applicable | `CORE-NAM-025`, `028`–`029`, `031`–`033`, `061`–`062`, `070`–`071`, `075`, `082` | PolySia controls repository identity, durable paths, identifiers, and current documents |
| Environment vocabulary | Applicable | `CORE-NAM-054`–`056`; `PRF-BASE-006`–`007` | Development, test, production, and additional environment or exposure classes are represented |
| Ephemeral environments | N/A | `CORE-NAM-057` | No repository-owned ephemeral environment is implemented |
| Released authority and production pin | Applicable | `CORE-LCY-001`, `CORE-VER-012` | The production-facing consumer pins one exact final immutable release |
| Python and interface naming | Applicable | `CORE-NAM-036`–`040`, `042`, `085`, `088`–`089`, `093`–`094`, `096`–`102`, `104`–`105` | Platform owns the Python assets, interface evidence, rename history, and enforcement changes |
| Absent Python naming events | N/A | `CORE-NAM-041`, `086`–`087`, `090`–`092`, `095` | No current public Python rename, collision, naming exception, or incompatible domain constraint exists |
| Python engineering | Applicable | `ENG-PY-001`–`020` | Installable project, public CLI and imports, models, typing, dependencies, build, and tests are present |

The resolved universe is exactly 114 evaluated identifiers: 89 Applicable, 15
N/A, and 10 Source-authority controls. No complete Standards directory or
unselected domain is inherited.

## Environment Vocabulary

| Canonical token | Purpose and boundary | Relationship |
|---|---|---|
| `development` | Developer-controlled local execution | Base class; legacy `local` input maps here during remediation |
| `test` | Deterministic automated and integration verification | Base class; not a trading mode |
| `staging` | Production-like validation before a production change | Base class; not currently implemented |
| `production` | Authoritative controlled server workload | Base class; legacy `server` input maps here during remediation |
| `research` | Offline hypothesis and replay work | Additional class; separate from deployment authority |
| `sandbox` | Isolated external-provider experimentation | Additional class; does not imply test credentials are available |
| `paper` | Simulated execution without venue mutation | Additional exposure class; not production authority |
| `shadow` | Real-data observation with paper-only decisions | Additional exposure class; not production authority |
| `limited-live` | Explicitly authorized, bounded real-account experiment | Additional exposure class; never a synonym for production readiness |
| `disaster-recovery` | Recovery and restore verification | Additional class; separate from ordinary production |

`TRADING_MODE` remains a distinct safety and execution-mode field. Environment,
release version, deployment instance, traffic stage, and trading authorization
must not be conflated.

## Full Enforcement

The temporary baseline recorded ten findings at pre-adoption revision
`35a6c2236188e5bc47742c2a802d4383b6dc1c8c`: five noncanonical `APP_ENV`
tokens, four non-snake-case Python utility filenames, and one Python module
filename that collides with the standard library.

All ten findings were resolved, full-repository validation passed, and the
temporary baseline was removed. CI now evaluates the complete tracked
repository on every run. The complete 114-requirement result is recorded in
[`standards/conformance.toml`](../../standards/conformance.toml).

## Exceptions and Deviations

None. No baseline, grandfathered finding, or approved exception remains.

## Adoption Review

| Check | Result | Evidence |
|---|---|---|
| Exact released baseline identified | PASS | Immutable release and commit verification above |
| Profile conditions supported by consumer facts | PASS | Material Selection Facts |
| Requirement authority checked | PASS | Active source documents at the pinned commit |
| Applicability set resolved without silent inheritance | PASS | Exact 114-ID manifest and grouped resolution |
| Exceptions and deviations linked | N/A | None exist |
| Consumer boundary and owner confirmed | PASS | Consumer Boundary and owner authorization in the adoption prompt |

## Decision and Next Review

| Field | Value |
|---|---|
| Adoption disposition | Accepted and fully enforced for PRF-BASE and PRF-PYS |
| Decision record | This owner-authorized adoption and its three sequential PRs |
| Next review owner | PolySia Platform Owner |
| Next review date or trigger | 2026-11-17, Profile or release upgrade, boundary change, or a material consumer-fact change |

## Related Records

- [`standards/adoption.toml`](../../standards/adoption.toml)
- [`standards/conformance.toml`](../../standards/conformance.toml)
- [Final conformance review](standards-conformance-v0.1.1.md)
- [Project naming pack](naming-pack.md)
- [Project status](PROJECT_STATUS.md)
- [Remediation and rollback](../10-operations/standards-v0.1.1-remediation.md)
