# Architecture Truth Refresh — 2026-08-18

## Outcome

PolySia's architecture documentation was audited against repository commit
`449f1c308fc74bd2a541e0e905f281fd19e5cd9b` and the adopted
`PolySia-Systems/Standards@v0.1.1` release. This was a documentation-truth and
drift-prevention change; it did not alter runtime behavior, dependencies,
credentials, deployment, or external accounts.

The audit reviewed all 18 registered architecture views. Nine diagrams required
content changes and were regenerated with Mermaid CLI 11.16.0:

- 03 — current C4 containers
- 04 — target C4 containers
- 05 — current component map
- 06 — multi-strategy target architecture
- 12 — runtime modes and promotion
- 13 — current deployment
- 15 — trust boundaries
- 16 — module dependency map
- 18 — capability roadmap

Views 01, 02, 07, 08, 09, 10, 11, 14, and 17 remained structurally accurate;
only their audited source revision metadata changed.

## Truth Clarifications

- The Strategy Registry, SHADOW-only Control Kernel, and bounded Copy strategy
  are represented as CURRENT capabilities.
- Generalized strategy orchestration, conflict resolution, allocation, and
  permanent Copy promotion remain TARGET or FUTURE capabilities.
- Tiny Live Copy run 004 is recorded as `FAILED_SAFE`: the accepted Post-only
  order did not fill, later evidence proved zero open orders, fills, exposure,
  and cost, but immediate cancellation confirmation remained ambiguous.
- The verified deployed revision is distinguished from the newer repository
  documentation baseline.

## Drift Prevention

`scripts/check_changed_docs.py` now validates architecture source/view/rendered
triples, index coverage, baseline metadata, exact-case paths and links, status
vocabulary, and CURRENT traceability evidence. The existing documentation CI
path invokes this check without adding a dependency or renaming a required job.

## Validation

- `python scripts/validate_standards.py --mode full` — passed, 0 findings
- `python -m compileall -q src tests` — passed
- `python -m ruff check .` — passed
- `python -m mypy src` — passed, 137 source files
- `python -m pytest -q` — passed, 657 tests
- `python -m pip check` — passed
- `python -m polysia.security.secret_scan` — passed
- `python -m build` — passed; sdist and wheel built
- focused architecture checker tests — passed, 3 tests
- Mermaid CLI 11.16.0 rendering and visual review — passed for all nine changed
  diagrams

Docker, OSV audit, and SBOM generation were not repeated because no runtime,
container, or dependency input changed.

## Remaining Limitations

The bounded cancellation-confirmation and upstream SDK terminal-order response
limitations remain explicit follow-up work. No additional live run is authorized
by this handoff.

Rollback is a normal revert of the documentation and drift-check commits.
