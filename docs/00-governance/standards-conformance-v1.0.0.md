# Standards v1.0.0 consumer adoption review

Date: 2026-10-24. Consumer: `PolySia-Systems/Platform` only.

Decision: the owner explicitly authorized P2 adoption of published Standards
v1.0.0 at `ccc3f4f69dbb9bdb94fefa10fc6bc22bd5f9bead`, selecting exactly
`PRF-BASE` and `PRF-PYS`. The prior P1 receipt remains valid; its engineering,
permission and unattended-cycle acceptance is not repeated by this adoption.

## Immutable source verification

- [Published release](https://github.com/PolySia-Systems/Standards/releases/tag/v1.0.0):
  ID `422686619`, immutable, not draft or prerelease, published 2026-10-24.
- Annotated tag `78479bc768db054a354e33897288b3e53e777258` resolves to the
  exact adopted commit. Local `git verify-tag v1.0.0` passed against existing
  owner trust; GitHub independently reports a valid tag signature.
- `gh release verify v1.0.0 --format json -R PolySia-Systems/Standards` passed;
  attestation repository, tag-object subject and Release ID match.
- [RELEASE_VERIFIED receipt](https://github.com/PolySia-Systems/Standards/pull/22#issuecomment-6307032903)
  records human approval/activation, matching reviewed and released trees,
  published-stage verification and exact-release Linux/Windows CI.

The exact release's `catalog/ir.json` and profile dependencies resolve 118
identities: the previous 114 plus `ENG-PY-022` through `ENG-PY-025`.
Retained requirement meanings, levels, conditions, statuses, owners and evidence
are unchanged; retained IR changes are source-line offsets only. Framework
requirements remain transitive selection dependencies, not a newly selected
Profile. No unrelated, Draft, Deferred or unselected requirement is adopted.
The consumer does not author or release a Profile: PRF-FRM-015 remains an
absent consumer event. The external publisher's material-change assessment,
Major classification and activation evidence are verified in the release receipt.

## Consumer assessment

`maintained_third_party_dependencies = true`: `pyproject.toml` owns runtime,
development/test and build declarations; canonical locks include their resolved
closure. The existing 89 applicable rows, 15 absent-event conditions and 10
source-authority responsibilities are retained. Four additional applicable
MUST rows pass: totals are 118 identities, 93 applicable/pass, 15 not applicable,
10 verified source-authority, zero unresolved findings and zero exceptions.

| Requirement | Consumer evidence and assessment |
|---|---|
| ENG-PY-022: maintenance scope | [Supply-chain runbook](../05-security/supply-chain.md) identifies canonical sources, complete runtime/dev/test/build inventory, Platform dependency maintainer, weekly cadence and GitHub run-artifact/Issue retrieval routes. `dependency_locks.py` owns generation; `dependency_lifecycle.py` owns scoped inventory and source hashes. PASS. |
| ENG-PY-023: assessment/verification | Weekly read-only PyPI discovery distinguishes newest from eligible, retains unknown coverage, classifies full resolved deltas and requires final-head CI/strict OSV before acceptance. Reuse the dated 123-package inventory and exact-main gates in the P1 receipt; no dependency input or assessor changes here. PASS. |
| ENG-PY-024: owned dispositions | Scan records carry owner, next action and weekly review trigger. The runbook records #205/#212 reasons, owners, next actions and review due 2026-10-31, with earlier advisory/compatibility triggers. Corrected advisories link to accepted #218 and final audit evidence. Held work does not become an exception or runtime approval. PASS. |
| ENG-PY-025: health visibility | Existing health and offline preflight distinguish configuration, complete scoped execution, seven-day freshness plus 48-hour grace, failure and effective permission. The P1 receipt binds real #219 App publication/PR CI/protected merge/leased cleanup and records unproven routes. Issue #207 recovery is retained; no new weekly clock firing or external notification delivery is inferred. PASS. |

[P1_COMPLETE evidence](https://github.com/PolySia-Systems/Platform/issues/202#issuecomment-6383393579)
includes exact main `76e08d31727340b6650259b3eb3d83b750ae316b`, successful
CI 40087029772, strict OSV, SBOM and the real unattended #219 cycle. P2 changes
the adopted authority, applicability, local validator and review documentation;
it does not change dependency pins, publication permissions or that proven path.
Future image manifests read their Standards identity from the canonical adoption
record, removing the obsolete duplicated pin; no image is deployed here.

Normal CI remains offline with respect to private Standards: the local exact
pin, requirement universe, fact and conformance checks need no source token.
New regression cases reject missing maintenance rows, absent/unknown dependency
facts, a wrong immutable release identity and a mismatched conformance report.
Affected validation and final integration evidence are recorded in the P2 PR
and Issue #202 receipt. These records certify scoped consumer conformance,
not deployment, live trading or future update acceptance.

## Compatibility and rollback

Keep the tailored Platform tooling; no wholesale Golden Path migration or
additional runtime dependency is needed. DATA_ONLY, disabled live trading,
existing review gates and open unrelated work remain unchanged.

Rollback reverts the complete focused P2 merge, including this review, local
validator, adoption/conformance records, guidance and policy additions. This
restores v0.5.2 at `2ccbe4dbbcb3574db52e5a8eb73e968a9165a83c` and its complete
114-row consumer tree without undoing P1. Preserve earlier dated reviews and
never move a published Standards tag.
