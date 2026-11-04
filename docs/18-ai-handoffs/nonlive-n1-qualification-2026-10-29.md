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

## Initial operational gates — superseded by the dated receipts below

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

## Installed finite attempt — 2026-11-04, acquisition stopped

**OBSERVATION_BLOCKED. Qualification is not complete.** The server never passed
the two-window canary and has collected **zero hours** of useful observation.
The mandatory real 48-hour period and final evidence review remain outstanding.
Do not describe this state as OBSERVATION_RUNNING.

The corrected release integrated through
[#249](https://github.com/PolySia-Systems/Platform/pull/249) at
`b051940aa5ce707c927b627e66a7da9cd85fdce5`.
[Exact-main CI 41812018960](https://github.com/PolySia-Systems/Platform/actions/runs/41812018960)
passed quality/full tests, Windows, browser, container, installed-package and
CI Gate checks. Supply-chain was skipped by the change classifier; comprehensive
[parent CI 41809429506](https://github.com/PolySia-Systems/Platform/actions/runs/41809429506)
passed strict OSV/SBOM gates with identical dependency inputs. Its superseded
automatic push run was cancelled; that run is not recorded as passed.

Both hosts verified the exact CI artifact `13311494736`, ZIP SHA-256
`44aa3b9e13175f663bcd5247bad8eaea539046181709be07fbf30514950a2bc9`.
The installed image is
`sha256:cc6cc42f73acbd47ea912efafe2594143579728caecf6a3184f523e41253fa45`;
archive SHA-256 `0be71067e06afc10de48fb7b8cdd0e5587cf8334d00f292964e026e266d7ebe3`;
first-party package digest
`c1af74e0c122e32d4cce5ad1d41ffbd74af06ce0d92b937335b625ad4127d4a0`.
All 333 installed first-party files matched the integrated Git bytes. The
retained non-flat copy passed transition, historical report, isolated drain,
autonomous stalled-flow STOP and actual installer/mount preflight checks.
The supported primary installation completed at 10:28:15 UTC, preserving
credential bytes, the unrelated 3x-ui service and all economic rows.

Exactly one finite grant was issued. Its frozen start is
`2026-11-04T10:28:52.481150+00:00`, expiry
`2026-11-06T22:26:02.810673+00:00`, cohort digest
`df10f8304eee1cf2983097d997d70c3f76a7d1d1bfb79a92e9593ab7fd36ad09`,
policy digest `faaaaa2c67c1604e858f1574b569901ea5339ef615c710514b2eb8058461bb16`,
configuration digest `0a4f4577443d38c6aa59cd2f56369ea30dcf18633fc244078390203ea65ab417`.
Frozen plan SHA-256 is
`4f46710daa78d78d1647132842f347ceba356dcd3c4d7b95cc2890288b7f1d92`.
The additional ceiling is 45,000 attempts / 251,658,240 response bytes;
cumulative ceilings preserve the old 210 attempts / 66,657,509 bytes.
Rolling caps remain 900 requests / 64 MiB per hour, response cap 4 MiB,
timeout 15 seconds, cadence 60 seconds, container 512 MiB / 0.5 CPU and
free-disk floor 9 GiB. Closure reserves remain 60 requests / 8 MiB.
No grant renewal, consumption reset or acceptance restart occurred.

At 10:29:05 UTC the retained cohort's required 300-second activity window
returned a complete empty v2 page: `data: []`, `has_more: false`, no next cursor.
The [current official contract](https://data-api.polymarket.com/v2/openapi.json)
specifies epoch-second bounds and recognizes an empty page as a valid result.
The worker correctly reported `native_cohort_revalidation_insufficient`.
This establishes insufficient current qualification evidence for that cohort;
it does not establish a provider outage or a decoder defect. No replacement
wallet, older activity, invented quote or looser criterion was substituted.

Protected administrative STOP followed, retaining the operating-system fence.
The actual installed supervisor subsequently persisted `FAILED` /
`useful_poll_flow_stalled` at 10:37:41 UTC. Actual private-TLS controls then proved
pending-versus-observed semantics, one durable duplicate revision, lost-reply
recovery, stale/wrong-target denial, STOP with zero source I/O and restart with
unchanged consumption. Resume dispatch was APPLIED, and the independent failed
campaign immediately retained STOP before source I/O. **Resume dispatch did not
produce a running data path.** Actual-session drain remains proved on the retained
installed copy only; the original session and its nine positions remain preserved.

## Measured coverage and recovery — 2026-11-04

The 10:48:15 UTC read-only receipt verified one grant, 211 total attempts,
66,657,594 total accounted response bytes, zero uncertain reservations,
durable STOP, the restart fence, no acquisition container and no pending commands.
Additional campaign consumption is **one request / 85 bytes**, with 44,999
requests / 251,658,155 bytes unspent. The single HTTP duration was 188 ms;
percentile claims are unsupported. There were no new successful research polls,
fresh evaluations or unique admitted events. Cost per useful event is undefined.
Request diagnostics cover 1/1 requests with duration; 0/1 has a poll correlation
because the read was cohort qualification before a poll existed.

Native spans/measurements remain zero and the native health sidecar/cache are
absent for this attempt. Operational cache savings, stage latency, CPU/RSS and
sustained throughput are therefore UNKNOWN / NOT_EXERCISED. Retained evidence
still proves 40 comparable broad/narrow response pairs and the offline contracts;
those results do not substitute for live optimized-path measurements. The actual
financial journal remains 148 events / 296 evaluations / 22 ledger entries with
nine open virtual positions. Long-gap live catch-up was not reached. Host free
disk was 23,848,271,872 bytes (22.21 GiB), above the unchanged floor.

The first new backup failed because the private artifact downloader's mode-0600
files were preserved by installation and were unreadable by the backup identity.
Only hash-verified non-secret release assets were normalized to the existing
mode-0644 convention; private configuration, ZIP and download-directory protection
were retained. Code/archive hashes were unchanged. The downloader was corrected
for future verified assets and cache reuse. The failed receipt is retained.

Exact current encrypted recovery then passed:

| Receipt | Measured result |
|---|---|
| Generation | `platform-20261104T104358Z.tar.age`, 147,195,160 bytes |
| Ciphertext SHA-256 | `db4afb134544602a5f532bf533ec5d2ecfec6da616eccc1dec398b1a884ec262` |
| Primary | ENCRYPTED_UPLOADED, no observational snapshot errors |
| Independent restore | VERIFIED_ISOLATED_RESTORE, same source/filename/hash, network none, acquisition false, STOPPED |
| RPO / RTO | 64.851 / 47.471 seconds; configured objectives met |
| Analytical digest | `4b4e5dc8cee13dad8d02f8d6b1644dd4323d7ae30b90fe5b79037e7ebb26df84` |
| Vault files | 441,237,894 bytes within the existing 4-GiB allocation; the underlying host filesystem is shared |

The fixed predecessor rollback was hash-verified again. Restoring it must still
reconcile the newest spent authority; it cannot refund this finite attempt.
Primary publisher/backup/recovery-status timers and secondary restore.timer are
active. The acquisition worker timer is inactive and both STOP fences remain.
No all-true canary control-proof file was fabricated from these partial controls.

## Current verdicts and remaining work

| Verdict | Dated assessment |
|---|---|
| ENGINEERING | PASS for integrated tested changes; real optimized-path performance remains unmeasured. |
| CONSOLE_CONTROL | PARTIAL: protected dispatch/denial/STOP/restart proven; useful running/resume blocked by current cohort evidence. |
| INTEGRATION | PASS through normal protections at the exact release above. |
| DEPLOYMENT | PASS, installed and independently recovered while acquisition is fenced. |
| SUSTAINED_NONLIVE | BLOCKED / NOT_QUALIFIED: canary FAILED, useful observation 0 hours; mandatory 48 hours and final review remain outstanding. |
| REPOSITORY_CLEANUP | PASS for assessed items; #208 remains maintainer-owned, and unique local dependency-review work is retained. |
| HUMAN_ACCEPTANCE | BLOCKED: actual human feedback absent. |
| PRE_LIVE_READINESS | BLOCKED by the independent account/custody/ADR/envelope/recovery/human gates above. |

#207 and #232 closed after current meaningful native evidence checks passed.
The first local Windows-health invocation failed on the local cp1252 decoder;
the same existing check passed with `python -X utf8`, then closed #232. That local
tooling failure is separate from passing native Windows CI. #208 is the sole
remaining open Issue. All assessed proposal branches are removed after their
exact commits were integrated or preserved. The local
`codex/dependency-runtime-review` worktree retains unique rejected work and is
not force-deleted. Documentation-report branches are temporary until protected merge.

The existing heartbeat remains active for meaningful state changes, expiry and
required final review, with silence for unchanged fenced failure. It must read
current protected receipts and must never replay the initial-grant helper or
renew the grant. No observation window may be declared from idle time. Any
permissible repair/restart needs an explicit retained reason, the same immutable
identities/criteria and enough remaining original authority. At expiry, verify
acquisition stopped and review all actual evidence again. This record is a
blocked operational handoff, not completed qualification.

## Owner-requested bounded readiness repair, 4 November 2026

The owner requested immediate engineering with server-owned real waits and the
existing automatic follow-up. The repair separates bounded PREPARING from useful
acceptance: the earlier campaign started its poll-gap clock before cohort
revalidation could produce any admitted poll. A valid empty response is retained
as adverse source-availability evidence; it is not a provider fault or a pass.

The candidate adds an explicit, idempotent, STOP-only repair command
`python -m polysia.deployment.nonlive_campaign_repair --config PATH`. This command
requires a root-owned `campaign_repair` definition in the worker configuration,
bound to the exact original plan bytes, prior failed status bytes, reason,
authorization reference, same cohort/policy and installed source/image/config.
It preserves the prior status and accounting in a bounded recovery receipt.
It cannot grant, resume, reset consumption or replace an existing repair attempt.
Use the supported retained-session source transition for a tested repair release;
never replay the consumed initial-grant helpers.

PREPARING receives no qualification credit. A real fresh successful poll, fresh
evaluations, current native telemetry/process observations and attempt-bound
control/recovery evidence must precede the prospective two-window canary.
The unchanged 48-hour useful observation follows that canary. Readiness stops if
less than both required periods plus a 30-minute margin remain before the
original expiry. All preparation I/O consumes the original finite allowance.
Complete quiet revalidation never refreshes selection timestamps: still-valid
evidence retains its original age; the existing four-hour selection limit holds.
Incomplete/provider failures retain fault handling and STOP controls. The frozen
300-second source window and 900-second useful-observation gap are unchanged.

This candidate is engineering work pending protected CI/integration and exact
artifact commissioning. It does not change the last verified fenced host state
or claim useful observation. No new grant, relaxed acceptance, financial
authority or Live activation is authorized. The existing heartbeat must resume
the concrete PR/CI work, then inspect protected current receipts; it must not
poll through the real canary or observation in an active model turn.

## Readiness repair installation, 4 November 2026 13:19 UTC

PR #251 passed all required checks in run `41829429646`, including Windows and
CI Gate, and merged through normal protections as
`783954f9c9fb1ffef3905c2536f503df71f3f43b`. Exact-main run `41832421155` then
passed quality, Windows, browser, container, installation and CI Gate. Its
classifier skipped supply-chain; full parent run `41809429506` passed those gates
with identical dependency/build inputs. Local full pytest also completed:
2,009 passed, 33 skipped in 486.33 seconds. Earlier local fixture/setup failures
were corrected and are not represented as passing invocations.

Artifact `13322459418` ZIP SHA-256
`9c56daf9a7779b405f87be1c71732e072ca65d39f6025c4a05fb963e3d8cacbb`
was downloaded directly on both pinned hosts without transferring an account
token. All 334 first-party files matched Git. Image
`sha256:12dff8e3cae85e8e9e8dcecb0ac1d73271ee4dc30ade92a83c423482b724639d`
and package digest
`5308d9ef5c9a67311785e575b5587460d07f22b7f4fee68708cd1231ce7c10c3`
were verified independently on both hosts. Archive SHA-256 is
`8c3f978077bde2384b901034989e04d1a644c5b2c066824d47da7e994cad1468`.

An isolated retained-copy proof exercised the installed repair command twice,
kept the existing finite grant/accounting and every economic row, and retained
the original failure. It proved PREPARING/idempotency, STOP fault detection,
nonliquidating drain, historical report integrity and 40 retained metadata
comparisons with network none. A helper placeholder substitution failed before
remote execution; that preparation failure was corrected before the proof ran.

The supported journaled transition and shipped installer then installed this
source on Helsinki with durable STOP and the OS fence retained. The original
plan bytes, admission expiry, cohort, financial experiment, consumption and
private credential bytes were preserved. Repair attempt
`a93866a41fff3006f6282bcc538cb2fc61656be610517a63577d39c1d423dab6`
records `owner-n1-readiness-20261104` and the premature-flow-clock repair reason.
The original failed status/accounting remains in its receipt and the protected
`readiness-original-checkpoint`. No new grant was created.

Exact encrypted recovery of the installed repair passed on both hosts:
`platform-20261104T132007Z.tar.age`, 147,246,376 bytes, SHA-256
`fbaa638653885c3d1ef25bdc0750b5f01c29fd748b92df46ecc9724a59a0b063`.
Independent restore was STOPPED, acquisition false, network none, with measured
RPO 65.197 seconds / RTO 47.986 seconds and the same nonempty analytical digest.
These receipts establish recovery of this generation, not useful observation
or financial recovery. Actual control commissioning and server readiness remain
separate gates. DATA_ONLY / Live-disabled / no financial authority still apply.

## Server readiness commissioned, 4 November 2026 13:26 UTC

Attempt-specific private TLS controls passed: STOP with zero new source I/O,
REQUESTED_NOT_OBSERVED, one durable revision for a duplicate, receipt recovery
after a lost reply, stale-preview denial, wrong-target denial, resume and a new
worker process retaining its due slot. STOP/resume revisions were 12/13. One
complete quiet revalidation charged 85 bytes; restart was WAITING_RETRY, with no
useful poll admitted. The pre-existing transient-failure count of one was
preserved; complete quiet did not add fault strikes. Both STOP fences were
restored after the controlled test.

A second exact encrypted generation captured that spent authority and telemetry
before scheduler commissioning: `platform-20261104T132358Z.tar.age`, 147,256,616
bytes, SHA-256
`1e1b7a9732739197fb72a67711109174f1cfdf739de9429ad70dd3c04a6d09b4`.
Independent STOPPED/network-none/acquisition-false restore passed with RPO 65.912
seconds and RTO 46.848 seconds. The current attempt's control proof binds the
actual control receipt hash, this recovery filename/hash, source, original
campaign/policy/cohort and attempt ID. It is not inherited from the older release.

At 13:26:13 UTC the existing worker scheduler was commissioned for bounded
**PREPARING**, under the same consumed grant. This is readiness operation,
not CANARY or OBSERVATION_RUNNING. The first tick returned
WAITING_SOURCE_EVIDENCE / native_cohort_no_recent_activity. Current acquisition
is enabled within the frozen public-data limits; the OS fence was archived only
after actual proofs, and the worker timer is active. The native worker
independently enforces STOP, expiry, budgets, real faults and the latest viable
canary start (19:56:02 UTC with its margin). Neither consumed grant helper was
replayed. Preparation cannot qualify from idle time or empty activity.

The 13:26:55 UTC receipt confirmed 213 cumulative requests / 66,657,764 accounted
response bytes, uncertainty zero; campaign usage is 3 requests / 255 bytes,
leaving 44,997 requests / 251,657,985 bytes. All 148 events / 296 evaluations /
22 ledger entries and nine virtual positions remain. Native qualification
telemetry is now persisted: zero errors/drops, two process samples, peak RSS
128,004,096 bytes, peak observed CPU 35.229% of one core and free disk at least
23,370,416,128 bytes. These are short prequalification samples; operational
cache savings, sustained capacity and useful poll latency remain unmeasured.

The real canary anchor is still absent: successful useful polls and fresh
evaluations are zero. The requested two-hour report must follow an actual future
canary_started_at, not installation, PREPARING or this chat's time. Only its
accepted two real windows may start the unchanged 48 useful real hours. The
existing automatic follow-up remains active; no model polling loop owns this
operation. Financial authority and Live remain NOT_AUTHORIZED / NOT_PERFORMED.

| Verdict | Dated readiness assessment |
|---|---|
| ENGINEERING | PASS for integrated and installed repair; useful real workload validation remains pending. |
| CONSOLE_CONTROL | PASS for actual bounded readiness STOP/resume/restart/negative controls; useful-flow acceptance remains separate. |
| INTEGRATION | PASS at exact-main source and CI above. |
| DEPLOYMENT | PASS with independent exact encrypted recovery; current phase is PREPARING. |
| SUSTAINED_NONLIVE | PENDING / NOT_YET_QUALIFIED: zero useful observation hours; real canary, 48 hours and final review outstanding. |
| REPOSITORY_CLEANUP | Assessed earlier items complete; #208/unique local work retained; this operational report awaits protected integration. |
| HUMAN_ACCEPTANCE | BLOCKED: actual human acceptance absent. |
| PRE_LIVE_READINESS | BLOCKED by the independent account/custody/ADR/envelope/recovery/human gates; no financial action performed. |

## Terminal failed-attempt review, 4 November 2026 22:27 UTC

**SUSTAINED_NONLIVE: NOT_QUALIFIED.** The server independently persisted FAILED /
`insufficient_remaining_real_observation_authority` at
`2026-11-04T19:56:10.700827+00:00`, before another acquisition request. The last
source response was at 19:55:11.706253 UTC. No canary_started_at or
observation_started_at exists: neither two accepted real rolling windows nor
the required 48 useful real hours was achieved. The requested two-hour pass
report cannot be issued. PREPARING and idle wall-clock time receive zero credit.

This is the terminal review of a failed finite attempt, not successful
qualification or a waiver of its required real period. With the original grant,
unchanged criteria and remaining time, completion is no longer possible. No
further restart, replacement cohort, new grant, expiry extension or acceptance
relaxation was performed or is authorized by this closeout. The unused allowance
is retained, not refunded or converted into qualification.

The 22:24 UTC protected read verified acquisition already durably STOPped by the
server with unchanged accounting since its last request. The administrative
closeout then restored the OS restart fence and stopped the acquisition timer;
no acquisition container remains. This added a STOP receipt, not source I/O.
The exact failed phase/reason, original failed attempt, repair receipt, immutable
plan and policy, all consumed accounting and virtual inventory remain preserved.

Measured retained evidence was reviewed without making another provider request:

| Measure | Actual result and limit |
|---|---|
| Cumulative authority | 454 requests / 66,678,249 accounted response bytes; uncertainty zero; exactly one finite grant. |
| Finite campaign consumption | 244 requests / 20,740 response bytes, including the original 1 request / 85 bytes; 44,756 requests / 251,637,500 bytes remain unspent. |
| Repair consumption | 243 requests / 20,655 bytes, all complete empty responses, first at 13:23:06.460944 UTC and last at 19:55:11.706253 UTC. |
| Evidence coverage | All 244 response hashes and frozen user/TRADE/300-second filters verified. Repair windows cover 23,825 seconds in union with no uncovered gaps; maximum request-end spacing 184 seconds. This describes provider responses, not independently proven absence of on-chain activity. |
| HTTP latency | 244 samples; nearest-rank p50 212 ms / p95 274 ms / p99 327 ms, mean 220.852 ms, range 134–614 ms. |
| Native qualification latency | 243 cohort_revalidation spans, all ok; p50 235.441 ms / p95 297.803 ms / p99 348.748 ms, mean 246.203 ms, range 156.975–635.122 ms. |
| Native correlation/health | 243/243 repaired qualification calls instrumented; zero admitted poll correlations because no admitted polls occurred. Zero telemetry errors/drops, no retained history-gap/fault flag. The first original-release attempt had no native span. |
| Process observations | 243 samples; 19.204 process CPU seconds across 62.694 sampled wall seconds, observed peak CPU 40.675% of one core, peak RSS 128,077,824 bytes, minimum sampled free disk 23,338,639,360 bytes. These are short qualification-call samples, not whole-host or sustained-load measurements. |
| Useful workload | Zero admitted polls, fresh evaluations, accepted canary windows and useful observation hours. Existing 148 events / 296 evaluations / 22 ledger entries and nine virtual positions preserved. |
| Operational cache/cost | Optimized-path cache savings, useful end-to-end latency and sustained throughput NOT_EXERCISED. The measured incremental public-data payload is 20,740 bytes; monetary provider/hosting cost was not measured. No new paid provider or infrastructure was introduced. |

The response envelope and request contract were cross-checked against the
[official account activity documentation](https://docs.polymarket.com/api-reference/feeds/list-account-activity).
No request/filter defect was established. The cause of empty responses beyond
the API boundary (wallet inactivity versus provider publication/indexing delay)
remains unproven. Historical activity cannot establish present availability.
The retained failure counter of one was not reset; valid empty responses did
not accumulate new fault strikes or manufacture eligibility.

After STOP/fencing, exact final spent-state recovery passed again:

| Receipt | Result |
|---|---|
| Generation | `platform-20261104T222519Z.tar.age`, 148,516,440 bytes |
| Ciphertext SHA-256 | `891ee15a4bee14be9bba70dbb2900ce128c5edc4a37117dfd3b09e2cb54f743f` |
| Primary | ENCRYPTED_UPLOADED, same installed source, no observational snapshot errors |
| Independent recovery | VERIFIED_ISOLATED_RESTORE, same filename/source/hash, network none, acquisition false, STOPPED |
| RPO / RTO | 67.229 / 48.150 seconds, configured objectives met |
| Analytical digest | `4b4e5dc8cee13dad8d02f8d6b1644dd4323d7ae30b90fe5b79037e7ebb26df84` |

The protected failed-readiness-review receipt preserves measured evidence.
The runtime's final_review=REQUIRED field is an automatic request for operator
review; this dated closeout records that review externally without rewriting
the adverse campaign state. Original expiry remains 6 November 22:26:02.810673
UTC; STOP and the OS fence prevent further operation independently of expiry.

| Required verdict | Terminal failed-attempt assessment |
|---|---|
| ENGINEERING | PASS: integrated tested repair, exact installed-copy accounting/idempotency proof and native fault detection; real useful performance remains unqualified. |
| CONSOLE_CONTROL | PASS for actual private-TLS STOP/resume/restart/negative controls on bounded readiness; no claim of a successful useful canary. |
| INTEGRATION | PASS: protected PR #251 and exact-main CI. |
| DEPLOYMENT | PASS: exact source installed, final spent-state independently recovered, acquisition STOPped and OS-fenced. |
| SUSTAINED_NONLIVE | NOT_QUALIFIED: no accepted real canary and no required 48-hour useful observation. |
| REPOSITORY_CLEANUP | PASS for assessed items; own integrated branches preserved then retired, #208 and unique dependency-review work retained; closeout uses normal protections. |
| HUMAN_ACCEPTANCE | BLOCKED / NOT_PERFORMED: actual human acceptance absent. |
| PRE_LIVE_READINESS | BLOCKED / LIVE_NOT_AUTHORIZED / NOT_PERFORMED: independent financial, custody, account, ADR, envelope, recovery and human gates unresolved. |

This failed-attempt review closes its operational work with an honest negative
qualification verdict. It does not claim that the original successful
qualification objective was achieved. Once this closeout is protected and the
final STOP/recovery/accounting receipts are checked, its follow-up may end;
unattended acquisition must remain fenced. No external alert was sent.
