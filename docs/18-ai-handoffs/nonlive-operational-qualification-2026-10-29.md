# Non-Live operational qualification — 2026-10-29

This is dated operational evidence, not a live status page. The final primary
sample was taken at **2026-10-29 00:23:12 UTC**. The owner explicitly expanded
the original D2 preparation scope to actual non-Live setup, public acquisition,
Shadow operation, necessary fixes and verification. Real financial actions
remain prohibited. No financial authorization, signer, real order, cancellation,
transfer, redemption or account mutation was created or performed.

**Requested bounded operational check: completed, with a negative sustained
capacity result.** Real public data reached the canonical persistent Shadow
engine, portfolios, reports and protected Console. Timers remain enabled, but
acquisition is currently waiting on its existing byte-window guard. This is not
continuous-capacity acceptance or a profitability finding.

**D2 readiness verdict: BLOCKED_WITH_PREPARATION_COMPLETE.** Actual human
acceptance, alert delivery, real-account completeness and financial commissioning
remain separate, unperformed gates. No further owner input was needed to perform
this non-Live check. See [D2](console-d2-readiness-2026-10-28.md) for the inactive
financial run specification and future owner decisions, and
[D1](console-d1-deployment-2026-10-28.md) for the original installation and trust.

## Exact implementation and installation

