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

Decision (2026-10-28, PR #233): the strict OSV gate reported
[CVE-2026-114613](https://github.com/msgpack/msgpack-python/security/advisories/GHSA-j586-36cw-2gc2)
in the existing `msgpack==1.2.2` transitive runtime/development dependency.
The canonical targeted resolver selected `1.2.4` for both locks; no other pin
changed. This upstream Apache-2.0 patch includes the memory-safety fix and
[bounded container preallocation](https://github.com/msgpack/msgpack-python/blob/main/CHANGELOG.md).
Retaining the vulnerable pin or suppressing the audit was rejected. SDK contract,
composition and final-source native gates qualify compatibility. Rollback must
select a complete compatible patched release, preserving custody and STOP;
this dependency update grants no deployment or financial authority.

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
The Platform dependency maintainer reviews actionable findings and existing
holds at least weekly, no later than seven calendar days after assessment or
the previous review, and earlier on an advisory or compatibility change.
Record the dated review and its next due date in the finding's Issue or PR;
renewal requires a reason and next action. An expired hold is overdue work,
not an approved Standards exception or evidence that the dependency is safe.

Current carried dispositions, reviewed 2026-10-24, next review due 2026-10-31:

| Finding | Disposition and reason | Accountable owner | Next action and earlier trigger |
|---|---|---|---|
| [Runtime bundle #205](https://github.com/PolySia-Systems/Platform/pull/205) | Deferred: runtime acceptance is absent; old source predates corrected certifi/security main. | Platform runtime maintainer | Obtain explicit bundle decision, then regenerate against current main and run affected gates; owner decision, advisory or compatibility change triggers earlier review. |
| [Actions major #212](https://github.com/PolySia-Systems/Platform/pull/212) | Held for human source/major-version review; outside automatic pip scope. | Platform dependency maintainer | Review exact Actions sources and compatibility, reconcile current main and run affected gates; owner decision, advisory or compatibility change triggers earlier review. |

The corrected security findings and completed low-risk proposal remain linked
to their integration and audit evidence in the Issue #202 P1 receipt. These
routine maintenance holds do not waive a mandatory requirement. New scan
findings retain their own source time, coverage, reason, owner and weekly
review trigger; unavailable registry or advisory data remains unknown.

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

For native Dependabot synchronization the publisher explicitly dispatches full
CI after its final commit.
[GITHUB_TOKEN push events do not trigger CI; token-created PR events create
approval-required runs](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs).
The explicit full dispatch provides engineering validation.
[Checks from workflow_dispatch do not satisfy required PR checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#checks-from-some-workflow-jobs-are-not-evaluated).
The handler rejects that event as merge authority even when every job succeeds.
Qualifying PR CI and unchanged repository rules remain required; a maintainer's
approval of the token-created PR workflows is human-assisted evidence.
The publisher suppresses an already running/successful dispatch for the same head.
Scheduled proposals instead use the approved PR-only App after the canonical
commit, so the normal `pull_request` event supplies qualifying CI. They do not
dispatch substitute checks. A
separate completion handler reclassifies the live diff after successful PR CI,
verifies `CI Gate` belongs to that exact run/head, requires the current base,
then requests an exact-head merge under repository rules. It never leaves an
auto-merge approval queued across subsequent changes. Runtime, SDK, build,
crypto, prerelease/epoch/local/post versions, `0.x` minor, new/removed packages
and ambiguous updates require review. Actions proposals require source review;
metadata-only Actions auto-approval has been removed.
Completion callbacks hold non-pip branches for review before checking mutable
proposal heads or bases. A held Actions, Docker, Conda or maintainer PR becoming
stale cannot be reported as a pip publication failure; eligible pip proposals
retain every freshness, identity, CI and guarded-cleanup check.

A scheduled proposal identity binds the base and candidate content. Reruns
reuse the single active, verified App proposal only when its content is identical.
An open proposal with changed content, a legacy author, or a stale/ambiguous branch
stops for owner disposition without updating its head. This preserves the bounded
PR-only App permission: synchronizing an existing branch with `GITHUB_TOKEN`
would require human workflow approval. Completed proposals do not block a new
candidate or get resurrected.
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
approving reviews as observed on 2026-10-21. Repository auto-merge capability
and `can_approve_pull_request_reviews` are not publication proof. Each actor's
branch-write, PR-create, CI-dispatch and merge route must be exercised. A
permission/provider failure is nonzero and retains sanitized stage/context.
When Actions PR creation is denied, authenticated maintainer generation is a
**degraded fallback**, not unattended completion. Never expand a token or
change policy to make the proof pass.

The owner-authorized publication route was enabled on 2026-10-21: the
organization permits Actions PR creation/approval and Platform enables that
capability. Default workflow permissions remain `read`; workflow jobs retain
their existing explicit permission scopes. The other five existing
organization repositories explicitly retain the disabled PR capability.
Organization changes can affect inherited settings, so inspect the effective
setting when adding a repository. Restore the organization and Platform
capability to disabled to roll back this route; retain read defaults and branch
rules. Actual production-cycle evidence and its limitations belong to
[Issue #202](https://github.com/PolySia-Systems/Platform/issues/202).

The owner approved and installed the private `polysia-platform-dependencies`
App (App ID `5408199`, installation `173681867`) on Platform alone on
2026-10-21. Its only grants are pull requests write and implicit metadata read;
webhooks, user authorization and device flow are disabled. The exact PR-author
login `polysia-platform-dependencies[bot]`, numeric bot ID `345725125`, and Bot
type are required. This does not add the App to the trusted commit identities.
Canonical commits, protected merge and guarded cleanup retain the existing
scoped `GITHUB_TOKEN`; report and health jobs receive no App credential.

Repository Actions secrets `DEPENDENCY_PUBLICATION_APP_CLIENT_ID` and
`DEPENDENCY_PUBLICATION_APP_PRIVATE_KEY` supply only the trusted-main publisher.
The official MIT-licensed `actions/create-github-app-token` v3.3.0 is pinned to
verified commit `64ab729a6294000f5aa4a4bc0b73d1f32bc45510`. It requests only
Platform and pull requests write, masks its token, and revokes it in its default
post step (tokens otherwise expire within one hour). The publisher verifies the
installation/slug and token repository inventory before branch mutation. Only
PR creation uses this separate token, through the child process environment;
it never enters arguments, artifacts or candidate execution. No new Python or
runtime package is required. A maintainer token is not an unattended substitute.

Owner: Platform dependency maintainer. Rotate by generating a replacement key,
updating the repository secret, verifying the next genuine publication, then
revoking the old key. Inspect token-revocation warnings; a successful job alone
does not establish revocation. Rollback: suspend/uninstall this installation,
remove its two repository secrets, and revert the workflow/exact actor entry.
Preserve open proposals and branch rules. The original #215 is historical
engineering evidence; actual App publication, required PR CI, unattended merge
and cleanup acceptance are recorded separately in
[Issue #202](https://github.com/PolySia-Systems/Platform/issues/202).

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
runs for Docker, deployment, runtime/development-lock, entrypoint, health, backup,
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

The [shared validation policy](../03-requirements/developer-context-packet.md#validation-policy-and-local-preflight)
owns applicability for native CI, scoped/full local checking and disposable context
packets. Weekly CI is comprehensive. Workflow, classifier, Gate and trust-control
changes select comprehensive validation. Known control records are validated
against their schema, immutable pin, applicability and consumer evidence without
requiring the full development environment. The complete historical P2 diff also
changed release-manifest implementation and retains image/install obligations.
Every PR runs dependency-free policy/Gate contracts without development installation;
Gate validates policy/source identity, complete inputs, flags and mandatory outcomes.
Job names and native final-head PR and exact-commit release authority are preserved.

Ordinary Markdown about governance, security or operations does not select the
product matrix merely through its directory. It retains document/link, full
Standards, secret, policy-contract and CI Gate checks. Actual instruction/control
inputs (including AGENTS/overrides), executable/non-Markdown document assets,
unknown inputs and mixed risky changes retain their required coverage. No skip
label or Windows-off switch can cancel a mandatory check. Gate verifies the
explicit skipped outcome for unselected jobs as well as success for required jobs.
A lightweight documentation run produces no replacement release image; later
release publication still requires full exact-source validation and artifacts.

### Full Windows health observation

`windows-health.yml` observes trusted-main CI daily at 06:43 UTC. It runs only the
stdlib `scripts/windows_health.py` with the existing `contents:read`, `actions:read`
and `issues:write` permissions. It installs no product, dispatches no tests and
executes no PR code. Weekly full CI remains the producer of periodic evidence.
GitHub schedule configuration does not prove future clock execution or independent
monitoring; see [GitHub's schedule semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Qualifying evidence must come from CI push/schedule/manual runs on this repository's
main, with exact source SHA/attempt, Windows runner, complete successful install,
compile, full Pytest, integrity, lock, build and CLI steps. The observer records
workflow/Windows-job and dependency/metadata input hashes; timing retention is
required when present in that source's contract. Failed/partial runs and nine-day
overdue execution are actionable. Unrelated lightweight green runs and in-progress
attempts cannot clear a failure. Only later complete qualifying Windows evidence
can recover it.

Observation is bounded to 100 main CI run summaries, 30 job queries and 12 meaningful
source candidates, stopping at a verified success boundary. Insufficient history,
unsupported source contracts, API denials and notification errors remain visible.
One marker-identified health Issue is created/reopened/updated only on meaningful
state changes and closed on recovery. While healthy it stays quiet. Inspect that
Issue and the observer workflow on failure, repair the native CI cause, and let a
qualifying full Windows run establish recovery. Do not expand permissions or copy
PR statuses. Rollback is revert of the validation-efficiency merge; disable only
this observer if it is the failing route, retaining weekly CI and main protections.

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


## E2 direct runtime imports (2026-10-26)

The disabled session composition now directly declares three packages already
present at exactly the same versions in both canonical locks. No resolved
package or version is added or upgraded: `cryptography==50.0.2` (Apache-2.0 OR
BSD-3-Clause), `eth-account==0.13.7` (MIT), and `httpx==0.28.1` (BSD-3-Clause).
License expressions are from the installed distributions' metadata. These are
maintained within the existing complete dependency lifecycle/advisory closure;
this statement does not claim latest-version or advisory-free status.

Cryptography supplies explicit Ed25519 receipt verification. Reusing JWT actor
labels or an editable grant would not verify this canonical owner envelope; a
new PKI service is unnecessary. Eth-account verifies the actual prepared EIP-712
EOA signature against the authorized exchange. Trusting an unsigned SDK object
would omit that boundary; implementing Ethereum signing independently would add
avoidable cryptographic code. HTTPX provides a bounded streaming transport for
all existing SDK/RPC clients, including request admission and retained evidence.
An unwrapped SDK transport would escape the financial request/byte owner.

Security-sensitive reachability is restricted to the new disabled composition
and separately gated account qualification. Tests use generated keys and HTTP
fakes; no real credentials are read. The exact existing versions remain pinned
and the Standards import mapping records their direct ownership. Regenerate
locks through `scripts/dependency_locks.py`; never hand-edit rows. Removing the
new composition and its direct declarations reverts this reachability; preserve
financial state, witness, consumed receipt custody and STOP. Existing SDK/PyJWT
transitive requirements remain and are not removed as part of rollback.
