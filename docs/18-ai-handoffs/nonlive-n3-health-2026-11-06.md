# N3 native technical-health qualification

Dated engineering handoff: **2026-11-06 04:59 UTC**; canary review updated
**2026-11-06 07:19 UTC**. Protected current host
configuration, frozen plan, authority and native stores own runtime truth;
this record is not a live dashboard. The delivery PR owns ordinary continuity.
All work is DATA_ONLY, `LIVE_TRADING_ENABLED=false`, and
`LIVE_NOT_AUTHORIZED / NOT_PERFORMED`.

## Current verdict

The original run is **48H_NOT_QUALIFIED**. A backup failure caused durable STOP
and restart fencing after 69,426 seconds of real observation. The separate
[N3-R1 incident repair](#n3-r1-incident-closure) closed on 2026-11-08 with the
installed publisher, encrypted transfer and independent restore verified.
Acquisition remains stopped. The original canary and commissioning entries
below are dated evidence.

## Initial phase handoff

**ENGINEERING_CLOSED / HEALTH_OBSERVATION_RUNNING**. The exact installed native
CONTINUOUS worker, public reads, persistent storage, private Console, actual
controls and affected-layout encrypted recovery passed commissioning. A real
scheduled invocation after the start was verified. The first two-hour canary
has **PASSED**; the final 48-hour empirical verdict remains **pending**.
This is an engineering/canary report, not the final 48-hour completion report.

| Binding | Verified value |
|---|---|
| Run / purpose | `n3-health-20261106` / `TECHNICAL_HEALTH_V1` |
| Installed source | `74406cb8751ec396588f810ef1e25cf9e6363b34` |
| Image | `sha256:01e72c3d18bfef07d5e453d97f5815923ac56642d3a1ec0d99c2c1975df32b0c` |
| CI release ZIP | `63761b007a353a5a21ffe192ae178de0281d230bb0efc0cf8fac4a53bbb8074a` |
| Package tree | `5b18ba7dfd42d87193b8e9b976c5b2105b6e565ffabf406e7e349a3177dc56cc`; 337 files matched Git on both hosts |
| Configuration | `b25746533aef0a1e1a2e3774fd11116ee6fb1eef349ec320a3e591f98e2d4c56` |
| Policy | `ebf35b3dfde59fb86b7bd75ba148d36cb2d3dba73ed317a226a33a45453ed447` |
| Fixed watch | `328bf98cde940f1672900946d4c8804e3f1b531a8e401a1c3e61040ad784e591`; one verified public identity |
| Native / campaign contracts | `continuous-shadow-native-health-v1` / `nonlive-technical-health/v1` |
| Watch / admission | `native-observation-watch/v1` / `native-health-admission/v1` |
| Policy start / immutable expiry | `2026-11-06T03:44:45.594307Z` / `2026-11-09T03:44:45.594307Z` |
| First actual public attempt | `2026-11-06T04:53:11.599919Z` |
| Actual observation anchor | `2026-11-06T04:57:39.381560Z` |
| Two-hour review not before | `2026-11-06T06:57:39.381560Z` |
| 48-hour review not before | `2026-11-08T04:57:39.381560Z` |
| Primary / independent recovery | `Hetzner-Finland-Helsinki-01` / fenced `Hetzner-Germany-Nuremberg-01` |

The one N3 grant is already issued. Its earlier fixed start is conservative:
the expiry was not moved forward to compensate for installation time. Screening,
controls, smoke, observation and retries share its counters. Never replay grant
or commissioning helpers, renew authority, reset usage, replace the watch, or
relax the frozen matrix. N1/N2 grants and verdicts remain separate historical
attempts and cannot fund this run.

## Changed behavior and demonstrated repairs

The owner changed this new purpose to technical health on public data. Complete
quiet reads, rejected opportunities and missing optional marks do not themselves
stop healthy observation. Observation permission is separate from actual current
entry eligibility. Genuine revalidation can renew entry; quiet cannot refresh
its timestamp, and entry expires after four hours. Three-hour revalidation can
continue observation while blocking unqualified exposure.

The implementation retains the existing native adapter, persistent CONTINUOUS
engine, independent Risk, Decimal accounting, journal/ledger, single writer,
source/per-event/fee/book checks, exposure limits and private Console. It rejects
fabricated prior simulations and cross-purpose admission. No signer, real
account capability, new provider, infrastructure or public ingress was added.
See the [versioned runbook contract](../10-operations/independent-platform-shadow.md#versioned-native-technical-health-purpose).

Fully retained bounded HTTP error bodies settle their actual bytes; unknown or
truncated responses retain uncertainty and contain acquisition. Metadata fanout
is serialized to distinguish a legitimate in-flight reservation from lost
accounting. Malformed received envelopes are typed source failures, distinct
from local processing defects. Storage forecasts retain a peak across SQLite
checkpoint shrinkage. The worker journals real ticks in its existing authority
store, with a finite 10,000-row bound.

Before any new public request, a regression reproduced a schema-only startup
retry being misclassified as a missing running period. [#259](https://github.com/PolySia-Systems/Platform/pull/259)
corrected PREPARING only; missing identity after collection still fails closed.
[#260](https://github.com/PolySia-Systems/Platform/pull/260) repaired CI selection
so both worker safety controllers require the installed artifact and Windows
gates. Console presentation keeps its narrower scope.

All pre-I/O plan/configuration/status receipts were preserved. The initial
commissioning helper failed on a variable binding before any provider request;
the isolated report probe later omitted writable temporary storage. Both probe
errors were corrected without repeating the grant or successful replay, and
without hiding their logs. They were not provider failures. Before I/O, the
owned timer was adjusted from 61 to 65 seconds and the coverage slot from 65 to
70 seconds to allow startup jitter; old bytes/reason were retained. This did not
change the numeric health matrix or credit elapsed waiting time.

## Validation and installation

[#258](https://github.com/PolySia-Systems/Platform/pull/258) introduced the scoped
health contract; #259/#260 closed the demonstrated startup/CI wiring defects.
Final exact-main [CI 42163180551](https://github.com/PolySia-Systems/Platform/actions/runs/42163180551)
passed **all required gates**, including fresh strict supply-chain, container,
installed acceptance and CI Gate. Required PR CI 42160395591 also passed.

- Final Linux suite: **2,065 passed, 28 skipped**.
- Final Windows suite: **2,061 passed, 32 skipped**; installed/browser gates passed.
- Full Standards, compile, Ruff, mypy, pip/locks, secret scan and package/frontend
  custody/build checks passed in required CI. No required gate was waived.
- Focused local evidence: 69 initial passes; 97 affected passes and one Windows
  symlink-permission skip; final controller/legacy regressions 9 passed;
  classifier regressions 37 passed and dependency-free CI policy contracts 8 passed.
- Full CI replaces another redundant local broad/Windows run. Skips remain
  explicit limitations of the configured suites, not additional passing tests.

Both hosts staged the same immutable CI artifact, with exact package/Git byte
matches. Helsinki used the shipped installer under durable STOP and an OS fence.
The single unused N3 grant, policy bytes, times, watch and matrix were preserved
through the pre-I/O source correction. N2's spent simulated scope remains at
`/var/lib/polysia-platform/quarantine/n3-20261106-predecessor` (six requests,
429,332 bytes, zero uncertainty). Older N1/F2 evidence and virtual accounting,
private access, unrelated 3x-ui, rollback evidence, maintainer #208 and the
separate dependency-review worktree remain preserved.

## Actual controls, replay and recovery

Actual dedicated-CA private-TLS checks passed: STOP with zero new source I/O,
resume, new-process restart, pending-versus-applied receipt distinction,
lost-reply lookup/idempotency, stale-preview rejection and wrong-target rejection.
STOP/resume revisions were 2/3. These controls do not claim a real-order/session
drain exercise. The four actual control proofs plus exact recovery were bound
to the final source/configuration/policy/watch before unattended collection.

The **exact installed image**, isolated with network denied, replayed retained
N1-F2 public responses: **32 unique events, 64 evaluations, 27 virtual postings,
7 restart duplicates suppressed**, with accounting invariants passing. Captured
initial-window fixture slicing and original recorded quotes/timestamps are
explicit. This is branch/accounting coverage, **zero prospective event/time
credit**. The real installed period and authenticated Console report had the
same analytical digest and correct accounting. The actual Operate workspace
published the new observation/entry distinction.

One new affected-purpose/store recovery check succeeded:

- Generation `platform-20261106T045600Z.tar.age`, **78,027,560 encrypted bytes**.
- Ciphertext SHA256 `67ed24911a5de8281123ccff86fe4a29bbdccba068c213a834dbedc146f587da`.
- Independent restore used the exact release, `network=none`, acquisition false
  and runtime STOPPED; measured **RPO 55.607 s / RTO 44.310 s**, both met.
- Publisher, daily encrypted backup, recovery-status and fenced secondary restore
  timers are enabled. Non-secret release asset modes and private protections
  were preserved. No unrelated full recovery drill was repeated.

## Frozen acceptance and initial measured evidence

Effective limits: 120,000 HTTP attempts / 4 GiB total, 4,320 attempts / 64 MiB
per rolling hour, 4 MiB response / 15 s socket, 512 MiB RAM / 50% of one CPU,
minimum 9 GiB free disk, one fixed watch, supported 100,000-event / 256-MiB
period database-plus-WAL. Public Data API/Gamma/CLOB only. No automatic cohort
churn, evidence deletion, period reset or financial-limit increase is permitted.

| Health criterion | Frozen rule |
|---|---|
| Observation | 48 real hours from actual commissioned collection |
| Canary | First two rolling one-hour windows **inside** those 48 hours |
| Completed scheduled polls | At least 95% of frozen 70-second slots |
| Complete-poll / durable-tick gap | At most 900 / 180 seconds |
| Provider failures | Existing bounded backoff; three consecutive failures STOP |
| Critical integrity | No unresolved accounting, corrupt-state or safety fault |
| Quiet / marks | No fill, profit, opportunity-frequency or perfect-mark requirement |
| Capacity | Actual ceilings; early forecasts advisory, unresolved growth contained |

At the protected **04:59 UTC** read: exactly one grant, **4 requests / 340 bytes /
zero uncertainty**. Three actual completed native polls existed (two before the
health anchor); all were complete and quiet. The observed interval was only
78 seconds: one post-anchor scheduled poll, two durable ticks, zero failed polls
or retries, maximum poll gap 78.510 s and tick gap 66.208 s. Its 100% initial
slot coverage is **not** a two-hour or sustained-health verdict.

The new actual period had one experiment and **zero events, evaluations,
positions or ledger entries**. Short startup telemetry had four process samples,
128,172,032-byte peak RSS, 43.059% maximum observed one-core CPU and
22,004,277,248 bytes minimum free disk; telemetry errors/drops were zero. These
are short quiet-workload samples, not stress capacity or sustained latency/cache
claims. Real-event processing and nonempty current book/mark/cache coverage are
not exercised by these quiet reads. The fixed identity came from a retained
complete two-row N2 sample (SHA256
`3f4090fcde55705e701151825acc1666a4987e7d509707921950e796418d619b`),
without an activity band, five-wallet limit or profitability ranking; this is
biased sampled coverage, not venue/population coverage.

## Two-hour canary review

The server recorded `canary_passed_at=2026-11-06T06:58:29.556236Z`
(10:28:29 Asia/Tehran), after both real rolling windows. The protected read at
**07:18:17 UTC**, reviewed at **07:19:18 UTC**, confirmed the unchanged installed
release, configuration binding and single grant, with healthy continuing
collection. These counts are from that review, not a claim that all occurred
within exactly the first 120 minutes.

| Measured item | Review evidence |
|---|---|
| Canary verdict | **PASS** for the frozen technical-health purpose |
| Actual observed interval at the latest worker check | 8,434 seconds |
| Successful post-anchor complete polls | 128 |
| Frozen-slot coverage | 100% |
| Failed polls / retry ticks | 0 / 0 |
| Maximum complete-poll / durable-tick gap | 78.510 / 66.912 seconds |
| Total grant usage, including commissioning | 131 requests / 11,135 accounted response bytes |
| Uncertain requests | 0 |
| Actual prospective events / evaluations / fills | 0 / 0 / 0 |
| Native telemetry errors / drops | 0 / 0 |
| Independent server safety | `SERVER_SAFETY_ACTIVE`; scheduled worker and recovery timers active |

All sampled source responses were complete and quiet. This is positive evidence
of the exercised observation/scheduling/accounting path, not proof of current
event processing, book/mark/cache coverage, strategy performance or provider-wide
inactivity. Captured replay remains separate. The two-hour pass neither completes
48 hours nor relabels historical N1/N2 economic-flow attempts as qualified.

The dated local receipts are `health-read-20261106T071821.json` and
`canary-review-20261106.json` under `artifacts/n3-20261106/`. A fresh **07:21 UTC**
safety read confirmed the same running phase and one grant, now at 133 requests /
11,305 bytes / zero uncertainty. No new authority, acceptance restart or runtime
change was needed for this review.

## Server-owned continuation and final closure

The stock worker timer owns acquisition. The root `polysia-n3-watch` independently
checks freshness, finite expiry, disk/recovery headroom and terminal STOP/fencing.
An actual scheduled post-start poll, current root safety receipt and all required
timers were verified; no chat polling loop owns the 48-hour wait.

Existing app follow-up **`platform-sol-1`** was updated, not duplicated. Its
initial canary review was configured for 07:10 UTC; the actual evidence review
above occurred at 07:19 UTC. The same follow-up was then updated and its persisted
ID/status/rule/target read back for final review at **2026-11-08 05:10 UTC /
08:40 Asia/Tehran**, after the actual 48-hour end of
**2026-11-08 04:57:39.381560 UTC**. Scheduler execution may be later;
the real host anchor, never alarm time, owns time credit.
Server safety is independent of this app follow-up. Do not retire it before
actual final review or explicit owner request.

Protected operational truth: `/etc/polysia-platform/n3-health-campaign.json`,
`/var/lib/polysia-platform/worker/status.json`,
`/var/lib/polysia-platform/worker/nonlive-campaign-status.json`, authority/native
stores and `/var/lib/polysia-platform/n3-20261106/current-safety.json`.
Local dated receipts/helpers are ignored under `artifacts/n3-20261106/`;
`collect_health.py` is compact/read-only. Commissioning helpers are consumed,
not resume commands. Preserve all adverse/partial receipts.

At completion/expiry verify durable acquisition STOP and OS fencing, review all
actual 48-hour coverage/gaps/retries/events/decisions/fills/accounting/fees/cost,
latency/cache/resources/source/mark evidence and limitations, then remove only
owned temporary `polysia-n3-watch` units and the N3 timer override. Keep publisher,
private Console, historical state and normal recovery usable. Do not fabricate
position liquidation. Update this same record and PROJECT_STATUS through normal
protected PRs before retiring the app follow-up.

## Seven required verdicts at this phase handoff

| Verdict | Evidence-based result |
|---|---|
| ENGINEERING_CLOSURE | CLOSED for this scoped release; no known unfinished critical fix, missing changed-component wiring or failing required check |
| INSTALLED_CONTINUOUS_RUNTIME | PASS for actual installed worker/storage/source/private Console and restart paths |
| TECHNICAL_HEALTH_SOAK | Two-hour canary PASS; 48-hour observation RUNNING / final verdict PENDING |
| ACCOUNTING_CORRECTNESS | PASS for exercised actual quiet state and isolated captured-event paths; prospective fills not exercised |
| REAL_EVENT_COVERAGE | NOT_EXERCISED in N3 prospective period; replay counts separate |
| CONSOLE_AND_CONTROLS | PASS for actual private-TLS Operate/report and scoped controls; human acceptance NOT_PERFORMED |
| SOURCE_AND_MARK_COVERAGE | Complete quiet reads from one identity; current nonempty event/book/mark coverage NOT_EXERCISED |

At this historical handoff, engineering/commissioning was closed and the
48-hour empirical review remained open. That evidence did not establish
profitable strategy/copying, complete NAV/source coverage, human acceptance nor
Live readiness. Optional private review: SSH forward
`ssh -N -L 8443:127.0.0.1:8443 Hetzner-Finland-Helsinki-01`, then
`https://localhost:8443/` with the existing private credentials/CA. No credential
is included in this record.

## N3-R1 incident closure

At 2026-11-07 00:15 UTC, publisher and backup jobs failed. The safety watcher
recorded `N3_RECOVERY_HEALTH_BACKUP` and fenced acquisition at 00:15:51 UTC.
The retained observation interval was **19h 17m 06s**. Its two-hour canary
passed. The 48-hour period did not. One grant consumed 2,290 requests and
5,417,306 accounted bytes with zero uncertainty. The retained state contains
61 unique events, 122 evaluations and 30 simulated executions across
independent portfolios, with zero real orders. The stopped follower ledger
has NAV 992.1660423543275769014108528, fees 2.74831 and total marked virtual
P&L −7.833957645672423098589147152 at the 00:14:45 UTC cutoff. This replaces
the stale positive publication as evidence for the stopped state.

The exact-image stopped-copy reproduction failed while converting a verified
zero settlement payout to a generic positive-only execution price. The
historical child exception was not logged. Retained zero marks, publisher
timing and the controlled reproduction support the attribution. The repair
stores terminal payout in verified settlement provenance and omits execution
price from that observation. Positive finite trade/book prices and the
causal payout rules remain enforced.

[PR #272](https://github.com/PolySia-Systems/Platform/pull/272) also separates
authoritative snapshot validation from optional derived analytics in recovery
v2. Degraded analytics can preserve encrypted state and receive a distinctly
degraded restore verdict. Required state, identity, accounting, consumption
and report digest checks remain strict. The v1 reader retains its recorded
validation rules. Host job failures expose a bounded stage, error code, child
exit status and attempt ID. The report API qualifies retained data as stale
after publisher failure. See the [recovery contract](../10-operations/independent-platform-shadow.md#recovery-and-terminal-settlement-evidence).

The final review checked settlement/quote semantics, recovery and legacy
contracts, secret redaction, stopped transition provenance and unchanged
monetary rows. Installed CI exposed two integration gaps before the final
pass. The success fixture had an unresolved reservation, and the initial
diagnostic wrapper changed the transfer exception type. The successful
fixture now settles its response while a separate regression rejects
uncertainty. The wrapper preserves the original exception contract and
attaches a redacted diagnostic.

Local validation included 40 focused unit and 6 focused integration passes,
Ruff, mypy, full Standards, secret scan, changed-file validation and diff
checks. Final protected PR CI `42450722549` and
[exact runtime-main CI 42452378743](https://github.com/PolySia-Systems/Platform/actions/runs/42452378743)
passed, including Linux **2,084 passed / 33 skipped**, Windows
**2,080 passed / 37 skipped**, browser, container, installed acceptance and CI
Gate. Dependency-health was not selected for these push/PR events. Supply-chain
used the successful strict run `42163180551` with unchanged dependency inputs.

| Installed proof | Verified evidence |
|---|---|
| Source / image | `96ddb5d887003423c10d9b118f6a9c0f1b53f0d7` / `sha256:5d804d55caa770dc0367d0868244d5dd4e34475d8e2fb69bacfd2db02b222d26` |
| Artifact custody | CI artifact `13606585211`; 343 first-party files matched Git on both hosts |
| Retained transition | Proved on a copy, then applied with the supported installer under durable STOP and the OS fence at 06:11:17 UTC. Exact economic and authority row fingerprints matched. Historical campaign and policy bytes, admission provenance, private binding and unrelated service were preserved. |
| Real publisher | `PUBLISHED`; private TLS report retained the stopped ledger totals and analytical digest `8af3ca803a2db058e6c54d3f162949f83b485bffd4a198109c5ba1dbbd3786f0` |
| Failure receipt | Installed wrapper rejected a diagnostic invalid recipient using a separate protected receipt. Stage `configuration`, code `INVALID_EVIDENCE`, child exit 1, attempt `139fa0aaf1e347d39f284db27a886a4f` |
| Encrypted transfer | `platform-20261108T061204Z.tar.age`, 105,108,728 bytes, SHA256 `5907e7ec56ab1c4a634fa649ecbe4386c6068a0dc57ba5ff1e02405c75583e12` matched both hosts |
| Independent restore | Nuremberg, `VERIFIED_ISOLATED_RESTORE` at 06:13:29 UTC, attempt `a3b3070c6c02416b802b01f474d9e799`; network none, acquisition false, runtime STOPPED |
| Restored accounting | Exact financial SQLite digest `e9a5c38a57897a886668ce373dceefbc9383be0a45d387be795082c42956e9a2` and experiment identity matched generation. Ledger invariants and analytical digest verified, with 2,290 requests / 5,417,306 bytes / zero uncertainty preserved through startup. |

Restore elapsed time was **50.702 s** and the fresh generation was **72.590 s**
old at verification. The stopped financial cutoff was approximately
**29h 57m** old when this generation was made. These are distinct measurements.
The fresh generation does not establish that the failed original backup met
its RPO. The prior verified generation was retained on both hosts.

Final state was durable STOP and OS fence on Helsinki and fenced recovery on
Nuremberg. The acquisition timer is inactive. Publisher, backup,
recovery-status and secondary restore timers are active. The owned N3 watcher
units and cadence override were retired into the protected maintenance record.
The app confirmed `platform-sol-1` was already absent (`not_found`).

| Verdict | Result |
|---|---|
| SETTLEMENT_REPORTING | PASS on the affected persisted settlement state |
| BACKUP_FAULT_ISOLATION | PASS, explicit degraded round trip in regression and verified normal installed generation |
| DIAGNOSTICS | PASS, allowlisted failure receipt and stale-publication regression |
| INSTALLED_REPAIR | PASS, exact immutable release commissioned under STOP |
| INDEPENDENT_RESTORE | PASS, affected encrypted state restored and verified on fenced Nuremberg |
| INCIDENT_ENGINEERING_CLOSURE | CLOSED |
| N3_48H_QUALIFICATION | 48H_NOT_QUALIFIED |
| LIVE_AUTHORIZATION | LIVE_NOT_AUTHORIZED / NOT_PERFORMED |

The protected pre-transition checkpoint is
`/var/lib/polysia-platform/n3-r1-96ddb5d88700/checkpoint`. Use the checkpoint
and corresponding trusted release for compatible rollback under STOP.
Operational receipts are retained under `artifacts/n3-r1-20261108/`. A future
observation requires its own finite owner authorization.
