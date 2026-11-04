# N1 non-Live qualification — 2026-10-29

This dated record distinguishes engineering, integration, deployment and real
observation. Ordinary resume uses the N1 PR. The activated owner prompt authorizes
one finite public-data/Shadow campaign, Helsinki primary and fenced Nuremberg
recovery. LIVE_NOT_AUTHORIZED / NOT_PERFORMED applies throughout.

## Baseline and evidence definitions

The starting report is PR #238 at `0b283d2709c4ede64d640f87cf8afe26486e6613`.
The deployed predecessor source is `fe645412bc024d2664f4b7aeb102ae9733c30b70`.
The baseline was reused from the owner's independent package. A consistent
retained copy was captured at 10:37:18 UTC: one qualified wallet, nine open
virtual positions, 148 journal events, 296 evaluations and 22 ledger entries.
Acquisition was expired; no provider request was made during this inspection.
Restricted inputs/results remain under `artifacts/n1-20261029/` and the matching
protected host directory. Wallet identifiers and provider bodies are excluded
from Git.

Baseline: 210 attempts and 66,657,509 accounted response bytes; Gamma event bodies
accounted for 59,516,357 bytes. Repeated metadata responses are an optimization
target, not automatically waste. Six successful polls admitted 148 events; all
246 stale UNKNOWN evaluations followed the long budget gap. No production SLO,
provider-only lag or profitability follows from these small samples.

Measurement definitions are frozen before new acquisition: HTTP attempts and
accounted response bytes (not network bandwidth), unique journal events, fresh
evaluations within the existing 300-second age limits, legitimate exclusions,
cache hits/misses/invalidations, monotonic stage durations, poll gaps and pending
wait. Rejected/UNKNOWN outcomes remain visible. Missing evidence stays UNKNOWN.
Deterministic fake response contracts do not establish real provider wire savings.

## Delivered correction and compatibility

Native composition owns telemetry flush at poll exit and publishes errors/drops
even if the optional telemetry database fails. Request receipts retain purpose
and local correlations. Recent SQLite-indexed summaries replace historical
filename-prefix sampling for new requests. The existing typed Console workspaces
show acquisition state, allowance, retry, stage evidence and final-review state.
Financial account mode remains UNKNOWN when uncommissioned.

