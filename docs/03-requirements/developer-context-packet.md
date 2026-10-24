# Developer Context Packet

- **Status:** CURRENT
- **Mode:** local developer tooling
- **No authority:** no Live, Risk, Execution, wallet, order, or host-control path

Produce a bounded, deterministic context packet so a model without chat
history can resume one scoped repository task from repository truth.

## Developer entry

Use CPython 3.14.8 and the locked environment from the root
[README](../../README.md#requirements-and-installation). Initial pip/Conda
bootstrap needs package-network access. No `.env`, provider credentials,
owner account, manifest or running server is needed afterward:

```bash
polysia system health
polysia research paper-trade --token-id fixture-token --order-size 1
python -m pytest -q tests/integration/test_native_drain_transport.py tests/unit/monitoring/test_console.py
```

These are offline fixtures, with no economic or capacity acceptance claim.
An installed server also offers `/demo`, separately labeled and read-only;
its JSON cannot become a canonical financial report. Ordinary Console reads
use retained data and never acquire provider data.

| Feature | Module | Contract | Focused evidence |
|---|---|---|---|
| Close-only native drain | `cli_support/native_lifecycle.py`, `application/services/continuous_shadow.py` | Original identity/capital; charged complete source and current market evidence; no new entry | `tests/integration/test_native_drain_transport.py` |
| Durable worker/STOP | `cli_commands/platform_worker.py` | No authority initialization on lost state; independent STOP and explicit receipts | `tests/unit/cli/test_platform_worker_boundaries.py` |
| Console reporting/auth | `monitoring/console.py`, `deployment/gateway.py` | Canonical report, exact identity/Origin/CSRF, exclusive verifier | `tests/unit/monitoring/test_console.py`, `tests/unit/deployment/test_gateway.py` |
| Guided maintenance | `deploy/platform_admin.py`, `platform_bootstrap.py` | Verified release, disabled activation, retained rollback | `tests/unit/deployment/test_platform_admin.py`, `scripts/installation_acceptance.py` |
| Backup and recovery | `deploy/platform_backup.py`, `deployment/platform_recovery.py` | Real encrypted generation, replay identity and STOP; separately held key | `tests/integration/test_continuous_shadow_portfolio.py`, `scripts/backup_destination_acceptance.py` |

Module paths above are relative to `src/polysia/` unless prefixed by `deploy/`.
Read the relevant path's instructions. For a small status-explanation change,
edit the centralized `STATUS_TEXT` in `monitoring/console_assets/console.js`,
update the corresponding browser expectation, then run that browser test and
`node --check` on the asset. Do not change worker authority states to fit wording.
For a report contract change, first add a canonical accounting fixture, then
change the reporting service and only then its Console renderer. Use the PR as
the resume artifact. Context packets below are optional assistance.

## Required behavior

The Issue or PR remains the ordinary task owner. [`docs/README.md`](../README.md)
remains the canonical documentation entrance. Generated packets are disposable
views and are never project truth.

A packet MUST report:

- repository identity, exact HEAD, and dirty-state fingerprint;
- an opaque Issue/PR identifier when a task reference is supplied;
- applicable `AGENTS.md` files discovered from the repository root toward the
  scoped path;
- relevant requirements and approved ADRs with path, digest, and why they apply;
- implementation boundaries and existing capabilities to reuse;
- validation scope derived from `scripts/classify_ci_changes.py`;
- reusable validation evidence and checks still missing;
- unresolved decisions and the next concrete action.

Task input is untrusted data. The packet and rendered text MUST contain only a
sanitized opaque identifier such as `PR #123`, or an omission marker. Raw task
text MUST NOT appear in JSON, excerpts, `next_action`, or human-readable output.
The tool MUST NOT read secret files, execute Issue/PR/log text, or silently
omit safety instructions when excerpts are truncated. Cache reuse is valid only
when HEAD, sanitized task reference, instruction digest, scope, and environment
fingerprints match. Dirty worktrees bypass the cache because a path-only status
fingerprint cannot prove that scoped file contents are unchanged.

Dependency preflight MUST remain offline, scoped and explicit about missing or stale
metadata. It reports GO, CONSTRAINED_GO or BLOCKED and includes relevant manifest,
lock, policy and tooling content hashes plus scan identity and age in cache
invalidation. Runtime/SDK/build/interface changes require deeper validation;
routine prose must not start an online audit. Registry coverage never replaces
final candidate CI or the advisory gate. No installed-host claim follows from
source pins or cached metadata.

Dependency-classified changes include both configured supply-chain gates:
`python -m pip_audit --strict --vulnerability-service osv` and
`cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json`.

## Command

```text
python -m polysia.cli system developer-context \
  --task <issue-or-pr-reference> \
  --scope <path> \
  --json-file artifacts/developer-context.json
```

Human-readable text is the default stdout. JSON is versioned as
`developer-context-packet-v1`.

## Validation policy and local preflight

The compact `validation.policy` projection is version 1 and is owned by
`scripts/classify_ci_changes.py`. It includes stable check IDs, exact source
event/base/head, policy content identity, complete changed paths, required
flags, execution contexts, reasons and conservative-fallback diagnostics.
CI, `fast_check.py` and packet/catalog recommendations MUST consume this policy;
execution adapters may differ. Unknown versions, flags, IDs or incomplete policy
data MUST fail visibly rather than make work optional.

Document-selection scope MUST NOT remove actual validation inputs. Packets union
requested scope with the complete branch diff against `origin/main`, staged and
unstaged changes and relevant untracked files, including both rename sides and
deletions. NUL-delimited Git output preserves irregular names, which select full
validation. A missing base uses the verified HEAD/tracked inventory and selects
full validation; unavailable Git identity fails visibly. Empty ambiguity selects
full validation. Scope and policy/source identity participate in cache invalidation.
Existing dirty-cache refusal, sanitized task references and retained safety text
remain mandatory. The legacy classifier injection argument is retained for API
compatibility; it cannot override the authoritative shared policy.

Every PR requires path/link/diff hygiene, full adopted Standards validation,
tracked-secret checks, policy/Gate contracts and the native CI Gate. Recognized
editorial files skip development installation. Governance, trust controls and
executable document assets are not blanket prose. Known adoption/conformance
records require the full schema/pin/applicability/fact/evidence validator and
consumer contracts; unsupported record schemas or meanings fail validation.
Executable Python/tooling requires the complete canonical Linux behavior/safety
suite plus compile/lint/type/integrity and applicable package checks. Console,
API, assets and transitive browser inputs add browser acceptance. Dependency,
bootstrap and supported OS-sensitive changes add full Windows; Docker's
development lock also selects image and real install/recovery validation.
Release-manifest implementation retains image/install checks. Unknown scope,
workflow/classifier/Gate/trust changes and weekly CI select comprehensive work.
Explicit release validation requires the complete exact-main-commit matrix and
source-bound artifacts; no dispatch result or equal-tree claim replaces native
final-head PR checks or another commit's artifacts.

`fast_check.py --mode scoped` runs applicable portable commands without installing
anything. `--mode full-local` selects all checks; `--plan` prints the policy.
Required native contexts remain pending with exit 2 after successful local work.
The no-argument legacy command is unchanged except for an accurate label: it
omits Pytest/build and is not comprehensive. A local Windows run never proves the
canonical Linux suite. CI Gate re-collects the actual diff, verifies the full
projection and routing flags, and rejects missing, failed, cancelled, timed-out
or unexpectedly skipped mandatory jobs. Dependency-free policy/Gate contract
tests run in both classification and Gate even for editorial changes.

Evidence is explicitly separated into recommendations, verified evidence,
stale/failed evidence, and unknown/unavailable evidence. The packet does not
fetch native CI, so its verified evidence list is empty. A clean SHA is only a
candidate for reuse after its native evidence has been inspected.

Full Windows runs retain `--durations=25` and standard JUnit timing XML as the
`windows-timing` artifact. Inspect timing before changing test execution; preserve
assertions, isolation, durability and recovery. Targets are under two minutes for
genuine editorial PRs and under five for non-OS Linux/tooling without install
scope. Report observed sample count, median and range separately from conditional
counterfactuals, runner time, task elapsed time, actual tokens and retrieval proxies.
Do not manufacture samples or claim token savings without reliable telemetry.
