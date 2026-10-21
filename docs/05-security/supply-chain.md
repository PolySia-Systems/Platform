# Software Supply-Chain Controls

## Local gates

- `python -m polysia.security.secret_scan`
- `python -m pip_audit --strict --vulnerability-service osv`
- `python -m build`
- `cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json`
- `python scripts/dependency_locks.py check`
- `pre-commit run --all-files`

The secret scanner reads only Git-tracked files, reports rule and path without
echoing matched values, and rejects tracked `.env`, key, and PEM files. Runtime
`.env` remains ignored and unchanged.

`pyproject.toml` is the only manually maintained pip declaration. Generated
outputs are `locks/requirements-runtime-py314.txt` and
`locks/requirements-dev-py314.txt`. They are produced by pip-tools 7.6.2 from
`pyproject.toml` (development extras only on the development lock) with a
stable header and no pip-compile annotations, so Linux and Windows Python 3.14
can verify the same committed pins. `colorama` is declared directly so Linux
`pip-compile` keeps the Windows-needed typer extra in the portable lock. Do
not hand-edit generated rows. Conventional `.txt` names let GitHub's dependency
graph see the resolved graph; Dependabot `exclude-paths` prevents duplicate
version PRs against those generated files.

```bash
python scripts/dependency_locks.py check
python scripts/dependency_locks.py refresh --scope pip --upgrade
python scripts/dependency_locks.py refresh --scope conda
make dependency-locks-check
make dependency-locks
```

`check` never selects newer versions. `refresh --scope pip --upgrade` selects
new versions across the closure; `refresh --scope pip --package NAME` selects
only named packages within the canonical resolver (repeat for a coherent slice).
Both paths resolve runtime first and constrain development to runtime.
Conda refresh is only
for Python/bootstrap/environment-owner changes.

## CURRENT dependency lifecycle

Decision (2026-10-20): retain Dependabot for pip declarations and Actions,
and `scripts/dependency_locks.py` for the resolved graph. One owner per input.
Renovate's [pip-compile manager](https://docs.renovatebot.com/modules/manager/pip-compile/)
requires a generated command header, whereas Platform deliberately uses
`--no-header` and canonical runtime-first/dev-constrained resolution. Switching
would require header/resolver migration and separately authorized App access;
no demonstrated gate justifies that cost. No alternate pilot or new token.

Dependabot version proposals use disjoint development patch/minor, runtime,
build-toolchain (including pip/bootstrap), venue-SDK and authentication/crypto
groups. Development majors
and security updates remain individual proposals. These are proposal boundaries,
not permission to merge: the complete resolved delta still determines risk.
Grouping follows GitHub's [group rules](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#groups);
explicit exclusions prevent sensitive packages entering general groups.

`dependency-automation.yml` runs weekly and on manual dispatch. Its `generate`
job resolves both locks in isolation without write authority. Scheduled generation
selects a genuine development target within existing declarations and active parent
bounds; it freezes every runtime and sensitive build/bootstrap pin. It tries at
most three canonical resolver slices, trying distinct targets before lower
fallback versions. Each complete resolved delta must independently qualify for
automatic merge. Deferred runtime work therefore does not force an unrelated
eligible development patch into the same proposal. Conflicts remain held;
no candidate yields `NO_ELIGIBLE_UPDATE` without a proposal artifact. Its `scan` job
reads official PyPI metadata for every resolved runtime/dev/build package,
including current yanked status, latest stable release, Python requirements,
published wheel presence and active parent bounds for Linux/Windows Python
3.14 and requested extras. Published, compatible, tested and installed versions
are separate facts. A published wheel does not prove a matching ABI/platform.
Metadata coverage does not establish advisory coverage or safe installation.
Latest published stable and highest eligible are distinct fields. Version-policy
exclusions cannot hide an eligible patch below a newer major. Eligibility checks
retain at most 100 qualifying releases and fetch at most three candidate metadata
records per package; incomplete evidence is `UNKNOWN`, never proof of absence.
Candidate eligibility includes incoming bounds, Python, yanks and reported
advisories, and remains provisional until canonical resolution and final-head CI.
The strict OSV gate and final-head CI remain mandatory for candidate changes.
Actions remain owned by Dependabot; Docker, Conda/bootstrap and declared host
pins are inventoried for the Platform dependency maintainer. Inventory is not
an observation of deployed software. No host is queried or mutated.

```bash
python scripts/dependency_lifecycle.py scan --output artifacts/dependency-scan.json
gh workflow run dependency-automation.yml --ref main
```