Native identity lookups use exact Gamma condition filters with explicit
`closed=any`, supported by the [official contract](https://docs.polymarket.com/api-reference/markets/list-markets).
Condition/token/outcome/event linkage is verified. The versioned disposable
SQLite cache survives oneshot restarts, preserves observation time and is bounded
to three hours / 512 entries / 2 MiB payload. Mutable status, fees, resolution,
risk and book evidence remain current reads. Equivalent in-flight identity work
is coalesced within the bounded native source.

Admission remains lock-owned. Earliest eligibility uses actual/uncertain charges
and inclusive rolling boundaries, with bounded settlement rechecks. A separate
audited finite grant preserves historical lifetime usage and independently caps
additional campaign charges; historical settlement cannot expand that allowance.
The old continuation API retains its restrictive semantics.

The supported native release transition preserves all economic rows and records
old/new source/admission bindings. It passed against the retained non-flat copy,
including canonical report validation and the actual installer preflight.
Downgrade over transitioned/newer data is unsupported: use a consistent compatible
checkpoint and reconcile. Disposable caches may be rebuilt.

The encrypted recovery inventory includes the optional native telemetry snapshot
and frozen campaign evidence. A diagnostic snapshot failure is reported without
preventing authoritative database recovery. Recovery stays fenced and does not
evaluate itself as an active campaign. The existing 480 MiB recovery payload cap
is retained, and SQLite copying preserves the stricter 9 GiB free-disk floor.
The new allowance must fit these storage bounds as well as provider limits.

## Operational gates

ENGINEERING: candidate validation in progress. INTEGRATION and DEPLOYMENT: pending
exact final-source CI and immutable installation. SUSTAINED_NONLIVE: pending real
canary and 48 hours of useful observation; ending a model turn is not completion.
CONSOLE_CONTROL and REPOSITORY_CLEANUP: evidence/disposition work in progress.
HUMAN_ACCEPTANCE: pending actual human feedback. PRE_LIVE_READINESS: blocked on
the independent financial/account/custody/ADR/run-envelope gates.

The server uses the existing worker scheduler for frozen campaign checks,
durable evidence and STOP. At least two full rolling windows precede canary
acceptance. Only then can a real 48-hour observation start. Missing control or
recovery receipts, stale/absent useful flow, infeasible projected cost, expiry
or completion stops acquisition and preserves virtual inventory. Final evidence
review remains mandatory. There is no automatic renewal or liquidation.

External alert delivery remains NOT_COMMISSIONED: an exact approved destination
and bounded test are absent. Local fault detection and independent SSH STOP do
not depend on an external recipient. Missing financial gates do not prevent
authorized public-data engineering or observation.

## Validation record

The first local full suite returned 1 failed / 1,977 passed / 33 skipped. Its
failure identified direct RPC receipt retention without native thread context;
the default uncorrelated context was restored. Impacted actual SDK/account,
custody, native-drain, worker and Console regressions then returned 33 passed /
1 skipped. No real accounts were accessed. A later focused telemetry, reporting,
campaign and Console set returned 34 passed. The new campaign/cache/admission
regressions separately returned 18 passed. Required final-head native CI remains
the acceptance gate; the failed local run is not relabelled successful.

Executed local checks: `python -m compileall -q src tests`, `python -m ruff check .`,
`python -m mypy src` (319 modules), `python -m pip check`,
`python scripts/dependency_locks.py check`, `python scripts/validate_standards.py
--mode full`, `python -m polysia.security.secret_scan`, `python
scripts/check_changed_docs.py --local`, `git diff --check` and `python -m build`.
Those checks passed at their recorded candidate states. Final source/package,
Windows, installation and supply-chain identities will be bound to native CI.
Windows local Python is 3.14.7; CI's pinned 3.14.8 owns patch-specific acceptance.

## Integration and repository disposition

The predecessor stack #234, #235, #237, #236 and #238 was integrated through
normal protections. #237 was merged into #236 first to repair its known
installation-test race. #238 was updated against main and passed its checks.
N1 implementation [#240](https://github.com/PolySia-Systems/Platform/pull/240)
integrated at `e96f15d849c9adf20c8dd58790a0f543c6d5f375`; its full native
[CI 40869536317](https://github.com/PolySia-Systems/Platform/actions/runs/40869536317)
passed Linux (1,997 passed / 28 skipped), Windows (1,993 passed / 32 skipped),
browser, immutable image, installation and strict OSV supply-chain gates.

Before activation, inspection found that the host backup job did not mount the
new frozen campaign file. [#241](https://github.com/PolySia-Systems/Platform/pull/241)
fixed that exact mount, with nine focused tests, and passed protected PR CI.
That integrated release source was `5a9a7378199a34b06d87ce57639e8445fd2e994b`.
It was staged and copy-tested, but never activated. Further inspection found
the same missing plan mount in worker/publisher commands; #242 corrects those
mounts and binds standalone backup loading to its own verified sibling release.
Each integrated artifact retains its own identity; preceding images are not relabelled.

Issue #239 was closed after verifying intentional tracked/indexed-file coverage
and final CI. #232's older Windows alert and #207's older dependency-workflow
alert were superseded by verified meaningful successful receipts. The dependency
observer now recognizes the actual approved-App publication step and prevents
callback no-ops from hiding the latest meaningful scan; 62 focused tests passed.
[#208](https://github.com/PolySia-Systems/Platform/issues/208) remains an active
maintainer-owned periodic dependency review: reconsider on a successful scheduled
scan, advisory or demonstrated compatibility failure. No blanket upgrade is approved.

PR #205 was closed as an unapproved stale settings/dotenv/Typer bundle; #212's
optional artifact-action major update and #222's optional setuptools update were
closed as not planned. Current strict advisory/build evidence established no
release blocker requiring those proposals. Their unique commits remain recoverable.
Disposition comments and exact receipt links are indexed in the restricted
`artifacts/n1-20261029/repository-dispositions.json`.

After refreshing stale remote references, eleven assessed remote branches and ten
merged local branches were deleted. The two closed bot branches had already been
removed. At that dated cleanup, main was the sole remaining remote development
branch; later dependency proposals and #242 require a fresh final inventory. The local
`codex/dependency-runtime-review` branch and its existing inactive worktree remain
because they contain unique rejected work; no forced deletion was used. Verified
complete Git bundles and SHA-by-SHA cleanup records are retained under
`artifacts/n1-20261029/`. The report branch is temporary until its protected merge.

## Recovery and authority boundaries

Before the upgrade, acquisition was durably stopped, its operating-system restart
fence retained, and consistent financial/authority/command SQLite checkpoints
verified. Consumption remained 210 attempts / 66,657,509 bytes, with nine open
virtual positions and 22 ledger entries. The encrypted generation
`platform-20261029T151250Z.tar.age` was independently restored on Nuremberg:
`VERIFIED_ISOLATED_RESTORE`, acquisition false, network none, runtime STOPPED,
measured RPO 315.175 seconds and RTO 46.086 seconds. This predecessor recovery
receipt does not establish recovery of the later activated release.

No financial account was queried or mutated by this task. PRE_LIVE_READINESS
still needs fresh complete evidence for the uniquely approved dedicated account,
signer custody, owner acceptance of Proposed ADR-0023, real financial recovery,
a run-specific signed authority envelope and capital/market/loss limits. Human
acceptance requires actual feedback. The missing external alert decision is an
exact approved destination and bounded delivery test. These are separate from
the authorized public-data campaign and do not confer financial authority.

## Resumption — 2026-11-04

Pinned current-host reads at 09:12 UTC found the predecessor release still
STOPped and operating-system fenced. There was no frozen campaign plan, campaign
status or finite grant. Accounting was unchanged at 210 attempts / 66,657,509
response bytes. **No real canary or observation time had accrued.** Idle days and
heartbeat invocations are not observation evidence.

PR #242 adds bounded process CPU/RSS/free-disk observations to the existing
optional native health sidecar. Corrupt history records a gap; probe failure
remains UNKNOWN and preserves the original economic result. Samples cover poll
processes rather than whole-host/container peaks. Local focused validation:
43 passed / 4 environment-gated skips; Ruff, Mypy (319 modules), standards,
secret and changed-document checks passed. One initial Ruff violation was fixed.
An ambient unpinned SDK type-check failure was distinguished from the passing
locked-environment check.

The locked one/five-wallet offline probe produced 4 polls and 40 persisted native
spans per case, respectively 3/15 admitted fixture events, 6/30 evaluations and
6/27 ledger rows. Wall duration was 0.739/0.762 seconds; actual provider requests
were zero. Its first locked invocation imported an older installed package and
failed telemetry assertions; explicitly binding the helper to current `src`
corrected the inspection environment. That failed invocation remains retained.
These fixture results do not establish production capacity or useful observation.

Independent recovery was refreshed at 09:21:10 UTC against the current
predecessor encrypted generation `platform-20261104T001519Z.tar.age`, ciphertext
SHA-256 `d17ebbb2524aa8399ab78b76df4c44af1438c090e50594de40e80e4ad3e4cb39`.
Nuremberg reported VERIFIED_ISOLATED_RESTORE, acquisition false, network none,
STOPPED, RPO 32,737.872 seconds and RTO 48.566 seconds, within configured limits.
Its timer was re-enabled while the primary remained stopped. The fixed Oct-29
rollback generation was hash-verified independently and retained outside rotation.

Main advanced with #248's development-only `filelock` 4.2.4 to 4.2.6 refresh.
#242 was updated normally to `bea58458ad249453d441d065125813bf6fdc81a9`.
Final-head PR CI and comprehensive exact-main CI are activation gates; an older
supply-chain receipt cannot cover the changed lock. Current dependency health
recognized the Nov-02 complete scan/publication and closed the stale #207 alert.
The new #243–#247 proposals were assessed against their exact heads, preserved
in a verified Git bundle and closed as not planned for N1. SDK/authentication
upgrades lacked the separate compatibility decision and synchronized locks;
the action, build-toolchain and six-tool development bundles were optional.
Reconsideration belongs to the dependency maintainer under #208 on an advisory,
demonstrated compatibility failure or accepted maintenance requirement. No new
version is claimed validated by that disposition. Their branches were already
absent after closure; the verified bundle retains all unique work. #232 awaits
the new successful exact-main Windows receipt before reassessment.

PR #242 merged at `f937df50e9465ac00b9a382e6fd9e33878808e93` after final-head
CI 41806113026 passed. The commissioning helper stopped at a transient GitHub
artifact API connection failure before host staging/activation; no provider
request or finite grant resulted. A final second pass found that a later healthy
oneshot process could overwrite an earlier optional telemetry fault indicator.
The correction retains a sticky error/drop indicator and a history-gap marker
in the existing bounded health sidecar, independent of resource-probe success.
A regression exercises a real optional-storage failure, original economic
exception, database recovery in a later process and retained adverse evidence.
All 17 focused N1 tests, Ruff and Mypy (319 modules) passed for that correction;
new final-source CI and immutable deployment remain required.
The System workspace exposes the retained fault and history-gap indicators even
when current counters return to zero. The combined N1/Console regression set
returned 34 passed / 1 skipped after correcting one new test's expectation of
human-readable fact labels; its initial 1 failed / 33 passed / 1 skipped result
is retained rather than relabelled successful.

## Human acceptance and financial readiness

Automated protected-control receipts do not constitute human acceptance. The
acceptance card is to review the existing private Console's acquisition target,
retained history and virtual inventory, pending-versus-applied receipt language,
retry/expiry and stage evidence, and the visible boundary between the CLI-owned
session and uncommissioned Lab operations. Record actual human feedback against
the installed source and dated evidence; do not self-certify it or perform extra
control mutations merely for this card during observation.

| Gate | Current evidence boundary / next decision |
|---|---|
| Dedicated account read | No fresh complete account input or current bounded read approval established; no account selected or queried by N1. |
| Signer custody | No financial signer commissioned or installed by N1. |
| ADR-0023 | Proposed; owner acceptance remains required. |
| Real financial recovery | Nonfinancial analytical recovery does not establish financial recovery. |
| Run authority | No signed run-specific financial envelope or capital/market/loss limits. |
| Human acceptance | Actual human feedback remains required. |
| External alerts | Exact approved destination and bounded delivery test remain absent; local detection and independent STOP are separate. |
| Shadow Lab | Create/Clone/Compare/Archive remain visibly NOT_COMMISSIONED until the acquisition owner registers slots and immutable policy templates under the shared allowance; the retained session remains CLI-owned. |

These missing gates do not block independent authorized public-data work.
LIVE_NOT_AUTHORIZED / NOT_PERFORMED remains the financial verdict.