The engineering changes are in [PR #236](https://github.com/PolySia-Systems/Platform/pull/236).
The disposable installation-test correction is stacked in
[PR #237](https://github.com/PolySia-Systems/Platform/pull/237). Neither PR was merged.

| Binding | Verified value |
| --- | --- |
| Final review head | `fc3d919824257bf8f1538a5cc77362e0e358aee6` |
| Native build / deployed source | `fe645412bc024d2664f4b7aeb102ae9733c30b70` |
| Identical head/build Git tree | `00d0d1f7073e4db92d9647d843917327a45dee35` |
| Accepted native CI | [40790796771](https://github.com/PolySia-Systems/Platform/actions/runs/40790796771), success |
| CI image artifact | `12861656473`, ZIP SHA-256 `f47743637e045f882cd8ca34909c42f0fb36ff53965ca1e1094fca9e3a2f2f7a` |
| Image archive SHA-256 | `33c8ef3d175a64bd5d7c2fa77fc6e1ad5f83c8ca5c329d65f2619624165defcf` |
| Release manifest SHA-256 | `3cdf54e0e88ede51881eeabf01de4e427a9de787b7370737e329a4195d8d550c` |
| Helsinki/Nuremberg OCI image | `sha256:bc6bccfbfb8aeb1e2776682e4d21aa3668cf145fcefabdd8bfdaa3a81a19732d` |
| Archive-bound Docker config ID used by Ubuntu CI | `sha256:84d39c047c4498e6fdb360c93c77bf38e6c59a00193ab70ca5ba8c83ea46faa0` |
| First-party package digest | `bc7082a27a41a8d82bd56245c309d2c0a78de822147c044fe148802ea0f0328d`; all 330 files match Git bytes |
| Unchanged Console source digest | `486d16d75740e939912fee9d86a1e9176b1c21e258d14b014b76c1854a598277` |
| Current worker configuration SHA-256 | `fcc1523b826e26a60c7c190c3289cc6e6de789f27bb44f62b185e139f216c4ae` |

The original `8faa568...` installation was upgraded with the exact shipped
`platform_admin.py update`, not a moving branch or a local Windows wheel.
Installation completed at 00:08:58 UTC in one successful attempt. Existing
gateway credentials, CSRF secret and backup upload-key bytes were preserved.
The unrelated `3x-ui` container identity and running state were unchanged.
Strict Ed25519 SSH trust and the existing dedicated Console CA were retained.
No public ingress, DNS, subscription or unrelated service was changed.

Helsinki remains the only acquisition/Shadow writer. Nuremberg remains fenced
recovery. Worker service arguments explicitly retain `TRADING_MODE=DATA_ONLY`
and `LIVE_TRADING_ENABLED=false`; web has no financial-store mount. The existing
modular monolith, independent Risk, Decimal arithmetic and emergency controls
were preserved.

## Demonstrated defects and corrections

1. Native research profiles already admitted 1–10 wallets, but a subsequent
   legacy three-wallet branch rejected native cohorts above three. Exclude the
   named native profiles from that legacy branch; retain all existing caps.
2. The live PolyCop response acquired exactly four profile fields. Accept the
   reviewed complete extension with bounded strings, integer timestamp and a
   retained digest. Keep profile names/URLs out of economic metrics, reject
   unknown/partial shapes and never fetch profile-image URLs.
3. Verified native event mapping needs Gamma `/events`. Add an exact,
   explicitly directed endpoint-addition option to policy continuation. Default
   scope expansion still fails; host, numeric ceilings, reserves, duration,
   retention promises, STOP and consumed reservations remain protected.
4. Event metadata can contain unlaunched sibling markets without dates. Validate
   dates/outcomes/token mapping for the exact requested conditions, while still
   rejecting invalid/duplicate condition IDs and unverifiable requested markets.
   Cache identity includes the requested condition set.
5. Two unchanged installation acceptance attempts raced a scheduled oneshot that
   had read the queue before STOP submission. Quiesce the disposable test timer
   and wait for its current tick before submitting STOP. The exact APPLIED
   assertion remains. The corrected native installation, browser and recovery
   acceptance all passed.

An initial operator configuration label was outside Console v1's dataset enum.
It was corrected to the canonical `RETAINED`, with all other configuration
unchanged. This restored publication context; real account/financial identity
remains absent and UNKNOWN. Shadow monetary values are explicitly virtual.

## Public inputs and bounded authority

The original allowance began at 20:06:27 UTC on October 28 and expired during
engineering. One explicit continuation at 23:17:26 UTC retained all 19 consumed
reservations and added only the required public `/events` route. No lifetime
quota was replenished. Later artifacts were bound to the same task purpose,
host, endpoint set, counters and finite window.

| Current allowance | Value |
| --- | --- |
| Policy digest | `cf1f59367e0506765e2b5474caf870b9591402677d581c0747aa82f4b36c42dc` |
| UTC window | October 28 23:17:26 through October 29 01:17:26 |
| Lifetime ceilings | 600 requests; 134,217,728 bytes |
| Rolling-hour ceilings | 300 requests; 67,108,864 bytes |
| Closure reserve | 60 requests; 8,388,608 bytes |
| Response / timeout | 4,194,304 bytes; 15 seconds |
| Workload / resources | At most 5 cohort members; current cohort 1; minimum cadence 60 seconds; 512 MiB RAM; 50% CPU |
| Retention / disk reserve | 7 days; 2 backup generations; 9,663,676,416 free bytes |

Only public GET paths were used: Data API v2 trades/activity, Gamma markets/events,
CLOB book and PolyCop leaderboard. Public positions was allowlisted but unused;
no authenticated account route was commissioned. The current
[official Data API v2 contract](https://data-api.polymarket.com/v2/docs) confirms
public access and cursor pagination. Goldsky, RPC, new providers and paid
services remain unused.

Native discovery initially sampled 500 seed rows and 279 distinct wallets, then
completed activity walks for five selected candidates. Subsequent strict source
qualification admitted **one of three research-eligible candidates**: one had
unverifiable observations and one had no measurable activity. Exclusions were
retained; no dates, activity, fills or profitability were invented. The frozen
qualified cohort digest is
`df10f8304eee1cf2983097d997d70c3f76a7d1d1bfb79a92e9593ab7fd36ad09`.

PolyCop completed 14 pages plus a repeated first-page guard: **1,360 records**,
15 requests in the corrected acquisition, observed at 23:18:21 UTC. Dataset
digest: `f021d22bfad10d99541e58d1cb3d054a7dab7adcc2bed6826c34c4c799b963da`.
It is a dated candidate snapshot, not an independent edge or live ranking claim.

## Actual Shadow results and current backpressure

Three successful initial isolated polls produced 13 new events and 14 simulated
evaluations, with six overlap duplicates detected and none processed twice.
A minimal rehearsal on the final native artifact produced four more simulated
evaluations, binding proof SHA-256
`6497c0116730f005e5d2b084209253f89d3c2e78d0ce0cae4216ef0ca7975bbd`.
These are separate virtual sessions and are not compounded into the running one.

Persistent session `837a28d9c8e54e7e9cee303536599173` started at 00:09:27 UTC:

| Retained result, cutoff 00:13:12 UTC | Value |
| --- | --- |
| Successful polls | 4 |
| Raw / new source events | 34 / 25 |
| Detected / processed duplicate events | 6 / 0 |
| Simulated / rejected evaluations | 22 / 28, across independent wallet/follower books |
| Follower opening virtual cash | 1,000 |
| Retained follower cash / cost exposure | 975 / 25 |
| Retained marked follower NAV / modeled P&L | 999.84375 / -0.15625 |
| Recorded modeled fees / open positions | 0 / 3 |
| Analytical economic verdict | UNKNOWN / insufficient evidence |

The marked P&L is a retained-cutoff model value, not a current executable exit
value or a realized financial return. Some prospective evidence/terminal
valuation is incomplete; operating costs remain unallocated. Native recency is
not skill, and these observations do not admit Alpha/Stress membership or prove
copyability, profitability or production capacity.

At 00:14:11 UTC the existing `byte_window_exhausted` guard paused acquisition.
At the final sample the enabled worker reports **WAITING_RETRY**, with retry at
**01:14:11 UTC**; last successful source poll remains 00:13:12 UTC. Lifetime
usage is **170 requests / 55,653,845 bytes**, with zero uncertain reservations.
Pre-I/O accounting reserves the maximum response size for in-flight requests;
a later settled total below 64 MiB does not prove that admission should have
succeeded. No ceiling, reserve, retry checkpoint or STOP was bypassed.

Thus the path works, but sustained operation at this workload under the current
window is **not qualified**. The timer is enabled, not continuously acquiring.
Any remaining permitted work ends no later than **01:17:26 UTC / 04:47:26 Tehran**,
or earlier on another guard. There is no automatic allowance extension or reset.
Open virtual inventory is retained; expiry does not imply settlement.

Endpoint receipts cover 170 completed HTTP requests, zero HTTP failures/429s and
no missing latency measurements. Observed p95 latency: CLOB book 94 ms, activity
193 ms, trades 222 ms, Gamma events 564 ms, Gamma markets 169 ms, PolyCop 1,356 ms.
Gamma event bodies account for 48,755,138 bytes of the retained traffic. The
capacity limitation is separate from provider HTTP availability.

At the final sample free disk was 25,220,378,624 bytes, available RAM
3,035,922,432 bytes, and NTP synchronization was `yes`. One candidate resource
sample used 110 MiB of its 512 MiB cap. This is a small workload observation,
not a peak-load or 10,000-wallet qualification.

## Controls, Console and recovery

The original D1 STOP receipt, revision 1, remains APPLIED. The actual owner-directed
nonfinancial resume was applied as revision 2 before the original OS fence was
archived. Fence SHA-256 remains recorded as
`7cb6403b37504a392de0db6a4afad9213c6f6990d6566bc5ce189589000dd8d1`.
This was an explicit nonfinancial transition, not financial commissioning.

The original allowance was stopped and copied through SQLite Backup API with
all 120 requests / 32,653,200 bytes retained. It stays stopped. Only the primary
copy was resumed. Protected HTTPS STOP/resume revisions 3 and 4 are APPLIED with
OBSERVED effects; STOP consumed **zero** requests/bytes. There are no unresolved
commands and no automatic POST retries.

All eight checked Console/report routes returned 200 through normal dedicated-CA
TLS, covering Overview, Discover, Operate, Evaluate, System and receipt history.
Reader GET returned 200; anonymous GET returned 401. Worker, publisher, web,
gateway, backup and recovery-status timers/services were active. Publication is
RETAINED; financial environment/mode/account and financial supervision remain
UNKNOWN/UNAVAILABLE because no real financial session was commissioned. Source
freshness can be stale during budget backpressure and must remain visible.

Use the existing strict-host-key SSH forwarding to `https://localhost:8443` and
the D1 dedicated CA. Retrieve only the owner's password privately from the
existing root-only credential reference. Do not disable TLS checks or change
global trust. See D2's acceptance card; automated browser success is not human
acceptance.

The first actual nonempty generation was independently restored at 00:12:58 UTC:
measured RPO 54.137 seconds, RTO 43.106 seconds, acquisition disabled and network
none. The scheduled **00:15 UTC backup was actually observed**, not inferred
from timer configuration. Its generation is `platform-20261029T001500Z.tar.age`,
134,576,392 bytes, ciphertext SHA-256
`ca7f22b5cca5760ee786730636c6a5bc2f1619129d44b2fdfc58b44f3067be64`.
It includes the corrected configuration and newer Shadow state. Its exact-generation
restore passed at **00:23:09 UTC**, measured RPO **478.266 seconds** and RTO
**47.976 seconds**, with analytical replay digest
`b55f2c846eaedcb4e824084b36bd111eb955c1a79e20cc912e5500c670149d2a` matching
the retained primary report. `restored_reports=0` means no archived report exports;
the nonempty current session/report was reconstructed and verified. Recovery
checks verify consumed authority, database integrity, artifact identity and
canonical analytical replay before starting an isolated STOPPED runtime.
Temporary plaintext is deliberately removed afterwards. No signer or real
financial custody was copied. These drills do not establish financial recovery
or a permanent RPO/RTO guarantee; the scheduled 00:45 restore was not yet observed.

## Validation, remaining gates and resume

- Final native CI: Standards, secret scan, compile, Ruff, mypy (316 modules),
  Linux pytest **1,975 passed / 28 skipped**, pip integrity, container custody,
  actual private installation, installed desktop/mobile/keyboard journeys,
  isolated ACME and nonempty recovery all passed.
- The unchanged runtime package's prior native Windows run passed **1,971 /
  32 skipped**; its operational preflight passed 8 tests. Final PR #237 changes
  only the disposable Ubuntu test harness. Canonical CI therefore skipped
  Windows and the separate browser job; installed browser acceptance still ran.
  Dependency health/supply-chain jobs were skipped by policy, with no dependency
  changes. They are not claimed as newly executed audits.
- Focused local checks included 48 adapter/operational regressions after the
  mapping fix, plus the earlier native/domain/storage/parser tests. Local full
  suite on the earlier fix passed 1,968 / 33 skipped. Ruff, mypy, compileall,
  Standards, pip/lock checks, secret scan and build passed on the engineering
  change. Native final-source CI owns final acceptance.
- Parent CI 40787396736 failed installation twice before the fixture correction;
  it is not relabelled successful. An older Windows cold-checkpoint timing
  failure was superseded by the unchanged passing Windows run. A local wheel
  with CRLF byte differences was rejected and never deployed. An auxiliary
  post-restore inspection expected disposable plaintext to remain; the restore
  itself passed and its existing receipt was read without repeating that drill.
  An extra non-gating formatter check reported existing formatting differences;
  no unrelated reformatting was performed.
- Deliberate second-pass review covered exact identities, endpoint additions,
  expiry, retained counters/STOP, unknown input rejection, duplicate processing,
  one writer, redaction, financial defaults and recovery fencing. No invariant
  was relaxed to obtain a positive result.

Executed engineering/native commands included `python scripts/validate_standards.py
--mode full`, `python -m compileall -q src tests`, `python -m ruff check .`,
`python -m mypy src`, `python -m pytest -q`, `python -m pip check`,
`python scripts/dependency_locks.py check`, `python -m polysia.security.secret_scan`
and `python -m build`. The final report-only change uses `git diff --check`,
`python scripts/check_changed_docs.py --local`, the secret scan, full Standards
validation and content/size review; runtime tests are reused because no runtime
bytes changed for this report.

| Remaining item | Status / exact next requirement |
| --- | --- |
| Sustained non-Live capacity | Not qualified under this window; review Gamma event traffic, bounded concurrency/cache opportunities and a finite workload proposal before a later admitted run; preserve this session and all counters |
| Actual human Console acceptance | PENDING: perform D2's short card against the actual private installation |
| External alert delivery | NOT_COMMISSIONED: no exact approved destination/test was available; no message sent |
| Real account / custody / financial recovery | UNKNOWN / NOT_COMMISSIONED: require complete fresh account evidence and the separate owner-controlled financial process |
| Operational financial ADR / Live | Unaccepted/unperformed; no signing, financial activation or trading inferred from this report |

Ordinary engineering resumes from #236 → #237 and this report's PR. Restricted
receipts/raw inputs remain outside Git under
`artifacts/nonlive-20261028/` locally and
`/var/lib/polysia-platform/nonlive-20261028` on the primary; current provider
evidence/authority and the persistent virtual session live in the protected worker
root. Exact artifacts remain on both hosts under the `fc3d919...` download root.

For an emergency use the active release's protected administrative STOP via
existing SSH. Retain all journals, virtual inventory, policy history and counters.
Do not delete a fence, reset stores, replace the pinned active session or force
the old D1 configuration over these stores. Any code rollback must satisfy the
existing compatible-session/flatness preflight; the retained prior checkpoint
is evidence, not automatic authority to downgrade.