Both scan and proposal are retained as GitHub run artifacts (30 and 14 days).
Failures/partial scans exit nonzero; `noop` only registers events and never
counts as freshness. Task/backlog disposition lives in
[Issue #202](https://github.com/PolySia-Systems/Platform/issues/202).
Each material hold records source time, owner, reason, next action and trigger.

### Trusted publication and merge

`dependency-publish.yml` runs trusted current-main code after the read-only
producer. It never installs candidates or executes PR/artifact code. The
publisher independently checks the originating workflow/event, repository,
actor, live PR identity, expected base/head and run/attempt, exact allowed
paths and SHA-256 hashes of the manifest/lock pair. It compares the manifest
with the assessed immutable GitHub content, rejects nondependency manifest
changes, and validates complete shared pins, declarations and build constraints.
GitHub atomically enforces `expectedHeadOid` when committing the lock pair.
Missing, partial, stale, ambiguous or tampered evidence fails closed.

The publisher explicitly dispatches full CI after its final commit because
[ordinary GITHUB_TOKEN writes do not trigger normal workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
It suppresses an already running/successful dispatch for the same head. A
separate completion handler reclassifies the live diff after successful CI,
verifies `CI Gate` belongs to that exact run/head, requires the current base,
then requests an exact-head merge under repository rules. It never leaves an
auto-merge approval queued across subsequent changes. Runtime, SDK, build,
crypto, prerelease/epoch/local/post versions, `0.x` minor, new/removed packages
and ambiguous updates require review. Actions proposals require source review;
metadata-only Actions auto-approval has been removed.

A scheduled proposal identity binds the base and candidate content. Reruns
reuse the single active, verified bot proposal; stale/ambiguous branches stop
for review. Completed proposals do not block a new candidate or get resurrected.
Existing branch diffs and signed bot identity are assessed before dispatch;
the final merge head must also be a verified bot commit.
Interrupted or denied publication preserves its branch for assessed recovery.
After a confirmed merge the handler verifies repository/PR/bot identity and Git
ancestry, checks for an active reused proposal, then conditionally deletes only
the integrated task bot ref using a server-enforced expected-ref lease. Changed
or reused refs are preserved. A lost response is reconciled with actual PR/ref
state. Merge and cleanup outcomes remain separate; interrupted cleanup retries
without a second merge. No confirmed integration means no cleanup attempt.
No candidate is copied from a historical run over newer declarations.
Restart a failed/partial producer through a fresh manual dispatch, regenerating
its entire proposal. A partial job rerun must not reuse another attempt's
artifact; attempt mismatch fails closed. Publication itself can safely retry
the same fully assessed producer artifact.

The repository rules require a PR and strict `CI Gate`, with zero mandatory
approving reviews as observed on 2026-10-20. Repository auto-merge capability
and `can_approve_pull_request_reviews` are not publication proof. Each actor's
branch-write, PR-create, CI-dispatch and merge route must be exercised. A
permission/provider failure is nonzero and retains sanitized stage/context.
When Actions PR creation is denied, authenticated maintainer generation is a
**degraded fallback**, not unattended completion. Never expand a token or
change policy to make the proof pass.

### Independent maintenance health and developer preflight

The existing CI workflow independently checks meaningful dependency jobs on
its weekly schedule and manual main dispatch. It requires both `scan` and
`generate` success, preserves the previous complete observation across failure,
checks publication and merge/cleanup failures, and exposes missed scans after the local default
of seven days plus 48 hours grace. It opens/reopens one actionable GitHub issue,
updates only changed state, closes it on recovery, and stays quiet while healthy
or unchanged. GitHub issue creation is the notification surface; subscriber,
email delivery and independence from GitHub availability remain unverified.
Advisories require prompt owner triage independently of weekly version scans.
Successful unrelated CI callbacks do not clear a publication failure; confirmed
dependency integration and cleanup can record recovery. Deterministic callback
tests are engineering evidence, not proof of an unattended production cycle.

Developer context adds offline `GO / CONSTRAINED_GO / BLOCKED` dependency
preflight using relevant source/config/policy/manifest/lock hashes, cached scan
identity and age. Dirty changes and age invalidate reuse. Routine prose scopes
perform no online audit. A current metadata scan can be reused; candidate CI
and advisory gates still apply. No secrets/runtime database enter the packet.
The cached file is disposable `artifacts/dependency-scan.json`, never authority.

## 2026-07-11 verification evidence

- Package build: passed for the source distribution and wheel.
- CycloneDX SBOM: generated as specification 1.6 with 121 components at
  `artifacts/sbom.json`; the generated directory is intentionally ignored.
- Environment integrity: `pip check` passed.
- Dependency audit: passed with `pip-audit --strict` using the OSV advisory
  service; no known vulnerabilities were reported. The default PyPI advisory
  endpoint remained unreachable through the workstation proxy, so OSV is the
  standardized local and CI service.

## CI

CI supports Python 3.14 only and keeps DATA_ONLY safety overrides. Pull requests
always run diff, local path/link, Standards, and tracked-file secret checks.
Executable Python changes run complete quality validation on canonical Linux,
including deterministic lock verification; full Windows compatibility runs
weekly, manually, and for verified Windows-sensitive changes. The container job
runs only for Docker, deployment, runtime-lock, entrypoint, health, backup,
state-path, or related executable configuration changes. The supply-chain job
performs a strict OSV audit and publishes a CycloneDX SBOM on canonical Linux
for dependency changes, on a weekly schedule, and by manual dispatch. It
retains a separate allowed-range wheel compatibility smoke without adding that
resolution work to ordinary source pull requests. GitHub Actions and pip
dependencies receive weekly Dependabot review.

A final fail-closed CI Gate checks that every job required by the risk-based
change map succeeded. Manual comprehensive validation covers migrations and
uncertain changes without making all future CI-only pull requests permanently
run unrelated jobs.

## Rollback

1. Revert the dependency automation merge on `main`.
2. Disable only the affected automation workflow if required; preserve `main`
   protection, required checks and organization security policy.
3. Preserve security-update discovery; disposition affected proposals explicitly.
4. Restore previous pip lock filenames only by reverting the same merge; do not
   keep both generated generations.

## Limitations

The Conda lock is the verified Windows owner-workstation snapshot. The exact
pip locks are portable across compatible Windows and Linux Python 3.14
environments but are not hash-locked; adding hashes remains a release-hardening
item. CODEOWNERS remains optional owner GitHub configuration.

The default PyPI advisory endpoint remains unavailable through the workstation
proxy. OSV provided the successful strict audit result; future release evidence
should record the selected advisory service and timestamp.
